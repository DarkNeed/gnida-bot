import json
import random
import shutil
import subprocess
import unittest
from dataclasses import asdict
from pathlib import Path

from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state, effective_skill, resolve_skill
from arena_npc_ai import choose_skill
from arena_wasteland import enemy_source
from arena_guild_rules import MONSTERS, MONSTER_KITS, SKILLS, CONTRACTS, mob_templates
from arena_encounters import create_encounter, set_intents
from arena_qte_patterns import profile, defense, prepare
from arena_qte_rules import replay

ROOT=Path(__file__).resolve().parents[1]
STATS=dict(accuracy=95,enemyEvasion=10,enemyAccuracy=98,evasion=10)


def descriptor(skill, tier=0):
    return dict(id=skill.skill_id+':review',base_id=skill.skill_id,name=skill.name,
                class_id=skill.class_id,damage_type=skill.damage_type,tags=list(skill.tags),
                strikes=3 if 'three_strike' in skill.tags else 1,npc_tier=tier,monster_pattern=2)


class EnemyVarietyTests(unittest.TestCase):
    def test_wasteland_only_native_skills_and_combo_prerequisites(self):
        for seed in range(150):
            src=enemy_source(20,rng=random.Random(seed))
            self.assertLessEqual(len(src['loadout']),4)
            self.assertEqual(src['archclass_stage'],20)
            self.assertTrue(all(BUILTIN_SKILLS[sid].class_id==src['class_id'] for sid in src['loadout']))
            self.assertTrue(all('raid_loot' not in BUILTIN_SKILLS[sid].tags for sid in src['loadout']))
            if src['class_id']=='hunter':self.assertIn('hunter_shot',src['loadout'])
            if src['class_id']=='mage':self.assertIn('mana_focus',src['loadout'])

    def state(self):
        return create_battle_state(dict(slave_id=0,owner_id=0,class_id='mage',level=20,npc_tier=2,
            loadout=['mana_shot','mana_blob','mana_focus','mana_overload']),
            dict(slave_id=10,owner_id=10,class_id='warrior',level=20))

    def test_ai_restores_only_when_useful_and_does_not_spam(self):
        state=self.state();side=state['sides']['a'];rng=random.Random(33)
        side['npc_skill_history']=['mana_overload']
        self.assertNotEqual(choose_skill(state,'a',BUILTIN_SKILLS,rng),'mana_overload')
        side['resource']=0
        self.assertEqual(choose_skill(state,'a',BUILTIN_SKILLS,rng),'mana_focus')
        side['resource']=100;side['npc_skill_history']=[]
        self.assertNotEqual(choose_skill(state,'a',BUILTIN_SKILLS,rng),'mana_focus')

    def test_npc_basic_is_thematic_but_player_punch_is_unchanged(self):
        state=self.state()
        skill=effective_skill(state,'a','bum_punch')
        self.assertEqual(skill.class_id,'mage')
        self.assertEqual(skill.damage_type,'magic')
        self.assertNotEqual(skill.name,'Удар бомжа')
        state['sides']['a']['controller_id']=10
        self.assertEqual(effective_skill(state,'a','bum_punch').name,'Удар бомжа')

    def test_legacy_foreign_filler_is_not_selected(self):
        state=self.state();side=state['sides']['a']
        side['loadout']=['dust_in_eyes','mana_shot']
        self.assertEqual(choose_skill(state,'a',BUILTIN_SKILLS,random.Random(3)),'mana_shot')

    def test_normalizer_does_not_reinsert_foreign_filler_into_native_enemies(self):
        for seed in range(40):
            source=enemy_source(5,rng=random.Random(seed))
            side=create_battle_state(source,dict(source,slave_id=10,owner_id=10))['sides']['a']
            self.assertTrue(all(BUILTIN_SKILLS[sid].class_id==side['class_id'] for sid in side['loadout']))

    def test_hand_tuned_raid_bosses_do_not_inherit_the_generic_pressure(self):
        from arena_raid_engine import create_raid_state
        participant=dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)
        source=dict(slave_id=10,owner_id=10,class_id='warrior',level=20)
        for boss in ('kit','chaplain','whaler','nazarick','doofenshmirtz'):
            with self.subTest(boss=boss):
                data=create_raid_state([participant],[source],FIGHTER_CLASSES,BUILTIN_SKILLS,boss)
                self.assertEqual(data['boss'].get('npc_tier',0),0)

    def test_every_monster_kit_is_valid_and_strong_ranks_have_four_moves(self):
        for mid,m in MONSTERS.items():
            self.assertEqual(m['skills'],['guild_'+sid for sid in MONSTER_KITS[mid]])
            self.assertTrue(all(sid in SKILLS for sid in m['skills']))
            self.assertGreaterEqual(len(m['skills']),4 if m['rank'] in ('B','A','S') else 2)
        self.assertNotIn('guild_fire',MONSTERS['wyvern']['skills'])
        self.assertNotIn('guild_stab',MONSTERS['spider']['skills'])
        self.assertNotIn('guild_hex',MONSTERS['slime']['skills'])

    def test_repeated_planning_does_not_consume_sequence_and_four_attacks_rotate(self):
        templates=mob_templates(CONTRACTS['s_elite'],dict(kind='boss'),1)
        participant=dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)
        source=dict(slave_id=10,owner_id=10,class_id='warrior',level=20)
        data=create_encounter([participant],[source],FIGHTER_CLASSES,BUILTIN_SKILLS,templates,11)
        mob=data['enemies']['e1'];seen=[]
        for turn in range(1,9):
            data['round']=turn;before=mob['rp_ai_index'];set_intents(data,BUILTIN_SKILLS)
            intent=data['enemy_intents']['e1']
            set_intents(data,BUILTIN_SKILLS)
            self.assertEqual(intent,data['enemy_intents']['e1'])
            self.assertEqual(mob.get('rp_ai_index'),before)
            seen.append(intent['skill']);mob['rp_ai_index']=intent['next_ai_index']
        self.assertEqual(len(set(seen[:4])),4)
        self.assertTrue(all(a!=b for a,b in zip(seen,seen[1:])))
        self.assertEqual(mob['npc_tier'],4)

    def test_npc_pressure_does_not_change_player_or_named_raid_patterns(self):
        from arena_qte_live import challenge
        state=self.state();a,b=state['sides'].values()
        npc=challenge('defense',a,b,BUILTIN_SKILLS['mana_shot'],10)
        self.assertGreater(npc['profile']['npc_tier'],0)
        a['controller_id']=10
        human=challenge('defense',a,b,BUILTIN_SKILLS['mana_shot'],10)
        self.assertEqual(human['profile']['npc_tier'],0)
        hard=defense(profile(npc['profile']),STATS,17)
        normal=defense(profile(human['profile']),STATS,17)
        self.assertGreater(len(hard['events']),len(normal['events']))
        self.assertGreater(hard['d']['speed'],normal['d']['speed'])
        self.assertGreaterEqual(hard['d']['warning'],.40)


@unittest.skipUnless(shutil.which('node'),'Node required for parity')
class MonsterPatternParityTests(unittest.TestCase):
    def test_selected_high_rank_attacks_have_a_damage_free_route(self):
        cases=[dict(version=2,kind='defense',profile=descriptor(SKILLS[sid],4),seed=17,stats=STATS,
                    strikes=1,defense_preparation=1,perfect=True)
               for sid in ('guild_rune_cross','guild_soul_prison','guild_ancient_sun')]
        proc=subprocess.run(['node','tests/qte_patterns_trace.cjs'],cwd=ROOT,input=json.dumps(cases),text=True,encoding='utf-8',capture_output=True,check=True,timeout=90)
        for config,trace in zip(cases,json.loads(proc.stdout)):
            with self.subTest(skill=config['profile']['base_id']):
                self.assertEqual(replay(config,trace['proof'],20)['contacts'],[])

    def test_all_monster_dodge_patterns_replay_identically_on_server(self):
        cases=[dict(version=2,kind='defense',profile=descriptor(s,4),seed=17,stats=STATS,strikes=descriptor(s)['strikes'],defense_preparation=1) for s in SKILLS.values()]
        proc=subprocess.run(['node','tests/qte_patterns_trace.cjs'],cwd=ROOT,input=json.dumps(cases),text=True,encoding='utf-8',capture_output=True,check=True)
        for config,trace in zip(cases,json.loads(proc.stdout)):
            with self.subTest(skill=config['profile']['base_id']):
                result=replay(config,trace['proof'],20)
                self.assertEqual(result,trace['result'])

    def test_all_monster_block_schedules_identical_and_have_reaction_time(self):
        from arena_guild_patterns import block_threats
        from arena_qte_block import parameters
        rows=[]
        for skill in SKILLS.values():
            p=profile(descriptor(skill,4));stats=dict(physicalDefense=20,magicDefense=20,enemyAttack=42,enemyAccuracy=98)
            rows.append(dict(profile=p['skill'],stats=stats))
        script="const E=require('./webapp/qte-unique/engine'),B=require('./webapp/qte-block/engine');let data='';process.stdin.on('data',s=>data+=s);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(data).map(v=>{const p=E.profile(v.profile);return E.guildBlockThreats(p,17,B.parameters(p,v.stats));}))));"
        result=json.loads(subprocess.run(['node','-e',script],cwd=ROOT,input=json.dumps(rows),text=True,encoding='utf-8',capture_output=True,check=True).stdout)
        for row,js in zip(rows,result):
            p=profile(row['profile']);events=block_threats(p,17,parameters(p,row['stats']))
            for a,b in zip(events,js):
                self.assertEqual(a.keys(),b.keys())
                for key in a:
                    if isinstance(a[key],float):self.assertAlmostEqual(a[key],b[key],places=10)
                    else:self.assertEqual(a[key],b[key])
                self.assertGreaterEqual(a['at']-a['warning'],1)
            self.assertEqual(len(events),len(js))

    def test_new_signatures_are_not_identical_geometry(self):
        signatures=[]
        for sid in ('guild_grave_crown','guild_crypt_blades','guild_ancient_sun','guild_ash_orbit','guild_rune_cross','guild_ice_tomb'):
            s=defense(profile(descriptor(SKILLS[sid],4)),STATS,17);prepare(s,s['events'][0])
            signatures.append(tuple((h['type'],h.get('motif'),h['start']) for h in s['hazards']))
        self.assertEqual(len(set(signatures)),len(signatures))

    def test_already_issued_old_monster_challenges_keep_legacy_geometry(self):
        old=descriptor(SKILLS['guild_fire']);old.pop('monster_pattern')
        s=defense(profile(old),STATS,17);prepare(s,s['events'][0])
        self.assertFalse(any(h.get('color')=='#e78654' for h in s['hazards']))
        new=defense(profile(descriptor(SKILLS['guild_fire'])),STATS,17);prepare(new,new['events'][0])
        self.assertTrue(any(h.get('color')=='#e78654' for h in new['hazards']))
