"""Offline raid smoke test with a simple heuristic, not optimal player strategy."""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, validate_skill
from arena_raid_engine import (
    create_raid_state,
    pair_state,
    resolve_round,
    alive_players,
)
from arena_archclasses import branch_options
from arena_archprogress import branch_skill_allowed
from simulate_arena_balance import BUILDS, damage_estimate


def choose(player, boss):
    actor = player["fighter"]
    pair = pair_state(actor, boss)
    candidates = []
    for sid in actor["loadout"] + ["bum_punch"]:
        try:
            skill = validate_skill(pair, "a", sid)
        except ValueError:
            continue
        value = damage_estimate(actor, boss, skill) - skill.cost * 0.06
        for e in skill.effects:
            target = actor if e.get("target") == "self" else boss
            if any(
                old.get("id") == e.get("id") and old["duration"] > 1
                for old in target["effects"]
            ):
                continue
            kind = e["kind"]
            amount = e.get("value", 0)
            if kind == "resource" and e.get("target") == "self":
                value += (
                    min(amount, actor["stats"]["resource_max"] - actor["resource"])
                    * 0.3
                )
            elif kind == "stun":
                value += 12
            elif kind == "bleed":
                value += amount * 2
            elif kind == "accuracy_flat" and e.get("target") == "enemy":
                value += max(0, -amount) * 0.3
            elif kind == "damage_pct":
                value += abs(amount) * (20 if e.get("target") == "enemy" else 12)
            elif kind.endswith("defense_pct"):
                value += abs(amount) * 8
        candidates.append((value, sid))
    return max(candidates)[1] if candidates else "defend"


def simulate(level, class_ids, seed, boss_id="iron"):
    rng = random.Random(seed)
    members = [
        dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i) for i in (1, 2, 3)
    ]
    sources = []
    for i, cls in enumerate(class_ids, 1):
        options = branch_options(cls) if level >= 10 else []
        branch = options[seed % len(options)]["id"] if options else ""
        native = [
            k
            for k in BUILDS.get(cls, [("bum_punch",)])[0]
            if BUILTIN_SKILLS[k].unlock_level <= level
        ]
        unique = [
            s.skill_id
            for s in BUILTIN_SKILLS.values()
            if any(t == "archclass:" + branch for t in s.tags)
            and s.unlock_level <= level
            and branch_skill_allowed(s, branch, level)
        ]
        loadout = (native[:2] + unique[:1] + native[2:])[:4]
        sources.append(
            dict(
                slave_id=i,
                owner_id=i,
                class_id=cls,
                level=level,
                loadout=loadout,
                archclass_id=branch,
                archclass_stage=10,
            )
        )
    data = create_raid_state(members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, boss_id)
    while not data["finished"]:
        for key, p in alive_players(data).items():
            p["selected"] = (
                "defend"
                if data["intent"].get("skill") == "lei_perfected_flurry"
                and key in data["intent"]["targets"]
                else choose(p, data["boss"])
            )
        resolve_round(data, BUILTIN_SKILLS, rng)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--boss", choices=("iron", "lei_heng"), default="iron")
    args = parser.parse_args()
    results = []
    for level in (1, 5, 10, 20):
        teams = (
            [("ragamuffin",) * 3]
            if level == 1
            else [("jock", "cutie", "nerd"), ("middle", "pinky", "ring")]
        )
        for team in teams:
            games = [simulate(level, team, n, args.boss) for n in range(args.seeds)]
            results.append(
                dict(
                    level=level,
                    team=team,
                    wins=sum(d["won"] for d in games),
                    games=len(games),
                    mean_rounds=round(sum(d["round"] for d in games) / len(games), 1),
                )
            )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
