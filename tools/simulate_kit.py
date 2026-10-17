"""Offline Kit calibration: scripted four-slot builds, not optimal human play."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_engine import BUILTIN_SKILLS, BUILTIN_PASSIVES, FIGHTER_CLASSES, validate_skill
from arena_raid_engine import create_raid_state, pair_state, alive_players, resolve_round
from arena_rpg import rpg_modifiers
from simulate_arena_balance import damage_estimate

BUILDS = {
    'mage_archmage': ('mage', ['mana_shot', 'mana_focus', 'mana_overload', 'arch_mage_archmage']),
    'mage_necromancer': ('mage', ['mana_barrier', 'mana_focus', 'mana_blob', 'arch_mage_necromancer']),
    'priest_bishop': ('priest', ['light_word', 'priest_heal', 'holy_judgment', 'arch_priest_bishop']),
    'priest_paladin': ('priest', ['light_word', 'priest_ward', 'holy_judgment', 'arch_priest_paladin']),
    'warrior_berserker': ('warrior', ['armor_split', 'steel_charge', 'counter_lunge', 'arch_warrior_berserker']),
    'warrior_knight': ('warrior', ['armor_split', 'counter_lunge', 'steel_charge', 'arch_warrior_knight']),
    'hunter_moon': ('hunter', ['hunter_cut', 'hunter_shot', 'blood_bullets', 'arch_hunter_moon']),
    'ring_fauvist': ('ring', ['first_stroke', 'unfinished_portrait', 'last_stroke', 'arch_ring_fauvist']),
    'middle_revenge': ('middle', ['recorded', 'grit_teeth', 'whole_family', 'arch_middle_revenge']),
    'pinky_tiansha': ('pinky', ['silent_cut', 'calm_breath', 'falling_star', 'arch_pinky_tiansha']),
}
TEAMS = (
    ('mage_archmage', 'priest_bishop', 'warrior_berserker'),
    ('mage_necromancer', 'warrior_knight', 'hunter_moon'),
    ('ring_fauvist', 'middle_revenge', 'pinky_tiansha'),
)


def candidate_actions(data, key, tactical=True):
    player, boss = data['players'][key], data['boss']
    actor = player['fighter']
    living = list(alive_players(data).values())
    intent = data['intent']['skill']
    if tactical and (intent == 'kit_eclipse' or any(e.get('id') == 'kit_mark' for e in actor['effects'])):
        return [(0, 'defend')]
    candidates = [(0, 'defend')]
    for sid in actor['loadout'] + ['bum_punch']:
        try:
            skill = validate_skill(pair_state(actor, boss), 'a', sid)
        except ValueError:
            continue
        score = damage_estimate(actor, boss, skill) * rpg_modifiers(actor, boss, skill)[1] - skill.cost * .08
        if tactical and intent == 'kit_field' and skill.damage_type:
            score -= 40
        prediction = data.get('kit_prediction', {})
        if tactical and prediction.get('target') == key and prediction.get('action') == (skill.damage_type or 'support'):
            score -= 18
        for effect in skill.effects:
            kind = effect['kind']
            if kind == 'resource':
                score += min(effect['value'], actor['stats']['resource_max'] - actor['resource']) * .65
            elif kind == 'rpg_blood_bullets':
                if actor['hp'] > actor['stats']['max_hp'] * .35:
                    score += min(35, actor['stats']['resource_max'] - actor['resource']) * .65 - 10
            elif kind in ('rpg_heal', 'rpg_dawn'):
                wounded = max(p['fighter']['stats']['max_hp'] - p['fighter']['hp'] for p in living)
                score += min(wounded, actor['stats']['max_hp'] * effect['value']) * 1.9
            elif kind in ('rpg_summon', 'rpg_death_servants'):
                score += 70 if actor.get('rpg_state', {}).get('summon', 0) == 0 else -100
            elif kind == 'rpg_armor_break':
                score += 12 if not any(e.get('value', 0) <= -.45 for e in boss['effects'] if e.get('id') == 'armor_split') else 0
            elif kind == 'rpg_parry':
                score += 5
            elif kind == 'damage_pct' and effect.get('target') == 'self':
                score += 20 if not any(e.get('id') == effect.get('id') for e in actor['effects']) else 0
            elif kind == 'resource_leech':
                score += 4
            elif kind == 'bleed':
                score += 8
        candidates.append((score, sid))
    return sorted(candidates, reverse=True)


def simulate(team, seed, tactical=True, level=20, prepared=False):
    participants, sources = [], []
    for i, branch in enumerate(team, 1):
        cls, loadout = BUILDS[branch]
        loadout = list(loadout)
        if prepared and not any(k in loadout for k in ('mana_focus', 'blood_bullets', 'calm_breath')):
            loadout[0] = 'go_to_store'
        participants.append(dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i))
        source = dict(slave_id=i, owner_id=i, class_id=cls, level=level,
                            archclass_id=branch, archclass_stage=20,
                            loadout=loadout, granted_skills=['go_to_store'] if prepared else [])
        if prepared:
            source['passive_details'] = [dict(effects=[p]) for p in FIGHTER_CLASSES[cls].passives]
            source['passive_details'].append(dict(effects=BUILTIN_PASSIVES['nothing_to_lose'].effects))
            source['pet'] = dict(id='dakimakura', level=10, power=2, tempo=1)
        sources.append(source)
    data = create_raid_state(participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, 'kit')
    rng = random.Random(seed)
    while not data['finished']:
        choices = {key: candidate_actions(data, key, tactical)[0] for key in alive_players(data)}
        if tactical and data['intent']['skill'] == 'kit_coins' and sum(max(0, c[0]) for c in choices.values()) < data['boss']['stats']['max_hp'] * .12:
            choices = {k: (0, 'defend') for k in choices}
        for key, (_, sid) in choices.items():
            data['players'][key]['selected'] = sid
        resolve_round(data, BUILTIN_SKILLS, rng)
    return data


def summary(seeds=30):
    output = []
    for team in TEAMS:
        for tactical, prepared in ((False, False), (True, False), (True, True)):
            games = [simulate(team, seed, tactical, prepared=prepared) for seed in range(seeds)]
            output.append(dict(team=team, tactical=tactical, prepared=prepared, games=seeds,
                               wins=sum(g['won'] for g in games),
                               mean_rounds=round(sum(g['round'] for g in games)/seeds, 1),
                               minimum_boss_hp=min(g['boss']['hp'] for g in games)))
    return output


if __name__ == '__main__':
    print(json.dumps(summary(int(sys.argv[1]) if len(sys.argv)>1 else 30), ensure_ascii=False, indent=2))
