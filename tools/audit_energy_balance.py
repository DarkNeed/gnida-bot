"""Offline cost audit for all classes, final paths and retained mastery; no DB."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena_engine import (FIGHTER_CLASSES, BUILTIN_SKILLS, create_battle_state,
                          effective_skill, passive_skill_limit)
from arena_archclasses import ARCHCLASSES
from arena_archprogress import skill_branch
from arena_mastery import skill_allowed
from arena_mirror_effects import gift_cost
from arena_pets import pet_cost


ROTATIONS = {
    'ragamuffin': ('dust_in_eyes', 'bum_punch'),
    'cutie': ('posing', 'uwu', 'meow', 'air_kiss', 'uwu'),
    'jock': ('flex_chest', 'smack', 'wallop', 'butt_peak'),
    'nerd': ('charging', 'doxxing', 'mother_joke', 'humiliate', 'go_to_store'),
    'thumb': ('reload', 'warning_shot', 'bayonet', 'senior_verdict'),
    'index': ('receive_prescript', 'literal', 'first_line', 'last_line'),
    'middle': ('grit_teeth', 'answer_for_it', 'recorded', 'whole_family'),
    'ring': ('unfinished_portrait', 'red_etude', 'first_stroke', 'last_stroke'),
    'pinky': ('calm_breath', 'silent_cut', 'moon_arc', 'falling_star'),
    'warrior': ('armor_split', 'steel_charge', 'counter_lunge', 'warrior_execute'),
    'mage': ('mana_barrier', 'mana_shot', 'mana_blob', 'mana_overload', 'mana_focus'),
    'priest': ('priest_ward', 'light_word', 'priest_heal', 'holy_judgment', 'priest_cleanse'),
    'hunter': ('hunter_transform', 'hunter_shot', 'hunter_visceral', 'hunter_cut', 'blood_bullets'),
}


def rotation_audit():
    """Fixed native cycles versus a passive dummy, not a PvP win-rate model.

    Compare current prices with/without the universal regen, in an isolated
    process; patching never touches saves, source files, or running servers.
    """
    import random
    from unittest.mock import patch
    from arena_engine import resolve_skill, skip_turn, validate_skill, restore_turn_resource

    rows = []
    for level in (9, 15, 20):
        for cid, rotation in ROTATIONS.items():
            for regen in (False, True):
                s = create_battle_state(
                    dict(owner_id=10, slave_id=10, class_id=cid, level=level,
                         progression_level=level if level >= 10 else 5),
                    dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=level))
                for side in s['sides'].values():
                    side['hp'] = side['stats']['max_hp'] = 100000
                    side['stats']['evasion'] = 0
                a = s['sides']['a']
                a['loadout'] = [sid for sid in rotation if BUILTIN_SKILLS[sid].unlock_level <= level] + ['bum_punch']
                s['active_side'] = 'a'
                rng = random.Random(21)
                paid = deliberate = fallbacks = 0
                regen_gains = []
                def track_regen(side):
                    gain = restore_turn_resource(side) if regen else 0
                    if side is a:
                        regen_gains.append(gain)
                    return gain
                actions = []
                with patch('arena_engine.restore_turn_resource', side_effect=track_regen):
                    for turn in range(16):
                        requested = rotation[turn % len(rotation)]
                        try:
                            skill = validate_skill(s, 'a', requested)
                        except ValueError:
                            skill = validate_skill(s, 'a', 'bum_punch')
                            fallbacks += 1
                        paid += pet_cost(a, skill, gift_cost(a, skill))
                        event = resolve_skill(s, 'a', skill.skill_id, rng=rng)
                        deliberate += event.get('deliberate_resource_restored', 0)
                        actions.append(skill.skill_id)
                        if s['active_side'] == 'b':
                            skip_turn(s)
                        assert s['active_side'] == 'a'
                        assert 0 <= a['resource'] <= a['stats']['resource_max']
                rows.append(dict(class_id=cid, level=level, regen_enabled=regen,
                    turns=16, paid=paid, deliberate_restored=deliberate,
                    turn_regen=sum(regen_gains), fallback_actions=fallbacks,
                    remaining=a['resource'], actions=actions))
    return rows


def audit():
    profiles = []
    for level in (9, 15, 20):
        for cid in FIGHTER_CLASSES:
            profiles.append((cid, '', level, 20, level if level >= 10 else 5))
        if level >= 10:
            for arch, definition in ARCHCLASSES.items():
                profiles.append((definition['class_id'], arch, level,
                                 20 if level == 20 else 10, level))
                if level == 20:
                    profiles.append((definition['class_id'], arch, level, 10, 20))
    result = []
    for cid, arch, level, stage, resolved in profiles:
        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id=cid, level=level,
                 archclass_id=arch, archclass_stage=stage, progression_level=resolved),
            dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=level))
        rows = []
        for mode in ('baseline', 'prepared'):
            s = deepcopy(state)
            a, b = s['sides'].values()
            if mode == 'prepared':
                a['own_turns'] = 5
                a['mechanics'] = dict(order=3, focus=3, grudge=3, prescript='last_line')
                a['rpg_state'] = dict(mana=3, souls=3, echo_ready=True, faith=3,
                                      retribution=3, onslaught=3, beast=3, moon_mark=True,
                                      visceral_until=8, steadfast=3)
                a['effects'].append(dict(id='charging_damage', kind='next_magic_damage',
                                         value=.6, duration=2))
                b['effects'] = [dict(id=k, kind=kind, value=value, duration=3)
                                for k, kind, value in (
                                    ('adoration', 'damage_pct', -.4),
                                    ('doxxing_magic', 'magic_defense_pct', -.2),
                                    ('portrait_accuracy', 'accuracy_flat', -15))]
            for sid, skill in BUILTIN_SKILLS.items():
                if (skill.class_id != cid or skill.unlock_level > level or
                        skill_branch(skill) not in ('', arch) or not skill_allowed(skill, a)):
                    continue
                variant = effective_skill(s, 'a', sid)
                rows.append(dict(mode=mode, id=sid, name=variant.name,
                                 catalog_cost=skill.cost, variant_cost=variant.cost,
                                 paid_cost=pet_cost(a, variant, gift_cost(a, variant)),
                                 power=variant.power, damage_type=variant.damage_type))
        result.append(dict(class_id=cid, arch=arch, stage=stage, level=level,
                           passives=state['sides']['a']['passive_details'][:passive_skill_limit(level)],
                           regen=state['sides']['a']['stats']['resource_regen'], skills=rows))
    return dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                classes=len(FIGHTER_CLASSES), paths=len(ARCHCLASSES), profiles=len(result),
                catalog={k:asdict(v) for k,v in BUILTIN_SKILLS.items()}, rows=result)


if __name__ == '__main__':
    target = Path(sys.argv[1])
    if target.exists():
        raise SystemExit('Refusing to overwrite an existing audit: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    report = audit()
    report['rotations'] = rotation_audit()
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), classes=report['classes'], paths=report['paths'],
                          profiles=report['profiles'], priced_skills=sum(len(r['skills']) for r in report['rows']),
                          rotations=len(report['rotations'])),ensure_ascii=False))
