"""Owner-only, persistent deletion of selected administrators' new messages."""

from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Filter
from aiogram.types import Message

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database


ADMIN_BLOCK_COMMAND = re.compile(
    r"^/(?:банадмин|разбанадмин)(?:@\w+)?(?:\s+.*)?$", re.IGNORECASE
)
GROUP_TYPES = {"group", "supergroup"}


def member_status(member) -> str:
    status = member.status
    return str(getattr(status, "value", status))


class BlockedAdminMessage(Filter):
    def __init__(self, database: Database) -> None:
        self.database = database

    async def __call__(self, message: Message) -> bool:
        return bool(
            message.chat.type in GROUP_TYPES
            and message.from_user
            and not message.sender_chat
            and await self.database.admin_messages_blocked(
                message.chat.id, message.from_user.id
            )
        )


def create_admin_message_block_router(
    database: Database, *, kargassia_chat_id: int | None = None
) -> Router:
    router = Router(name="admin_message_blocks")

    async def resolve_member(bot: Bot, chat_id: int, token: str):
        if token.isdecimal():
            try:
                return await bot.get_chat_member(chat_id, int(token))
            except TelegramAPIError:
                return None
        if not re.fullmatch(r"@[A-Za-z0-9_]+", token):
            return None
        candidates = await database.users_by_username(chat_id, token)
        matches = []
        for candidate in candidates:
            try:
                member = await bot.get_chat_member(chat_id, int(candidate["user_id"]))
            except TelegramAPIError:
                continue
            username = getattr(member.user, "username", None)
            if username and username.casefold() == token[1:].casefold():
                matches.append(member)
        return matches[0] if len(matches) == 1 else None

    async def bot_can_delete(bot: Bot, chat_id: int) -> bool:
        try:
            member = await bot.get_chat_member(chat_id, bot.id)
        except TelegramAPIError:
            return False
        status = member_status(member)
        return status == "creator" or (
            status == "administrator" and bool(getattr(member, "can_delete_messages", False))
        )

    @router.message(F.from_user.id == CUSTOM_COMMAND_OWNER_ID, F.text.regexp(ADMIN_BLOCK_COMMAND))
    async def change_admin_block(message: Message, bot: Bot) -> None:
        if (
            not message.from_user
            or message.from_user.id != CUSTOM_COMMAND_OWNER_ID
            or message.chat.type not in {*GROUP_TYPES, "private"}
        ):
            return
        parts = (message.text or "").strip().split(maxsplit=1)
        block = parts[0].split("@", 1)[0].casefold() == "/банадмин"
        payload = parts[1].strip() if len(parts) > 1 else ""
        if message.chat.type == "private":
            if kargassia_chat_id is None:
                await message.answer("Для команды в личке нужно задать KARGASSIA_CHAT_ID.")
                return
            chat_id = kargassia_chat_id
        else:
            chat_id = message.chat.id

        member = None
        if payload:
            token = payload.split()[0]
            member = await resolve_member(bot, chat_id, token)
            if member is None:
                if not block and token.isdecimal():
                    changed = await database.unblock_admin_messages(chat_id, int(token))
                    await message.answer(
                        f"Сообщения ID {token} больше не удаляются."
                        if changed else f"ID {token} не было в списке."
                    )
                    return
                await message.answer(
                    "Не нашёл участника по текущему @тегу/ID в этом чате. "
                    "Бот должен сначала увидеть его сообщение; можно также ответить на него в группе."
                )
                return
        elif message.reply_to_message and message.reply_to_message.sender_chat:
            await message.answer(
                "Это анонимное сообщение от имени чата: Telegram не сообщает ID администратора. "
                "Укажи его @тег или ID."
            )
            return
        elif message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            try:
                member = await bot.get_chat_member(chat_id, target.id)
            except TelegramAPIError:
                await message.answer("Не удалось проверить участника в чате.")
                return
        else:
            await message.answer("Ответь на сообщение администратора или укажи @тег/Telegram ID.")
            return

        target = member.user
        if target.id == CUSTOM_COMMAND_OWNER_ID or target.id == bot.id or target.is_bot:
            await message.answer("Эту команду нельзя применить к себе или боту.")
            return
        if block:
            if member_status(member) not in {"administrator", "creator"}:
                await message.answer("Этот участник сейчас не администратор чата.")
                return
            if not await bot_can_delete(bot, chat_id):
                await message.answer("У бота нет права удалять сообщения в этом чате.")
                return
        await database.upsert_user(
            chat_id, target.id, target.username, target.full_name, touch=False
        )
        label = html.escape("@" + target.username if target.username else target.full_name)
        if block:
            changed = await database.block_admin_messages(
                chat_id, target.id, CUSTOM_COMMAND_OWNER_ID
            )
            text = (
                f"Новые сообщения администратора {label} буду удалять."
                if changed else f"Сообщения {label} уже удаляются."
            )
        else:
            changed = await database.unblock_admin_messages(chat_id, target.id)
            text = (
                f"Сообщения {label} больше не удаляются."
                if changed else f"{label} не было в списке."
            )
        await message.answer(text, parse_mode="HTML")

    @router.message(BlockedAdminMessage(database))
    @router.edited_message(BlockedAdminMessage(database))
    async def delete_blocked_admin_message(message: Message, bot: Bot) -> None:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except TelegramAPIError as error:
            logging.getLogger(__name__).warning(
                "Could not delete blocked administrator message %s/%s: %s",
                message.chat.id, message.message_id, error,
            )

    return router
