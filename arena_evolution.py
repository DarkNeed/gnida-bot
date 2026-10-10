"""Conditional versions of native skills: same learned ID, slot and cooldown."""

from dataclasses import replace

EVOLUTION_LEVEL = 10
EVOLUTIONS = {
    "uwu": dict(
        name="Ты уже мой",
        condition="Противник под умилением",
        trigger="adoration",
        changes=dict(power=12, cost=20, effects=()),
        description="Усиленная атака. При попадании снимает умиление; при промахе оно сохраняется.",
    ),
    "smack": dict(
        name="Последний подход",
        condition="После успешного «Напрячь сиси» или «Зажим булками», в течение двух своих ходов",
        trigger="preparation",
        changes=dict(power=12, cost=15),
        description="Усиленная подготовленная атака. Подготовка расходуется даже при промахе; бонус экипированной пассивки учитывается один раз.",
    ),
    "humiliate": dict(
        name="Полный деанон",
        condition="На противнике действует снижение магической защиты от Деанона",
        trigger="doxxing",
        changes=dict(power=15, cost=25, drain=20),
        description="Отнимает до 20 энергии и возвращает половину действительно отнятого ресурса. Деанон не снимается.",
    ),
    "meow": dict(
        name="Кульминация: Мяу",
        condition="Завершены четыре собственных хода бойца",
        trigger="turns",
        changes=dict(power=19, cost=40),
        description="Усиленная версия до конца боя. Против умилённой цели сохраняются +25% урона и снятие умиления при попадании.",
    ),
}


def evolution_info(skill, class_id):
    rule = EVOLUTIONS.get(skill.skill_id)
    if not rule or skill.class_id != class_id:
        return None
    return dict(
        name=rule["name"],
        min_level=EVOLUTION_LEVEL,
        condition=rule["condition"],
        description=rule["description"],
        cost=rule["changes"]["cost"],
        power=rule["changes"]["power"],
        active=False,
    )


def is_evolved(skill, actor, target, own_turns):
    rule = EVOLUTIONS.get(skill.skill_id)
    if (
        not rule
        or actor["class_id"] != skill.class_id
        or actor["level"] < EVOLUTION_LEVEL
    ):
        return False
    effects = target["effects"]
    if rule["trigger"] == "adoration":
        return any(
            e.get("id") == "adoration"
            and e["kind"] == "damage_pct"
            and e.get("value", 0) < 0
            for e in effects
        )
    if rule["trigger"] == "doxxing":
        return any(
            e.get("id") == "doxxing_magic"
            and e["kind"] == "magic_defense_pct"
            and e.get("value", 0) < 0
            for e in effects
        )
    if rule["trigger"] == "preparation":
        return any(e.get("id") == "evolution_prepared" for e in actor["effects"])
    return own_turns >= 4


def skill_variant(skill, actor, target, own_turns):
    if not is_evolved(skill, actor, target, own_turns):
        return skill
    rule = EVOLUTIONS[skill.skill_id]
    changes = dict(rule["changes"])
    drain = changes.pop("drain", None)
    if drain is not None:
        changes["effects"] = tuple(
            dict(e, value=drain) if e["kind"] == "resource_leech" else e
            for e in skill.effects
        )
    return replace(skill, name=rule["name"], description=rule["description"], **changes)


def evolution_after_action(actor, target, skill, hit, evolved):
    if evolved and skill.skill_id == "uwu" and hit:
        target["effects"] = [e for e in target["effects"] if e.get("id") != "adoration"]
    # All physical attempts consume the charge, as with Right Version: choosing
    # another physical attack cannot save the same preparation for a second hit.
    if skill.damage_type == "physical":
        actor["effects"] = [
            e for e in actor["effects"] if e.get("id") != "evolution_prepared"
        ]
    if (
        actor["class_id"] == "jock"
        and actor["level"] >= EVOLUTION_LEVEL
        and hit
        and skill.skill_id in {"flex_chest", "clench"}
    ):
        actor["effects"] = [
            e for e in actor["effects"] if e.get("id") != "evolution_prepared"
        ]
        actor["effects"].append(
            dict(
                id="evolution_prepared",
                kind="prepared_attack",
                value=0,
                duration=2,
                target="self",
                description="«Въебать» усилено; подготовка расходуется на следующую физическую попытку.",
            )
        )
