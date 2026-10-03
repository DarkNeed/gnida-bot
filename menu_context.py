"""Shared selected-chat context for private owner constructors."""

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import Database


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


def choose_chat_view() -> tuple[str, InlineKeyboardMarkup]:
    return (
        "<b>💬 Выбери чат</b>\nСначала выбери доступный чат в /menu. Конструкторы показывают только команды и события выбранного чата.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Выбрать чат", callback_data="sm:chats")],
        ]),
    )
