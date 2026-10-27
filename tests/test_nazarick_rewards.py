"""Trophies, preserving-level ticket, unanimous combat-local rescue and new patterns."""
from copy import deepcopy
from dataclasses import asdict
import asyncio
import json
import random
import subprocess
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from arena_engine import BUILTIN_SKILLS,BUILTIN_PASSIVES,create_battle_state,Skill
from arena_nazarick import offer_blessing,vote_blessing,load_stage,progress,contact_afflictions,SKILLS
from arena_relics import RELIC_IDS,TICKET_ID,modifiers,after_action,incoming,periodic_damage
import test_nazarick as nztests
encounter=nztests.encounter


class RelicTests(unittest.TestCase):
    def fighter(self,*ids):
        source=dict(owner_id=10,slave_id=10,class_id='mage',level=20,
            loadout=['mana_shot','mana_clot'],passive_details=[asdict(BUILTIN_PASSIVES[k]) for k in ids])
        return create_battle_state(source,dict(source,slave_id=20,passive_details=[]))

    def test_mask_tracks_attacks_not_support_including_misses(self):
        s=self.fighter(RELIC_IDS[0]);a,b=s['sides'].values();skill=BUILTIN_SKILLS['mana_shot']
        self.assertEqual(modifiers(a,b,skill),(0,1))
        after_action(a,skill,0)
        self.assertEqual(modifiers(a,b,skill),(0,1))
        other=Skill('test','test','mage',1,'magic',20,100,0,0)
        self.assertEqual(modifiers(a,b,other),(0,1.2))
        after_action(a,BUILTIN_SKILLS['mana_focus'],0)
        self.assertEqual(modifiers(a,b,other),(0,1.2))

    def test_glasses_distinct_temporary_debuffs_capped(self):
        s=self.fighter(RELIC_IDS[1]);a,b=s['sides'].values()
        b['effects']=[dict(id=str(i),kind=k,value=v,duration=t) for i,(k,v,t) in enumerate([
            ('burn',3,2),('burn',2,3),('damage_pct',-.1,3),('accuracy_flat',-10,2),
            ('speed_pct',-.1,2),('damage_pct',.3,2),('magic_defense_pct',-.1,100000)])]
        self.assertEqual(modifiers(a,b,BUILTIN_SKILLS['mana_shot']),(8,1.3))

    def test_helmet_actual_damage_cap_no_revive_or_dot_healing(self):
        s=self.fighter(RELIC_IDS[2]);a,b=s['sides'].values();a['hp']=10
        self.assertEqual(modifiers(a,b,BUILTIN_SKILLS['mana_shot']),(0,1.15))
        after_action(a,BUILTIN_SKILLS['mana_shot'],100000)
        self.assertEqual(a['hp'],10+int(a['stats']['max_hp']*.08))
        before=a['hp'];after_action(a,BUILTIN_SKILLS['mana_focus'],999)
        self.assertEqual(a['hp'],before)
        a['hp']=0;after_action(a,BUILTIN_SKILLS['mana_shot'],999)
        self.assertEqual(a['hp'],0)

    def test_hermes_and_plot_armor_have_separate_direct_periodic_rules(self):
        from arena_engine import _tick
        s=self.fighter(RELIC_IDS[3]);a,b=s['sides'].values()
        self.assertEqual(incoming(a),.85);self.assertEqual(periodic_damage(a,10),10)
        a['hp']=10;self.assertEqual(incoming(a),.70)
        a['effects'].append(dict(id='nz_plot_armor',kind='incoming_damage_multiplier',value=.5,duration=1000000))
        self.assertEqual(periodic_damage(a,10),5)
        a['hp']=20;a['effects'].append(dict(id='test_burn',kind='burn',value=10,duration=2));_tick(a)
        self.assertEqual(a['hp'],15)

    def test_engine_damage_really_uses_relic_and_no_passive_plague_cleanse(self):
        from arena_raid_engine import native_attack
        def attack(relic=None,armor=False):
            s=self.fighter(*( [relic] if relic else []));a,b=s['sides'].values()
            b['hp']=b['stats']['max_hp']=10000;a['hp']=20
            a['effects'].extend([dict(id='spore',kind='plague_spores',value=1,duration=1000000),dict(id='nz_contact_burn',kind='burn',value=3,duration=2)])
            if armor:b['effects'].append(dict(id='nz_plot_armor',kind='incoming_damage_multiplier',value=.5,duration=1000000))
            a['_qte_attack']=[True]
            event=native_attack(a,b,'mana_shot',BUILTIN_SKILLS,random.Random(1))
            return event,a
        base,_=attack();half,_=attack(armor=True)
        self.assertAlmostEqual(base['damage']/2,half['damage'],delta=1)
        helm,a=attack(RELIC_IDS[2]);self.assertGreater(helm['damage'],base['damage'])
        self.assertTrue(any(e['kind']=='plague_spores' for e in a['effects']))


class BlessingTests(unittest.TestCase):
    def wipe(self,stage=3):
        d=encounter();d['nazarick'].update(stage=stage,phase=2);load_stage(d)
        d['boss']['hp']=1
        for p in d['players'].values():p['fighter']['hp']=0;p['selected']='defend'
        self.assertFalse(offer_blessing(d));return d

    def test_unanimity_restarts_only_current_boss_first_phase_and_once(self):
        d=self.wipe();offer=d['nazarick']['blessing_offer'];oldround=d['round']
        for actor in(10,20):self.assertEqual(vote_blessing(d,actor,True,offer['id']),'waiting')
        self.assertTrue(all(p['fighter']['hp']==0 for p in d['players'].values()))
        self.assertEqual(vote_blessing(d,30,True,offer['id']),'restarted')
        self.assertEqual((d['nazarick']['stage'],d['nazarick']['phase']),(3,1))
        self.assertEqual(d['boss']['hp'],d['boss']['stats']['max_hp'])
        self.assertGreater(d['round'],oldround);self.assertTrue(d['nazarick']['ticket_forfeited'])
        for p in d['players'].values():
            f=p['fighter'];self.assertEqual(f['hp'],f['stats']['max_hp']);self.assertIsNone(p['selected'])
            self.assertTrue(any(e['id']=='nz_plot_armor' for e in f['effects']))
        d['nazarick'].update(stage=1,phase=2);d['boss']['hp']=0;progress(d)
        self.assertEqual(d['nazarick']['stage'],2)
        self.assertTrue(all(any(e['id']=='nz_plot_armor' for e in p['fighter']['effects']) for p in d['players'].values()))
        for p in d['players'].values():p['fighter']['hp']=0
        self.assertTrue(offer_blessing(d));self.assertTrue(d['finished']);self.assertFalse(d['won'])

    def test_duplicate_stale_foreign_votes_and_refusal(self):
        d=self.wipe();offer=d['nazarick']['blessing_offer'];oid=offer['id']
        with self.assertRaises(ValueError):vote_blessing(d,99,True,oid)
        with self.assertRaises(ValueError):vote_blessing(d,10,True,'old')
        vote_blessing(d,10,True,oid)
        self.assertEqual(vote_blessing(d,10,True,oid),'unchanged')
        self.assertEqual(vote_blessing(d,20,False,oid),'declined')
        self.assertTrue(d['finished']);self.assertFalse(d['won']);self.assertEqual(d['rewards'],{})

    def test_turn_start_plague_wipe_offers_blessing_immediately(self):
        from arena_nazarick import resolve
        d=encounter(1);p=d['players']['10'];p['fighter']['hp']=1;p['selected']='defend'
        p['fighter']['effects'].append(dict(id='plague',kind='plague_spores',value=3,duration=1000000))
        d['enemy_intents']['boss']['kind']='stance'
        resolve(d,BUILTIN_SKILLS,random.Random(5))
        self.assertEqual(p['fighter']['hp'],0);self.assertIn('blessing_offer',d['nazarick'])


class NewPatternTests(unittest.TestCase):
    state=nztests.RevisedMechanicsTests.state

    def test_only_inscriptions_distinguish_shelters_random_sizes(self):
        from arena_nazarick_patterns import shapes
        for sid,labels in [('nz_demiurge_p1_2',{'ПУТЬ','ЛОВУШКА'}),('nz_ainz_p2_1',{'СМЕРТЬ','ЖИЗНЬ'})]:
            s=self.state(sid);rows=shapes(s,s['events'][0])
            self.assertEqual({h['label'] for h in rows},labels)
            self.assertEqual(len({h['color'] for h in rows}),1)
            self.assertTrue(all(h['uniform'] and h['motif']=='sigil' for h in rows))
            self.assertTrue(all(40<=h['r']<71 for h in rows))
            self.assertGreater(len({h['r'] for h in rows}),1)

    def test_two_phase2_attacks_use_orbs_and_seven_statuses(self):
        from arena_nazarick_patterns import shapes,STONE_STATUSES
        for sid in ('nz_ainz_p2_0','nz_ainz_p2_2'):
            s=self.state(sid);hs=shapes(s,s['events'][0])
            self.assertTrue(any(h['motif']=='staff_orb' for h in hs))
            self.assertEqual(set(STONE_STATUSES),{h.get('status') for h in hs})
        s=self.state('nz_ainz_p1_0');e=dict(s['events'][0],index=1)
        self.assertEqual(sum(h['motif']=='lightning' for h in shapes(s,e)),6)

    def test_trap_never_overlaps_shelter_even_near_edges(self):
        from arena_nazarick_patterns import shapes
        s=self.state('nz_demiurge_p1_2')
        for x in (8,78,180,360,642,712):
            for index in range(2):
                s['player']['x']=x;a,b=shapes(s,dict(s['events'][0],index=index,jitter=.99))
                self.assertGreater(abs(a['x']-b['x']),a['r']+b['r']+12)

    def test_orbit_positions_and_block_freeze_have_client_server_agreement(self):
        from arena_nazarick_patterns import shapes,block_threats
        from arena_qte_patterns import geometry
        from arena_qte_block import parameters
        s=self.state('nz_ainz_p2_2');h=next(h for h in shapes(s,s['events'][0]) if h.get('orbit'));h['start']=0
        script="const E=require('./webapp/qte-unique/engine'),N=require('./webapp/nazarick-qte.js');let b='';process.stdin.on('data',s=>b+=s);process.stdin.on('end',()=>{let h=JSON.parse(b);process.stdout.write(JSON.stringify([E.geometry(h,.8),[1.2,2,3,3.5,4].map(t=>N.blockFlight({at:4.2,warning:3.15,freezeStart:1.5,freezeEnd:3.5},t))]));});"
        g,flights=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(h).encode()))
        actual=geometry(h,.8)
        for k in ('x','y','vx','vy'):self.assertAlmostEqual(g[k],actual[k],places=9)
        self.assertGreater(flights[0],0);self.assertEqual(flights[1],flights[2]);self.assertEqual(flights[1],flights[3]);self.assertGreater(flights[-1],flights[3])
        s=self.state('nz_ainz_p2_0');bs=block_threats(s['p'],42,parameters(s['p'],{}))
        self.assertEqual(len(bs),10);self.assertTrue(all(e['at']-e['warning']<e['freezeStart'] for e in bs))

    def test_all_orb_statuses_use_verified_contacts_and_do_not_stack_indefinitely(self):
        from arena_nazarick_patterns import STONE_STATUSES
        f=encounter(1)['players']['10']['fighter'];guard=dict(pattern_dodge=dict(contacts=[dict(status=k,weight=.2) for k in STONE_STATUSES]))
        for _ in range(4):notes=contact_afflictions(f,'nz_ainz_p2_2',dict(hit=True,damage=10),guard)
        self.assertEqual(len(notes),7)
        self.assertEqual(len([e for e in f['effects'] if e['id'].startswith('nz_contact_')]),8)
        before=deepcopy(f);guard['pattern_dodge']['contacts']=[dict(status=k,weight=0,reduction=1) for k in STONE_STATUSES]
        self.assertEqual(contact_afflictions(f,'nz_ainz_p2_2',dict(hit=True,damage=10),guard),[]);self.assertEqual(f,before)


class RewardStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=nztests.StoreTests.asyncSetUp
    asyncTearDown=nztests.StoreTests.asyncTearDown

    def wipe(self,party=False):
        row=self.db._raid_row_locked(self.row['token']);d=json.loads(row['data_json'])
        if party:
            first=deepcopy(d['players']['10'])
            for actor in(20,30):
                p=deepcopy(first);p.update(actor_id=actor,fighter_id=actor,slave_owner=actor)
                d['players'][str(actor)]=p;d['nazarick']['initial_players'][str(actor)]=deepcopy(p['fighter'])
        d['nazarick'].update(stage=3,phase=2);load_stage(d)
        for p in d['players'].values():p['fighter']['hp']=0
        offer_blessing(d);self.db._raid_save_locked(row,d);self.db.connection.commit()
        return self.db._raid_row_locked(row['token']),d

    async def test_vote_api_preserves_deadline_and_rejects_actions_foreign_stale(self):
        row,d=self.wipe(True);oid=d['nazarick']['blessing_offer']['id'];deadline=row['deadline']
        for actor,offer in ((99,oid),(10,'stale')):
            with self.assertRaises(ValueError):await self.db.arena_raid_setup(row['token'],actor,'blessing_accept',blessing_id=offer)
        with self.assertRaises(ValueError):await self.db.arena_raid_action(row['token'],10,row['revision'],'defend')
        row=await self.db.arena_raid_setup(row['token'],10,'blessing_accept',blessing_id=oid)
        self.assertEqual(row['deadline'],deadline)
        revision=row['revision'];row=await self.db.arena_raid_setup(row['token'],10,'blessing_accept',blessing_id=oid)
        self.assertEqual(row['revision'],revision)
        await self.db.arena_raid_setup(row['token'],20,'blessing_accept',blessing_id=oid)
        results=await asyncio.gather(*(self.db.arena_raid_setup(row['token'],30,'blessing_accept',blessing_id=oid) for _ in range(2)),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,ValueError) for r in results),1)
        d=json.loads(self.db._raid_row_locked(row['token'])['data_json'])
        self.assertEqual((d['nazarick']['stage'],d['nazarick']['phase']),(3,1))
        self.assertTrue(d['nazarick']['blessed'])
        self.assertEqual(self.db._arena_profile_locked(1,10,True)['class_id'],'mage')

    async def test_vote_timeout_or_refusal_gives_nothing(self):
        row,d=self.wipe();oid=d['nazarick']['blessing_offer']['id']
        self.db.connection.execute('UPDATE arena_raids SET deadline=? WHERE token=?',(int(time.time())-1,row['token']));self.db.connection.commit()
        await self.db.arena_raid_expire()
        row=self.db._raid_row_locked(row['token']);self.assertEqual(row['status'],'finished')
        self.assertEqual(json.loads(row['data_json'])['rewards'],{})

    async def test_loot_one_trophy_ticket_70_percent_and_no_duplicate_settlement(self):
        from test_arena_daily_balance import LootRoll
        row=self.db._raid_row_locked(self.row['token']);d=json.loads(row['data_json']);d.update(finished=True,won=True)
        d['players']['10']['manual_turns']=2
        with patch('arena_raid.random.SystemRandom',return_value=LootRoll(.69)):
            self.db._raid_finish_locked(row,d)
        self.db.connection.commit()
        items=self.db._arena_inventory_locked(1,10)
        self.assertEqual(sum(i['quantity'] for i in items if i['content_id'] in RELIC_IDS),1)
        self.assertEqual(sum(i['quantity'] for i in items if i['content_id']==TICKET_ID),1)
        self.assertTrue(d['rewards']['10']['class_ticket'])
        with self.assertRaises(ValueError):self.db._raid_finish_locked(row,d)
        self.assertEqual(items,self.db._arena_inventory_locked(1,10))
        self.assertFalse((await self.db.arena_raid_reward_status(10))['nazarick']['full_reward'])

    async def test_blessing_forfeits_only_ticket_not_trophy_and_no_shop_relics(self):
        from test_arena_daily_balance import LootRoll
        row,d=self.wipe();oid=d['nazarick']['blessing_offer']['id']
        row=await self.db.arena_raid_setup(row['token'],10,'blessing_accept',blessing_id=oid)
        d=json.loads(row['data_json']);d.update(finished=True,won=True);d['players']['10']['manual_turns']=2
        with patch('arena_raid.random.SystemRandom',return_value=LootRoll(0)):self.db._raid_finish_locked(row,d)
        self.db.connection.commit()
        items=self.db._arena_inventory_locked(1,10)
        self.assertEqual(len(items),1);self.assertIn(items[0]['content_id'],RELIC_IDS)
        self.assertFalse(d['rewards']['10']['class_ticket'])
        shop=self.db._arena_shop_catalog_locked()
        self.assertTrue(all(('passive',key) not in shop for key in RELIC_IDS))

    async def test_ticket_chance_boundary_and_repeat_no_items(self):
        from test_arena_daily_balance import LootRoll
        row=self.db._raid_row_locked(self.row['token']);d=json.loads(row['data_json']);d.update(finished=True,won=True)
        d['players']['10']['manual_turns']=2
        with patch('arena_raid.random.SystemRandom',return_value=LootRoll(.70)):self.db._raid_finish_locked(row,d)
        self.db.connection.commit();self.assertFalse(d['rewards']['10']['class_ticket'])
        before=self.db._arena_inventory_locked(1,10)
        row=await self.db.arena_raid_create(1,10,boss_id='nazarick',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        d=json.loads(row['data_json']);d.update(finished=True,won=True);d['players']['10']['manual_turns']=2
        with patch('arena_raid.random.SystemRandom',return_value=LootRoll(0)):self.db._raid_finish_locked(row,d)
        self.db.connection.commit()
        self.assertEqual(before,self.db._arena_inventory_locked(1,10));self.assertFalse(d['rewards']['10']['full_reward'])

    async def test_trophy_can_be_learned_equipped_and_carried_into_real_combat(self):
        self.db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE token=?",(self.row['token'],))
        self.db._arena_add_item_locked(1,10,'passive',RELIC_IDS[0],'legendary');self.db.connection.commit()
        item=next(i for i in self.db._arena_inventory_locked(1,10) if i['content_id']==RELIC_IDS[0])
        self.assertEqual(item['name'],'Маска Пандоры')
        await self.db.arena_use_item(1,10,item['id'],10)
        profile=self.db._arena_profile_locked(1,10,True)
        self.assertIn(RELIC_IDS[0],json.loads(profile['passive_loadout']))
        row=await self.db.arena_raid_create(1,10,boss_id='nazarick',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        from arena_fingers import has_trait
        self.assertTrue(has_trait(json.loads(row['data_json'])['players']['10']['fighter'],RELIC_IDS[0]))

    async def test_ticket_preserves_level_xp_learned_inventory_sprite_and_locks(self):
        self.db._arena_add_item_locked(1,10,'class_ticket',TICKET_ID,'legendary')
        self.db.connection.execute("INSERT OR IGNORE INTO arena_learned VALUES(0,10,1,'skill','smack')")
        self.db.connection.execute("INSERT OR IGNORE INTO arena_learned VALUES(0,10,1,'passive','light_step')")
        self.db.connection.commit()
        item=next(i for i in self.db._arena_inventory_locked(1,10) if i['content_id']==TICKET_ID)['id']
        with self.assertRaises(ValueError):await self.db.arena_use_item(1,10,item,10,confirm=True,new_class='warrior')
        self.db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE token=?",(self.row['token'],));self.db.connection.commit()
        await self.db.arena_set_sprite(1,10,b'test-image',False)
        before=dict(self.db._arena_profile_locked(1,10,True));learned=list(self.db.connection.execute('SELECT * FROM arena_learned').fetchall())
        for kwargs in (dict(new_class='warrior'),dict(confirm=True,new_class='gambler'),dict(confirm=True,new_class='mage'),dict(confirm=True,new_class='warrior',expected_slot=2)):
            with self.assertRaises(ValueError):await self.db.arena_use_item(1,10,item,10,**kwargs)
        await self.db.arena_use_item(1,10,item,10,confirm=True,new_class='warrior',expected_slot=1)
        after=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((after['level'],after['xp']),(before['level'],before['xp']))
        self.assertEqual((after['class_id'],after['archclass_id']),('warrior',''))
        self.assertEqual(learned,list(self.db.connection.execute('SELECT * FROM arena_learned').fetchall()))
        self.assertIn('smack',self.db._arena_known_skills_locked(1,10,True))
        self.assertTrue((await self.db.arena_sprite_info(1,10))['sprite_url'])
        self.assertFalse(self.db._arena_inventory_locked(1,10))
        from arena_web import menu_view
        view=await menu_view(self.db,1,10)
        self.assertTrue(view['personal']['progression_choice'])


if __name__=='__main__':unittest.main()
