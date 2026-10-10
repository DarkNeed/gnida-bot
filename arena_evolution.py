"""Conditional versions of native skills: same learned ID, slot and cooldown."""

from dataclasses import replace
from arena_archclasses import arch_rule
from arena_fingers import negative_kinds

EVOLUTION_LEVEL = 10
EVOLUTIONS = {
    "dust_in_eyes": dict(
        name="Уличные правила",
        condition="Завершены четыре собственных хода бойца",
        trigger="turns",
        changes=dict(power=0, cost=25),
        description="Снижает точность на 3 хода и дополнительно уклонение на 10 на 2 хода.",
    ),
    "senior_verdict": dict(
        name="Приговор без обжалования",
        condition="Накоплены три заряда субординации",
        trigger="order",
        changes=dict(power=21, cost=45, pierce=0.50, tags=("no_order_bonus",)),
        description="Пробивает 50% защиты и снижает физическую атаку цели на 15% на 2 хода. Заменяет обычный бонус зарядов; заряды расходуются.",
    ),
    "last_line": dict(
        name="Предписание исполнено",
        condition="«Последняя строка» указана в предписании",
        trigger="prescript",
        changes=dict(power=17, cost=40, accuracy=95),
        description="Повышенная точность; при попадании возвращает дополнительно 5 Воли.",
    ),
    "whole_family": dict(
        name="Долг крови",
        condition="Накоплены три обиды",
        trigger="grudge",
        changes=dict(power=17, cost=45),
        description="Прежний бонус обид; при попадании обе защиты +20% на один свой ход.",
    ),
    "last_stroke": dict(
        name="Завершённый шедевр",
        condition="На цели три разных отрицательных эффекта",
        trigger="negatives",
        changes=dict(power=18, cost=40, tags=("consume_negatives",)),
        description="Снимает отрицательные эффекты после попадания. При промахе эффекты сохраняются.",
    ),
    "moon_arc": dict(
        name="Затмение",
        condition="Накоплены три заряда сосредоточенности",
        trigger="focus",
        changes=dict(
            power=13,
            cost=20,
            accuracy=95,
            pierce=0.45,
            tags=("consume_focus", "no_critical"),
        ),
        description="Пробивает 45% защиты, не критует. Расходует 2 заряда только при попадании.",
    ),
    "uwu": dict(
        name="Ты уже мой",
        condition="Противник под умилением",
        trigger="adoration",
        changes=dict(power=12, cost=15, effects=()),
        description="Усиленная атака за 15 Любви. Не снимает и не обновляет умиление: оно действует до обычного истечения.",
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
        changes=dict(power=22, cost=35),
        description="Усиленная версия до конца боя. Против умилённой цели сохраняются +25% урона и снятие умиления при попадании.",
    ),
}


def evolution_info(skill, class_id, source=None, target=None, own_turns=0):
    specialization = arch_rule(skill, source) if source else None
    base_rule = EVOLUTIONS.get(skill.skill_id)
    rule = specialization or base_rule
    if (
        target is not None
        and base_rule
        and rule_active(base_rule, skill, source, target, own_turns)
        and not rule_active(specialization, skill, source, target, own_turns)
    ):
        rule = base_rule
    if not rule or skill.class_id != class_id:
        return None
    info = dict(
        name=rule["name"],
        min_level=rule.get("min_level", EVOLUTION_LEVEL),
        condition=rule["condition"],
        description=rule["description"],
        cost=rule["changes"].get("cost", skill.cost),
        power=rule["changes"].get("power", skill.power),
        active=False,
        specialization=rule is specialization,
    )
    if (
        specialization
        and base_rule
        and specialization["trigger"] != base_rule["trigger"]
    ):
        base_variant = apply_rule(skill, base_rule)
        combined = apply_rule(base_variant, arch_rule(base_variant, source))
        info["description"] += (
            f" При дополнительном условии «{base_rule['condition']}» сохраняется базовое превращение: "
            f"{combined.name}, сила {combined.power}, цена {combined.cost}."
        )
    return info


def rule_active(rule, skill, actor, target, own_turns):
    if (
        not rule
        or actor["class_id"] != skill.class_id
        or actor["level"] < rule.get("min_level", EVOLUTION_LEVEL)
    ):
        return False
    effects = target["effects"]
    memory = actor.get("mechanics", {})
    if rule["trigger"] == "always":
        return True
    if rule["trigger"] in {"order", "grudge", "focus"}:
        return memory.get(rule["trigger"], 0) >= 3
    if rule["trigger"] == "prescript":
        return memory.get("prescript") == skill.skill_id
    if rule["trigger"] == "negatives":
        return len(negative_kinds(target)) >= 3
    if rule["trigger"] == "charging":
        return any(
            e.get("id") == "charging_damage" and e.get("kind") == "next_magic_damage"
            for e in actor["effects"]
        )
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


def is_evolved(skill, actor, target, own_turns):
    rule = arch_rule(skill, actor) or EVOLUTIONS.get(skill.skill_id)
    return rule_active(rule, skill, actor, target, own_turns)


def skill_variant(skill, actor, target, own_turns):
    base = skill
    rule = EVOLUTIONS.get(skill.skill_id)
    if rule_active(rule, skill, actor, target, own_turns):
        skill = apply_rule(skill, rule)
    rule = arch_rule(skill, actor)
    if rule_active(rule, skill, actor, target, own_turns):
        skill = apply_rule(skill, rule)
    return skill if skill != base else base


def apply_rule(skill, rule):
    changes = dict(rule["changes"])
    drain = changes.pop("drain", None)
    if drain is not None:
        changes["effects"] = tuple(
            dict(e, value=drain) if e["kind"] == "resource_leech" else e
            for e in skill.effects
        )
    if skill.skill_id == "dust_in_eyes":
        changes["effects"] = skill.effects + (
            dict(
                id="street_evasion",
                kind="evasion_flat",
                value=-10,
                turns=2,
                target="enemy",
            ),
        )
    elif skill.skill_id == "senior_verdict" and "effects" not in changes:
        changes["effects"] = (
            dict(
                id="verdict_suppression",
                kind="physical_attack_pct",
                value=-0.15,
                turns=2,
                target="enemy",
            ),
        )
    elif skill.skill_id == "last_line" and "effects" not in changes:
        changes["effects"] = (
            dict(id="proxy_refund", kind="resource", value=5, target="self"),
        )
    elif skill.skill_id == "whole_family" and "effects" not in changes:
        changes["effects"] = tuple(
            dict(
                id="revenge_guard_" + dtype,
                kind=dtype + "_defense_pct",
                value=0.20,
                turns=1,
                target="self",
            )
            for dtype in ("physical", "magic")
        )
    return replace(skill, name=rule["name"], description=rule["description"], **changes)


def evolution_after_action(actor, target, skill, hit, evolved):
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
