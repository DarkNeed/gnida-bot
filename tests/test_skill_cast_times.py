import json
import subprocess
import unittest
from dataclasses import asdict
from pathlib import Path

from arena_action_queue import direct_public_queue
from arena_skill_timing import duration as cast_time
from arena_engine import BUILTIN_SKILLS, create_battle_state, effective_skill, effective_stat


class SkillCastTimeTests(unittest.TestCase):
    def fighter(self, branch=''):
        return create_battle_state(
            dict(slave_id=1, owner_id=1, class_id='assassin', level=20, archclass_id=branch),
            dict(slave_id=2, owner_id=2, class_id='ragamuffin', level=20),
            action_queue_version=True,
        )

    def test_assassin_casts_have_distinct_durations(self):
        state = self.fighter()
        fighter = state['sides']['a']
        ids = ['assassin_smoke', 'assassin_cut', 'assassin_needle', 'assassin_expose', 'assassin_execution']
        times = [cast_time(fighter, effective_skill(state, 'a', sid)) for sid in ids]
        self.assertEqual(times, sorted(set(times)))
        self.assertGreater(times[-1], times[1] * 1.8)

    def test_variants_retain_individual_timing_and_speed_reduces_time(self):
        for branch in ('assassin_shadow', 'assassin_blood'):
            state = self.fighter(branch)
            fighter = state['sides']['a']
            for sid in ('assassin_cut', 'assassin_needle', 'assassin_execution'):
                skill = effective_skill(state, 'a', sid)
                self.assertEqual(skill.cast_base, BUILTIN_SKILLS[sid].cast_base)
                slow = dict(fighter, stats=dict(fighter['stats'], speed=0), effects=[])
                self.assertLess(cast_time(fighter, skill), cast_time(slow, skill))

    def test_browser_fallback_matches_server_and_fixed_scale_separates_markers(self):
        state = self.fighter()
        fighter = state['sides']['a']
        fighter['effective_stats'] = {k: effective_stat(fighter, k) for k in fighter['stats']}
        skills = [asdict(BUILTIN_SKILLS[sid]) for sid in
                  ('assassin_smoke', 'assassin_cut', 'assassin_needle', 'assassin_expose', 'assassin_execution', 'arch_assassin_shadow')]
        script = """
const timeline=require('./webapp/raid-timeline.js');
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
console.log(JSON.stringify({times:input.skills.map(s=>timeline.castTime(input.fighter,s)),
  positions:[1,2,3].map(at=>timeline.model({...input.queue,entries:[{actor:'a',at}]})[0].position)}));
"""
        output = json.loads(subprocess.check_output(['node', '-e', script],
            cwd=Path(__file__).resolve().parents[1], input=json.dumps(dict(
                fighter=fighter, skills=skills, queue=direct_public_queue(state, BUILTIN_SKILLS)
            )).encode()))
        self.assertEqual(output['times'], [cast_time(fighter, BUILTIN_SKILLS[s['skill_id']]) for s in skills])
        self.assertEqual(output['positions'], [.2, .4, .6])


if __name__ == '__main__':
    unittest.main()
