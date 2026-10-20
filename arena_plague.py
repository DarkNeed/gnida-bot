"""Shared, saved plague statuses. No resource refunds or client-side damage."""

KINDS = {"plague_fever", "plague_spores"}


def clear(side):
    old = len(side["effects"])
    side["effects"] = [e for e in side["effects"] if e["kind"] not in KINDS]
    return len(side["effects"]) != old


def infect(side, fever=5, turns=5, spores=1, viscous=False):
    previous = next((e for e in side["effects"] if e["kind"] == "plague_spores"), {})
    stacks = min(3, int(previous.get("value", 0)) + spores)
    previous_fever = next(
        (e for e in side["effects"] if e["kind"] == "plague_fever"), {}
    )
    clear(side)
    side["effects"].extend(
        [
            dict(
                id="plague_fever",
                kind="plague_fever",
                value=max(fever, previous_fever.get("value", 0)),
                duration=max(turns, previous_fever.get("duration", 0)),
                name="Чумная лихорадка",
                viscous=viscous or previous_fever.get("viscous", False),
                description=f"−{max(fever, previous_fever.get('value', 0))} HP в начале своего хода. Очищение или отдельное восстановление энергии снимает чуму.",
            ),
            dict(
                id="plague_spores",
                kind="plague_spores",
                value=stacks,
                duration=9999,
                name="Болотные споры",
                description="−1 HP за стак в начале своего хода, до 3. Полезное лечение снимает один стак; очищение или отдельное восстановление энергии снимает всю чуму.",
            ),
        ]
    )


def healed(side):
    for e in side["effects"]:
        if e["kind"] == "plague_spores":
            e["value"] -= 1
    side["effects"] = [
        e for e in side["effects"] if e["kind"] != "plague_spores" or e["value"] > 0
    ]


def begin_turn(side):
    turn = side.get("own_turns", 0)
    if side.get("plague_tick_turn", -1) >= turn or side["hp"] <= 0:
        return 0
    side["plague_tick_turn"] = turn
    damage = min(
        side["hp"],
        sum(max(0, int(e["value"])) for e in side["effects"] if e["kind"] in KINDS),
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
