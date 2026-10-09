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
from arena_engine import (
    level_progress,
    normalize_loadout,
    unlocked_skill_ids,
    stats_for,
    effective_stat,
    RARITY_LABELS,
    MAX_FIGHTER_LEVEL,
)
from custom_commands import CUSTOM_COMMAND_OWNER_ID
from arena_images import MAX_SPRITE_BYTES, normalize_sprite

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
            side["class_name"] = cls.name
            side["resource_name"] = cls.resource_name
            side["class_rarity"] = cls.rarity
            side["class_rarity_name"] = RARITY_LABELS[cls.rarity]
            side["sprite"] = (
                side["class_id"]
                if side["class_id"] in {"cutie", "jock", "nerd"}
                else "ragamuffin"
            )
            side.update(
                await db.arena_sprite_info(row["chat_id"], row[key + "_fighter"] or 0)
            )
            side["skill_details"] = [
                asdict(skills[s]) for s in side["loadout"] if s in skills
            ]
            side["passive_details"] = side.get("passive_details", [])[:2]
            side["effective_stats"] = {
                k: effective_stat(side, k) for k in side["stats"]
            }
            side["accuracy_bonus"] = sum(
                e.get("value", 0)
                for e in side["effects"]
                if e["kind"] == "accuracy_flat"
            )
            side["damage_bonus"] = sum(
                e.get("value", 0) for e in side["effects"] if e["kind"] == "damage_pct"
            )
            side["can_use_potion"] = side["controller_id"] == actor and bool(
                await db.arena_potion_count(row["chat_id"], actor)
            )
            if "bum_punch" not in side["loadout"] and not any(
                skills[s].cost <= side["resource"] and not side["cooldowns"].get(s, 0)
                for s in side["loadout"]
                if s in skills
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
        state=state,
        names=names,
        own_side=own_side,
        consent_side=consent,
        available=available,
        actor_id=actor,
    )


async def menu_view(db, chat: int, actor: int) -> dict:
    result = await db.arena_menu(chat, actor)
    classes, skills = await db.get_fighter_catalog()
    profiles = [(result["personal"], True), *((p, False) for p in result["slaves"])]
    if result["self_slave"]:
        profiles.append((result["self_slave"], False))
    for profile, personal in profiles:
        profile["personal"] = personal
        profile["progress"] = level_progress(profile["xp"])
        profile["stats"] = stats_for(
            profile["class_id"], profile["level"], False, classes
        )
        profile["class_name"] = classes.get(
            profile["class_id"], classes["ragamuffin"]
        ).name
        profile["class_rarity"] = classes.get(
            profile["class_id"], classes["ragamuffin"]
        ).rarity
        profile["class_rarity_name"] = RARITY_LABELS[profile["class_rarity"]]
        profile["sprite"] = (
            profile["class_id"]
            if profile["class_id"] in {"cutie", "jock", "nerd"}
            else "ragamuffin"
        )
        profile.update(await db.arena_sprite_info(chat, profile["user_id"]))
        profile["can_edit_sprite"] = profile["user_id"] == actor
        # Grants are scoped to this user/chat, not the entire custom catalog.
        passive_view = await db.arena_passive_view(chat, profile["user_id"], personal)
        grants = passive_view.pop("granted")
        profile.update(passive_view)
        async with db._lock:
            class_grants = db._granted_content_locked(chat, profile["user_id"], "class")
        profile["skills"] = [
            asdict(skills[k])
            for k in unlocked_skill_ids(
                profile["class_id"], profile["level"], skills, grants
            )
        ]
        profile["classes"] = [
            dict(id=k, name=c.name, rarity=c.rarity)
            for k, c in classes.items()
            if k in {"cutie", "jock", "nerd"} or k in class_grants
        ]
    result["chat_id"] = chat
    result["actor_id"] = actor
    result["admin"] = actor == CUSTOM_COMMAND_OWNER_ID
    result["max_level"] = MAX_FIGHTER_LEVEL
    result.update(await db.arena_market_view(chat, actor))
    return result


def create_arena_app(db, bot, token: str, changed=None) -> web.Application:
    member_cache: dict[tuple[int, int], float] = {}

    async def read_member(chat: int, actor: int) -> None:
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
        return web.FileResponse(
            ROOT / "index.html", headers={"Cache-Control": "no-cache"}
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

    async def get_battle(request):
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
        if action in {"accept", "select", "consent", "skill"}:
            for k in ("a", "b"):
                if row[k + "_owner"]:
                    await require_member(bot, row["chat_id"], row[k + "_owner"])
                if row[k + "_fighter"]:
                    await require_member(bot, row["chat_id"], row[k + "_fighter"])
        if action == "select":
            await require_member(bot, row["chat_id"], int_field(body, "fighter"))
        if action == "skill":
            row = await db.arena_action(
                row["token"],
                actor,
                int_field(body, "revision"),
                str(body.get("skill", "")),
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
        return web.json_response(await menu_view(db, chat, actor))

    async def upload_sprite(request):
        chat, actor = int(request.match_info["chat"]), request[ACTOR]
        await require_member(bot, chat, actor)
        if request.content_type not in {"image/png", "application/octet-stream"}:
            raise ValueError("Можно загрузить только PNG.")
        pixel_art = request.headers.get("X-Pixel-Art", "false")
        if pixel_art not in {"true", "false"}:
            raise ValueError("Некорректный режим пиксельного рисунка.")
        async with image_slots:
            raw = await request.clone(client_max_size=MAX_SPRITE_BYTES + 1).read()
            png = await asyncio.to_thread(normalize_sprite, raw)
        await db.arena_set_sprite(chat, actor, png, pixel_art == "true")
        return web.json_response(
            {
                "notice": "Свой спрайт сохранён.",
                "menu": await menu_view(db, chat, actor),
            }
        )

    async def reset_sprite(request):
        chat, actor = int(request.match_info["chat"]), request[ACTOR]
        await require_member(bot, chat, actor)
        await db.arena_reset_sprite(chat, actor)
        return web.json_response(
            {
                "notice": "Стандартный спрайт возвращён.",
                "menu": await menu_view(db, chat, actor),
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
        await require_member(bot, chat, actor)
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Некорректный запрос.")
        action = body.get("action")
        if action == "wasteland":
            fighter = int_field(body, "fighter")
            if fighter:
                await require_member(bot, chat, fighter)
            personal = body.get("personal", True)
            if type(personal) is not bool:
                raise ValueError("Некорректный режим персонажа.")
            row = await db.arena_wasteland(
                chat, actor, fighter, str(body.get("previous", "")), personal
            )
            return web.json_response({"token": row["token"]})
        if action == "equipment":
            fighter = int_field(body, "user")
            equipped = body.get("equipped")
            if type(equipped) is not bool:
                raise ValueError("Некорректный режим экипировки.")
            if equipped:
                await require_member(bot, chat, fighter)
            notice = await db.arena_equip_slave(chat, actor, fighter, equipped)
        elif action in {"class", "loadout", "passives"}:
            personal = body.get("personal", False)
            if type(personal) is not bool:
                raise ValueError("Некорректный персонаж.")
            await db.arena_edit_profile(
                chat,
                actor,
                int_field(body, "user", actor),
                personal,
                action,
                body.get("value"),
            )
            notice = "Сохранено."
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
                chat, actor, int_field(body, "item"), user, personal, confirm
            )
        elif action == "craft":
            raise ValueError("Крафт убран. Зелья и конфеты есть у торговца.")
        elif action == "candy":
            notice = await db.give_candy(chat, actor, int_field(body, "user"))
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
            {"notice": notice, "menu": await menu_view(db, chat, actor)}
        )

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/static/client.js", client)
    app.router.add_static("/static/", ROOT, show_index=False)
    app.router.add_get("/api/battle/{token}", get_battle)
    app.router.add_post("/api/battle/{token}", post_battle)
    app.router.add_get("/api/menu/{chat}", get_menu)
    app.router.add_post("/api/menu/{chat}", post_menu)
    app.router.add_post("/api/menu/{chat}/sprite", upload_sprite)
    app.router.add_delete("/api/menu/{chat}/sprite", reset_sprite)
    app.router.add_get("/sprites/{key}.png", get_sprite)
    return app
