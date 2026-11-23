"""Weekly chatter ranking, with plain names instead of Telegram mentions."""

import re

from aiogram import BaseMiddleware, F, Router
from aiogram.types import Message

MESSAGE_TOP_RE = re.compile(r"^\s*кто\s+больше\s+всех\s+пиздит\s*\??\s*$", re.IGNORECASE)
GROUP_TYPES = {"group", "supergroup"}
USER_CONTENT = {
    "text", "animation", "audio", "document", "photo", "sticker", "video",
    "video_note", "voice", "contact", "dice", "game", "poll", "venue",
    "location", "paid_media", "story", "checklist",
}


class MessageActivityMiddleware(BaseMiddleware):
    def __init__(self, database):
        self.database = database

    async def __call__(self, handler, event, data):
        if (
            isinstance(event, Message)
            and event.chat.type in GROUP_TYPES
            and event.from_user and not event.from_user.is_bot
            and not event.sender_chat
            and event.content_type in USER_CONTENT
        ):
            await self.database.record_chat_message(
                event.chat.id, event.message_id, event.from_user.id,
                event.from_user.full_name, event.from_user.username,
                int(event.date.timestamp()),
            )
        return await handler(event, data)


def plain_name(value, limit=120):
    # Newlines/control characters cannot forge another ranking row. Neutralize
    # even user-supplied @names so Telegram cannot turn them into mentions.
    return " ".join("".join(c for c in str(value) if c.isprintable()).split()).replace("@", "＠")[:limit]


def format_message_top(top):
    lines = [f"Люди без личной жизни за неделю {top['start']:%d.%m.%Y} - {top['end']:%d.%m.%Y}"]
    for place, row in enumerate(top["entries"], 1):
        name = plain_name(row["display_name"]) or "Без имени"
        username = plain_name(row["username"], 32) if row["username"] else ""
        label = f"{name} ({username})" if username else name
        lines.append(f"{place}. {label} - {row['message_count']}")
    if not top["entries"]:
        lines.append("За прошедшую неделю нет учтённых сообщений.")
    return "\n".join(lines)


def create_message_activity_router(database):
    router = Router(name="message_activity")

    @router.message(F.text.regexp(MESSAGE_TOP_RE))
    async def message_top(message: Message):
        if message.chat.type not in GROUP_TYPES:
            await message.answer("Напиши «Кто больше всех пиздит?» в нужном чате.", parse_mode=None)
            return
        top = await database.weekly_message_top(message.chat.id)
        await message.answer(format_message_top(top), parse_mode=None)

    return router
