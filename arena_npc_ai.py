"""Native PvE action selection. Never bypass cost, cooldown or combo conditions."""
import random
from dataclasses import replace


def basic_skill(skill, side):
    """Energy-starved NPCs use a thematic weak attack, not another class's punch."""
    if skill.skill_id != 'bum_punch' or side.get('controller_id') != 0 or side['class_id'] == 'ragamuffin':
        return skill
    names = {
        'cutie': ('Насмешливый жест', 'magic'), 'jock': ('Простой джеб', 'physical'),
        'nerd': ('Искра разряда', 'magic'), 'thumb': ('Одиночный выстрел', 'physical'),
        'index': ('Короткий росчерк', 'physical'), 'middle': ('Прямой удар', 'physical'),
        'ring': ('Мазок кистью', 'physical'), 'pinky': ('Короткий разрез', 'physical'),
        'warrior': ('Удар клинком', 'physical'), 'mage': ('Искра маны', 'magic'),
        'priest': ('Искра света', 'magic'), 'hunter': ('Удар охотничьим клинком', 'physical'),
    }
    name, dtype = names.get(side['class_id'], ('Простой удар', 'physical'))
    return replace(skill, name=name, class_id=side['class_id'], damage_type=dtype,
                   tags=skill.tags+('npc_basic',))


def choose_skill(state, key, skills, rng=None):
    from arena_engine import validate_skill, effective_stat
    rng = rng or random.SystemRandom()
    actor, target = state['sides'][key], state['sides']['b' if key == 'a' else 'a']
    history = actor.get('npc_skill_history', [])
    hp = actor['hp'] / actor['stats']['max_hp']
    missing = actor['stats']['resource_max'] - actor['resource']
    rows = []
    for sid in actor['loadout']:
        base=skills.get(sid)
        if base is None:
            continue
        if not actor.get('rp_sandbox') and (base.class_id != actor['class_id'] or 'raid_loot' in base.tags):
            continue
        try:
            skill = validate_skill(state, key, sid, skills)
        except (ValueError, KeyError):
            continue
        score = 0.0
        if skill.damage_type:
            attack = effective_stat(actor, skill.damage_type+'_attack')
            score = 16 + skill.power * .7 + attack * .12
            if skill.tags and any(t in skill.tags for t in ('rpg_visceral','rpg_soul_spend','rpg_faith_spend','rpg_mana_spend')):
                score += 5
            if sid == 'hunter_shot' and not actor.get('rpg_state', {}).get('visceral_ready'):
                score += 14
            if sid == 'armor_split' and not any(e.get('id') == 'armor_split' for e in target['effects']):
                score += 13
            if sid == 'mana_shot' and actor['resource'] < 35:
                score += 10
        for effect in skill.effects:
            kind = effect.get('kind', '')
            if kind in ('resource','rpg_blood_bullets') and effect.get('target') == 'self':
                score += 55 if actor['resource'] < 25 else 24 if missing >= 45 else -40
            elif kind in ('rpg_heal','heal_pct'):
                score += 62 if hp < .40 else 30 if hp < .72 else -45
            elif kind == 'rpg_summon':
                score += 45 if not actor.get('rpg_state', {}).get('summon') else -40
            elif effect.get('target') == 'self' and kind not in ('resource', 'rpg_heal', 'heal_pct'):
                score += -20 if any(e.get('id') == effect.get('id') for e in actor['effects']) else 12
            elif kind == 'bleed' and not any(e['kind'] == 'bleed' for e in target['effects']):
                score += 6
        if sid == 'mana_focus' and actor.get('archclass_id') == 'mage_necromancer' and not actor.get('rpg_state', {}).get('summon'):
            score += 45
        if history and sid == history[-1]:
            score -= 28
        if len(history) >= 2 and sid == history[-2]:
            score -= 8
        rows.append((sid, score))
    if not rows:
        return 'bum_punch'
    # No repeated attack while another damaging option is legal; emergency
    # healing/restoration may repeat only when it is actually necessary.
    alternatives = [row for row in rows if row[0] != (history[-1] if history else None)]
    if alternatives and max(score for _, score in alternatives) > 0:
        rows = alternatives
    best = max(score for _, score in rows)
    if best <= 0:
        return 'bum_punch'
    return rng.choice([sid for sid, score in rows if score >= best-12])
