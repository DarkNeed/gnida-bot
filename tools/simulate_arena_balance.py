"""Repeatable, offline balance smoke test. No database, tokens or Telegram calls.

Two heuristic policies and rotating four-skill builds are not optimal play.
Use these results to detect dominant classes, not to promise PvP win rates.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    effective_stat,
    effective_skill,
    resolve_skill,
)
from arena_fingers import combat_modifiers, has_trait
from arena_class_mechanics import class_modifiers, JOCK_PREPARATION_SKILLS
from arena_archclasses import ARCHCLASSES

BUILDS = {
    "jock": [
        ("smack", "butt_peak", "wallop", "clench"),
        ("smack", "wallop", "flex_chest", "clench"),
    ],
    "cutie": [
        ("uwu", "posing", "air_kiss", "meow"),
        ("uwu", "posing", "air_kiss", "dust_in_eyes"),
    ],
    "nerd": [
        ("humiliate", "charging", "mother_joke", "go_to_store"),
        ("humiliate", "doxxing", "mother_joke", "go_to_store"),
    ],
    "thumb": [("bayonet", "reload", "warning_shot", "senior_verdict")],
    "index": [("first_line", "receive_prescript", "literal", "last_line")],
    "middle": [("recorded", "grit_teeth", "answer_for_it", "whole_family")],
    "ring": [("first_stroke", "unfinished_portrait", "red_etude", "last_stroke")],
    "pinky": [("silent_cut", "calm_breath", "moon_arc", "falling_star")],
}


def damage_estimate(actor, target, skill):
    if not skill.damage_type:
        return 0
    extra_accuracy, boost, pierce, _, _ = combat_modifiers(
        actor, target, skill, random.Random(0)
    )
    if skill.pierce is not None:
        pierce = skill.pierce
    c_accuracy, c_boost = class_modifiers(actor, target, skill)
    chance = max(
        0.05,
        min(
            0.95,
            (
                skill.accuracy
                + extra_accuracy
                + c_accuracy
                + sum(
                    e["value"] for e in actor["effects"] if e["kind"] == "accuracy_flat"
                )
                - effective_stat(target, "evasion")
            )
            / 100,
        ),
    )
    buffs = [e["value"] for e in actor["effects"] if e["kind"] == "damage_pct"]
    attack = effective_stat(actor, skill.damage_type + "_attack")
    defense = effective_stat(target, skill.damage_type + "_defense") * (1 - pierce)
    critical = (0.25 if skill.skill_id == "falling_star" else 0) + (
        0.12 * actor.get("mechanics", {}).get("focus", 0)
        if has_trait(actor, "constellation")
        else 0
    )
    critical = 0 if "no_critical" in skill.tags else min(0.75, critical)
    return (
        chance
        * max(
            1,
            skill.power
            * (1 + attack / 20)
            * 100
            / (100 + defense * 4)
            * max(0.1, 1 + sum(v for v in buffs if v >= 0) + boost + c_boost)
            * max(0.1, 1 + sum(v for v in buffs if v < 0)),
        )
        * (1 + 0.5 * critical)
    )


def select_skill(state, style):
    key = state["active_side"]
    actor, target = state["sides"][key], state["sides"]["b" if key == "a" else "a"]
    candidates = [
        effective_skill(state, key, k)
        for k in actor["loadout"]
        if effective_skill(state, key, k).cost <= actor["resource"]
        and not actor["cooldowns"].get(k, 0)
    ]
    if not candidates:
        candidates = [BUILTIN_SKILLS["bum_punch"]]
    enemy_peak = max(
        damage_estimate(
            target, actor, effective_skill(state, "b" if key == "a" else "a", k)
        )
        for k in target["loadout"] + ["bum_punch"]
    )
    own_peak = max(
        damage_estimate(actor, target, effective_skill(state, key, k))
        for k in actor["loadout"] + ["bum_punch"]
    )
    best, score = None, -float("inf")
    for skill in candidates:
        value = damage_estimate(actor, target, skill)
        hit = (
            max(
                0.05,
                min(0.95, (skill.accuracy - effective_stat(target, "evasion")) / 100),
            )
            if skill.hostile
            else 1
        )
        if style == "tactical":
            energy_value = 0.07 if actor["resource"] >= 40 else 0.18
            value -= skill.cost * energy_value
            enemy_order = actor.get("mechanics", {}).get("enemy_prescript")
            if enemy_order and enemy_order["skill_id"] != skill.skill_id:
                value -= (
                    min(actor["resource"] - skill.cost, enemy_order["penalty"])
                    * energy_value
                )
            for e in skill.effects:
                recipient = actor if e.get("target") == "self" else target
                old = next(
                    (
                        old
                        for old in recipient["effects"]
                        if (old.get("id"), old["kind"]) == (e.get("id"), e["kind"])
                    ),
                    None,
                )
                turns = max(
                    0, e.get("turns", 0) - (old.get("duration", 0) if old else 0)
                )
                if e["kind"] == "resource":
                    value += (
                        hit
                        * e.get("chance", 1)
                        * min(
                            max(0, e["value"]),
                            recipient["stats"]["resource_max"] - recipient["resource"],
                        )
                        * energy_value
                    )
                elif e["kind"] == "resource_leech":
                    value += (
                        hit
                        * min(e["value"], target["resource"])
                        * (0.5 * energy_value + 0.05)
                    )
                elif e["kind"] == "stun":
                    value += hit * e.get("chance", 1) * enemy_peak
                elif e["kind"] == "bleed":
                    value += hit * e.get("chance", 1) * e["value"] * max(1, turns)
                elif e["kind"] == "damage_pct" and recipient is target:
                    value -= (
                        hit
                        * e.get("chance", 1)
                        * e["value"]
                        * enemy_peak
                        * min(3, turns)
                    )
                elif e["kind"] in {"accuracy_flat", "evasion_flat"}:
                    improvement = e["value"] if recipient is actor else -e["value"]
                    value += (
                        hit
                        * improvement
                        / 100
                        * (
                            enemy_peak
                            if e["kind"] == "evasion_flat"
                            and recipient is actor
                            or e["kind"] == "accuracy_flat"
                            and recipient is target
                            else own_peak
                        )
                        * turns
                    )
                elif e["kind"].endswith("defense_pct"):
                    improvement = e["value"] if recipient is actor else -e["value"]
                    value += (
                        hit
                        * improvement
                        * 0.45
                        * (enemy_peak if recipient is actor else own_peak)
                        * turns
                    )
                elif e["kind"] == "next_magic_damage" and not old:
                    value += e["value"] * own_peak
            if skill.skill_id == "receive_prescript" and has_trait(actor, "prescript"):
                value += 2
            if skill.skill_id == "calm_breath" and has_trait(actor, "constellation"):
                value += 0.06 * own_peak
            if skill.skill_id in JOCK_PREPARATION_SKILLS:
                if has_trait(actor, "right_version") and not any(
                    e["kind"] == "next_physical_damage" for e in actor["effects"]
                ):
                    physical_peak = max(
                        (
                            damage_estimate(actor, target, BUILTIN_SKILLS[k])
                            for k in actor["loadout"] + ["bum_punch"]
                            if BUILTIN_SKILLS[k].damage_type == "physical"
                        ),
                        default=0,
                    )
                    value += hit * 0.15 * physical_peak
                if has_trait(actor, "fucking_stamina"):
                    value += hit * min(8, skill.cost) * energy_value
        elif value <= 0:
            value = sum(
                min(
                    max(0, e["value"]),
                    actor["stats"]["resource_max"] - actor["resource"],
                )
                * 0.2
                for e in skill.effects
                if e["kind"] == "resource" and e.get("target") == "self"
            )
        if value > score:
            best, score = skill.skill_id, value
    return best


def match(
    first,
    second,
    level,
    seed,
    style,
    controlled=False,
    foreign=False,
    jock_passives=True,
):
    def source(cls, user):
        archclass_id = cls if cls in ARCHCLASSES else ""
        if archclass_id:
            cls = ARCHCLASSES[archclass_id]["class_id"]
        builds = BUILDS[cls]
        build = list(builds[seed % len(builds)])
        if foreign:
            build = ["uwu", "humiliate", "go_to_store", "mother_joke"]
        build = [k for k in build if BUILTIN_SKILLS[k].unlock_level <= level]
        result = dict(
            slave_id=user,
            owner_id=user,
            class_id=cls,
            archclass_id=archclass_id,
            level=level,
            controlled=controlled,
            loadout=build,
            granted_skills=build if foreign else [],
        )
        if cls == "jock" and not jock_passives:
            result["passive_details"] = []
        return result

    state = create_battle_state(source(first, 1), source(second, 2))
    a, b = state["sides"]["a"], state["sides"]["b"]
    state["active_side"] = (
        "a"
        if effective_stat(a, "speed") > effective_stat(b, "speed")
        else (
            "b"
            if effective_stat(b, "speed") > effective_stat(a, "speed")
            else ("a" if seed % 2 else "b")
        )
    )
    rng = random.Random(seed)
    while not state["finished"]:
        resolve_skill(state, state["active_side"], select_skill(state, style), rng=rng)
    return state["winner"], state["turn"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", type=int, default=200)
    p.add_argument(
        "--classes",
        default=",".join(BUILDS),
        help="Comma-separated class IDs or archclass IDs, e.g. femboy,princess,mge_bro",
    )
    p.add_argument("--levels", default="5,10,20")
    p.add_argument("--style", choices=("damage", "tactical"), default="tactical")
    p.add_argument("--controlled", action="store_true")
    p.add_argument("--foreign", action="store_true")
    p.add_argument(
        "--no-jock-passives",
        action="store_true",
        help="Compare the same policy with jock's new passives disabled.",
    )
    args = p.parse_args()
    classes = args.classes.split(",")
    if args.samples < 1 or any(
        k not in BUILDS and k not in ARCHCLASSES for k in classes
    ):
        p.error("Use positive samples and known class/archclass IDs.")
    results = []
    for level in map(int, args.levels.split(",")):
        for i, first in enumerate(classes):
            for second in classes[i + 1 :]:
                wins = draws = turns = 0
                for seed in range(args.samples):
                    winner, duration = match(
                        first,
                        second,
                        level,
                        seed,
                        args.style,
                        args.controlled,
                        args.foreign,
                        not args.no_jock_passives,
                    )
                    wins += winner == "a"
                    draws += winner is None
                    turns += duration
                results.append(
                    dict(
                        level=level,
                        first=first,
                        second=second,
                        first_win_pct=round(100 * wins / args.samples, 1),
                        draw_pct=round(100 * draws / args.samples, 1),
                        mean_actions=round(turns / args.samples, 1),
                    )
                )
    print(
        json.dumps(
            dict(
                policy=args.style,
                samples=args.samples,
                controlled=args.controlled,
                foreign=args.foreign,
                jock_passives=not args.no_jock_passives,
                results=results,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
