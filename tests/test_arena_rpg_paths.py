import json
import unittest

from arena_engine import BUILTIN_SKILLS, effective_skill, skip_turn, resolve_skill
from arena_rpg import RPG_BRANCHES
from arena_rpg_paths import PATHS
from arena_progression import pending_choice, choice_avatar
from arena_archclasses import archclass_view
from arena_raid_engine import create_raid_state, resolve_round
from arena_engine import FIGHTER_CLASSES
import test_arena_rpg as helpers
from test_arena_epic import FixedRoll


class RPGPathTests(unittest.TestCase):
    state = helpers.RPGTests.state
    use = helpers.RPGTests.use

    def final(self, key):
        state = self.state(RPG_BRANCHES[key][0], key)
        state['sides']['a'].update(level=20, archclass_stage=20)
        return state

    def test_all_paths_have_distinct_final_names_choice_and_skins(self):
        self.assertEqual(len(PATHS), 9)
        for key, (cls, name, _) in RPG_BRANCHES.items():
            with self.subTest(key=key):
                p=dict(class_id=cls,level=20,archclass_id=key,archclass_stage=10,progression_level=10)
                self.assertEqual(pending_choice(p),20)
                self.assertEqual(archclass_view(p)['title'],name)
                self.assertEqual(archclass_view(dict(p,archclass_stage=20))['title'],PATHS[key][0])
                self.assertNotEqual(name,PATHS[key][0])
                self.assertNotEqual(choice_avatar(cls,key),choice_avatar(cls,key,20))
                self.assertEqual(pending_choice(dict(p,progression_level=20)),0)

    def test_staying_at_ten_has_no_final_skill(self):
        state=self.final('warrior_berserker')
        actor=state['sides']['a'];actor['archclass_stage']=10
        actor['rpg_state']={'heat':5,'onslaught':3}
        skill=effective_skill(state,'a','arch_warrior_berserker')
        self.assertEqual(skill.name,'Кровавый вихрь')
        self.assertEqual(skill.cost,45)

    def test_phoenix_three_rolls_one_payment_and_charge_spend_on_hit(self):
        state=self.final('warrior_berserker');actor=state['sides']['a']
        actor['rpg_state']={'heat':5}
        event=self.use(state,'arch_warrior_berserker')
        self.assertEqual(event['skill_name'],'Всё обратить в пепел')
        self.assertEqual(len(event['hit_results']),3)
        self.assertEqual(actor['resource'],50)
        self.assertEqual(actor['rpg_state']['heat'],2)
        self.assertEqual(actor['hp'],950)
        self.assertEqual(actor['cooldowns']['arch_warrior_berserker'],4)
        actor['rpg_state']['heat']=5
        self.use(state,'arch_warrior_berserker',hit=False)
        self.assertEqual(actor['rpg_state']['heat'],5)

    def test_phoenix_revive_is_once_saved_and_not_self_cost(self):
        state=self.final('warrior_berserker');actor=state['sides']['a']
        actor['hp']=1;actor['rpg_state']={'heat':3}
        self.use(state,'bum_punch','b')
        self.assertEqual(actor['hp'],300)
        self.assertTrue(actor['rpg_state']['phoenix_revived'])
        state=json.loads(json.dumps(state));actor=state['sides']['a']
        actor['hp']=1;actor['rpg_state']['heat']=5
        self.use(state,'bum_punch','b')
        self.assertEqual(actor['hp'],0)
        state=self.final('warrior_berserker');actor=state['sides']['a']
        actor['hp']=1;actor['rpg_state']={'heat':5}
        self.use(state,'armor_split')
        self.assertEqual(actor['hp'],1)
        self.assertFalse(actor['rpg_state'].get('phoenix_revived'))

    def test_three_strikes_roll_hits_evasion_and_miss_independently(self):
        class Rolls(FixedRoll):
            def __init__(self):self.rolls=iter((.01,.94,.99))
            def random(self):return next(self.rolls,.01)
        state=self.final('warrior_berserker');actor=state['sides']['a']
        actor['rpg_state']={'heat':5};state['sides']['b']['stats']['evasion']=10
        event=resolve_skill(state,'a','arch_warrior_berserker',rng=Rolls(),advance_turn=False)
        self.assertEqual([part['hit'] for part in event['hit_results']],[True,False,False])
        self.assertEqual([part['dodged'] for part in event['hit_results']],[False,True,False])
        self.assertEqual(actor['resource'],50)
        self.assertEqual(actor['rpg_state']['heat'],2)

    def test_attack_plus_summon_grants_one_incoming_heat(self):
        state=self.state('mage','mage_necromancer')
        target=state['sides']['b'];target.update(class_id='warrior',archclass_id='warrior_berserker',level=20,archclass_stage=20)
        self.use(state,'mana_barrier')
        event=self.use(state,'mana_shot')
        self.assertGreater(event['damage'],0)
        self.assertIn('Скелет',event['text'])
        self.assertEqual(target['rpg_state']['heat'],1)

    def test_berserker_and_knight_milestones(self):
        state=self.state('warrior','warrior_berserker');actor=state['sides']['a']
        self.use(state,'armor_split');self.use(state,'steel_charge')
        self.assertEqual(actor['rpg_state']['onslaught'],3)
        event=self.use(state,'arch_warrior_berserker')
        self.assertEqual(len(event['hit_results']),3)
        self.assertEqual(actor['rpg_state']['onslaught'],1)
        state=self.final('warrior_knight');actor=state['sides']['a']
        self.use(state,'counter_lunge');self.use(state,'bum_punch','b')
        self.assertEqual(actor['rpg_state']['steadfast'],1)
        self.assertTrue(any(e.get('id')=='armor_split' for e in state['sides']['b']['effects']))
        actor['rpg_state']['steadfast']=3
        ally=dict(actor,hp=100,effects=[])
        event=self.use(state,'arch_warrior_knight',allies=[actor,ally])
        self.assertEqual(event['skill_name'],'Бастион отвечает')
        self.assertEqual(actor['rpg_state']['steadfast'],0)
        self.assertTrue(any(e.get('id')=='bastion_guard' for e in ally['effects']))

    def test_death_two_servants_replace_and_guard_has_cost(self):
        state=self.final('mage_necromancer');actor=state['sides']['a']
        actor['rpg_state']={'souls':3}
        event=self.use(state,'mana_barrier')
        self.assertEqual(event['skill_name'],'Мёртвые не знают усталости')
        self.assertEqual(actor['rpg_state']['souls'],0)
        self.assertEqual(actor['rpg_state']['summon'],3)
        before=actor['hp'];self.use(state,'bum_punch','b')
        self.assertEqual(actor['rpg_state']['summon'],2)
        state=json.loads(json.dumps(state));actor=state['sides']['a']
        self.use(state,'mana_focus')
        self.use(state,'mana_focus')
        self.assertEqual(actor['rpg_state']['summon'],0)
        actor['rpg_state']['souls']=3
        self.use(state,'mana_barrier')
        self.assertEqual(actor['rpg_state']['summon'],3)
        self.assertLess(actor['hp'],before)

    def test_element_cycle_and_cataclysm_miss_keeps_marks(self):
        state=self.final('mage_elementalist');actor=state['sides']['a'];enemy=state['sides']['b']
        for sid in ('mana_shot','mana_blob','mana_overload'):self.use(state,sid)
        self.assertEqual(actor['rpg_state']['elements'],[])
        self.assertEqual(actor['resource'],85) # 100-35+20
        self.assertEqual(effective_skill(state,'a','arch_mage_elementalist').name,'Катаклизм')
        self.use(state,'arch_mage_elementalist',hit=False)
        self.assertTrue(any(e.get('id')=='rpg_frost' for e in enemy['effects']))
        event=self.use(state,'arch_mage_elementalist')
        self.assertEqual(len(event['hit_results']),3)
        self.assertFalse(any(e.get('id') in ('rpg_burn','rpg_frost','rpg_conductivity') for e in enemy['effects']))

    def test_void_echo_cost_miss_flag_and_paid_horizon(self):
        state=self.final('mage_archmage');actor=state['sides']['a'];enemy=state['sides']['b']
        for sid in ('mana_shot','mana_blob','mana_focus'):self.use(state,sid)
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.assertEqual(effective_skill(state,'a','mana_shot').cost,1)
        actor['own_turns']=4
        self.use(state,'arch_mage_archmage',hit=False)
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.assertFalse(actor['rpg_state'].get('void_used'))
        event=self.use(state,'arch_mage_archmage')
        self.assertEqual(event['skill_name'],'Точка небытия')
        self.assertTrue(actor['rpg_state']['void_used'])
        self.assertEqual(actor['resource'],30)
        self.use(state,'mana_blob','b');self.assertEqual(actor['resource'],40)
        self.use(state,'bum_punch','b');self.assertEqual(actor['resource'],40)
        state=json.loads(json.dumps(state))
        state['sides']['a']['rpg_state']['echo_ready']=True
        self.assertNotEqual(effective_skill(state,'a','arch_mage_archmage').name,'Точка небытия')

    def test_healer_dawn_solo_once_and_low_hp_cleanse(self):
        state=self.final('priest_bishop');actor=state['sides']['a']
        actor['hp']=100;actor['rpg_state']={'faith':3}
        event=self.use(state,'priest_heal')
        self.assertEqual(event['skill_name'],'Пока горит свет')
        self.assertEqual(actor['hp'],600)
        self.assertEqual(actor['resource'],40)
        actor['rpg_state']['faith']=3
        self.assertNotEqual(effective_skill(state,'a','priest_heal').name,'Пока горит свет')
        actor['hp']=100;actor['effects'].append(dict(id='test',kind='accuracy_flat',value=-10,duration=3))
        self.use(state,'priest_heal')
        self.assertFalse(any(e.get('id')=='test' for e in actor['effects']))

    def test_raid_dawn_shared_limit_and_excludes_withdrawn(self):
        people=[dict(actor_id=i,fighter_id=i,personal=True,slave_owner=i) for i in (10,20,30)]
        sources=[dict(slave_id=i,owner_id=i,class_id='priest',level=20,archclass_id='priest_bishop',archclass_stage=20) for i in (10,20,30)]
        data=create_raid_state(people,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,'iron')
        for p in data['players'].values():
            p['fighter'].update(hp=500,stats=dict(p['fighter']['stats'],max_hp=1000),loadout=['priest_heal'])
            p['fighter']['rpg_state']={'faith':3};p['selected']='priest_heal'
        data['players']['30']['fighter']['hp']=0
        resolve_round(data,BUILTIN_SKILLS,FixedRoll())
        self.assertTrue(data['rpg_revive_used'])
        self.assertGreater(data['players']['30']['fighter']['hp'],0)
        data=json.loads(json.dumps(data));data['players']['30']['fighter']['hp']=0
        for key in ('10','20'):
            p=data['players'][key];p['fighter']['rpg_state']={'faith':3};p['fighter']['cooldowns']={};p['fighter']['resource']=100;p['selected']='priest_heal'
        resolve_round(data,BUILTIN_SKILLS,FixedRoll())
        self.assertEqual(data['players']['30']['fighter']['hp'],0)
        data=create_raid_state(people,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,'iron')
        for p in data['players'].values():
            p['fighter']['rpg_state']={'faith':3};p['fighter']['loadout']=['priest_heal'];p['selected']='priest_heal'
        data['players']['30'].update(withdrawn=True)
        data['players']['30']['fighter']['hp']=0
        resolve_round(data,BUILTIN_SKILLS,FixedRoll())
        self.assertFalse(data.get('rpg_revive_used'))
        self.assertEqual(data['players']['30']['fighter']['hp'],0)

    def test_horizon_mana_belongs_to_caster_and_one_claim_per_boss_action(self):
        from arena_rpg_combat import paid_action
        state=self.final('mage_archmage');caster=state['sides']['a'];boss=state['sides']['b']
        caster['resource']=10
        other=dict(caster,controller_id=30,resource=20,rpg_state={})
        boss['effects']=[dict(id='event_horizon',kind='magic_defense_pct',value=-.25,duration=2,source_controller=10)]
        raid=dict(players={'10':dict(fighter=caster),'30':dict(fighter=other)})
        paid_action(boss,other,25,raid)
        paid_action(boss,other,25,raid)
        self.assertEqual(caster['resource'],20)
        self.assertEqual(other['resource'],20)
        boss['own_turns']+=1
        paid_action(boss,other,0,raid)
        self.assertEqual(caster['resource'],20)

    def test_inquisitor_multihit_spends_once_and_retains_one_retribution(self):
        state=self.final('priest_paladin');actor=state['sides']['a']
        actor['rpg_state']={'faith':3,'retribution':3}
        self.use(state,'arch_priest_paladin',hit=False)
        self.assertEqual(actor['rpg_state']['faith'],3)
        self.assertEqual(actor['rpg_state']['retribution'],3)
        event=self.use(state,'arch_priest_paladin')
        self.assertEqual(event['skill_name'],'Последний приговор')
        self.assertEqual(len(event['hit_results']),2)
        self.assertEqual(actor['rpg_state']['retribution'],1)
        self.assertEqual(actor['rpg_state']['faith'],0)
        self.assertEqual(actor['resource'],40)

    def test_beast_fury_three_actions_and_moon_miss_window(self):
        state=self.final('hunter_beast');actor=state['sides']['a']
        actor['rpg_state']={'beast':3}
        event=self.use(state,'arch_hunter_beast')
        self.assertEqual(event['skill_name'],'Ярость первородного')
        self.assertEqual(effective_skill(state,'a','arch_hunter_beast').name,'Первобытный разрыв')
        for _ in range(3):state['active_side']='a';skip_turn(state)
        actor['rpg_state']['beast']=3
        self.assertNotEqual(effective_skill(state,'a','arch_hunter_beast').name,'Ярость первородного')
        state=self.final('hunter_moon');actor=state['sides']['a']
        self.use(state,'hunter_shot');self.use(state,'bum_punch','b')
        self.assertTrue(actor['rpg_state']['moon_mark'])
        self.use(state,'arch_hunter_moon',hit=False)
        self.assertTrue(actor['rpg_state']['visceral_ready'])
        event=self.use(state,'arch_hunter_moon')
        self.assertEqual(event['skill_name'],'Луна не прощает')
        self.assertEqual(len(event['hit_results']),2)
        self.assertTrue(actor['rpg_state']['moon_used'])


if __name__ == '__main__':
    unittest.main()
