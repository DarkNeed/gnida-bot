from __future__ import annotations

import hashlib
import hmac
import html
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database import Database


STATIC_DIR = Path(__file__).with_name("webapp")


def validate_telegram_init_data(
    init_data: str, bot_token: str, *, max_age_seconds: int = 86400, now: int | None = None
) -> dict[str, Any] | None:
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        current = int(time.time()) if now is None else now
        if auth_date > current + 30 or current - auth_date > max_age_seconds:
            return None
        check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        return json.loads(values["user"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _json_response(payload: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=lambda value: json.dumps(value, ensure_ascii=False))


def create_webapp(
    database: Database,
    bot: Bot,
    bot_token: str,
    *,
    superadmin_id: int | None = None,
) -> web.Application:
    app = web.Application(client_max_size=128 * 1024)

    @web.middleware
    async def telegram_auth(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user = validate_telegram_init_data(init_data, bot_token)
        if not user or not isinstance(user.get("id"), int):
            return _json_response({"error": "Откройте приложение через Telegram."}, 401)
        request["telegram_user"] = user
        return await handler(request)

    app.middlewares.append(telegram_auth)

    async def battle_payload(token: str, user_id: int) -> tuple[dict[str, Any] | None, int]:
        battle = await database.get_slave_battle(token=token)
        if not battle:
            return {"error": "Битва не найдена."}, 404
        participant_ids = {
            int(battle["challenger_owner_id"]),
            int(battle["defender_owner_id"]),
            int(battle["challenger_slave_id"]),
            int(battle["defender_slave_id"]),
        }
        if user_id not in participant_ids and user_id != superadmin_id:
            return {"error": "У вас нет доступа к этой битве."}, 403
        chat_id = int(battle["chat_id"])
        first_user = await database.get_user(chat_id, int(battle["challenger_slave_id"]))
        second_user = await database.get_user(chat_id, int(battle["defender_slave_id"]))
        state = json.loads(battle["state_json"]) if battle["state_json"] else None
        controller_sides: list[str] = []
        owner_sides: list[str] = []
        if state:
            for side, fighter in state["sides"].items():
                if int(fighter["controller_id"]) == user_id:
                    controller_sides.append(side)
                if int(fighter["owner_id"]) == user_id:
                    owner_sides.append(side)
        fighter_classes, fighter_skills = await database.get_fighter_catalog()
        skills = {
            skill_id: {
                "id": skill.skill_id,
                "name": skill.name,
                "cost": skill.cost,
                "cooldown": skill.cooldown,
                "hostile": skill.hostile,
                "accuracy": skill.accuracy,
                "power": skill.power,
            }
            for skill_id, skill in fighter_skills.items()
        }
        class_data = {
            class_id: {
                "name": fighter_class.name,
                "resource_name": fighter_class.resource_name,
            }
            for class_id, fighter_class in fighter_classes.items()
        }
        return (
            {
                "battle": {
                    "id": int(battle["id"]),
                    "token": str(battle["token"]),
                    "status": str(battle["status"]),
                    "state": state,
                    "fighters": {
                        "a": {
                            "id": int(battle["challenger_slave_id"]),
                            "name": (first_user["display_name"] if first_user else str(battle["challenger_slave_id"])),
                        },
                        "b": {
                            "id": int(battle["defender_slave_id"]),
                            "name": (second_user["display_name"] if second_user else str(battle["defender_slave_id"])),
                        },
                    },
                    "controller_sides": controller_sides,
                    "owner_sides": owner_sides,
                },
                "skills": skills,
                "classes": class_data,
            },
            200,
        )

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def state(request: web.Request) -> web.Response:
        payload, status = await battle_payload(
            request.match_info["token"], int(request["telegram_user"]["id"])
        )
        return _json_response(payload or {"error": "Ошибка."}, status)

    async def action(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        battle = await database.get_slave_battle(token=token)
        if not battle:
            return _json_response({"error": "Битва не найдена."}, 404)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            return _json_response({"error": "Некорректный запрос."}, 400)
        result = await database.submit_slave_battle_action(
            int(battle["id"]), int(request["telegram_user"]["id"]), body
        )
        if result["status"] in {"forbidden", "inactive"}:
            return _json_response(result, 403)
        if result["status"] == "invalid":
            return _json_response(result, 400)
        if result["status"] == "finished":
            finished = await database.get_slave_battle(int(battle["id"]))
            if finished and finished["message_id"]:
                state_data = result["state"]
                winner_side = state_data.get("winner")
                if winner_side == "draw":
                    outcome = "Ничья."
                else:
                    winner_id = int(state_data["sides"][winner_side]["slave_id"])
                    winner = await database.get_user(int(battle["chat_id"]), winner_id)
                    name = winner["display_name"] if winner else str(winner_id)
                    outcome = f"Победил {html.escape(name)}."
                try:
                    await bot.edit_message_text(
                        f"🏁 <b>Битва рабов завершена</b>\n{outcome}",
                        chat_id=int(finished["chat_id"]),
                        message_id=int(finished["message_id"]),
                        parse_mode="HTML",
                    )
                except TelegramAPIError:
                    pass
        return _json_response(result)

    async def potion(request: web.Request) -> web.Response:
        battle = await database.get_slave_battle(token=request.match_info["token"])
        if not battle:
            return _json_response({"error": "Битва не найдена."}, 404)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            body = {}
        result = await database.use_slave_battle_potion(
            int(battle["id"]), int(request["telegram_user"]["id"]), body.get("side")
        )
        status = 200 if result["status"] == "used" else 400
        return _json_response(result, status)

    app.router.add_get("/", index)
    app.router.add_get("/api/battle/{token}", state)
    app.router.add_post("/api/battle/{token}/action", action)
    app.router.add_post("/api/battle/{token}/potion", potion)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    return app
