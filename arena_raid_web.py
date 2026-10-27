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
from arena_encounters import MOBS
from arena_casino import public_state as casino_public_state


async def raid_view(db, row, actor):
    classes, skills = await db.get_fighter_catalog()
    if row.get('boss_id') == 'encounter':
        from arena_rp import rp_skills
        skills = rp_skills(skills)
    data = json.loads(row["data_json"]) if row["data_json"] else None
    boss_info = BOSSES.get(row.get("boss_id", "iron"), BOSSES["iron"])
    nazarick = bool(data and row.get('boss_id') == 'nazarick')

    async def decorate(side, fighter, boss=False, character_slot=1, mob=False):
        mob_info = MOBS.get(side.get('mob_id')) if mob else None
        cls = classes.get(side["class_id"], classes["ragamuffin"])
        user = await db.get_user(row["chat_id"], fighter) if fighter else None
        side.update(
            name=(
                side['name'] if mob or side.get('rp_sandbox') else boss_info["name"]
                if boss
                else user["display_name"] if user else str(fighter)
            ),
            class_name=mob_info['role'] if mob_info else class_title(side, cls.name) if side.get('rp_sandbox') else 'Рейдовый босс' if boss else class_title(side, cls.name),
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
        if not boss and not side.get('rp_sandbox'):
            side.update(await db.arena_character_sprite_info(fighter,character_slot))
        elif boss_info.get("sprite"):
            side["class_avatar_url"] = raid_boss_sprite(row.get('boss_id', 'iron'), data.get('phase', 1))
        if nazarick and boss:
            from arena_nazarick import sprite, identity
            who, phase = identity(data)
            side['name'] = side.get('name') if mob else data['boss']['name']
            side['class_avatar_url'] = sprite(who, phase) if not side.get('nz_sprite') else sprite(side['nz_sprite'])
            side['sprite_flip'] = False
        if mob_info:
            side['class_avatar_url'] = mob_info['sprite']
        if boss and boss_info.get("ally_sprite"):
            side["resource_name"] = "Заряд инатора"
        side["skill_details"] = []
        target = (
            data["boss"]
            if not boss
            else next(iter(data["players"].values()))["fighter"]
        )
        catalog = skills if side.get('rp_sandbox') else BOSS_SKILLS if boss else skills
        if side.get('rp_sandbox'):
            from arena_rp import appearance
            side.update(appearance(side))
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
        rp_template = None
        if row.get('boss_id') == 'encounter':
            async with db._lock:
                selected = db.connection.execute('SELECT template_id FROM arena_rp_selections WHERE token=? AND actor_id=?', (row['token'], p['actor_id'])).fetchone()
                if selected:
                    try:
                        rp_template = db._rp_template_locked(p['actor_id'], selected['template_id'])
                    except ValueError:
                        rp_template = dict(id=selected['template_id'], definition=dict(name='Удалённый RP-шаблон'))
        participants.append(
            dict(
                actor_id=p["actor_id"],
                fighter_id=p["fighter_id"],
                personal=bool(p["personal"]),
                rp_template=rp_template['id'] if rp_template else None,
                name=user["display_name"] if user else str(p["actor_id"]),
                fighter_name=(
                    rp_template['definition']['name'] if rp_template else fighter["display_name"] if fighter else str(p["fighter_id"])
                ),
            )
        )
    if data:
        # Authoritative full combat checkpoints are private and can be large.
        data.pop('_chaplain_snapshot', None)
        data.pop('_chaplain_results', None)
        data.pop('_chaplain_previous', None)
        if data.get('kind') == 'encounter':
            for enemy in data['enemies'].values():
                await decorate(enemy, 0, True, mob=True)
            data['boss'] = next(iter(data['enemies'].values()))
        elif nazarick:
            from arena_nazarick import presentation
            for enemy in data['enemies'].values():
                await decorate(enemy, 0, True, mob=enemy.get('nz_sprite') is not None)
            data['boss'] = data['enemies']['boss']
            data['nazarick_view'] = presentation(data)
            data['nazarick'].pop('initial_players', None)
        else:
            await decorate(data['boss'], 0, True)
        for key, player in data["players"].items():
            player.pop('qte_result',None)
            await decorate(player["fighter"], player["fighter_id"],character_slot=player.get('character_slot',1))
            player["ready"] = player["selected"] is not None
            # Other players see only readiness, not the selected ability.
            if player["actor_id"] != actor:
                player["selected"] = None
                player.pop('selected_target', None)
    choices = []
    if row["status"] == "lobby":
        choices.append(
            dict(fighter_id=actor, personal=True, name="Мой личный персонаж")
        )
        if row.get('boss_id') == 'encounter':
            for template in await db.arena_rp_templates(actor):
                if template['kind'] == 'character':
                    choices.append(dict(fighter_id=actor, personal=True, rp_template=template['id'],
                                        name='🎭 ' + template['definition']['name'] + ' · Lv.' + str(template['definition']['level'])))
    config = json.loads(row['encounter_json']) if row.get('encounter_json') else None
    master = await db.get_user(row['chat_id'], row['creator_id']) if config else None
    return dict(
        token=row["token"],
        chat_id=row["chat_id"],
        creator_id=row["creator_id"],
        kind='encounter' if config else 'raid',
        rp_menu=bool(config and config.get('rp')),
        master_name=master['display_name'] if master else str(row['creator_id']),
        is_master=bool(config and actor == row['creator_id']),
        encounter_roster=([dict(id=mob, name=MOBS[mob]['name']) if isinstance(mob, str) else dict(id=mob['id'], name=mob['name']) for mob in config['roster']] if config else []),
        rewards_enabled=not bool(config),
        actor_id=actor,
        qte=await db.arena_qte_view('raid',row['token'],actor),
        qte_watch=await db.arena_qte_watchables('raid',row['token'],actor),
        status=row["status"],
        revision=row["revision"],
        deadline=row["deadline"],
        server_time=int(time.time()),
        boss_name=data['boss']['name'] if nazarick else boss_info["name"],
        boss_id=row.get("boss_id", "iron"),
        silent=bool(row.get("silent", False)),
        recommended_level=boss_info.get("recommended_level", 1),
        fixed_level=boss_info.get('fixed_level'),
        min_level=boss_info.get('min_level', 1),
        encounter_rules=('С 20 уровня. 600/900/1200 HP на 1/2/3 бойцов, обе защиты 0, уклонение 5%. '
                         'Кара — по восстановившему больше всех, один раз за раунд; пассивные 8% не учитываются. '
                         'На последней четверти HP: восстановите 30 энергии на живого участника за раунд, добейте босса или защищайтесь от Гнили.'
                         if row.get('boss_id')=='whaler' else
                         'Без ограничения по уровню; рекомендуется 20+. Обычный откат — отдельное объявленное действие раз в 5–7 раундов. '
                         'Закрепление тратит действие, действует три раунда и сохраняет выбранный результат. '
                         'Восстановление на 30% HP возвращает только здоровье босса, не состояние игроков. '
                         'Помеченный навык отнимает ещё 10% максимального HP, но не убивает. Предел — 100 реальных раундов.'
                         if row.get('boss_id')=='chaplain' else ''),
        difficulty=boss_info.get('difficulty', ''),
        phase_count=boss_info.get('phase_count', 2),
        boss_sprites=dict(boss_info.get('phase_sprites', {})),
        ally_sprite=boss_info.get("ally_sprite", ""),
        loot_name=(
            skills[boss_info["loot_skill"]].name if boss_info.get("loot_skill") else ""
        ),
        participants=participants,
        choices=choices,
        reward_status=dict(disabled=True) if config else (await db.arena_raid_reward_status(actor))[row.get('boss_id', 'iron')],
        data=casino_public_state(data),
    )
