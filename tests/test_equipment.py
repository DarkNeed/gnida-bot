"""Equipment ownership, reward idempotency, snapshots and native/QTE combat."""
from copy import deepcopy
import json
import random
import secrets
import time
import unittest
from aiohttp.test_utils import TestClient,TestServer
import test_guild as guild_tests
from test_arena import signed,TOKEN
from arena_web import create_arena_app,menu_view
from arena_engine import create_battle_state,resolve_skill,Skill
import arena_equipment as gear


def item(key,rarity='epic',rank='C'):
    return dict(id='test-'+key,key=key,rank=rank,rarity=rarity,upgrade=0,affixes=[])


def battle(first=(),second=()):
    source=dict(slave_id=10,owner_id=10,class_id='warrior',level=20,passive_details=[],
                loadout=['bum_punch'],progression_level=20,equipment=list(first))
    target=dict(source,slave_id=20,owner_id=20,equipment=list(second))
    state=create_battle_state(source,target)
    for f in state['sides'].values():f['stats']['evasion']=0
    return state


class EquipmentCombatTests(unittest.TestCase):
    def test_catalog_and_weights(self):
        self.assertEqual(len(gear.CATALOG),32)
        self.assertEqual(len({v['slot'] for v in gear.CATALOG.values()}),4)
        self.assertTrue(all(sum(row)==100 for row in gear.CHANCES))

    def test_snapshot_deepcopy_stats_and_no_energy_changes(self):
        pieces=[item('fang')];state=battle(pieces)
        bare=battle();pieces[0]['upgrade']=5
        self.assertEqual(state['sides']['a']['equipment'][0]['upgrade'],0)
        self.assertGreater(state['sides']['a']['stats']['physical_attack'],bare['sides']['a']['stats']['physical_attack'])
        for k in ('resource_max','resource_regen'):
            self.assertEqual(state['sides']['a']['stats'][k],bare['sides']['a']['stats'][k])

    def test_no_proc_on_rare_and_conditional_bleed(self):
        state=battle([item('fang','rare')]);a,b=state['sides'].values();skill=Skill('s','s','warrior',1,'physical',20,100,0,0)
        b['effects'].append(dict(kind='bleed',value=2,duration=3))
        self.assertEqual(gear.modifiers(a,b,skill),1)
        a['equipment']=[item('fang')]
        self.assertAlmostEqual(gear.modifiers(a,b,skill),1.2)
        b['effects']=[];self.assertEqual(gear.modifiers(a,b,skill),1)

    def test_stone_once_per_action_not_per_projectile(self):
        state=battle(second=[item('golem')]);side=state['sides']['b']
        self.assertEqual(gear.incoming(side,30,[10,1]),25)
        self.assertEqual(gear.incoming(side,30,[10,1]),30)
        self.assertEqual(gear.incoming(side,30,[10,2]),25)

    def test_save_once_and_healing_penalty(self):
        state=battle(second=[item('mantle')]);a,b=state['sides'].values();b['hp']=20
        self.assertEqual(gear.incoming(b,100,[10,1]),19)
        b['hp']=1
        self.assertEqual(gear.heal_amount(a,b,20),10)
        self.assertGreater(gear.incoming(b,100,[10,2]),b['hp'])
        b['own_turns']=2;self.assertEqual(gear.heal_amount(a,b,20),20)
        self.assertEqual(gear.heal_amount(b,b,20),10)
        b['own_turns']=3;self.assertEqual(gear.heal_amount(b,b,20),20)

    def test_troll_cooldown_and_no_resurrection(self):
        state=battle(second=[item('heart')]);a,b=state['sides'].values();maximum=b['stats']['max_hp'];old=maximum
        b['hp']=maximum//2;gear.after_action(a,b,Skill('s','s','warrior',1,'physical',20,100,0,0),old-b['hp'],old,0,[10,1])
        healed=b['hp'];self.assertGreater(healed,maximum//2)
        b['hp']=maximum//2;gear.after_action(a,b,Skill('s','s','warrior',1,'physical',20,100,0,0),old-b['hp'],old,0,[10,2])
        self.assertEqual(b['hp'],maximum//2)
        b['hp']=0;b['own_turns']=3;gear.after_action(a,b,Skill('s','s','warrior',1,'physical',20,100,0,0),old,old,0,[10,3]);self.assertEqual(b['hp'],0)

    def test_dot_owned_repeat_and_cap(self):
        state=battle([item('eye')]);a,b=state['sides'].values();previous=None
        for n in range(6):
            new=dict(id='bleed',kind='bleed',value=2)
            gear.enhance_dot(a,new,previous);previous=new
            self.assertEqual(new['value'],2+min(3,n))
        other=dict(b,equipment=[item('eye')]);new=dict(id='bleed',kind='bleed',value=2)
        gear.enhance_dot(other,new,previous);self.assertEqual(new['value'],2)

    def test_cycle_and_opener_consume_misses(self):
        state=battle([item('ledger'),item('brick')]);a,b=state['sides'].values();s=Skill('s','s','warrior',1,'physical',20,100,0,0)
        self.assertAlmostEqual(gear.modifiers(a,b,s),.9*1.3)
        gear.after_action(a,b,s,0,b['hp'],0,[10,1]);self.assertAlmostEqual(gear.modifiers(a,b,s),.9)
        gear.after_action(a,b,s,0,b['hp'],0,[10,2]);self.assertAlmostEqual(gear.modifiers(a,b,s),1.4)

    def test_summon_refund_once_without_plague_cleansing(self):
        state=battle([item('staff')]);a,b=state['sides'].values();a['resource']=30
        s=Skill('s','s','warrior',1,'magic',20,100,0,0)
        gear.after_action(a,b,s,0,b['hp'],1,[10,1]);self.assertEqual(a['resource'],45)
        gear.after_action(a,b,s,0,b['hp'],1,[10,2]);self.assertEqual(a['resource'],45)

    def test_native_and_weighted_qte_budget_keep_equipment_bonus(self):
        s=Skill('test_hit','test hit','warrior',1,'physical',30,100,0,0)
        catalog={s.skill_id:s}
        outputs=[]
        for equipped in ([],[item('brick')]):
            state=battle(equipped);state['sides']['a']['loadout']=[s.skill_id]
            event=resolve_skill(state,'a',s.skill_id,catalog,random.Random(5),advance_turn=False,
                qte={'attack':[True],'luck_evasion':False,'pattern_attack':{'criticals':[False]}})
            outputs.append(event['damage'])
        self.assertGreater(outputs[1],outputs[0]*1.2)

    def test_weighted_projectiles_reduce_only_five_total(self):
        s=Skill('test_hit','test hit','warrior',1,'physical',40,100,0,0);catalog={s.skill_id:s};outputs=[]
        for equipped in ([],[item('golem')]):
            state=battle(second=equipped);state['sides']['a']['loadout']=[s.skill_id]
            state['sides']['b']['stats']=deepcopy(battle()['sides']['b']['stats'])
            state['sides']['b']['hp']=1000
            event=resolve_skill(state,'a',s.skill_id,catalog,random.Random(9),advance_turn=False,
                qte={'attack':[True],'luck_evasion':False,'pattern_dodge':{
                    'contacts':[dict(strike=0,weight=.1,tick=x) for x in range(10)]}})
            outputs.append(event['damage']);self.assertEqual(sum(c['damage'] for c in event['qte_projectiles']),event['damage'])
        self.assertEqual(outputs[0]-outputs[1],5)


class EquipmentStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=guild_tests.GuildTests.asyncSetUp
    asyncTearDown=guild_tests.GuildTests.asyncTearDown
    create=guild_tests.GuildTests.create
    start=guild_tests.GuildTests.start
    win_room=guild_tests.GuildTests.win_room

    def grant(self,key='fang',actor=10,rank='C',rarity='epic'):
        with self.db.connection:return self.db._gear_grant_locked(actor,key,rank,rarity)

    async def act(self,action,item=None,actor=10,**extra):
        v=await self.db.gear_view(-100,actor)
        return await self.db.gear_action(-100,actor,dict(action=action,item=item,revision=v['revision'],character_slot=v['character_slot'],nonce=secrets.token_hex(10),**extra))

    async def test_foreign_ownership_and_account_scope(self):
        i=self.grant()
        with self.assertRaises(ValueError):await self.act('equip',i['id'],actor=20)
        await self.act('equip',i['id'])
        a=await self.db.gear_view(-100,10);b=await self.db.gear_view(-200,10)
        self.assertEqual(a['equipped'],b['equipped']);self.assertEqual(a['items'],b['items'])

    async def test_protected_salvage_and_upgrade_cap(self):
        i=self.grant()
        with self.db.connection:self.db._gear_material_locked(10,'C',100)
        await self.act('favorite',i['id'])
        with self.assertRaises(ValueError):await self.act('salvage',i['id'])
        await self.act('favorite',i['id']);await self.act('equip',i['id'])
        with self.assertRaises(ValueError):await self.act('salvage',i['id'])
        for _ in range(5):await self.act('upgrade',i['id'])
        with self.assertRaises(ValueError):await self.act('upgrade',i['id'])
        await self.act('unequip',i['id']);v=await self.act('salvage',i['id'])
        self.assertEqual(v['items'],[]);self.assertEqual(v['materials']['C'],78)

    async def test_idempotent_requests_stale_revision_and_failed_rollback(self):
        i=self.grant();v=await self.db.gear_view(-100,10)
        b=dict(action='equip',item=i['id'],revision=v['revision'],character_slot=1,nonce='same-request-001')
        first=await self.db.gear_action(-100,10,b);second=await self.db.gear_action(-100,10,b)
        self.assertEqual(first['revision'],second['revision'])
        with self.assertRaises(ValueError):await self.db.gear_action(-100,10,dict(b,nonce='new-request-002'))
        with self.assertRaises(ValueError):await self.act('upgrade',i['id'])
        current=await self.db.gear_view(-100,10);self.assertEqual(current['items'][0]['upgrade'],0)

    async def test_level_and_character_loadouts(self):
        i=self.grant(rank='S');self.db.connection.execute('UPDATE personal_profiles SET level=7 WHERE chat_id=0 AND user_id=10');self.db.connection.commit()
        with self.assertRaises(ValueError):await self.act('equip',i['id'])
        self.db.connection.execute('UPDATE personal_profiles SET level=20 WHERE chat_id=0 AND user_id=10');self.db.connection.commit()
        await self.act('equip',i['id'])
        with self.db.connection:
            self.db._character_account_locked(10)
            self.db.connection.execute('UPDATE arena_character_accounts SET active_slot=2 WHERE user_id=10')
        self.assertEqual(self.db._gear_snapshot_locked(10,20),[])
        self.assertEqual(len(self.db._gear_snapshot_locked(10,20,1)),1)

    async def test_reroll_once_distinct_and_insufficient_materials(self):
        i=self.grant();v=await self.db.gear_view(-100,10);p=v['items'][0]
        with self.assertRaises(ValueError):await self.act('reroll',i['id'],index=0,choice=p['reroll_options'][0])
        with self.db.connection:self.db._gear_material_locked(10,'C',5)
        v=await self.act('reroll',i['id'],index=0,choice=p['reroll_options'][0]);self.assertTrue(v['items'][0]['rerolled'])
        self.assertEqual(v['materials']['C'],0)
        with self.assertRaises(ValueError):await self.act('reroll',i['id'],index=0,choice=p['reroll_options'][1])

    async def test_busy_snapshots_and_shared_menu_stats(self):
        i=self.grant();v=await self.act('equip',i['id'])
        menu=await menu_view(self.db,-100,10)
        self.assertEqual(menu['personal']['stats'],v['stats'])
        run=await self.start();f=self.db._guild_row_locked(run['id'])['data']['players']['10']['fighter']
        self.assertEqual(f['equipment'][0]['id'],i['id']);self.assertEqual(f['stats'],v['stats'])
        with self.assertRaises(ValueError):await self.act('unequip',i['id'])
        self.db.connection.execute('DELETE FROM gear_items WHERE id=?',(i['id'],));self.db.connection.commit()
        saved=self.db._guild_row_locked(run['id'])['data']['players']['10']['fighter']
        self.assertEqual(saved['stats'],f['stats']);self.assertEqual(saved['equipment'],f['equipment'])

    async def test_guaranteed_personal_loot_exactly_once_and_no_loss_rewards(self):
        run=await self.start(party=True)
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id'])
                self.db._guild_settle_locked(row,True,'test win')
                first=deepcopy(row['data']['results']);self.db._guild_settle_locked(row,True,'test replay')
        for actor in (10,20):
            drops=first[str(actor)]['equipment_loot'];self.assertEqual(len(drops[0]['items']),1)
            self.assertEqual(len((await self.db.gear_view(-100,actor))['items']),1)
        ids=[first[str(a)]['equipment_loot'][0]['items'][0]['id'] for a in (10,20)];self.assertNotEqual(*ids)
        run=await self.db.guild_create(-100,10,'c_dungeon','another-creation')
        run=await self.db.guild_action(run['id'],10,'start',run['revision'])
        with self.db.connection:
            row=self.db._guild_row_locked(run['id']);self.db._guild_settle_locked(row,False,'failed')
        self.assertEqual(len((await self.db.gear_view(-100,10))['items']),1)

    async def test_api_auth_cannot_supply_owner_or_stats(self):
        i=self.grant()
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)));await client.start_server()
        try:
            response=await client.get('/api/equipment?chat=-100');self.assertNotEqual(response.status,200)
            headers={'X-Telegram-Init-Data':signed(20,int(time.time()))}
            response=await client.get('/api/equipment?chat=-100',headers=headers);v=await response.json();self.assertEqual(v['items'],[])
            response=await client.post('/api/equipment',headers=headers,json=dict(chat=-100,actor=10,action='equip',item=i['id'],revision=v['revision'],character_slot=1,nonce='forged-owner-01'))
            self.assertNotEqual(response.status,200)
            response=await client.get('/api/equipment?chat=-999',headers=headers);self.assertNotEqual(response.status,200)
        finally:await client.close()

    async def test_craft_rank_gate_and_cost(self):
        with self.db.connection:self.db._gear_material_locked(10,'C',48)
        v=await self.act('craft',key='staff',rank='C');self.assertEqual(v['materials']['C'],8)
        self.assertEqual(v['items'][0]['rarity'],'epic')
        v=await self.act('buy',key='brick',rank='C');self.assertEqual(v['materials']['C'],0)
        self.assertEqual(len(v['items']),2)
        with self.assertRaises(ValueError):await self.act('craft',key='staff',rank='S')

    async def test_hero_sprite_and_explicit_equipment_bonuses(self):
        i=self.grant();view=await self.act('equip',i['id'])
        self.assertEqual(view['hero']['sprite_url'],'/static/assets/rpg/warrior.png')
        self.assertFalse(view['hero']['pixel_art'])
        self.assertEqual(view['hero']['name'],'Охотник 10')
        for key in view['stat_names']:
            self.assertAlmostEqual(view['stats'][key],view['base_stats'][key]+view['stat_bonuses'][key])
        self.assertGreater(view['stat_bonuses']['physical_attack'],0)
        key='a'*64
        with self.db.connection:
            self.db.connection.execute('INSERT INTO arena_sprites VALUES(0,?,?,?,1)',(10,key,b'fake-test-bytes'))
        view=await self.db.gear_view(-100,10)
        self.assertEqual(view['hero']['sprite_url'],'/sprites/'+key+'.png')
        self.assertTrue(view['hero']['pixel_art'])
        self.assertEqual(view['hero']['fallback_url'],'/static/assets/rpg/warrior.png')

    async def test_final_branch_sprite_matches_character(self):
        with self.db.connection:
            self.db.connection.execute("UPDATE personal_profiles SET archclass_id='warrior_knight',archclass_stage=20 WHERE chat_id=0 AND user_id=10")
        view=await self.db.gear_view(-100,10)
        self.assertEqual(view['class_name'],'Страж')
        self.assertEqual(view['hero']['sprite_url'],'/static/assets/archclasses/warrior_knight_final.png')
