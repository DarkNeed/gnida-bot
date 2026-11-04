"""Export a read-only combat reference; never open the bot DB or read secrets."""
from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena_engine import BUILTIN_SKILLS, BUILTIN_PASSIVES, FIGHTER_CLASSES, create_battle_state, resolve_skill, stats_for
from arena_archclasses import ARCHCLASSES
from arena_finals import FINALS
from arena_mastery import BASE, BASE_FINAL, BRANCHES
from arena_rpg_paths import PATHS
from arena_progression import choice_avatar
from arena_raid_engine import AVAILABLE_BOSSES, BOSSES, BOSS_SKILLS
from arena_qte_unique import review_catalog
import arena_qte_patterns as patterns
import arena_qte_block as blocking


def serial(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def write_json(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=serial) + '\n', encoding='utf-8')


class TraceRandom(random.Random):
    """Record primitive draws so a C# fixture need not copy Python's PRNG."""
    def __init__(self, seed):
        super().__init__(seed)
        self.draws = []

    def random(self):
        value = super().random()
        self.draws.append(dict(kind='unit', value=value))
        return value

    def getrandbits(self, k):
        value = super().getrandbits(k)
        self.draws.append(dict(kind='bits', bits=k, value=value))
        return value


def attack_proof(challenge, miss_first=False):
    state = patterns.attack(patterns.profile(challenge['profile']), challenge['stats'], challenge['seed'])
    clicks, start = [], 1.0
    for index, slot in enumerate(state['slots']):
        for tick in range(math.ceil(start * 120), math.ceil((start + slot) * 120)):
            state['time'] = tick / 120
            frame = patterns.attack_frame(state)
            if frame['index'] != index or not frame['canHit']:
                continue
            distance = abs(frame['cursor'] - frame['center'])
            if (miss_first and index == 0 and distance > frame['width'] or
                    (not miss_first or index != 0) and distance < frame['width'] / 3):
                clicks.append(tick)
                break
        start += slot
    return dict(ticks=math.ceil(state['duration'] * 120), clicks=clicks)


def export(folder):
    folder.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    classes = [asdict(v) for v in FIGHTER_CLASSES.values()]
    branches = []
    for key, value in ARCHCLASSES.items():
        final = FINALS[key][1] if key in FINALS else PATHS[key][0]
        branches.append(dict(value, id=key, final_name=final,
                             rpg_path=PATHS.get(key), humour_fingers_final=FINALS.get(key),
                             avatar10=choice_avatar(value['class_id'], key, 10),
                             avatar20=choice_avatar(value['class_id'], key, 20)))
    catalog = review_catalog()
    profiles = [dict(descriptor=s, pattern=patterns.profile(s)) for s in catalog]
    write_json(folder, 'catalog.json', dict(
        schema_version=1, source_commit=commit, date='2026-10-20',
        classes=classes, branches=branches,
        active_skills=[asdict(s) for s in BUILTIN_SKILLS.values()],
        passive_skills=[asdict(s) for s in BUILTIN_PASSIVES.values()],
        boss_skills=[asdict(s) for s in BOSS_SKILLS.values()],
        bosses={k: BOSSES[k] for k in AVAILABLE_BOSSES},
        mastery_base=BASE, mastery_base_final=BASE_FINAL, mastery_arch=BRANCHES,
        stats_by_level={cid: {str(n): stats_for(cid, n) for n in range(1, 21)} for cid in FIGHTER_CLASSES},
        note='Base definitions only. Conditional variants and effect ordering must be ported from source_python, not inferred from names.'
    ))
    write_json(folder, 'qte_profiles.json', profiles)
    representatives = {}
    for s in catalog:
        family = patterns.family(s)
        if family not in representatives or s['strikes'] > representatives[family]['strikes']:
            representatives[family] = s
    fixtures = []
    stats = dict(accuracy=75, enemyEvasion=25, enemyAccuracy=95, evasion=10)
    for family, descriptor in representatives.items():
        challenge = dict(version=2, kind='attack', profile=descriptor, seed=23,
                         strikes=descriptor['strikes'], stats=stats, defense_preparation=1)
        for name, miss in [('perfect', False), ('miss_first', True)]:
            proof = attack_proof(challenge, miss)
            expected = patterns.replay(challenge, proof, 120)
            assert len(proof['clicks']) == descriptor['strikes']
            assert expected['mask'] == [not (miss and i == 0) for i in range(descriptor['strikes'])]
            fixtures.append(dict(id=family + '/attack/' + name, challenge=challenge,
                                 input=proof, expected=expected))
        defend = dict(challenge, kind='defense')
        initial = patterns.defense(patterns.profile(descriptor), stats, 23)
        for event in initial['events']:
            patterns.prepare(initial, event)
        proof = dict(ticks=936, inputs=[dict(t=0, x=0, y=0)])
        fixtures.append(dict(id=family + '/dodge/idle', challenge=defend,
                             generated=initial, input=proof, expected=patterns.replay(defend, proof, 120)))
        block = dict(defend, version=3, defense_mode='block',
                     stats=dict(physicalDefense=25, magicDefense=20, enemyAttack=30, enemyAccuracy=95))
        proof = dict(ticks=1140, inputs=[dict(t=t, angle=math.sin(t / 120) * math.pi,
                                           active=(t // 60) % 2 == 1) for t in range(0, 1140, 60)])
        fixtures.append(dict(id=family + '/block/pulses', challenge=block,
                             generated=blocking.create(block), input=proof,
                             expected=blocking.replay(block, proof, 120)))
    write_json(folder, 'qte_fixtures.json', fixtures)
    combat = []
    for cid in FIGHTER_CLASSES:
        skills = [s.skill_id for s in BUILTIN_SKILLS.values() if s.class_id == cid
                  and s.unlock_level <= 20 and not s.skill_id.startswith(('arch_', 'mastery_'))]
        initial = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id=cid, level=20, loadout=skills[:4]),
            dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=20))
        sid = next(s for s in initial['sides']['a']['loadout'] if BUILTIN_SKILLS[s].damage_type)
        state = json.loads(json.dumps(initial))
        rng = TraceRandom(123)
        result = resolve_skill(state, 'a', sid, rng=rng)
        combat.append(dict(id=cid, initial=initial, command=dict(side='a', skill=sid),
                           python_random_seed=123, random_draws=rng.draws,
                           expected_state=state, expected_event=result))
    write_json(folder, 'combat_fixtures.json', combat)
    # Only code modules, never databases, account records, credentials or config.
    seeds = ['arena_engine', 'arena_raid_engine', 'arena_qte_patterns', 'arena_qte_block',
             'arena_qte_rules', 'arena_qte_live', 'arena_qte_unique', 'arena_progression']
    pending, included = list(seeds), set()
    code = folder / 'source_python'
    code.mkdir()
    while pending:
        module = pending.pop()
        if module in included:
            continue
        path = ROOT / (module + '.py')
        if not path.is_file():
            continue
        included.add(module)
        shutil.copy2(path, code / path.name)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = ([node.module] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            pending.extend(n for n in names if n and n.startswith('arena_'))
    web = folder / 'source_web'
    for name in ('battle-client', 'style.css', 'arena-audio', 'qte-input', 'qte-input.css',
                 'qte-live', 'qte-live.css', 'qte-view', 'qte-block-view',
                 'qte-unique/engine', 'qte-unique/client', 'qte-unique/index.html',
                 'qte-unique/style.css', 'qte-block/engine', 'qte-block/client',
                 'qte-block/index.html', 'qte-block/style.css'):
        dest = web / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'webapp' / name, dest)
    # Kept OUTSIDE Unity Assets: several legacy images have unverified rights.
    shutil.copytree(ROOT / 'webapp' / 'assets', folder / 'art_reference_unverified')
    tests = folder / 'reference_tests'
    tests.mkdir()
    for path in (ROOT / 'tests').glob('*'):
        if path.is_file() and (path.name.startswith(('test_qte_', 'qte_')) or path.name in {
                'test_arena_archclasses.py', 'test_arena_finals.py', 'test_arena_mastery.py',
                'test_arena_resource_regen.py', 'test_arena_whaler.py', 'test_arena_kit.py',
                'test_arena_rpg.py', 'test_arena_rpg_combat.py'}):
            shutil.copy2(path, tests / path.name)
    for source, dest in [('docs/UNITY_COMBAT_HANDOFF_20261020.md', '00_START_HERE.md'),
                         ('docs/UNITY_MOBILE_ARENA_GDD.md', 'OLD_GDD_20261016_REFERENCE_ONLY.md')]:
        shutil.copy2(ROOT / source, folder / dest)
    roster = ['# Актуальные классы и пути\n', '| База | 10 уровень | 20 уровень |', '|---|---|---|']
    for cid, definition in FIGHTER_CLASSES.items():
        own = [b for b in branches if b['class_id'] == cid]
        if not own:
            roster.append(f'| {definition.name} | Мастерство | Мастерство |')
        for b in own:
            roster.append(f"| {definition.name} | {b['name']} | {b['final_name']} |")
    roster += ['\nВсе базовые классы, включая Оборванца, имеют альтернативное мастерство.',
               'Оставшаяся на 20 уровне ветка 10 уровня получает мастерство архикласса, не финальную форму.']
    (folder / 'CLASS_PATHS.md').write_text('\n'.join(roster) + '\n', encoding='utf-8')
    counts = dict(classes=len(classes), branches10=len(branches), branches20=len(branches),
                  active_skills=len(BUILTIN_SKILLS), passives=len(BUILTIN_PASSIVES),
                  boss_skills=len(BOSS_SKILLS), qte_profiles=len(profiles),
                  qte_families=len(representatives), qte_fixtures=len(fixtures), combat_fixtures=len(combat))
    manifest = dict(schema_version=1, source_commit=commit, counts=counts,
                    python_reference_modules=sorted(included),
                    warnings=['art_reference_unverified is NOT a commercial-use license or approval to ship copied characters.',
                              'Reference Python tests may import test helpers not included. Use the original repository for the full suite.',
                              'No Unity implementation is claimed by this export.'],
                    files={p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(folder.rglob('*')) if p.is_file()})
    write_json(folder, 'MANIFEST.json', manifest)
    archive = folder.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
        for path in folder.rglob('*'):
            if path.is_file():
                output.write(path, path.relative_to(folder))
    print(json.dumps(dict(folder=str(folder), archive=str(archive), counts=counts), ensure_ascii=False))


if __name__ == '__main__':
    export(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'output' / 'unity-combat-handoff-20261020')
