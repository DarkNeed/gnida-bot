"""Disposable local mimic review; no real Telegram token or production database."""
import argparse
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from aiohttp import web
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_engine import BUILTIN_SKILLS,fighter_xp_limit,effective_skill
from arena_raid_engine import BOSS_SKILLS,pair_state
from arena_web import create_arena_app,ROOT
from database import Database
import arena_mimic as mimic

TOKEN='local-mimic-review-not-a-real-bot-token'


async def application():
    temporary=tempfile.TemporaryDirectory(prefix='gnida-mimic-review-')
    db=Database(Path(temporary.name)/'review.sqlite3');await db.connect()
    await db.upsert_chat(1,'Мимик · локальное демо')
    await db.upsert_user(1,10,'tester','Испытатель')
    db._arena_profile_locked(1,10,True)
    db._grant_profile_xp_locked('personal_profiles',1,10,fighter_xp_limit())
    db.connection.commit()
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
    app=create_arena_app(db,bot,TOKEN);app['mimic_review_db']=db

    async def start(request):
        build=request.query.get('build','mage');build=build if build in ('mage','priest','hunter') else 'mage'
        branch={'mage':'mage_archmage','priest':'priest_bishop','hunter':'hunter_moon'}[build]
        loadout={'mage':['mana_shot','mana_overload','mana_barrier','mana_focus'],
            'priest':['light_word','priest_heal','arch_priest_bishop','mana_focus'],
            'hunter':['hunter_shot','hunter_cut','blood_bullets','calm_breath']}[build]
        mode=request.query.get('mode','fresh')
        if mode=='scroll':loadout[-1]='plagiarism'
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute('DELETE FROM arena_qte_flows')
                db.connection.execute('''UPDATE personal_profiles SET class_id=?,archclass_id=?,archclass_stage=20,
                    progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=10''',
                    (build,branch,json.dumps(loadout)))
                db.connection.execute('INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)',(0,10,1,'skill','plagiarism'))
        await db.arena_combat_settings(10,enabled=request.query.get('qte','1')!='0',
            defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        row=await db.arena_raid_create(1,10,'mimic',silent=True)
        row=await db.arena_raid_setup(row['token'],10,'join')
        row=await db.arena_raid_setup(row['token'],10,'start')
        async with db._lock:
            data=json.loads(row['data_json']);p=data['players']['10']['fighter'];b=data['boss']
            if request.query.get('sturdy')=='1':p['hp']=p['stats']['max_hp']=500
            if mode in ('phase2','phase3','threshold','charged','passives','first_combo'):
                source=deepcopy(p);source.update(class_id='mage',archclass_id='mage_archmage',rpg_state=dict(mana=3,echo_ready=True))
                source['loadout']=['mana_shot','mana_overload'];catalog={**BOSS_SKILLS,**BUILTIN_SKILLS}
                for slot,sid in enumerate(('mana_shot',) if mode=='first_combo' else ('mana_shot','mana_overload')):
                    skill=effective_skill(pair_state(source,b),'a',sid,catalog)
                    record=mimic.compile_copy(skill,source,b)
                    record.update(uid=str(slot+1),slot=slot,seen=1,charges=1,source='Испытатель',threat=record['skill']['power'])
                    data['mimic']['attacks'].append(record)
                data['mimic']['serial']=len(data['mimic']['attacks'])
            if mode in ('phase2','phase3','passives'):
                b['hp']=round(b['stats']['max_hp']*(.34 if mode=='phase3' else .69));mimic.phase(data)
            if mode=='threshold':b['hp']=round(b['stats']['max_hp']*.37)
            if mode in ('phase2','passives','first_combo'):b['own_turns']=2
            if mode=='charged':p.setdefault('rpg_state',{}).update(mana=3,echo_ready=True)
            if mode=='passives':
                from arena_engine import BUILTIN_PASSIVES
                from dataclasses import asdict
                for sid in ('battle_rhythm','stone_skin'):
                    definition=asdict(BUILTIN_PASSIVES[sid])
                    data['mimic']['passives'].append(dict(key=sid,definition=definition,source='Испытатель',until=b.get('own_turns',0)+3))
            mimic.set_intent(data)
            data.pop('_unified',None);data.pop('_queue_wait',None);data.pop('_cast_queue',None)
            import arena_unified_queue as queue
            queue.initialize(data,{**BOSS_SKILLS,**BUILTIN_SKILLS})
            with db.connection:db._raid_save_locked(row,data)
        raise web.HTTPFound('/mimic-preview?tgWebAppStartParam=r_'+row['token'])

    async def preview(request):
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=10)))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def review(request):
        html=Path(__file__).with_name('mimic_review.html').read_text(encoding='utf-8')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def music(request):
        revision=hashlib.sha256((ROOT/'arena-audio').read_bytes()).hexdigest()[:16]
        html=Path(__file__).with_name('mimic_music.html').read_text(encoding='utf-8').replace('__AUDIO_REV__',revision)
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    app.router.add_get('/mimic-demo',start);app.router.add_get('/mimic-preview',preview);app.router.add_get('/mimic-review',review)
    app.router.add_get('/mimic-music',music)
    async def close(_):await db.close();temporary.cleanup()
    app.on_cleanup.append(close)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8158)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
