"""Public raid snapshots; actions remain private until the round is resolved."""

from dataclasses import asdict
import json
import time

from arena_engine import effective_stat, effective_skill, skill_restriction
from arena_evolution import evolution_info
from arena_archclasses import archclass_view, class_title
from arena_progression import choice_avatar
from arena_raid_engine import BOSSES, BOSS_SKILLS, pair_state
from arena_mirror_effects import gift_cost


async def raid_view(db, row, actor):
    classes, skills = await db.get_fighter_catalog()
    data = json.loads(row["data_json"]) if row["data_json"] else None
    boss_info = BOSSES.get(row.get("boss_id", "iron"), BOSSES["iron"])

    async def decorate(side, fighter, boss=False):
        cls = classes.get(side["class_id"], classes["ragamuffin"])
        user = await db.get_user(row["chat_id"], fighter) if fighter else None
        side.update(
            name=(
                boss_info["name"]
                if boss
                else user["display_name"] if user else str(fighter)
            ),
            class_name="Рейдовый босс" if boss else class_title(side, cls.name),
            class_avatar_url=choice_avatar(
                side["class_id"], side.get("archclass_id", "")
            ),
            sprite=side["class_id"],
            resource_name=cls.resource_name,
            class_rarity=cls.rarity,
            archclass=archclass_view(side),
            effective_stats={k: effective_stat(side, k) for k in side["stats"]},
        )
        side["accuracy_bonus"] = sum(
            e.get("value", 0) for e in side["effects"] if e["kind"] == "accuracy_flat"
        )
        boosts = [
            e.get("value", 0) for e in side["effects"] if e["kind"] == "damage_pct"
        ]
        side["damage_bonus"] = (
            max(0.1, 1 + sum(v for v in boosts if v >= 0))
            * max(0.1, 1 + sum(v for v in boosts if v < 0))
            - 1
        )
        if not boss:
            side.update(await db.arena_sprite_info(row["chat_id"], fighter))
        elif boss_info.get("sprite"):
            side["class_avatar_url"] = boss_info["sprite"]
        side["skill_details"] = []
        target = (
            data["boss"]
            if not boss
            else next(iter(data["players"].values()))["fighter"]
        )
        catalog = BOSS_SKILLS if boss else skills
        pair = pair_state(side, target)
        ids = list(side["loadout"])
        if (
            not boss
            and "bum_punch" not in ids
            and not any(
                gift_cost(side, effective_skill(pair, "a", sid, catalog))
                <= side["resource"]
                and not side["cooldowns"].get(sid, 0)
                and not skill_restriction(side, catalog[sid])
                for sid in ids
                if sid in catalog
            )
        ):
            ids.append("bum_punch")
        for sid in ids:
            if sid not in catalog:
                continue
            variant = effective_skill(pair, "a", sid, catalog)
            info = evolution_info(
                catalog[sid], side["class_id"], side, target, side.get("own_turns", 0)
            )
            if info:
                info["active"] = variant is not catalog[sid]
                if info["active"]:
                    info.update(
                        name=variant.name, cost=variant.cost, power=variant.power
                    )
            side["skill_details"].append(
                dict(
                    asdict(variant),
                    cost=gift_cost(side, variant),
                    evolution=info,
                    unavailable_reason=skill_restriction(side, variant),
                )
            )

    participants = []
    for p in row["participants"]:
        user = await db.get_user(row["chat_id"], p["actor_id"])
        fighter = await db.get_user(row["chat_id"], p["fighter_id"])
        participants.append(
            dict(
                actor_id=p["actor_id"],
                fighter_id=p["fighter_id"],
                personal=bool(p["personal"]),
                name=user["display_name"] if user else str(p["actor_id"]),
                fighter_name=(
                    fighter["display_name"] if fighter else str(p["fighter_id"])
                ),
            )
        )
    if data:
        await decorate(data["boss"], 0, True)
        for key, player in data["players"].items():
            await decorate(player["fighter"], player["fighter_id"])
            player["ready"] = player["selected"] is not None
            # Other players see only readiness, not the selected ability.
            if player["actor_id"] != actor:
                player["selected"] = None
    choices = []
    if row["status"] == "lobby":
        choices.append(
            dict(fighter_id=actor, personal=True, name="Мой личный персонаж")
        )
        async with db._lock:
            rows = db.connection.execute(
                """SELECT s.slave_id,u.display_name FROM arena_combat_slots s JOIN ownership o
                   ON o.chat_id=s.chat_id AND o.slave_id=s.slave_id AND o.owner_id=s.owner_id
                   LEFT JOIN users u ON u.chat_id=s.chat_id AND u.user_id=s.slave_id
                   WHERE s.chat_id=? AND (s.owner_id=? OR s.slave_id=?)""",
                (row["chat_id"], actor, actor),
            ).fetchall()
            choices += [
                dict(
                    fighter_id=r["slave_id"],
                    personal=False,
                    name="Раб: " + (r["display_name"] or str(r["slave_id"])),
                )
                for r in rows
            ]
    return dict(
        token=row["token"],
        chat_id=row["chat_id"],
        creator_id=row["creator_id"],
        actor_id=actor,
        status=row["status"],
        revision=row["revision"],
        deadline=row["deadline"],
        server_time=int(time.time()),
        boss_name=boss_info["name"],
        boss_id=row.get("boss_id", "iron"),
        recommended_level=boss_info.get("recommended_level", 1),
        participants=participants,
        choices=choices,
        data=data,
    )
