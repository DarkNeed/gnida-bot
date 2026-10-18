"""Public raid snapshots; actions remain private until the round is resolved."""

from dataclasses import asdict
import json
import time

from arena_engine import effective_stat, effective_skill, skill_restriction
from arena_evolution import evolution_info
from arena_rpg_descriptions import skill_description as rpg_skill_description
from arena_archclasses import archclass_view, class_title
from arena_progression import choice_avatar
from arena_mastery import view as mastery_view
from arena_raid_engine import BOSSES, BOSS_SKILLS, pair_state, raid_boss_sprite
from arena_mirror_effects import gift_cost
from arena_pets import pet_cost


async def raid_view(db, row, actor):
    classes, skills = await db.get_fighter_catalog()
    data = json.loads(row["data_json"]) if row["data_json"] else None
    boss_info = BOSSES.get(row.get("boss_id", "iron"), BOSSES["iron"])

    async def decorate(side, fighter, boss=False, character_slot=1):
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
                side["class_id"], side.get("archclass_id", ""), 20 if side.get('level', 0) >= 20 and side.get('archclass_stage', 20) >= 20 else 10
            ),
            sprite=side["class_id"],
            resource_name=cls.resource_name,
            class_rarity=cls.rarity,
            archclass=archclass_view(side),
            mastery=mastery_view(side),
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
            * side.get("raid_damage_multiplier", 1)
            - 1
        )
        if not boss:
            side.update(await db.arena_character_sprite_info(fighter,character_slot))
        elif boss_info.get("sprite"):
            side["class_avatar_url"] = raid_boss_sprite(row.get('boss_id', 'iron'), data.get('phase', 1))
        if boss and boss_info.get("ally_sprite"):
            side["resource_name"] = "Заряд инатора"
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
                pet_cost(side, effective_skill(pair, "a", sid, catalog), gift_cost(side, effective_skill(pair, "a", sid, catalog)))
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
                info["active"] = info.get('final_ready',variant is not catalog[sid])
                if info["active"]:
                    info.update(
                        name=variant.name, cost=variant.cost, power=variant.power
                    )
            side["skill_details"].append(
                dict(
                    asdict(variant),
                    description=rpg_skill_description(variant,side),
                    cost=pet_cost(side, variant, gift_cost(side, variant)),
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
            await decorate(player["fighter"], player["fighter_id"],character_slot=player.get('character_slot',1))
            player["ready"] = player["selected"] is not None
            # Other players see only readiness, not the selected ability.
            if player["actor_id"] != actor:
                player["selected"] = None
    choices = []
    if row["status"] == "lobby":
        choices.append(
            dict(fighter_id=actor, personal=True, name="Мой личный персонаж")
        )
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
        silent=bool(row.get("silent", False)),
        recommended_level=boss_info.get("recommended_level", 1),
        fixed_level=boss_info.get('fixed_level'),
        difficulty=boss_info.get('difficulty', ''),
        phase_count=boss_info.get('phase_count', 2),
        boss_sprites=dict(boss_info.get('phase_sprites', {})),
        ally_sprite=boss_info.get("ally_sprite", ""),
        loot_name=(
            skills[boss_info["loot_skill"]].name if boss_info.get("loot_skill") else ""
        ),
        participants=participants,
        choices=choices,
        reward_status=(await db.arena_raid_reward_status(actor))[row.get("boss_id", "iron")],
        data=data,
    )
