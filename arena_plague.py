"""Shared, saved plague statuses. No resource refunds or client-side damage."""

KINDS = {"plague_fever", "plague_spores"}


def _variant(effect):
    # Unmarked saved effects retain their original (Whaler) rules.
    return effect.get('plague_variant', 'boss')


def clear(side, variant=None):
    old = len(side["effects"])
    side["effects"] = [e for e in side["effects"]
                       if e['kind'] not in KINDS or variant is not None and _variant(e) != variant]
    return len(side["effects"]) != old


def infect(side, fever=5, turns=5, spores=1, viscous=False, variant='boss'):
    previous = next((e for e in side['effects'] if e['kind'] == 'plague_spores' and _variant(e) == variant), {})
    stacks = min(3, int(previous.get("value", 0)) + spores)
    previous_fever = next(
        (e for e in side['effects'] if e['kind'] == 'plague_fever' and _variant(e) == variant), {}
    )
    clear(side, variant)
    trophy = variant == 'trophy'
    prefix = 'trophy_' if trophy else ''
    spore_damage = 2 if trophy else 1
    counterplay = ('Лечебный навык или очищение снимает всю чуму. Активное восстановление энергии снимает один стак спор, но не лихорадку. Пассивный хил и реген не очищают.'
                   if trophy else 'Очищение или отдельное восстановление энергии снимает чуму.')
    side["effects"].extend(
        [
            dict(
                id=prefix + 'plague_fever',
                kind="plague_fever",
                plague_variant=variant,
                value=max(fever, previous_fever.get("value", 0)),
                duration=max(turns, previous_fever.get("duration", 0)),
                name="Чумная лихорадка",
                viscous=viscous or previous_fever.get("viscous", False),
                description=f"−{max(fever, previous_fever.get('value', 0))} HP в начале своего хода. " + counterplay,
            ),
            dict(
                id=prefix + 'plague_spores',
                kind="plague_spores",
                plague_variant=variant,
                damage_per_stack=spore_damage,
                value=stacks,
                duration=9999,
                name="Болотные споры",
                description=('−2 HP за стак в начале своего хода; до 3 стаков, максимум −6 HP за ход. ' + counterplay
                             if trophy else '−1 HP за стак в начале своего хода, до 3. Полезное лечение снимает один стак; очищение или отдельное восстановление энергии снимает всю чуму.'),
            ),
        ]
    )


def healed(side):
    """Legacy boss plague reacts to any useful healing; the tractate does not."""
    for e in side["effects"]:
        if e['kind'] == 'plague_spores' and _variant(e) == 'boss':
            e["value"] -= 1
    side["effects"] = [
        e for e in side["effects"] if e["kind"] != "plague_spores" or e["value"] > 0
    ]


def actively_healed(side):
    """Called at an explicit healing effect, never from a net-HP/passive hook."""
    return clear(side, 'trophy')


def actively_restored(side):
    clear(side, 'boss')
    for e in side['effects']:
        if e['kind'] == 'plague_spores' and _variant(e) == 'trophy':
            e['value'] -= 1
    side['effects'] = [e for e in side['effects'] if e['kind'] != 'plague_spores' or e['value'] > 0]


def begin_turn(side):
    turn = side.get("own_turns", 0)
    if side.get("plague_tick_turn", -1) >= turn or side["hp"] <= 0:
        return 0
    side["plague_tick_turn"] = turn
    from arena_relics import periodic_damage
    damage = min(
        side["hp"],
        periodic_damage(side,sum(max(0, int(e['value'])) * (int(e.get('damage_per_stack', 1)) if e['kind'] == 'plague_spores' else 1)
            for e in side['effects'] if e['kind'] in KINDS)),
    )
    side["hp"] -= damage
    if side["hp"] <= 0:
        from arena_rpg import branch
        from arena_rpg_combat import revive

        revive(side, branch(side))
    return damage


def deliberate_restore(skill):
    return not skill.hostile and any(
        e["kind"] == "rpg_blood_bullets"
        or e["kind"] == "resource"
        and e.get("target") == "self"
        and e.get("value", 0) > 0
        for e in skill.effects
    )
