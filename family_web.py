"""Telegram Mini App access for the shared family archive."""
import hmac
import json
import re
import secrets
import time

from aiohttp import web
from aiogram.exceptions import TelegramAPIError

from arena_guild_avatars import GuildAvatarCache
from custom_commands import CUSTOM_COMMAND_OWNER_ID
from family_tree import FamilyError

MAX_ID = 2**52 - 1
EDITS = {"origin", "link", "unlink", "appoint", "revoke"}


def telegram_id(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise FamilyError("Нужен корректный ID участника.")
    return value


async def family_access(bot, require_member, chat, actor):
    if actor == CUSTOM_COMMAND_OWNER_ID:
        return True
    member = await require_member(bot, chat, actor)
    return member.status == "creator"


async def family_target(db, bot, require_member, chat, user):
    member = await require_member(bot, chat, telegram_id(user))
    if member.user.is_bot:
        raise FamilyError("Ботов нельзя добавлять в семейный архив.")
    await db.upsert_user(chat, user, member.user.username, member.user.full_name, touch=False)
    return member


def register_family(app, db, bot, actor_key, require_member, root):
    photos = GuildAvatarCache(bot)
    readers = {}
    preview_secret = secrets.token_bytes(32)

    def preview_proof(chat, actor, edit, a, b, reason, revision):
        payload = json.dumps((chat, actor, edit, a, b, reason, revision), separators=(",", ":"))
        return hmac.digest(preview_secret, payload.encode(), "sha256").hex()

    async def scope(request, *, fresh=False):
        raw = request.match_info["chat"]
        if not re.fullmatch(r"-[1-9][0-9]{0,15}", raw) or abs(int(raw)) > MAX_ID:
            raise FamilyError("Выбери группу через !семья.")
        chat, actor = int(raw), request[actor_key]
        pair, now = (chat, actor), time.monotonic()
        cached = readers.get(pair)
        if not fresh and cached and cached[0] > now:
            return chat, actor, cached[1]
        if actor == CUSTOM_COMMAND_OWNER_ID:
            try:
                group = await bot.get_chat(chat)
            except TelegramAPIError as error:
                raise FamilyError("Этот чат недоступен боту.") from error
            if group.type not in ("group", "supergroup"):
                raise FamilyError("Архив доступен только для групп.")
        owner = await family_access(bot, require_member, chat, actor)
        if len(readers) >= 2048:
            readers.clear()
        readers[pair] = (now + 20, owner)
        return chat, actor, owner

    async def page(_):
        return web.FileResponse(root / "family.html", headers={"Cache-Control": "no-store"})

    async def state(request):
        # Case and editor permissions must reflect the latest Telegram owner.
        chat, actor, owner = await scope(request, fresh=True)
        raw = request.query.get("case")
        case = telegram_id(int(raw)) if raw is not None else None
        offset = int(request.query.get("offset", 0))
        if not 0 <= offset <= 100000:
            raise FamilyError("Некорректная страница.")
        return web.json_response(await db.family_view(chat, actor, owner, case, offset, request.query.get("mine")=="1"))

    async def search(request):
        directory = request.query.get("directory") == "1"
        chat, _, owner = await scope(request, fresh=directory)
        if directory and not owner:
            raise FamilyError("Поиск вне древа доступен владельцу.")
        return web.json_response(await db.family_search(chat, request.query.get("q", ""), directory))

    async def avatar(request):
        chat, _, _ = await scope(request)
        user = telegram_id(int(request.match_info["user"]))
        if not await db.family_avatar_allowed(chat, user):
            return web.Response(status=404)
        picture = await photos.get(user)
        if not picture:
            return web.Response(status=404)
        return web.Response(body=picture[0], content_type=picture[1])

    async def action(request):
        chat, actor, owner = await scope(request, fresh=True)
        body = await request.json()
        if not isinstance(body, dict):
            raise FamilyError("Некорректный запрос.")
        op = body.get("op")
        reason = body.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 500:
            raise FamilyError("Причина не должна превышать 500 знаков.")
        reason = reason.strip()
        if op == "file":
            case, _, _ = await db.family_filing(chat, actor, reason)
            return web.json_response({"case": case})
        if op in ("approve", "reject"):
            case = telegram_id(body.get("case"))
            return web.json_response({"parties": await db.family_decide(chat, actor, owner, case, op == "approve")})
        if op not in ("preview", "apply") or not owner or body.get("edit") not in EDITS:
            raise FamilyError("Эта правка доступна только владельцу чата.")
        edit = body["edit"]
        a = telegram_id(body.get("a"))
        b = telegram_id(body.get("b")) if edit in ("link", "unlink") else None
        revision = body.get("revision") if op == "apply" else None
        if op == "apply":
            proof = body.get("proof")
            if (type(revision) is not int or revision < 0 or not isinstance(proof, str)
                or not re.fullmatch(r"[a-f0-9]{64}", proof)
                or not hmac.compare_digest(proof, preview_proof(chat, actor, edit, a, b, reason, revision))):
                raise FamilyError("Сначала проверь правку.")
        # Removing a departed person's old edge/appointment is still possible.
        if edit in ("origin", "link", "appoint"):
            member = await family_target(db, bot, require_member, chat, a)
            if edit == "appoint" and (member.status == "creator" or a == CUSTOM_COMMAND_OWNER_ID):
                raise FamilyError("Этот участник уже судья по должности.")
            if b:
                await family_target(db, bot, require_member, chat, b)
        result = await db.family_edit(chat, actor, edit, a, b, reason, expected=revision)
        if op == "preview":
            result["proof"] = preview_proof(chat, actor, edit, a, b, reason, result["revision"])
        return web.json_response(result)

    app.router.add_get("/family", page)
    base = "/api/family/{chat}"
    app.router.add_get(base, state)
    app.router.add_get(base + "/search", search)
    app.router.add_get(base + r"/avatar/{user:\d+}", avatar)
    app.router.add_post(base, action)
