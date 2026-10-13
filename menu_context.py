"""Shared selected-chat context for private owner constructors."""

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import Database
from custom_commands import CUSTOM_COMMAND_OWNER_ID


async def selected_chat(database: Database, user_id: int):
    chat_id = await database.selected_menu_chat(user_id)
    if chat_id is None:
        return None
    return next((row for row in await database.list_menu_chats()
                 if int(row["chat_id"]) == chat_id), None)


async def verified_selected_chat(database: Database, bot: Bot, user_id: int):
    chat = await selected_chat(database, user_id)
    if chat is None:
        return None
    try:
        member = await bot.get_chat_member(int(chat["chat_id"]), user_id)
    except (TelegramAPIError, asyncio.TimeoutError):
        return None
    status = getattr(member.status, "value", member.status)
    present = bool(getattr(member, "is_member", False)) if status == "restricted" else status not in {"left", "kicked"}
    return chat if present else None


async def manages_chat(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Fresh Telegram authorization, never an enterprise owner or cached admin."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except (TelegramAPIError, asyncio.TimeoutError):
        return False
    status = getattr(member.status, "value", member.status)
    if user_id == CUSTOM_COMMAND_OWNER_ID:
        return bool(getattr(member, "is_member", False)) if status == "restricted" else status not in {"left", "kicked"}
    return status in {"creator", "owner"}


async def verified_constructor_chat(database: Database, bot: Bot, user_id: int):
    chat = await selected_chat(database, user_id)
    return chat if chat is not None and await manages_chat(bot, int(chat["chat_id"]), user_id) else None


def choose_chat_view() -> tuple[str, InlineKeyboardMarkup]:
    return (
        "<b>💬 Выбери чат</b>\nОткрой /админ и выбери свой Telegram-чат. Конструкторы показывают только команды и события выбранного чата.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Выбрать чат", callback_data="adm:chats")],
        ]),
    )
