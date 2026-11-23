"""Benchmark authoritative minigame replay with deterministic combat fixtures."""

import argparse
import cProfile
from contextlib import ExitStack
import copy
import json
import math
import pstats
from unittest.mock import patch

from benchmark_performance import head_function, measure
import arena_ainz_motion
import arena_nazarick_patterns
import arena_qte_block
import arena_qte_combined
import arena_qte_patterns
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_qte_live import challenge
from arena_qte_rules import replay
from arena_raid_engine import BOSS_SKILLS, create_raid_state


def fixtures():
    state = create_raid_state(
        [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
        [dict(slave_id=10, owner_id=10, class_id='assassin', level=20)],
        FIGHTER_CLASSES, BUILTIN_SKILLS, 'kit', unified=True)
    fighter = state['players']['10']['fighter']
    boss = state['boss']
    skills = {**BUILTIN_SKILLS, **BOSS_SKILLS}
    cases = {
        'normal': ('dodge', ('bum_punch',)),
        'ainz': ('dodge', ('nz_ainz6_p6_0',)),
        'victim': ('dodge', ('nz_victim_p2_4',)),
        'maids': ('dodge', ('nz_yuri_p2_1', 'nz_lupusregina_p2_0', 'nz_narberal_p2_2')),
        'heavy': ('dodge', ('nz_ainz6_p6_0', 'nz_ainz6_p2_0', 'nz_ainz6_p5_2',
                            'nz_mare_p2_2', 'chaplain_p4_1', 'nz_narberal_p2_2')),
        'block': ('block', ('nz_yuri_p2_1', 'nz_lupusregina_p2_0', 'nz_narberal_p2_2')),
    }
    for case, (mode, ids) in cases.items():
        fighter['defense_mode'] = mode
        members = []
        for i, sid in enumerate(ids):
            source = dict(boss, loadout=[sid])
            member = challenge('defense', source, fighter, skills[sid], 10, skills=skills)
            member.update(seed=2026 + i, encounter_enemy=f'e{i}')
            members.append(member)
        stage = arena_qte_combined.combine(members, 10, fighter['hp'])
        ticks = math.ceil(stage['duration'] * 120 - 1e-7)
        proof = dict(ticks=ticks, inputs=[
            dict(t=t, **(dict(angle=math.sin(t/40)*3, active=t % 100 < 70) if mode == 'block'
                        else dict(target=[360 + 216*math.sin(t/83), 160 + 126*math.cos(t/97)])))
            for t in range(0, ticks, 10)])
        yield case, stage, proof


def baseline(stack, ref):
    for module, names in (
        (arena_ainz_motion, ('geometry',)),
        (arena_nazarick_patterns, ('time_stopped',)),
        (arena_qte_patterns, ('touches', 'defense_begin', 'defense_move', 'defense_contacts', 'replay')),
        (arena_qte_combined, ('replay',)),
        (arena_qte_block, ('step', 'replay')),
    ):
        # Baseline functions can call each other. Keep their globals linked to
        # one module namespace, while imports of other modules use the patches.
        old = {name: head_function(module.__name__ + '.py', None, name, vars(module), ref)
               for name in names}
        for name, fn in old.items():
            fn.__globals__.update(old)
            stack.enter_context(patch.object(module, name, fn))


def main(args):
    report = {}
    for label, stage, proof in fixtures():
        if args.case and args.case != label:
            continue
        cases = {'complete': proof, 'abort': {'abort': True}}
        report[label] = {}
        for mode, commands in cases.items():
            def run():
                return replay(stage, commands, 60)
            with ExitStack() as stack:
                if args.baseline_ref:
                    baseline(stack, args.baseline_ref)
                expected = copy.deepcopy(run())
                if args.profile and mode == 'complete':
                    profile = cProfile.Profile()
                    profile.runcall(run)
                    pstats.Stats(profile).sort_stats('cumulative').print_stats(25)
                before = measure(run, args.repeats)
            report[label][mode] = {
                'baseline': before,
                'current': measure(run, args.repeats),
                'same_proof_result': expected == run(),
            }
    print(json.dumps(report, indent=2))
    if any(not case['same_proof_result'] for group in report.values() for case in group.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', default=25, type=int)
    parser.add_argument('--baseline-ref', default='a07baf1')
    parser.add_argument('--case', choices=('normal', 'ainz', 'victim', 'maids', 'heavy', 'block'))
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    main(args)
