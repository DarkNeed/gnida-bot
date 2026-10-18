import copy
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state,
    effective_skill, resolve_skill, unlocked_skill_ids, battle_status_snapshot)
from arena_archclasses import ARCHCLASSES
from arena_mastery import BASE, BRANCHES, path, view, info, final_base
from arena_evolution import evolution_info
from arena_raid_engine import native_attack, raid_snapshot, create_raid_state
from arena_web import menu_view, battle_view
from database import Database
from test_arena_rebalance import FixedRoll
import test_arena_market_client as client_tests


PRIMARY = dict(ragamuffin='bum_punch',cutie='meow',jock='smack',nerd='humiliate',
    thumb='senior_verdict',index='last_line',middle='whole_family',ring='last_stroke',
    pinky='moon_arc',warrior='warrior_execute',mage='mana_overload',priest='holy_judgment',hunter='hunter_cut')


class MasteryEngineTests(unittest.TestCase):
    def state(self, cls='mage', level=20, resolved=20, arch='', stage=10):
        state=create_battle_state(dict(slave_id=10,owner_id=10,class_id=cls,level=level,
            progression_level=resolved,archclass_id=arch,archclass_stage=stage),
            dict(slave_id=20,owner_id=20,class_id='jock',level=20))
        for s in state['sides'].values():
            s['hp']=s['stats']['max_hp']=1000
            s['loadout']=list(BUILTIN_SKILLS)
        return state

    def prepare(self, state, branch=False):
        a,b=state['sides'].values()
        a['mastery_state']=dict(street_ready=True,combo=['a','b','c'],last_cute='uwu',
            theory_ready=True,executions=2,flow=3,prayers=3,hunt_ready=True)
        a['effects']=[dict(id='evolution_prepared',kind='prepared_attack',value=1,duration=2)]
        a['mechanics']=dict(order=3,grudge=3,focus=3,last_attack='bum_punch',
            prescript=BRANCHES[a['archclass_id']][0] if branch else 'last_line')
        a['rpg_state']=dict(onslaught=3,steadfast=3,souls=3,summon=3,summon_power=6,
            faith=3,retribution=3,beast=3,echo_ready=True,visceral_ready=True,visceral_until=4,moon_mark=True)
        b['effects']=[dict(id='adoration',kind='damage_pct',value=-.4,duration=3),
            dict(id='doxxing_magic',kind='magic_defense_pct',value=-.2,duration=3),
            dict(id='rpg_burn',kind='burn',value=3,duration=3),
            dict(id='dust',kind='accuracy_flat',value=-15,duration=3)]

    def tap(self,state,sid,roll=0,**kwargs):
        a=state['sides']['a'];a['cooldowns'].pop(sid,None);state['active_side']='a'
        return resolve_skill(state,'a',sid,rng=FixedRoll(roll),advance_turn=False,**kwargs)

    def test_all_thirteen_base_paths_have_real_final_variants_and_keep_slots(self):
        self.assertEqual(set(BASE),set(FIGHTER_CLASSES))
        for cls in BASE:
            with self.subTest(cls=cls):
                state=self.state(cls);self.prepare(state)
                a,b=state['sides'].values();sid=PRIMARY[cls]
                variant=effective_skill(state,'a',sid)
                self.assertIn('mastery_base',variant.tags)
                self.assertEqual(variant.skill_id,sid)
                before=copy.deepcopy((a['loadout'],a['passive_details']))
                event=self.tap(state,sid)
                self.assertEqual((a['loadout'],a['passive_details']),before)
                self.assertGreaterEqual(a['resource'],0)
                self.assertIn('mastery_state',event['status_after']['a'])
                self.assertEqual(json.loads(json.dumps(state)),state)
                self.assertEqual(view(a)['stage'],20)

    def test_all_twenty_five_retained_branches_get_conditional_mastery(self):
        self.assertEqual(set(BRANCHES),set(ARCHCLASSES))
        for arch,entry in BRANCHES.items():
            with self.subTest(arch=arch):
                state=self.state(ARCHCLASSES[arch]['class_id'],arch=arch);self.prepare(state,True)
                a=state['sides']['a'];sid=entry[0]
                self.assertEqual(path(a),'branch')
                v=effective_skill(state,'a',sid)
                self.assertIn('mastery_branch',v.tags)
                self.assertEqual(v.name,entry[1])
                self.assertEqual(evolution_info(BUILTIN_SKILLS[sid],a['class_id'],a,state['sides']['b'])['min_level'],20)
                count=len(a['passive_details'])
                self.tap(state,sid)
                self.assertEqual(len(a['passive_details']),count)
                self.assertGreaterEqual(a['resource'],0)
                self.assertEqual(view(a)['kind'],'branch')

    def test_not_granted_by_level_alone_no_stacking_no_boss_mastery(self):
        for cls in BASE:
            for level,resolved in ((4,20),(20,0)):
                self.assertFalse(path(dict(class_id=cls,level=level,progression_level=resolved)))
        for arch,entry in ARCHCLASSES.items():
            for stage,resolved in ((20,20),(10,10),(20,0)):
                a=self.state(entry['class_id'],arch=arch,stage=stage,resolved=resolved)['sides']['a']
                self.assertFalse(path(a))
            a=self.state(entry['class_id'],arch=arch)['sides']['a'];a['is_boss']=True
            self.assertFalse(path(a))
        state=self.state('mage',level=20,resolved=10)
        self.assertFalse(final_base(state['sides']['a']))
        self.assertFalse(view(state['sides']['a'])['milestones'][-1]['unlocked'])

    def test_skill_unlocks_do_not_leak_to_other_classes_branches_grants_or_npcs(self):
        for cls in BASE:
            key='mastery_'+cls
            self.assertIn(key,unlocked_skill_ids(cls,15,progression_level=10))
            self.assertNotIn(key,unlocked_skill_ids(cls,14,progression_level=10))
            self.assertNotIn(key,unlocked_skill_ids(cls,20,progression_level=0))
            self.assertNotIn(key,unlocked_skill_ids('jock' if cls!='jock' else 'mage',20,granted=[key],progression_level=20))
            branches=[a for a,e in ARCHCLASSES.items() if e['class_id']==cls]
            if branches:self.assertNotIn(key,unlocked_skill_ids(cls,20,archclass_id=branches[0],progression_level=20))
        state=self.state('mage',arch='mage_necromancer')
        before=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'мастерства'):self.tap(state,'mastery_mage')
        self.assertEqual(before,state)

    def test_all_level_fifteen_skills_execute_and_improve_at_eighteen(self):
        for cls in BASE:
            sid='mastery_'+cls
            for level in (15,18):
                with self.subTest(cls=cls,level=level):
                    state=self.state(cls,level=level,resolved=10)
                    if cls=='priest':state['sides']['a']['hp']=500
                    v=effective_skill(state,'a',sid)
                    expected=BUILTIN_SKILLS[sid].power+(4 if level==18 and v.damage_type else 0)
                    self.assertEqual(v.power,expected)
                    event=self.tap(state,sid)
                    self.assertTrue(event['hit'])

    def test_preview_and_failed_cast_never_change_state(self):
        for cls in BASE:
            state=self.state(cls);self.prepare(state)
            a,b=state['sides'].values();a['resource']=0;sid=PRIMARY[cls]
            before=copy.deepcopy(state)
            for _ in range(3):
                effective_skill(state,'a',sid)
                info(BUILTIN_SKILLS[sid],a,b)
            self.assertEqual(before,state)
            if cls=='ragamuffin':
                self.assertEqual(effective_skill(state,'a',sid).cost,0)
                continue  # The emergency attack deliberately remains usable.
            with self.assertRaises(ValueError):resolve_skill(state,'a',sid)
            self.assertEqual(before,state)

    def test_ragamuffin_growth_only_after_stay_and_street_combo(self):
        source=dict(slave_id=1,owner_id=1,class_id='ragamuffin',level=5)
        old=create_battle_state(source,source)['sides']['a']
        new=create_battle_state(dict(source,progression_level=5),source)['sides']['a']
        self.assertEqual(old['stats']['max_hp'],36)
        self.assertEqual(new['stats']['max_hp'],46)
        self.assertIn('street_breath',new['loadout'])
        state=self.state('ragamuffin')
        for sid in ('dust_in_eyes','street_breath','mastery_ragamuffin'):self.tap(state,sid)
        self.assertEqual(effective_skill(state,'a','bum_punch').name,'Последний из подворотни')
        self.tap(state,'bum_punch');self.assertEqual(state['sides']['a']['mastery_state']['combo'],[])

    def test_cutie_alternation_keeps_adoration_at_twenty(self):
        state=self.state('cutie');a,b=state['sides'].values()
        self.tap(state,'mastery_cutie');self.tap(state,'uwu')
        self.assertEqual(effective_skill(state,'a','meow').name,'Милота массового поражения')
        self.tap(state,'meow')
        self.assertTrue(any(e.get('id')=='adoration' for e in b['effects']))

    def test_jock_three_independent_hits_one_cost_one_pet_proc(self):
        class Rolls(FixedRoll):
            def __init__(self):self.values=iter([0,.99,0])
            def random(self):return next(self.values,0)
        state=self.state('jock');self.prepare(state)
        with patch('arena_engine.pet_after_action',return_value=[]) as pet:
            event=resolve_skill(state,'a','smack',rng=Rolls(),advance_turn=False)
        self.assertEqual([p['hit'] for p in event['hit_results']],[True,False,True])
        self.assertEqual(state['sides']['a']['resource'],70)
        self.assertEqual(event['damage'],sum(event['hits']))
        pet.assert_called_once()

    def test_nerd_three_categories_count_misses_and_consumption_is_one_use(self):
        state=self.state('nerd');a=state['sides']['a']
        self.tap(state,'doxxing',roll=.99);self.tap(state,'humiliate',roll=.99);self.tap(state,'go_to_store')
        self.assertTrue(a['mastery_state']['theory_ready'])
        self.assertEqual(effective_skill(state,'a','humiliate').name,'Я просчитал этот бой')
        self.tap(state,'humiliate',roll=.99)
        self.assertFalse(a['mastery_state']['theory_ready'])

    def test_middle_uses_real_pre_hit_grudge_and_no_revenge_recoil(self):
        state=self.state('middle');a=state['sides']['a'];a['mechanics']=dict(grudge=3)
        self.tap(state,'whole_family',roll=.99)
        self.assertEqual(a['mechanics']['grudge'],3)
        event=self.tap(state,'whole_family')
        self.assertEqual(a['mechanics']['grudge'],1)
        self.assertEqual(event['self_damage'],0)

    def test_ring_retains_only_owned_effects_not_allied_setup(self):
        state=self.state('ring');a,b=state['sides'].values()
        self.tap(state,'unfinished_portrait');self.tap(state,'first_stroke')
        b['effects'].append(dict(id='ally',kind='speed_pct',value=-.2,duration=3,mastery_owner=999))
        self.tap(state,'last_stroke')
        owned=[e for e in b['effects'] if e.get('mastery_owner')==10]
        self.assertGreaterEqual(len(owned),2)
        self.assertFalse(any(e.get('id')=='ally' for e in b['effects']))

    def test_index_self_written_order_no_confirmation_and_miss_counts(self):
        state=self.state('index');a=state['sides']['a']
        self.tap(state,'mastery_index')
        self.assertTrue(a['mastery_state']['free_prescript'])
        event=self.tap(state,'first_line',roll=.99)
        self.assertIn('предписание исполнено',event['text'])
        self.assertEqual(a['mastery_state']['executions'],1)
        self.assertFalse(a['mastery_state']['free_prescript'])

    def test_self_written_order_also_gets_normal_prescript_transformation_and_pierce(self):
        from arena_fingers import combat_modifiers
        state=self.state('index');a,b=state['sides'].values()
        self.tap(state,'mastery_index')
        skill=effective_skill(state,'a','last_line')
        self.assertEqual(skill.name,'Предписание исполнено')
        self.assertEqual(combat_modifiers(a,b,skill,FixedRoll())[2],.35)

    def test_warrior_armor_step_and_cap_and_finisher_above_execute_threshold(self):
        state=self.state('warrior');a,b=state['sides'].values()
        self.tap(state,'armor_split')
        self.assertEqual(next(e['value'] for e in b['effects'] if e.get('id')=='armor_split'),-.25)
        self.tap(state,'armor_split')
        self.assertEqual(next(e['value'] for e in b['effects'] if e.get('id')=='armor_split'),-.45)
        self.tap(state,'steel_charge');self.tap(state,'counter_lunge')
        self.assertGreater(b['hp'],b['stats']['max_hp']*.3)
        self.assertEqual(effective_skill(state,'a','warrior_execute').power,28)

    def test_mage_misses_give_flow_refund_only_on_hit_and_guard_is_alternative(self):
        state=self.state('mage');a=state['sides']['a']
        for _ in range(3):self.tap(state,'mana_shot',roll=.99)
        self.assertEqual(a['mastery_state']['flow'],3)
        a['resource']=100
        self.tap(state,'mana_overload',roll=.99)
        self.assertEqual(a['resource'],65)
        self.assertEqual(a['mastery_state']['flow'],3)
        self.tap(state,'mana_overload')
        self.assertEqual(a['resource'],40)
        self.assertEqual(a['mastery_state']['flow'],0)
        a['mastery_state']['flow']=3
        self.tap(state,'mana_barrier')
        self.assertEqual(a['mastery_state']['flow'],0)
        self.assertEqual(next(e['value'] for e in a['effects'] if e.get('id')=='mana_barrier'),.5)

    def test_priest_no_prayers_or_mercy_for_full_hp_heal_and_one_miracle(self):
        state=self.state('priest');a=state['sides']['a']
        self.tap(state,'priest_heal')
        self.assertEqual(a['mastery_state'].get('prayers',0),0)
        self.assertFalse(a['mastery_state'].get('mercy_ready'))
        a['hp']=200;a['resource']=100
        self.tap(state,'priest_heal')
        self.assertEqual(a['mastery_state']['prayers'],1)
        self.assertTrue(a['mastery_state']['mercy_ready'])
        a['mastery_state']['prayers']=3
        a['resource']=100
        self.assertEqual(effective_skill(state,'a','priest_heal').effects[0]['value'],.5)
        self.tap(state,'priest_heal')
        self.assertEqual(a['mastery_state']['prayers'],0)

    def test_priest_heals_raid_ally_and_gains_prayer(self):
        state=self.state('priest');a,b=state['sides'].values()
        ally=copy.deepcopy(a);ally['controller_id']=99;ally['hp']=100
        self.tap(state,'priest_heal',allies=[a,ally])
        self.assertGreater(ally['hp'],100)
        self.assertEqual(a['mastery_state']['prayers'],1)
        self.assertTrue(a['mastery_state']['mercy_ready'])

    def test_hunter_two_attacks_and_no_self_refreshing_chain(self):
        state=self.state('hunter');a=state['sides']['a']
        a['rpg_state']=dict(visceral_ready=True,visceral_until=5)
        self.tap(state,'hunter_visceral')
        self.assertEqual(a['mastery_state']['hunt_chain'],2)
        for _ in range(2):self.tap(state,'hunter_cut')
        self.assertEqual(a['mastery_state']['hunt_chain'],0)

    def test_branch_mastery_consumes_and_preserves_existing_resources_correctly(self):
        for arch,counter,value in (('warrior_berserker','onslaught',1),('mage_necromancer','souls',1),
            ('priest_bishop','faith',1),('priest_paladin','retribution',2),('hunter_beast','beast',1)):
            state=self.state(ARCHCLASSES[arch]['class_id'],arch=arch);self.prepare(state,True)
            self.tap(state,BRANCHES[arch][0])
            self.assertEqual(state['sides']['a']['rpg_state'][counter],value,arch)

    def test_programmer_optimization_and_knight_guard_do_not_double_stack(self):
        state=self.state('nerd',arch='programmer');a=state['sides']['a']
        a['cooldowns']['mother_joke']=5
        self.tap(state,'arch_programmer')
        # One normal action tick, plus two actions of explicit optimization.
        self.assertEqual(a['cooldowns']['mother_joke'],2)
        state=self.state('warrior',arch='warrior_knight');self.prepare(state,True)
        self.tap(state,'arch_warrior_knight')
        guards=[e for e in state['sides']['a']['effects'] if e['kind']=='incoming_damage_multiplier']
        self.assertEqual([e['value'] for e in guards],[.65])

    def test_branch_necromancer_full_miss_keeps_souls_and_does_not_heal(self):
        state=self.state('mage',arch='mage_necromancer');self.prepare(state,True)
        a=state['sides']['a'];a['hp']=500;a['rpg_state']['summon']=0
        self.tap(state,'arch_mage_necromancer',roll=.99)
        self.assertEqual(a['rpg_state']['souls'],3)
        self.assertEqual(a['hp'],500)

    def test_street_dust_cost_does_not_rise_when_old_evolution_opens(self):
        state=self.state('ragamuffin');a=state['sides']['a']
        for turns in (0,4,12):
            a['own_turns']=turns
            self.assertEqual(effective_skill(state,'a','dust_in_eyes').cost,15)

    def test_mastery_in_real_equipped_build_does_not_require_extra_memory_slots(self):
        for cls in BASE:
            source=dict(slave_id=1,owner_id=1,class_id=cls,level=20,progression_level=20,
                loadout=['bum_punch',PRIMARY[cls],'mastery_'+cls],
                known_skills=['bum_punch',PRIMARY[cls],'mastery_'+cls])
            state=create_battle_state(source,dict(source,slave_id=2,owner_id=2))
            self.assertLessEqual(len(state['sides']['a']['loadout']),4)
            self.assertIn('mastery_'+cls,state['sides']['a']['loadout'])
            state['sides']['a']['hp']=max(1,state['sides']['a']['hp']//2)
            self.tap(state,'mastery_'+cls)

    def test_native_raid_uses_same_mastery_and_detached_snapshot(self):
        state=self.state('mage');self.prepare(state);a,b=state['sides'].values()
        event=native_attack(a,b,'mana_overload',BUILTIN_SKILLS,FixedRoll())
        self.assertEqual(event['skill_name'],'Идеальный поток')
        snapshot=battle_status_snapshot(state)
        snapshot['a']['mastery_state']['flow']=999
        self.assertEqual(a['mastery_state']['flow'],0)
        self.assertNotIn('mastery_state',self.state()['sides']['a'])


class MasteryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        self.temp=tempfile.TemporaryDirectory();self.db=Database(Path(self.temp.name)/'mastery.sqlite3')
        await self.db.connect();await self.db.upsert_chat(1,'Test')
        for user in (10,20):
            await self.db.upsert_user(1,user,str(user),str(user));await self.db.arena_menu(1,user)

    async def asyncTearDown(self):
        await self.db.close();self.temp.cleanup()

    def profile(self,cls='mage',level=20,resolved=20,arch='',stage=10):
        self.db.connection.execute('UPDATE personal_profiles SET class_id=?,level=?,progression_level=?,archclass_id=?,archclass_stage=? WHERE chat_id=0 AND user_id=10',
            (cls,level,resolved,arch,stage));self.db.connection.commit()

    async def menu(self):return (await menu_view(self.db,1,10))['personal']

    async def test_old_stay_is_retroactive_persistent_and_no_money_or_inventory_rewards(self):
        self.profile()
        before=await self.db.franc_balance(1,10)
        p=await self.menu()
        self.assertEqual(p['mastery']['stage'],20)
        self.assertTrue(any(s['skill_id']=='mastery_mage' for s in p['skill_offers']+p['skills']+p['available_skills']))
        self.assertLessEqual(len(p['known_skills']),6)
        self.assertLessEqual(len(p['loadout']),4)
        await self.db.close();await self.db.connect()
        self.assertEqual((await self.menu())['mastery']['stage'],20)
        self.assertEqual(await self.db.franc_balance(1,10),before)
        async with self.db._lock:
            self.assertFalse(any(k[1].startswith('mastery_') or k[1]=='street_breath' for k in self.db._arena_shop_catalog_locked()))
            self.assertFalse(any(k[1].startswith('mastery_') for k in self.db._forge_catalog_locked()))

    async def test_ragamuffin_has_three_choices_and_can_stay_or_change_later(self):
        self.profile('ragamuffin',20,0)
        for level in (5,10,20):
            p=await self.menu()
            self.assertEqual(p['progression_choice']['level'],level)
            self.assertIn('Путь мастерства',p['progression_choice']['options'][0]['description'])
            await self.db.arena_edit_profile(1,10,10,True,'progression','stay')
        p=await self.menu();self.assertIsNone(p['progression_choice'])
        self.assertEqual(p['class_id'],'ragamuffin')
        self.assertEqual(p['mastery']['stage'],20)
        self.profile('ragamuffin',20,10)
        await self.db.arena_edit_profile(1,10,10,True,'progression','mage')
        p=await self.menu()
        self.assertEqual(p['class_id'],'mage')
        self.assertIsNone(p['mastery'])
        self.assertEqual(p['progression_choice']['level'],10)

    async def test_branch_choice_replaces_base_mastery_and_new_skill_is_not_retained(self):
        self.profile('mage',20,10)
        p=await self.menu();self.assertEqual(p['mastery']['stage'],10)
        await self.db.arena_edit_profile(1,10,10,True,'progression','mage_necromancer')
        p=await self.menu();self.assertIsNone(p['mastery'])
        self.assertNotIn('mastery_mage',p['known_skills'])
        self.assertEqual(p['archclass']['stage'],20)

    async def test_retained_branch_snapshot_contains_explicit_choice_and_view(self):
        self.profile('jock',20,10,'mge_bro')
        await self.db.arena_edit_profile(1,10,10,True,'progression','stay')
        self.assertEqual((await self.menu())['mastery']['kind'],'branch')
        row=await self.db.arena_wasteland(1,10)
        side=(await battle_view(self.db,row,10))['state']['sides']['a']
        self.assertEqual(side['progression_level'],20)
        self.assertEqual(side['mastery']['kind'],'branch')

    async def test_reset_removes_mastery_without_new_columns_or_consumables(self):
        self.profile()
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        p=await self.menu()
        self.assertIsNone(p['mastery'])
        self.assertEqual(p['progression_choice']['level'],5)

    async def test_loadout_can_equip_unlocked_mastery_skill_and_rejects_foreign_one(self):
        self.profile()
        await self.menu()
        await self.db.arena_edit_profile(1,10,10,True,'forget_skill','dust_in_eyes')
        await self.db.arena_edit_profile(1,10,10,True,'learn_skill','mastery_mage')
        await self.db.arena_edit_profile(1,10,10,True,'loadout',['mastery_mage','mana_shot'])
        self.assertIn('mastery_mage',(await self.menu())['loadout'])
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,10,10,True,'loadout',['mastery_jock'])


class MasteryClientTests(unittest.TestCase):
    def test_mastery_card_is_rendered_without_extra_combat_slots(self):
        runner=client_tests.ArenaMarketClientTests()
        data=dict(class_id='ragamuffin',level=20,progression_level=20)
        result=runner.run_client('out=archInfo(input);',dict(mastery=view(data)))
        self.assertIn('Совершенное мастерство',result)
        self.assertIn('Уличная закалка',result)
        self.assertIn('Последний из подворотни',result)
