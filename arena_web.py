"""HTTP boundary: Telegram-signed identity, chat membership and server-side combat."""

from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qsl
from aiohttp import web
from aiogram.exceptions import TelegramAPIError
from arena_assets import render_arena_index
from arena_qte import add_qte_lab_routes
from arena_engine import (
    level_progress,
    level_from_total_xp,
    normalize_loadout,
    unlocked_skill_ids,
    stats_for,
    effective_stat,
    effective_skill,
    passive_skill_limit,
    completed_turns,
    skill_restriction,
    RARITY_LABELS,
    MAX_FIGHTER_LEVEL,
    VISIBLE_CLASS_ALIASES,
    SKILL_DELEGATION_SECONDS,
)
from arena_fingers import FINGER_IDS
from custom_commands import CUSTOM_COMMAND_OWNER_ID
from arena_images import MAX_SPRITE_BYTES, normalize_sprite
from arena_mirror_effects import GIFTS, gift_cost, gift_modifiers
from arena_evolution import evolution_info
from arena_rpg_descriptions import skill_description as rpg_skill_description
from arena_archclasses import archclass_view, class_title, branch_options
from arena_progression import pending_choice, choice_avatar
from arena_mastery import view as mastery_view, street_stats, variant as mastery_variant, BASE, BASE_FINAL, BRANCHES
from arena_raid_web import raid_view
from arena_raid_engine import BOSSES, AVAILABLE_BOSSES
from arena_pets import pet_cost, PET_PACKS, PET_TERMS_VERSION
from arena_characters import CHARACTER_PACK, CHARACTER_TERMS_VERSION
from aiogram.types import LabeledPrice

ROOT = Path(__file__).parent / "webapp"
ACTOR = web.RequestKey("arena_actor", int)


def validate_init_data(raw: str, token: str, now: int | None = None) -> dict:
    if not raw or len(raw) > 16384:
        raise ValueError("Откройте арену через Telegram.")
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("Некорректная авторизация.")
    supplied = data.pop("hash", "")
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret,
        "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("Некорректная подпись Telegram.")
    now = int(time.time()) if now is None else now
    date = int(data.get("auth_date", 0))
    if date > now + 30 or now - date > 86400:
        raise ValueError("Сессия истекла. Откройте арену заново.")
    user = json.loads(data.get("user", "{}"))
    if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
        raise ValueError("Нет пользователя Telegram.")
    return user


async def require_member(bot, chat: int, user: int):
    try:
        member = await bot.get_chat_member(chat, user)
    except TelegramAPIError as error:
        raise ValueError("Не удалось проверить участие в чате.") from error
    status = member.status.value if hasattr(member.status, "value") else member.status
    if status in {"left", "kicked"} or (
        status == "restricted" and not member.is_member
    ):
        raise ValueError("Арена доступна только участникам этого чата.")
    return member


def int_field(data: dict, key: str, default=0) -> int:
    value = data.get(key, default)
    if type(value) is not int:
        raise ValueError("Некорректное число.")
    return value


async def battle_view(db, row: dict, actor: int) -> dict:
    classes, skills = await db.get_fighter_catalog()
    state = json.loads(row["state_json"]) if row["state_json"] else None
    names = {}
    for key in ("a", "b"):
        for kind in ("owner", "fighter"):
            user = row[key + "_" + kind]
            if user is not None:
                info = await db.get_user(row["chat_id"], user) if user else None
                names[key + "_" + kind] = (
                    info["display_name"]
                    if info
                    else ("Пустошь" if not user else str(user))
                )
    if state:
        for key, side in state["sides"].items():
            side["name"] = names.get(key + "_fighter", "Боец")
            cls = classes.get(side["class_id"], classes["ragamuffin"])
            if row["mode"] == "wasteland" and key == "b":
                prefix = (
                    "Зеркальный босс"
                    if state.get("mirror_token") and row["floor"] == 5
                    else "Зеркало" if state.get("mirror_token") else "Пустошь"
                )
                side["name"] = f"{prefix} · {class_title(side, cls.name)}"
                names["b_fighter"] = side["name"]
            side["archclass"] = archclass_view(side)
            side['mastery'] = mastery_view(side)
            side["class_name"] = class_title(side, cls.name)
            side["class_avatar_url"] = choice_avatar(
                side["class_id"], side.get("archclass_id", ""), 20 if side["archclass"] and side["archclass"]["stage"] == 20 else 10
            )
            side["resource_name"] = cls.resource_name
            side["class_rarity"] = cls.rarity
            side["class_rarity_name"] = RARITY_LABELS[cls.rarity]
            side["sprite"] = (
                side["class_id"]
                if side["class_id"] in {"cutie", "jock", "nerd", "warrior", "mage", "priest", "hunter"} | FINGER_IDS
                else "ragamuffin"
            )
            side.update(
                await db.arena_character_sprite_info(row[key + "_fighter"] or 0,row.get(key+'_character_slot',1))
            )
            side["skill_details"] = []
            for s in side["loadout"]:
                if s not in skills:
                    continue
                variant = effective_skill(state, key, s, skills)
                info = evolution_info(
                    skills[s],
                    side["class_id"],
                    side,
                    state["sides"]["b" if key == "a" else "a"],
                    completed_turns(state, key),
                )
                if info:
                    info["active"] = info.get('final_ready',variant is not skills[s])
                    if info["active"]:
                        info.update(
                            name=variant.name,
                            cost=variant.cost,
                            power=variant.power,
                            description=rpg_skill_description(variant,side),
                        )
                side["skill_details"].append(
                    dict(
                        asdict(variant),
                        description=rpg_skill_description(variant,side),
                        cost=pet_cost(side, variant, gift_cost(side, variant)),
                        evolution=info,
                        unavailable_reason=skill_restriction(
                            side, variant, completed_turns(state, key)
                        ),
                    )
                )
            side["mirror_gift_details"] = [
                dict(name=GIFTS[k][0], description=GIFTS[k][1])
                for k in side.get("mirror_gifts", [])
                if k in GIFTS
            ]
            side["passive_details"] = side.get("passive_details", [])[
                : passive_skill_limit(side["level"])
            ]
            side["effective_stats"] = {
                k: effective_stat(side, k) for k in side["stats"]
            }
            mirror_accuracy, mirror_damage = gift_modifiers(side, {})
            side["accuracy_bonus"] = mirror_accuracy + sum(
                e.get("value", 0)
                for e in side["effects"]
                if e["kind"] == "accuracy_flat"
            )
            damage_effects = [
                e.get("value", 0) for e in side["effects"] if e["kind"] == "damage_pct"
            ]
            side["damage_bonus"] = (
                max(0.1, 1 + sum(v for v in damage_effects if v >= 0))
                * max(0.1, 1 + sum(v for v in damage_effects if v < 0))
                * mirror_damage
                - 1
            )
            side["can_use_potion"] = side["controller_id"] == actor and bool(
                await db.arena_potion_count(row["chat_id"], actor)
            )
            order = side.get("mechanics", {}).get("enemy_prescript")
            side["enemy_prescript_name"] = (
                skills[order["skill_id"]].name
                if order and order.get("skill_id") in skills
                else ""
            )
            if "bum_punch" not in side["loadout"] and (
                (order and 'bum_punch' in order.get('allowed',[order['skill_id']]))
                or not any(
                    pet_cost(side, effective_skill(state, key, s, skills), gift_cost(side, effective_skill(state, key, s, skills)))
                    <= side["resource"]
                    and not side["cooldowns"].get(s, 0)
                    and not skill_restriction(
                        side, skills[s], completed_turns(state, key)
                    )
                    for s in side["loadout"]
                    if s in skills
                )
            ):
                side["skill_details"].append(asdict(skills["bum_punch"]))
    own_side = (
        "a" if actor == row["a_owner"] else "b" if actor == row["b_owner"] else None
    )
    available = []
    if row["status"] == "pending" and own_side and row["mode"] == "slaves":
        for slave in await db.arena_combat_slaves(row["chat_id"], actor):
            available.append(
                dict(
                    id=slave["user_id"],
                    name=slave["name"],
                    level=slave["level"],
                    slot=slave["combat_slot"],
                    choice_required=bool(pending_choice(slave)),
                )
            )
    consent = next(
        (
            k
            for k in ("a", "b")
            if row[k + "_fighter"] == actor and not row[k + "_control"]
        ),
        None,
    )
    return {
        k: row[k]
        for k in (
            "token",
            "chat_id",
            "mode",
            "status",
            "revision",
            "stake",
            "floor",
            "deadline",
            "a_control",
            "b_control",
            "a_fighter",
            "b_fighter",
            "a_consent",
            "b_consent",
            "b_accepted",
        )
    } | dict(
        ranked=bool(row.get("ranked")),
        a_character_slot=row.get('a_character_slot',1),
        b_character_slot=row.get('b_character_slot',1),
        server_time=int(time.time()),
        state=state,
        names=names,
        own_side=own_side,
        consent_side=consent,
        available=available,
        actor_id=actor,
        qte=await db.arena_qte_view('battle',row['token'],actor),
    )


async def menu_view(db, chat: int, actor: int) -> dict:
    await db.arena_require_enabled(chat)
    for _ in range(3):
        before=await db.arena_characters(actor)
        result=await _menu_view(db,chat,actor)
        if result['characters']['revision']==before['revision']:
            await db.arena_require_enabled(chat)
            return result
    raise ValueError('Персонаж изменился в другом окне. Обнови меню.')


async def _menu_view(db, chat: int, actor: int) -> dict:
    mirror_runs = await db.arena_mirror_list(chat, actor)
    result = await db.arena_menu(chat, actor)
    result['combat_settings']=await db.arena_combat_settings(actor)
    classes, skills = await db.get_fighter_catalog()
    enabled_classes=set(classes)
    profiles = [(result["personal"], True), *((p, False) for p in result["slaves"])]
    if result["self_slave"]:
        profiles.append((result["self_slave"], False))
    for profile, personal in profiles:
        profile["personal"] = personal
        profile["progress"] = level_progress(profile["xp"])
        profile["stats"] = stats_for(
            profile["class_id"], profile["level"], False, classes
        )
        profile['stats'] = street_stats(profile, profile['stats'])
        profile['mastery'] = mastery_view(profile)
        profile["class_name"] = classes.get(
            profile["class_id"], classes["ragamuffin"]
        ).name
        profile["base_class_name"] = profile["class_name"]
        profile["archclass"] = archclass_view(profile)
        profile["class_name"] = class_title(profile, profile["class_name"])
        profile["class_avatar_url"] = choice_avatar(
            profile["class_id"], profile.get("archclass_id", ""), 20 if profile["archclass"] and profile["archclass"]["stage"] == 20 else 10
        )
        profile["archclass_options"] = branch_options(profile["class_id"])
        pending = profile.get("archclass_pending_at")
        profile["archclass_can_choose"] = profile["user_id"] == actor or (
            not personal
            and pending is not None
            and time.time() >= pending + SKILL_DELEGATION_SECONDS
        )
        profile["class_rarity"] = classes.get(
            profile["class_id"], classes["ragamuffin"]
        ).rarity
        profile["class_rarity_name"] = RARITY_LABELS[profile["class_rarity"]]
        target = profile.get("catchup_target_xp", 0)
        profile["catchup_level"] = level_from_total_xp(target) if target > profile["xp"] else 0
        profile["sprite"] = (
            profile["class_id"]
            if profile["class_id"] in {"cutie", "jock", "nerd", "warrior", "mage", "priest", "hunter"} | FINGER_IDS
            else "ragamuffin"
        )
        profile.update(await db.arena_sprite_info(chat, profile["user_id"]))
        profile["can_edit_sprite"] = profile["user_id"] == actor
        # Grants are scoped to this user/chat, not the entire custom catalog.
        passive_view = await db.arena_passive_view(chat, profile["user_id"], personal)
        grants = passive_view.pop("granted")
        profile.update(passive_view)
        profile.update(await db.arena_module_profile(chat,profile['user_id'],personal,profile['class_id']))
        profile['loadout']=[k for k in profile['loadout'] if k in skills and (skills[k].class_id in enabled_classes or skills[k].class_id not in classes)]
        async with db._lock:
            class_grants = db._granted_content_locked(chat, profile["user_id"], "class")
        from arena_rpg import branch as rpg_branch, rpg_variant
        def profile_skill(skill):
            if rpg_branch(profile) and skill.class_id==profile['class_id']:
                variant=rpg_variant(skill,dict(profile,effects=[],rpg_state={}),dict(hp=100,stats=dict(max_hp=100),effects=[]))
                return dict(asdict(variant),description=rpg_skill_description(variant,profile),evolution=evolution_info(skill,profile['class_id'],profile) if profile['mastery'] else None)
            variant=mastery_variant(skill,dict(profile,effects=[],mastery_state={}),dict(hp=100,stats=dict(max_hp=100),effects=[]))
            if variant is not skill:
                return dict(asdict(variant),evolution=evolution_info(skill,profile['class_id'],profile))
            return dict(asdict(skill),evolution=evolution_info(skill,profile['class_id'],profile))
        profile["skills"] = [
            dict(
                profile_skill(skills[k]),
                module_disabled=skills[k].class_id in classes and skills[k].class_id not in enabled_classes,
            )
            for k in unlocked_skill_ids(
                profile["class_id"],
                profile["level"],
                skills,
                grants,
                profile["known_skills"],
                profile["archclass_id"],
                profile['progression_level'],
            )
        ]
        for entry in profile.get('skill_offers',[])+profile.get('available_skills',[]):
            entry.update(profile_skill(skills[entry['skill_id']]))
        profile["classes"] = [
            dict(
                id=k,
                name=c.name,
                rarity=c.rarity,
                avatar_url=choice_avatar(k),
                description="Ресурс: " + c.resource_name,
            )
            for k, c in classes.items()
            if k in enabled_classes and ((k in set(VISIBLE_CLASS_ALIASES.values()) and k != "ragamuffin")
            or k in class_grants)
        ]
        stage = pending_choice(profile)
        pending_at = profile.get("progression_pending_at")
        async with db._lock:
            blocked = db._arena_choice_busy_locked(chat, profile["user_id"])
        can_choose = not blocked and (
            profile["user_id"] == actor
            or (
                not personal
                and pending_at is not None
                and time.time() >= pending_at + SKILL_DELEGATION_SECONDS
            )
        )
        profile['module_can_choose']=not blocked and (profile['user_id']==actor or (not personal and profile.get('module_pending_at') and time.time()>=profile['module_pending_at']+SKILL_DELEGATION_SECONDS))
        profile['module_options']=[dict(id='ragamuffin',name='Оборванец',avatar_url=choice_avatar('ragamuffin'),description='Базовый класс всегда доступен. Уровень и опыт сохранятся.'),
                                   *[c for c in profile['classes'] if classes[c['id']].base_level<=profile['level']]]
        for a in profile['module_archives']:
            a['name']=classes.get(a['class_id'],classes['ragamuffin']).name
            a['avatar_url']=choice_avatar(a['class_id'],a['archclass_id'])
        options = []
        if stage:
            current_name = (
                profile["archclass"]["name"]
                if profile["archclass"]
                else profile["base_class_name"]
            )
            options.append(
                dict(
                    id="stay",
                    name=current_name,
                    avatar_url=profile["class_avatar_url"],
                    description=('Совершенное владение ветвью: '+BRANCHES[profile['archclass_id']][5] if profile.get('archclass_id') in BRANCHES else
                        'Путь мастерства: '+(BASE_FINAL[profile['class_id']] if stage==20 else BASE[profile['class_id']][1]) if profile['class_id'] in BASE else 'Сохранить текущий класс.'),
                    current=True,
                )
            )
            if stage == 5 or profile['class_id']=='ragamuffin':
                options.extend(profile["classes"])
            elif stage == 20 and profile["archclass"]:
                a = profile["archclass"]
                options.append(
                    dict(
                        id="advance",
                        name=a["final_name"],
                        avatar_url=choice_avatar(profile["class_id"], profile["archclass_id"], 20),
                        description=a["final_description"],
                        current=False,
                    )
                )
            else:
                options.extend(
                    dict(
                        id=a["id"],
                        name=a["final_name"] if stage == 20 else a["name"],
                        avatar_url=choice_avatar(profile["class_id"], a["id"], stage),
                        description=a["description"]
                        + (" " + a["final_description"] if stage == 20 else ""),
                        current=False,
                    )
                    for a in profile["archclass_options"]
                )
        profile["progression_choice"] = (
            dict(level=stage, can_choose=can_choose, busy=blocked, options=options)
            if stage
            else None
        )
    result["chat_id"] = chat
    result["actor_id"] = actor
    result["admin"] = False
    result['characters']=await db.arena_characters(actor)
    result["max_level"] = MAX_FIGHTER_LEVEL
    result.update(await db.arena_market_view(chat, actor))
    result["mirror_runs"] = mirror_runs
    result["raids"] = await db.arena_raid_list(chat, actor)
    reward_status = await db.arena_raid_reward_status(actor)
    result["raid_bosses"] = [
        dict(id=boss_id, name=boss["name"], sprite=boss.get("sprite", ""),
             recommended_level=boss.get("recommended_level", 1),
             fixed_level=boss.get('fixed_level'), difficulty=boss.get('difficulty', ''),
             **reward_status[boss_id])
        for boss_id, boss in BOSSES.items() if boss_id in AVAILABLE_BOSSES
    ]
    return result


def create_arena_app(
    db, bot, token: str, changed=None, raid_changed=None, *, pets_payments_enabled=False
) -> web.Application:
    member_cache: dict[tuple[int, int], float] = {}

    async def app_menu(chat,actor):
        result=await menu_view(db,chat,actor)
        result['characters']['payments_enabled']=pets_payments_enabled
        result['leaderboard']=await db.arena_leaderboard(actor)
        return result

    async def read_member(chat: int, actor: int) -> None:
        await db.arena_require_enabled(chat)
        now = time.monotonic()
        key = (chat, actor)
        if member_cache.get(key, 0) > now:
            return
        await require_member(bot, chat, actor)
        if len(member_cache) > 2000:
            for stale in [k for k, expires in member_cache.items() if expires <= now]:
                member_cache.pop(stale, None)
        member_cache[key] = now + 20

    @web.middleware
    async def guard(request, handler):
        try:
            if request.path.startswith("/api/"):
                request[ACTOR] = validate_init_data(
                    request.headers.get("X-Telegram-Init-Data", ""), token
                )["id"]
            response = await handler(request)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            return web.json_response(
                {"error": str(error)}, status=400, headers={"Cache-Control": "no-store"}
            )
        except web.HTTPRequestEntityTooLarge:
            return web.json_response(
                {
                    "error": (
                        "Файл слишком большой. Максимум — 2 МБ."
                        if request.path.endswith("/sprite")
                        else "Запрос слишком большой."
                    )
                },
                status=413,
            )
        except web.HTTPException:
            raise
        except Exception:
            logging.exception("Arena request failed: %s", request.path)
            return web.json_response(
                {"error": "Ошибка сервера. Попробуйте ещё раз."}, status=500
            )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app = web.Application(middlewares=[guard], client_max_size=64 * 1024)
    image_slots = asyncio.Semaphore(2)

    async def index(request):
        return web.Response(
            text=render_arena_index(ROOT),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def stylesheet(request):
        return web.FileResponse(
            ROOT / "style.css", headers={"Cache-Control": "no-cache"}
        )

    async def client(request):
        return web.FileResponse(
            ROOT / "battle-client",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    async def health(request):
        return web.json_response({"ok": True})

    async def audio(request):
        return web.FileResponse(
            ROOT / "arena-audio",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    async def pets_page(request):
        text = (ROOT / "pets.html").read_text(encoding="utf-8")
        version = hashlib.sha256(b"".join((ROOT / name).read_bytes() for name in ("pets.html", "pet-client", "pet-style.css", "pet-scene.css"))).hexdigest()[:16]
        return web.Response(text=text.replace("pet-client.js\"", f"pet-client.js?v={version}\"").replace("pet-style.css\"", f"pet-style.css?v={version}\"").replace("pet-scene.css\"", f"pet-scene.css?v={version}\""),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def pets_client(request):
        return web.FileResponse(ROOT / "pet-client", headers={"Content-Type": "application/javascript; charset=utf-8", "Cache-Control": "no-cache"})

    async def get_pets(request):
        chat = int(request.query.get("chat", 0))
        if chat:
            await read_member(chat, request[ACTOR])
        view = await db.pet_view(request[ACTOR], chat)
        view["payments_enabled"] = pets_payments_enabled
        return web.json_response(view)

    async def post_pets(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Некорректное действие.")
        actor, chat = request[ACTOR], int_field(data, "chat")
        if chat:
            await require_member(bot, chat, actor)
        revision = int_field(data, "revision", None)
        action = data.get("action")
        if action == "open":
            result = await db.pet_open(actor, revision, data.get("nonce"), chat)
            result["view"]["payments_enabled"] = pets_payments_enabled
            return web.json_response(result)
        view = await db.pet_action(actor, revision, action, data.get("pet_id", ""), data.get("choice", ""), chat)
        view["payments_enabled"] = pets_payments_enabled
        return web.json_response(dict(view=view))

    async def pets_invoice(request):
        if not pets_payments_enabled:
            raise ValueError("Продажи пока выключены. Бесплатные билеты доступны.")
        data = await request.json()
        if not isinstance(data, dict) or data.get("accept_terms") is not True or data.get("terms_version") != PET_TERMS_VERSION:
            raise ValueError("Примите условия покупки.")
        pack = data.get("pack")
        if not isinstance(pack, str) or pack not in PET_PACKS:
            raise ValueError("Неизвестный пакет.")
        order = await db.pet_create_order(request[ACTOR], pack, PET_TERMS_VERSION)
        link = await bot.create_invoice_link(
            title="Посылки с питомцами", description=f"{order['tickets']} билетов. Питомец определяется случайно; шансы и гарантии показаны в магазине.",
            payload=order["payload"], provider_token="", currency="XTR",
            prices=[LabeledPrice(label="Билеты", amount=order["stars"])])
        return web.json_response(dict(invoice=link, order_id=order["id"]))

    async def characters_invoice(request):
        if not pets_payments_enabled:raise ValueError('Продажи временно выключены.')
        data=await request.json()
        if not isinstance(data,dict) or data.get('accept_terms') is not True or data.get('terms_version')!=CHARACTER_TERMS_VERSION:
            raise ValueError('Примите условия открытия персонажей.')
        chat=int_field(data,'chat')
        await require_member(bot,chat,request[ACTOR])
        await db.arena_require_enabled(chat)
        order=await db.pet_create_order(request[ACTOR],CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        link=await bot.create_invoice_link(title='Четыре дополнительных персонажа',
            description='Всего 5 слотов во всех чатах. Без подписки. Новые персонажи с 1 уровня; лимиты наград общие для аккаунта.',
            payload=order['payload'],provider_token='',currency='XTR',prices=[LabeledPrice(label='4 слота персонажей',amount=order['stars'])])
        return web.json_response(dict(invoice=link,order_id=order['id']))

    async def get_battle(request):
        await db.arena_qte_refresh('battle',request.match_info['token'])
        row = await db.arena_get(request.match_info["token"])
        await read_member(row["chat_id"], request[ACTOR])
        return web.json_response(await battle_view(db, row, request[ACTOR]))

    async def post_battle(request):
        row = await db.arena_get(request.match_info["token"])
        actor = request[ACTOR]
        await require_member(bot, row["chat_id"], actor)
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Некорректный запрос.")
        action = body.get("action")
        # Controllers/fighters must still be in the group, even for offers created earlier.
        if action in {"accept", "select", "consent", "skill", "qte"}:
            for k in ("a", "b"):
                if row[k + "_owner"]:
                    await require_member(bot, row["chat_id"], row[k + "_owner"])
                if row[k + "_fighter"]:
                    await require_member(bot, row["chat_id"], row[k + "_fighter"])
        if action == "select":
            await require_member(bot, row["chat_id"], int_field(body, "fighter"))
        if action in {"skill","qte"}:
            row = await db.arena_interactive_action(
                row["token"],
                actor,
                int_field(body, "revision"),
                str(action),str(body.get("skill", "")),
                proof=body.get('proof'),challenge_id=body.get('challenge_id'),
            )
        else:
            controlled = body.get("controlled", True)
            if type(controlled) is not bool:
                raise ValueError("Некорректный режим контроля.")
            row = await db.arena_setup(
                row["token"], actor, str(action), int_field(body, "fighter"), controlled
            )
        if changed:
            await changed(row["token"])
        return web.json_response(await battle_view(db, row, actor))

    async def get_menu(request):
        chat = int(request.match_info["chat"])
        actor = request[ACTOR]
        await read_member(chat, actor)
        return web.json_response(await app_menu(chat, actor))

    async def get_leaderboard(request):
        chat = int(request.match_info["chat"])
        await read_member(chat, request[ACTOR])
        return web.json_response(await db.arena_leaderboard(request[ACTOR],
            season=request.query.get("season"), page=int(request.query.get("page", "0")),
            mine=request.query.get("mine") == "1"))

    async def get_raid(request):
        await db.arena_qte_refresh('raid',request.match_info['token'])
        row = await db.arena_raid_get(request.match_info["token"])
        await read_member(row["chat_id"], request[ACTOR])
        return web.json_response(await raid_view(db, row, request[ACTOR]))

    async def post_raid(request):
        actor = request[ACTOR]
        row = await db.arena_raid_get(request.match_info["token"])
        member = await require_member(bot, row["chat_id"], actor)
        if member.user.is_bot:
            raise ValueError("Боты не могут участвовать в рейде.")
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("action"), str):
            raise ValueError("Некорректный запрос.")
        action = body["action"]
        if action in {"skill","qte"}:
            participant = next(
                (p for p in row["participants"] if p["actor_id"] == actor), None
            )
            if participant:
                await require_member(bot, row["chat_id"], participant["fighter_id"])
            row = await db.arena_interactive_raid(
                row["token"], actor, int_field(body, "round"), body.get("skill"),
                proof=body.get('proof'),challenge_id=body.get('challenge_id') if action=='qte' else None,
            )
        else:
            personal = body.get("personal", True)
            if type(personal) is not bool:
                raise ValueError("Некорректный выбор бойца.")
            fighter = int_field(body, "fighter", actor)
            if action == "join":
                selected = await require_member(bot, row["chat_id"], fighter)
                if selected.user.is_bot:
                    raise ValueError("Бот не может быть бойцом рейда.")
            if action == "start":
                for p in row["participants"]:
                    for user in {p["actor_id"], p["fighter_id"]}:
                        selected = await require_member(bot, row["chat_id"], user)
                        if selected.user.is_bot:
                            raise ValueError("Боты не могут участвовать в рейде.")
            row = await db.arena_raid_setup(
                row["token"],
                actor,
                action,
                fighter,
                personal,
                row["revision"] if action == "start" else None,
            )
        if raid_changed:
            await raid_changed(row["token"])
        return web.json_response(await raid_view(db, row, actor))

    async def get_mirror(request):
        run = await db.arena_mirror_get(request.match_info["token"], request[ACTOR])
        await read_member(run["chat_id"], request[ACTOR])
        return web.json_response(run)

    async def post_mirror(request):
        actor = request[ACTOR]
        run = await db.arena_mirror_get(request.match_info["token"], actor)
        await require_member(bot, run["chat_id"], actor)
        body = await request.json()
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("action"), str)
            or not isinstance(body.get("value", ""), str)
        ):
            raise ValueError("Некорректный запрос.")
        if body["action"] == "next":
            await require_member(bot, run["chat_id"], run["fighter_id"])
        run = await db.arena_mirror_action(
            run["token"],
            actor,
            int_field(body, "revision"),
            body["action"],
            body.get("value", ""),
        )
        return web.json_response(run)

    async def upload_sprite(request):
        chat, actor = int(request.match_info["chat"]), request[ACTOR]
        await require_member(bot, chat, actor)
        if request.content_type not in {"image/png", "application/octet-stream"}:
            raise ValueError("Можно загрузить только PNG.")
        pixel_art = request.headers.get("X-Pixel-Art", "false")
        if pixel_art not in {"true", "false"}:
            raise ValueError("Некорректный режим пиксельного рисунка.")
        flip = request.headers.get("X-Flip-Horizontal", "false")
        if flip not in {"true", "false"}:
            raise ValueError("Некорректный режим отражения спрайта.")
        async with image_slots:
            raw = await request.clone(client_max_size=MAX_SPRITE_BYTES + 1).read()
            png = await asyncio.to_thread(normalize_sprite, raw, flip == "true")
        await db.arena_set_sprite(chat, actor, png, pixel_art == "true",expected_slot=int(request.query.get('character_slot',1)))
        return web.json_response(
            {
                "notice": "Свой спрайт сохранён.",
                "menu": await app_menu(chat, actor),
            }
        )

    async def reset_sprite(request):
        chat, actor = int(request.match_info["chat"]), request[ACTOR]
        await require_member(bot, chat, actor)
        await db.arena_reset_sprite(chat, actor,expected_slot=int(request.query.get('character_slot',1)))
        return web.json_response(
            {
                "notice": "Стандартный спрайт возвращён.",
                "menu": await app_menu(chat, actor),
            }
        )

    async def get_sprite(request):
        # Public appearance, like the default sprites; opaque content-addressed URL.
        key = request.match_info["key"]
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise web.HTTPNotFound()
        png = await db.arena_sprite_png(key)
        if png is None:
            raise web.HTTPNotFound()
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def post_menu(request):
        chat = int(request.match_info["chat"])
        actor = request[ACTOR]
        member = await require_member(bot, chat, actor)
        await db.arena_require_enabled(chat)
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Некорректный запрос.")
        action = body.get("action")
        expected_slot=int_field(body,'character_slot',1)
        if action=='combat_settings':
            if type(body.get('enabled')) is not bool:raise ValueError('Некорректная настройка мини-игр.')
            await db.arena_combat_settings(actor,body['enabled'])
            return web.json_response(dict(notice='Настройка сохранена. Применится со следующего боя.',menu=await app_menu(chat,actor)))
        if action=='select_character':
            notice=await db.arena_select_character(chat,actor,int_field(body,'slot'),int_field(body,'character_revision'))
            return web.json_response(dict(notice=notice,menu=await app_menu(chat,actor)))
        if action in {'leave_battle','leave_mirror','leave_raid'}:
            battle_token=body.get('token')
            if not isinstance(battle_token,str):
                raise ValueError('Некорректный бой.')
            if action=='leave_mirror':
                notice=await db.arena_leave_mirror(chat,actor,battle_token)
            elif action=='leave_raid':
                notice=await db.arena_leave_raid(chat,actor,battle_token)
                if raid_changed:await raid_changed(battle_token)
            else:
                notice=await db.arena_leave_battle(chat,actor,battle_token)
            if changed and action=='leave_battle':
                await changed(battle_token)
            return web.json_response(dict(notice=notice,menu=await app_menu(chat,actor)))
        if action == "forge":
            notice = await db.arena_forge_action(chat, actor, body)
            return web.json_response({"notice": notice, "menu": await app_menu(chat, actor)})
        if action == "raid_create":
            if member.user.is_bot:
                raise ValueError("Боты не участвуют в рейдах.")
            row = await db.arena_raid_create(chat, actor, str(body.get("boss", "")), silent=True,expected_slot=expected_slot)
            return web.json_response({"raid": await raid_view(db, row, actor)})
        if action in {"wasteland", "mirror_start"}:
            fighter = int_field(body, "fighter")
            if fighter:
                await require_member(bot, chat, fighter)
            personal = body.get("personal", True)
            if type(personal) is not bool:
                raise ValueError("Некорректный режим персонажа.")
            if action == "mirror_start":
                return web.json_response(
                    {
                        "mirror": await db.arena_mirror_start(
                            chat, actor, fighter, personal,expected_slot=expected_slot
                        )
                    }
                )
            row = await db.arena_wasteland(
                chat, actor, fighter, str(body.get("previous", "")), personal,expected_slot=expected_slot
            )
            return web.json_response({"token": row["token"]})
        if action in {"equipment","module_class","restore_class"}:
            raise ValueError("Боевые рабы и модули классов удалены.")
        if action == "equipment":
            fighter = int_field(body, "user")
            equipped = body.get("equipped")
            if type(equipped) is not bool:
                raise ValueError("Некорректный режим экипировки.")
            if equipped:
                await require_member(bot, chat, fighter)
            notice = await db.arena_equip_slave(chat, actor, fighter, equipped)
        elif action in {
            "class",
            "archclass",
            "progression",
            "reset_class",
            "module_class",
            "restore_class",
            "loadout",
            "passives",
            "forget_skill",
            "forget_passive",
            "learn_skill",
            "learn_passive",
            "skill_offer",
        }:
            personal = body.get("personal", True)
            if type(personal) is not bool:
                raise ValueError("Некорректный персонаж.")
            notice = await db.arena_edit_profile(
                chat,
                actor,
                int_field(body, "user", actor),
                personal,
                action,
                body.get("value"),
                expected_slot=expected_slot,
            )
        elif action == "buy_item":
            notice = await db.arena_buy_item(chat, actor, int_field(body, "offer"))
        elif action == "use_item":
            personal = body.get("personal", True)
            confirm = body.get("confirm", False)
            if type(personal) is not bool or type(confirm) is not bool:
                raise ValueError("Некорректный режим предмета.")
            user = int_field(body, "user", actor)
            await require_member(bot, chat, user)
            notice = await db.arena_use_item(
                chat,
                actor,
                int_field(body, "item"),
                user,
                personal,
                confirm,
                body.get("replace_skill"),
                expected_slot=expected_slot,
            )
        elif action == "craft":
            raise ValueError("Крафт убран. Зелья и конфеты есть у торговца.")
        elif action == "candy":
            raise ValueError('Боевые рабы удалены. Конфета применяется только к своему персонажу из инвентаря.')
        elif (
            action in {"create_content", "grant_content"}
            and actor == CUSTOM_COMMAND_OWNER_ID
        ):
            content_type = str(body.get("type"))
            content_id = str(body.get("id"))
            if action == "create_content":
                definition = body.get("definition")
                if not isinstance(definition, dict):
                    raise ValueError("Нужен JSON-объект.")
                notice = await db.create_custom_fighter_content(
                    content_type,
                    content_id,
                    definition,
                    actor,
                    hidden=definition.get("merchant_available") is not True,
                )
            else:
                user = int_field(body, "user")
                await require_member(bot, chat, user)
                personal = body.get("personal", False)
                if type(personal) is not bool:
                    raise ValueError("Некорректный режим персонажа.")
                notice = await db.arena_admin_grant(
                    chat, user, content_type, content_id, actor, personal
                )
        else:
            raise ValueError("Действие недоступно.")
        return web.json_response(
            {"notice": notice, "menu": await app_menu(chat, actor)}
        )

    add_qte_lab_routes(app, ROOT)
    app.router.add_get("/", index)
    app.router.add_get("/pets", pets_page)
    app.router.add_get("/static/pet-client.js", pets_client)
    app.router.add_get("/api/pets", get_pets)
    app.router.add_post("/api/pets", post_pets)
    app.router.add_post("/api/pets/invoice", pets_invoice)
    app.router.add_post('/api/characters/invoice',characters_invoice)
    app.router.add_get("/health", health)
    app.router.add_get("/static/client.js", client)
    app.router.add_get("/static/audio.js", audio)
    app.router.add_get("/static/style.css", stylesheet)
    async def holdings_client(request):
        return web.FileResponse(ROOT/'holdings-client',headers={'Content-Type':'application/javascript; charset=utf-8','Cache-Control':'no-cache'})
    async def holdings_style(request):
        return web.FileResponse(ROOT/'holdings.css',headers={'Cache-Control':'no-cache'})
    app.router.add_get('/static/holdings.js',holdings_client)
    app.router.add_get('/static/holdings.css',holdings_style)
    app.router.add_static("/static/", ROOT, show_index=False)
    app.router.add_get("/api/battle/{token}", get_battle)
    app.router.add_post("/api/battle/{token}", post_battle)
    app.router.add_get("/api/raid/{token}", get_raid)
    app.router.add_post("/api/raid/{token}", post_raid)
    app.router.add_get("/api/mirror/{token}", get_mirror)
    app.router.add_post("/api/mirror/{token}", post_mirror)
    app.router.add_get("/api/menu/{chat}", get_menu)
    app.router.add_get("/api/leaderboard/{chat}", get_leaderboard)
    app.router.add_post("/api/menu/{chat}", post_menu)
    app.router.add_post("/api/menu/{chat}/sprite", upload_sprite)
    app.router.add_delete("/api/menu/{chat}/sprite", reset_sprite)
    app.router.add_get("/sprites/{key}.png", get_sprite)
    from holdings_web import register_holdings
    register_holdings(app,db,bot,ACTOR,require_member,int_field)
    return app
