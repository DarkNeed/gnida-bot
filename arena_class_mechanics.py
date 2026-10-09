"""Core class identities; equipped passives, not class labels, enable traits."""

from arena_fingers import has_trait

JOCK_PREPARATION_SKILLS = frozenset({"flex_chest", "clench"})


def has_adoration(side):
    return any(
        e.get("id") == "adoration"
        and e["kind"] == "damage_pct"
        and e.get("value", 0) < 0
        for e in side["effects"]
    )


def class_modifiers(actor, target, skill):
    accuracy = boost = 0
    if has_adoration(target):
        boost += {"air_kiss": 0.20, "meow": 0.25}.get(skill.skill_id, 0)
    if skill.skill_id == "mother_joke" and any(
        e.get("id") == "doxxing_magic" for e in target["effects"]
    ):
        boost += 0.20
    if skill.damage_type == "magic":
        boost += sum(
            e.get("value", 0)
            for e in actor["effects"]
            if e["kind"] == "next_magic_damage"
        )
        last = actor.get("mechanics", {}).get("last_magic")
        if has_trait(actor, "analysis") and last not in {None, skill.skill_id}:
            accuracy += 10
    if skill.damage_type == "physical":
        boost += sum(
            e.get("value", 0)
            for e in actor["effects"]
            if e["kind"] == "next_physical_damage"
        )
    return accuracy, boost


def class_after_action(actor, target, skill, hit, dodged, adored, charmed):
    memory = actor.setdefault("mechanics", {})
    refund = 5 if charmed and has_trait(actor, "charming") else 0
    if skill.damage_type == "magic":
        memory["last_magic"] = skill.skill_id
        if skill.cost and has_trait(actor, "economy"):
            count = memory.get("paid_magic", 0) + 1
            memory["paid_magic"] = count % 3
            if count == 3:
                refund += 10
    if hit and skill.skill_id in JOCK_PREPARATION_SKILLS:
        if has_trait(actor, "right_version"):
            # Refresh one charge after the current action's tick, never stack it.
            actor["effects"] = [
                e for e in actor["effects"] if e.get("id") != "right_version_ready"
            ]
            actor["effects"].append(
                dict(
                    id="right_version_ready",
                    kind="next_physical_damage",
                    value=0.15,
                    duration=2,
                    target="self",
                )
            )
        if has_trait(actor, "fucking_stamina"):
            refund += min(8, skill.cost)
    actor["resource"] = min(actor["stats"]["resource_max"], actor["resource"] + refund)
    if dodged and has_trait(target, "evasive_love"):
        target["resource"] = min(
            target["stats"]["resource_max"], target["resource"] + 8
        )
    if hit and adored and skill.skill_id == "meow":
        target["effects"] = [e for e in target["effects"] if e.get("id") != "adoration"]
