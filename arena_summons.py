"""First-class combat slots for temporary companions; never party members."""
from contextlib import contextmanager

BITE = 'cult_brood_bite'
NAME = 'Отпрыск Шуб-Ниггурата'
SKELETON, WARDEN, EXECUTIONER, EFFIGY = 'skeleton', 'warden', 'executioner', 'effigy'
TYPES = {
    SKELETON: ('Скелет', 'Костяной разряд', 'magic', 26, 4, 2.8),
    WARDEN: ('Страж', None, None, 42, 12, 0),
    EXECUTIONER: ('Палач', 'Казнь', 'physical', 32, 6, 3.15),
    EFFIGY: ('Чучело хищника', 'Укус чучела', 'physical', 31, 6, 1.15),
}
UNDEAD = (SKELETON, WARDEN, EXECUTIONER)


def is_key(key):
    return isinstance(key, str) and key.startswith(('brood:', 'summon:'))


def _owners(data):
    if 'sides' in data:
        return data['sides']
    return {key: p['fighter'] for key, p in data['players'].items() if not p.get('withdrawn')}


def _live(owner, kind):
    u = owner.get('summon_entities', {}).get(kind)
    if not u or u['hp'] <= 0 or owner['hp'] <= 0 or u.get('charges', 1) <= 0:
        return None
    if 'until' in u and owner.get('own_turns', 0) >= u['until']:
        if kind != EFFIGY or not (u.get('order') or u.get('guard_turn') == owner.get('own_turns', 0)):
            return None
    return u


def undead_active(owner):
    return any(_live(owner, kind) for kind in UNDEAD) if owner.get('board_summons') else bool(owner.get('rpg_state', {}).get('summon', 0))


def effigy_active(owner):
    return bool(_live(owner, EFFIGY)) if owner.get('board_summons') else bool(owner.get('final_state', {}).get('beast', 0))


def raise_units(owner, kinds, turns=3):
    if owner['hp'] <= 0:return
    memory = owner.setdefault('summon_entities', {})
    serial = owner.get('summon_serial', 0) + 1
    owner['summon_serial'] = serial
    for kind in (UNDEAD if any(k in UNDEAD for k in kinds) else kinds):
        memory.pop(kind, None)
    for kind in kinds:
        hp = TYPES[kind][3]
        unit = memory[kind] = dict(kind=kind, serial=serial, hp=hp, max_hp=hp, effects=[], cooldowns={}, own_turns=0)
        if kind in (SKELETON, EXECUTIONER):
            unit['charges'] = turns
        else:
            unit['until'] = owner.get('own_turns', 0) + turns


def enable(data):
    """Migrate an in-progress unified fight once; old alternating fights are untouched."""
    for owner in _owners(data).values():
        if owner.get('board_summons'):continue
        owner['board_summons'] = True
        rpg, final = owner.get('rpg_state', {}), owner.get('final_state', {})
        if rpg.get('summon', 0) > 0:
            kinds = (WARDEN, EXECUTIONER) if rpg.get('death_servants') else (SKELETON,)
            raise_units(owner, kinds, rpg['summon'])
        for key in ('summon', 'summon_power', 'summon_fresh', 'death_servants'):
            rpg.pop(key, None)
        turns = final.pop('beast', 0) if owner.get('archclass_id') == 'ring_fauvist' else 0
        if turns > 0 and owner['hp'] > 0:
            raise_units(owner, (EFFIGY,), turns)
            if any(e.get('id') == 'final_beast_guard' for e in owner['effects']):
                owner['summon_entities'][EFFIGY]['guard_turn'] = owner.get('own_turns', 0)
                owner['effects'] = [e for e in owner['effects'] if e.get('id') != 'final_beast_guard']


def extend_undead(owner):
    for kind in UNDEAD:
        if unit := _live(owner, kind):
            if 'charges' in unit:unit['charges'] = min(3, unit['charges'] + 1)
            else:unit['until'] = min(owner.get('own_turns', 0) + 3, unit['until'] + 1)


def order_effigy(owner, skill, target, native, qte_avoided):
    u = owner.get('summon_entities', {}).get(EFFIGY)
    turn = owner.get('own_turns', 0)
    if not u or u['hp'] <= 0 or turn > u['until']:return []
    if native and not skill.damage_type:
        u['guard_turn'] = turn
        return ['чучело прикрывает хозяина']
    if native and skill.damage_type and not qte_avoided and 'final_joint' not in skill.tags and target['hp'] > 0:
        u['order'] = True
        return ['чучело готовит укус']
    return []


def units(data):
    from arena_cultist import _brood
    result = {}
    if data.get('finished'):
        return result
    for key, owner in _owners(data).items():
        if owner['hp'] <= 0:
            continue
        candidates = [(f'summon:{key}:{kind}:{u["serial"]}', kind, u) for kind in TYPES if (u := _live(owner, kind))]
        if unit := _brood(owner):
            candidates.append((f'brood:{key}:{unit.get("serial", 1)}', 'brood', unit))
        for ident, kind, unit in candidates:
            name, _, _, _, armor, _ = TYPES.get(kind, (NAME, None, None, 0, 5, 0))
            power = 5 + 2 * unit['stage'] if kind == 'brood' else 3 + round(owner['stats'].get('magic_attack', 0) * .14)
            props = dict(max_hp=unit['max_hp'], physical_attack=power, magic_attack=power if kind != 'brood' else 0,
                         physical_defense=armor, magic_defense=armor, speed=10, evasion=0, resource_max=0)
            unit.update(kind=kind, is_summon=True, summon_identity=ident, name=name, class_id='ragamuffin',
                        level=owner['level'], controller_id=0, slave_id=0, owner_id=0,
                        resource=0, stats=props, loadout=[action_id(kind)], passive_details=[])
            unit.setdefault('effects', [])
            unit.setdefault('cooldowns', {})
            unit.setdefault('own_turns', 0)
            result[ident] = (key, owner, unit)
    return result


def troop(data):
    return {key: unit for key, (_, _, unit) in units(data).items()}


def public(data):
    return {key: dict(owner=key_owner, name=u['name'], hp=u['hp'], max_hp=u['max_hp'],
                      kind=u['kind'], stage=u.get('stage'), predator=u.get('predator', False), effects=u['effects'],
                      remaining=u.get('charges', max(0, u.get('until', 0)-owner.get('own_turns', 0))),
                      guarding=cover_percent(owner, u))
            for key, (key_owner, owner, u) in units(data).items()}


def cleanup(data, entries):
    from arena_cultist import remove_brood
    for _, owner, unit in entries.values():
        if min(unit['hp'], owner['hp']) <= 0 and owner.get('rpg_state', {}).get('cult_brood') is unit:
            remove_brood(owner)
    for key, owner in _owners(data).items():
        memory = owner.get('summon_entities', {})
        had_undead = any(kind in memory for kind in UNDEAD)
        for kind in tuple(memory):
            if not _live(owner, kind):del memory[kind]
        if had_undead and not undead_active(owner):
            from arena_equipment import summoner_refund
            if refund := summoner_refund(owner):
                yield key, refund


def scripted_splash(data, target, skill_id):
    lookup = data.get('_scripted_brood_areas', {}) if data and data.get('_qte_boss_phase') else {}
    if skill_id in lookup:
        source, targets = lookup[skill_id]
        return [(source, key, unit) for key, (_, fighter, unit) in units(data).items()
                if key in targets and fighter is target]
    return []


def intercepted_own_brood(intent, key):
    original = intent.get('original_target', '')
    return intent.get('interceptor') == key and is_key(original) and original.split(':')[1] == key


def cover_percent(owner, unit):
    if unit['kind'] == 'brood':return 15 if unit['predator'] else 30
    if unit['kind'] == SKELETON and owner['level'] >= 12:return 25
    if unit['kind'] == WARDEN:return 35
    if unit['kind'] == EFFIGY and unit.get('guard_turn') == owner.get('own_turns', 0):return 20
    return 0


def guard(owner):
    if owner.get('_cult_brood_exposed'):return None, 0
    for kind in (WARDEN, SKELETON, EFFIGY):
        if (u := _live(owner, kind)) and (pct := cover_percent(owner, u)):
            return u, pct
    return None, 0


def choose_target(data, owner_key, actions):
    """Mobs finish off weakened summons, or test one every few turns."""
    options = [(u['hp']/u['max_hp'], key) for key,(owner,_,u) in units(data).items() if owner==owner_key]
    if options:
        health, key = min(options)
        if health <= .5 or actions % 3 == 1:return key
    return owner_key


@contextmanager
def expose(owner, active=True):
    """Permit normal AoE damage, without redirecting a second hit."""
    previous = owner.get('_cult_brood_exposed')
    if active:
        owner['_cult_brood_exposed'] = True
    try:
        yield
    finally:
        if active:
            if previous is None:
                owner.pop('_cult_brood_exposed', None)
            else:
                owner['_cult_brood_exposed'] = previous


def action_id(kind):
    return BITE if kind == 'brood' else 'summon_' + kind


def action_skill(unit, target=None):
    from arena_engine import Skill
    kind = unit['kind']
    if kind == 'brood':
        if not unit.get('predator'):return None
        return Skill(BITE, 'Хватка корней', 'ragamuffin', 1, 'physical', .85, 100, 0, 0,
                     tags=('no_critical',), cast_base=3.2)
    if kind == WARDEN or kind == EFFIGY and not unit.get('order'):return None
    _, name, damage_type, _, _, base = TYPES[kind]
    power = {SKELETON: 5, EXECUTIONER: 8, EFFIGY: 6}[kind]
    pierce = None
    if target is not None and kind == EFFIGY:
        from arena_finals import negative_kinds
        if len(negative_kinds(target)) >= 2:pierce=.50
        if any(e['kind']=='speed_pct' and e['value']<0 for e in target['effects']):power *= 1.4
    return Skill(action_id(kind), name, 'ragamuffin', 1, damage_type, power, 95, 0, 0,
                 tags=('no_critical',), cast_base=base, pierce=pierce)


def strike(actor, target, rng):
    from arena_engine import resolve_skill, _tick
    from arena_raid_engine import pair_state
    from arena_plague import begin_turn
    skill = action_skill(actor, target)
    actor.pop('order', None)
    if 'charges' in actor:actor['charges'] -= 1
    begin_turn(actor)
    if actor['hp'] <= 0:
        return dict(text='Атака отменена: призыв погиб от чумы.', damage=0, hit=False)
    if any(effect['kind'] == 'stun' for effect in actor['effects']):
        _tick(actor)
        return dict(text='Атака отменена: призыв оглушён.', damage=0, hit=False)
    return resolve_skill(pair_state(actor, target), 'a', skill.skill_id, {skill.skill_id: skill}, rng,
                         advance_turn=False, qte=dict(luck_accuracy=False, luck_evasion=False))


def credit_soul(owner, unit, event):
    if unit['kind'] in (SKELETON, EXECUTIONER) and event['damage'] > 0 and owner['hp'] > 0:
        memory = owner.setdefault('rpg_state', {})
        memory['souls'] = min(3, memory.get('souls', 0) + 1)
        event['text'] += f" · души {memory['souls']}/3"


def tick_protector(owner, unit):
    from arena_cultist import remove_brood
    from arena_engine import _tick
    from arena_plague import begin_turn
    if (unit['kind']==WARDEN or unit['kind']=='brood' and not unit['predator']) and unit['effects']:
        before = unit['hp']
        begin_turn(unit)
        if unit['hp'] > 0:
            _tick(unit)
        if unit['hp'] <= 0 and unit['kind']=='brood':
            remove_brood(owner)
        return before - unit['hp']
    return 0
