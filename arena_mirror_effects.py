"""Temporary mirror gifts. Never attach these to permanent class/passive memory."""

GIFTS = {
    "broken": ("Разбитое зеркало", "Первый промах за бой возвращает стоимость навыка."),
    "blood": (
        "Багровый осколок",
        "Попадание по кровоточащему врагу лечит 5% максимального HP.",
    ),
    "smile": (
        "Ответная улыбка",
        "Умиление дополнительно снижает физическую защиту цели на 10% на 2 хода.",
    ),
    "nerve": (
        "Последний нерв",
        "При HP не выше 35% навыки стоят на 20% меньше энергии.",
    ),
    "curtain": (
        "Железный занавес",
        "Первая прямая атака врага за бой наносит на 25% меньше урона.",
    ),
    "edge": ("Острый отблеск", "Прямой урон +10%."),
    "focus": ("Ясный отблеск", "Точность +8."),
    "shell": ("Зеркальный панцирь", "Физическая и магическая защита +12%."),
    "risk": ("Запретное отражение", "Прямой урон +20%, но обе защиты −15%."),
}
NORMAL_GIFTS = tuple(k for k in GIFTS if k != "risk")


def has_gift(side, gift):
    return gift in side.get("mirror_gifts", [])


def gift_cost(side, skill):
    if has_gift(side, "nerve") and side["hp"] <= side["stats"]["max_hp"] * 0.35:
        return max(1, (skill.cost * 4 + 4) // 5) if skill.cost else 0
    return skill.cost


def gift_modifiers(actor, target):
    accuracy = 8 if has_gift(actor, "focus") else 0
    outgoing = (
        1
        + (0.10 if has_gift(actor, "edge") else 0)
        + (0.20 if has_gift(actor, "risk") else 0)
    )
    incoming = (
        0.75
        if has_gift(target, "curtain")
        and not target.get("mechanics", {}).get("mirror_attacked")
        else 1
    )
    return accuracy, outgoing * incoming


def gift_after_action(actor, target, skill, hit, damage, cost, bleeding, charmed):
    if not actor.get("mirror_gifts") and not target.get("mirror_gifts"):
        return
    memory = actor.setdefault("mechanics", {})
    if (
        not hit
        and skill.hostile
        and has_gift(actor, "broken")
        and not memory.get("mirror_refund")
    ):
        actor["resource"] = min(
            actor["stats"]["resource_max"], actor["resource"] + cost
        )
        memory["mirror_refund"] = True
    if damage and bleeding and has_gift(actor, "blood"):
        actor["hp"] = min(
            actor["stats"]["max_hp"],
            actor["hp"] + max(1, round(actor["stats"]["max_hp"] * 0.05)),
        )
    if charmed and has_gift(actor, "smile"):
        target["effects"] = [
            e for e in target["effects"] if e.get("id") != "mirror_smile"
        ]
        target["effects"].append(
            dict(
                id="mirror_smile",
                kind="physical_defense_pct",
                value=-0.10,
                duration=2,
                target="enemy",
            )
        )
    if skill.damage_type:
        target.setdefault("mechanics", {})["mirror_attacked"] = True


def apply_gifts(side, gifts):
    side["mirror_gifts"] = list(dict.fromkeys(gifts))
    if "shell" in gifts:
        for stat in ("physical_defense", "magic_defense"):
            side["effects"].append(
                dict(
                    id="mirror_shell_" + stat,
                    kind=stat + "_pct",
                    value=0.12,
                    duration=1_000_000,
                )
            )
    if "risk" in gifts:
        for stat in ("physical_defense", "magic_defense"):
            side["effects"].append(
                dict(
                    id="mirror_risk_" + stat,
                    kind=stat + "_pct",
                    value=-0.15,
                    duration=1_000_000,
                )
            )
