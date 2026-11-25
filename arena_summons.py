"""First-class combat slots for temporary companions; never party members."""
from contextlib import contextmanager

BITE = 'cult_brood_bite'
NAME = 'Отпрыск Шуб-Ниггурата'


def units(data):
    from arena_cultist import _brood
    owners = data.get('sides')
    if owners is None:
        owners = {key: p['fighter'] for key, p in data['players'].items() if not p.get('withdrawn')}
    result = {}
    if data.get('finished'):
        return result
    for key, owner in owners.items():
        if owner['hp'] <= 0 or not (unit := _brood(owner)):
            continue
        props = dict(max_hp=unit['max_hp'], physical_attack=5 + 2 * unit['stage'],
                     magic_attack=0, physical_defense=5, magic_defense=5, speed=10, evasion=0,
                     resource_max=0)
        unit.update(is_summon=True, name=NAME, class_id='ragamuffin',
                    level=owner['level'], controller_id=0, slave_id=0, owner_id=0,
                    resource=0, stats=props, loadout=[BITE], passive_details=[])
        unit.setdefault('effects', [])
        unit.setdefault('cooldowns', {})
        unit.setdefault('own_turns', 0)
        result[f"brood:{key}:{unit.get('serial', 1)}"] = (key, owner, unit)
    return result


def troop(data):
    return {key: unit for key, (_, _, unit) in units(data).items()}


def public(data):
    return {key: dict(owner=owner, name=u['name'], hp=u['hp'], max_hp=u['max_hp'],
                      stage=u['stage'], predator=u['predator'], effects=u['effects'])
            for key, (owner, _, u) in units(data).items()}


def cleanup(data, entries):
    from arena_cultist import remove_brood
    for _, owner, unit in entries.values():
        if min(unit['hp'], owner['hp']) <= 0 and owner.get('rpg_state', {}).get('cult_brood') is unit:
            remove_brood(owner)


def scripted_splash(data, target, skill_id):
    lookup = data.get('_scripted_brood_areas', {}) if data and data.get('_qte_boss_phase') else {}
    if skill_id in lookup:
        source, targets = lookup[skill_id]
        for key, (owner, fighter, unit) in units(data).items():
            if key in targets and fighter is target:
                return source, key, unit
    return None, None, None


def intercepted_own_brood(intent, key):
    original = intent.get('original_target', '')
    return intent.get('interceptor') == key and original.startswith(f'brood:{key}:')


def choose_target(data, owner_key, actions):
    """Mobs finish off wounded offspring, or test them once every few turns."""
    for key, (owner, _, unit) in units(data).items():
        if owner == owner_key and (unit['hp'] * 2 <= unit['max_hp'] or actions % 3 == 1):
            return key
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


def strike(actor, target, rng):
    from arena_engine import Skill, resolve_skill, _tick
    from arena_raid_engine import pair_state
    from arena_plague import begin_turn
    begin_turn(actor)
    if actor['hp'] <= 0:
        return dict(text='Отпрыск погиб от чумы до завершения атаки.', damage=0, hit=False)
    if any(effect['kind'] == 'stun' for effect in actor['effects']):
        _tick(actor)
        return dict(text='Отпрыск оглушён: укус сорван.', damage=0, hit=False)
    skill = Skill(BITE, 'Хватка корней', 'ragamuffin', 1, 'physical', .85, 100, 0, 0,
                  tags=('no_critical',))
    return resolve_skill(pair_state(actor, target), 'a', BITE, {BITE: skill}, rng,
                         advance_turn=False, qte=dict(luck_accuracy=False, luck_evasion=False))


def tick_protector(owner):
    from arena_cultist import _brood, remove_brood
    from arena_engine import _tick
    from arena_plague import begin_turn
    unit = _brood(owner)
    if unit and unit.get('is_summon') and not unit['predator'] and unit['effects']:
        before = unit['hp']
        begin_turn(unit)
        if unit['hp'] > 0:
            _tick(unit)
        if unit['hp'] <= 0:
            remove_brood(owner)
        return before - unit['hp']
    return 0
