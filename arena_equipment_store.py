"""Account-owned gear, character loadouts and atomic, idempotent loot settlement."""
import hashlib
import json
import random
import secrets
import time
from arena_equipment import (CATALOG,RANKS,RARITIES,LEVELS,SLOTS,STATS,AFFIXES,CHANCES,EFFECTS,
                             public_item,apply_stats)


class EquipmentMixin:
    def _connect_equipment(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS gear_accounts(actor INTEGER PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS gear_items(id TEXT PRIMARY KEY, actor INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS gear_items_actor ON gear_items(actor);
            CREATE TABLE IF NOT EXISTS gear_loadouts(actor INTEGER NOT NULL, character_slot INTEGER NOT NULL,
                slot TEXT NOT NULL, item TEXT NOT NULL, PRIMARY KEY(actor,character_slot,slot));
            CREATE TABLE IF NOT EXISTS gear_materials(actor INTEGER NOT NULL, rank TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(actor,rank));
            CREATE TABLE IF NOT EXISTS gear_requests(actor INTEGER NOT NULL, nonce TEXT NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY(actor,nonce));
            CREATE TABLE IF NOT EXISTS gear_loot(source TEXT NOT NULL, actor INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(source,actor));
        ''')

    def _gear_revision_locked(self,actor):
        self.connection.execute('INSERT OR IGNORE INTO gear_accounts VALUES(?,0)',(actor,))
        return self.connection.execute('SELECT revision FROM gear_accounts WHERE actor=?',(actor,)).fetchone()[0]

    def _gear_touch_locked(self,actor):
        self._gear_revision_locked(actor)
        self.connection.execute('UPDATE gear_accounts SET revision=revision+1 WHERE actor=?',(actor,))

    def _gear_item_locked(self,actor,ident):
        if not isinstance(ident,str):raise ValueError('Выбери предмет.')
        row=self.connection.execute('SELECT data FROM gear_items WHERE id=? AND actor=?',(ident,actor)).fetchone()
        if not row:raise ValueError('Предмет не найден в твоём инвентаре.')
        return json.loads(row[0])

    def _gear_save_locked(self,actor,item):
        self.connection.execute('INSERT INTO gear_items VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                                (item['id'],actor,json.dumps(item,ensure_ascii=False)))

    def _gear_grant_locked(self,actor,key,rank,rarity,rng=None):
        rng=rng or random.SystemRandom()
        count=min(2,RARITIES.index(rarity))
        choices=[k for k in AFFIXES if k!=CATALOG[key]['main']]
        item=dict(id=secrets.token_hex(10),key=key,rank=rank,rarity=rarity,upgrade=0,affixes=rng.sample(choices,count),
                  favorite=False,rerolled=False,created=int(time.time()))
        self._gear_save_locked(actor,item);self._gear_touch_locked(actor)
        return item

    def _gear_snapshot_locked(self,actor,level,slot=None):
        slot=slot or self._character_active_locked(actor)
        rows=self.connection.execute('''SELECT i.data FROM gear_loadouts l JOIN gear_items i ON i.id=l.item AND i.actor=l.actor
            WHERE l.actor=? AND l.character_slot=? ORDER BY l.slot''',(actor,slot))
        return [i for r in rows if LEVELS[RANKS.index((i:=json.loads(r[0]))['rank'])]<=level]

    def _gear_material_locked(self,actor,rank,amount):
        self.connection.execute('INSERT INTO gear_materials VALUES(?,?,0) ON CONFLICT DO NOTHING',(actor,rank))
        current=self.connection.execute('SELECT quantity FROM gear_materials WHERE actor=? AND rank=?',(actor,rank)).fetchone()[0]
        if current+amount<0:raise ValueError('Недостаточно материалов этого ранга.')
        self.connection.execute('UPDATE gear_materials SET quantity=quantity+? WHERE actor=? AND rank=?',(amount,actor,rank))

    def _gear_loot_locked(self,source,actor,contract,*,guaranteed=False,chance=.2,materials=1):
        """Called only from existing eligible guild settlement, inside its transaction."""
        old=self.connection.execute('SELECT data FROM gear_loot WHERE source=? AND actor=?',(source,actor)).fetchone()
        if old:return json.loads(old[0])
        rng=random.SystemRandom();rank=contract['rank'];tier=RANKS.index(rank)
        loot=dict(items=[],materials=materials,rank=rank)
        self._gear_material_locked(actor,rank,materials)
        if guaranteed or rng.random()<chance:
            rarity=rng.choices(RARITIES,weights=CHANCES[tier])[0]
            key=rng.choice([k for k,v in CATALOG.items() if v['biome']==contract['biome']])
            item=self._gear_grant_locked(actor,key,rank,rarity,rng)
            loot['items'].append(public_item(item))
        self.connection.execute('INSERT INTO gear_loot VALUES(?,?,?)',(source,actor,json.dumps(loot,ensure_ascii=False)))
        self._gear_touch_locked(actor)
        return loot

    def _gear_view_locked(self,chat,actor):
        profile=dict(self._arena_profile_locked(chat,actor,True));slot=self._character_active_locked(actor)
        from arena_engine import stats_for
        from arena_mastery import street_stats
        from arena_progression import choice_avatar
        from arena_archclasses import class_title
        classes,_=self._fighter_catalog_locked()
        base=street_stats(profile,stats_for(profile['class_id'],profile['level'],False,classes))
        current=self._gear_snapshot_locked(actor,profile['level'])
        equipped={r['slot']:r['item'] for r in self.connection.execute('SELECT slot,item FROM gear_loadouts WHERE actor=? AND character_slot=?',(actor,slot))}
        used={}
        for r in self.connection.execute('SELECT item,character_slot FROM gear_loadouts WHERE actor=?',(actor,)):
            used.setdefault(r['item'],[]).append(r['character_slot'])
        items=[]
        for r in self.connection.execute('SELECT data FROM gear_items WHERE actor=? ORDER BY rowid DESC',(actor,)):
            i=public_item(json.loads(r[0]));i.update(equipped=equipped.get(i['slot'])==i['id'],used_by=used.get(i['id'],[]))
            replacement=[g for g in current if CATALOG[g['key']]['slot']!=i['slot']]+[i]
            i['comparison']=apply_stats(base,replacement);i['reroll_options']=self._gear_options(i)
            items.append(i)
        hunter=self._guild_hunter_locked(actor)
        sprite=self.connection.execute('SELECT sprite_key,pixel_art FROM arena_sprites WHERE chat_id=0 AND user_id=?',(actor,)).fetchone()
        fallback=choice_avatar(profile['class_id'],profile.get('archclass_id',''),
            20 if profile['level']>=20 and profile.get('archclass_stage',10)>=20 else 10)
        name=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()
        total=apply_stats(base,current)
        return dict(revision=self._gear_revision_locked(actor),character_slot=slot,level=profile['level'],
                    class_name=class_title(profile,classes[profile['class_id']].name),busy=self._arena_busy_locked(chat,actor),
                    hero=dict(name=name['display_name'] if name else 'Твой персонаж',
                        sprite_url='/sprites/'+sprite['sprite_key']+'.png' if sprite else fallback,
                        fallback_url=fallback,pixel_art=bool(sprite and sprite['pixel_art'])),
                    equipped=equipped,items=items,slots=SLOTS,stat_names=STATS,base_stats=base,stats=total,
                    stat_bonuses={key:round(total.get(key,0)-base.get(key,0),2) for key in STATS},
                    materials={r['rank']:r['quantity'] for r in self.connection.execute('SELECT * FROM gear_materials WHERE actor=?',(actor,))},
                    catalog=[dict(v,description=EFFECTS[v['effect']]) for v in CATALOG.values()],ranks=list(RANKS),min_levels=list(LEVELS),hunter_rank=RANKS[hunter['rank']],
                    chances=[dict(zip(RARITIES,row)) for row in CHANCES])

    @staticmethod
    def _gear_options(item):
        excluded=set(item.get('affixes',[]))|{CATALOG[item['key']]['main']}
        return sorted((k for k in AFFIXES if k not in excluded),key=lambda k:hashlib.sha256((item['id']+k).encode()).hexdigest())[:3]

    async def gear_view(self,chat,actor):
        async with self._lock:
            with self.connection:return self._gear_view_locked(chat,actor)

    async def gear_action(self,chat,actor,body):
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        nonce=body.get('nonce');revision=body.get('revision');action=body.get('action');ident=body.get('item')
        if not isinstance(nonce,str) or not 8<=len(nonce)<=80:raise ValueError('Нужен номер запроса.')
        if type(revision) is not int:raise ValueError('Обнови снаряжение.')
        mark=json.dumps({k:v for k,v in body.items() if k not in ('nonce','revision')},sort_keys=True)
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                old=self.connection.execute('SELECT fingerprint FROM gear_requests WHERE actor=? AND nonce=?',(actor,nonce)).fetchone()
                if old:
                    if old[0]!=mark:raise ValueError('Номер запроса уже использован.')
                    return self._gear_view_locked(chat,actor)
                if revision!=self._gear_revision_locked(actor):raise ValueError('Снаряжение изменилось в другом окне. Обнови страницу.')
                slot=self._character_require_locked(actor,body.get('character_slot'))
                if self._arena_busy_locked(chat,actor) and action!='favorite':raise ValueError('Менять снаряжение можно после завершения боя или похода.')
                if action in ('craft','buy'):
                    key=body.get('key');rank=body.get('rank');rarity='epic' if action=='craft' else 'uncommon'
                    if not isinstance(key,str) or key not in CATALOG or rank not in RANKS:raise ValueError('Неизвестный предмет или ранг.')
                    if RANKS.index(rank)>self._guild_hunter_locked(actor)['rank']:raise ValueError('Нужен соответствующий ранг гильдии.')
                    self._gear_material_locked(actor,rank,-40 if action=='craft' else -8)
                    self._gear_grant_locked(actor,key,rank,rarity)
                else:
                    item=self._gear_item_locked(actor,ident);definition=CATALOG[item['key']]
                    if action=='equip':
                        profile=self._arena_profile_locked(chat,actor,True)
                        if profile['level']<LEVELS[RANKS.index(item['rank'])]:raise ValueError('Недостаточный уровень персонажа.')
                        self.connection.execute('INSERT INTO gear_loadouts VALUES(?,?,?,?) ON CONFLICT(actor,character_slot,slot) DO UPDATE SET item=excluded.item',
                                                (actor,slot,definition['slot'],ident))
                    elif action=='unequip':self.connection.execute('DELETE FROM gear_loadouts WHERE actor=? AND character_slot=? AND item=?',(actor,slot,ident))
                    elif action=='favorite':
                        item['favorite']=not item['favorite'];self._gear_save_locked(actor,item)
                    elif action=='salvage':
                        if item['favorite']:raise ValueError('Сначала убери вещь из избранного.')
                        if self.connection.execute('SELECT 1 FROM gear_loadouts WHERE actor=? AND item=?',(actor,ident)).fetchone():raise ValueError('Вещь надета на одном из персонажей.')
                        self._gear_material_locked(actor,item['rank'],public_item(item)['salvage'])
                        self.connection.execute('DELETE FROM gear_items WHERE actor=? AND id=?',(actor,ident))
                    elif action=='upgrade':
                        if item['upgrade']>=5:raise ValueError('Уже достигнуто +5.')
                        self._gear_material_locked(actor,item['rank'],-(2+item['upgrade']*2));item['upgrade']+=1;self._gear_save_locked(actor,item)
                    elif action=='reroll':
                        index=body.get('index');choice=body.get('choice')
                        if item['rerolled'] or type(index) is not int or not 0<=index<len(item['affixes']) or choice not in self._gear_options(item):raise ValueError('Недоступная замена свойства.')
                        self._gear_material_locked(actor,item['rank'],-5);item['affixes'][index]=choice;item['rerolled']=True;self._gear_save_locked(actor,item)
                    else:raise ValueError('Неизвестное действие.')
                self.connection.execute('INSERT INTO gear_requests VALUES(?,?,?)',(actor,nonce,mark))
                self._gear_touch_locked(actor)
                return self._gear_view_locked(chat,actor)
