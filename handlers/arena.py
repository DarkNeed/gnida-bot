"""Group battle invitations; the actual fight lives in the Mini App."""

from __future__ import annotations
import asyncio
import html
import logging
import re
from aiogram import Bot, F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from arena_links import arena_link
from arena_web import require_member
from handlers.raids import RaidPublisher, create_raid_router
from handlers.transfers import handle_transfers
from handlers.routes import (
    message_content,
    text_or_caption_regexp,
    resolve_target,
    TrackingMiddleware,
)

OFFER_RE = re.compile(
    r"^\s*(?:(?P<slave>(?:/бой(?:@\w+)?|!бой|бой)\s+раб(?:ами|ы)|я\s+выбираю\s+тебя)|(?P<personal>/бой(?:@\w+)?|!бой|бой|/дуэль(?:@\w+)?|!дуэль|дуэль))\b\s*(?P<payload>.*)$",
    re.I | re.S,
)
MENU_RE = re.compile(r"^\s*/(?:арена|arena)(?:@\w+)?\s*$", re.I)
ITEM_TRANSFER_RE = re.compile(
    r"^\s*(?:[/!]?передать)(?:@\w+)?\s+(?:трактат(?:ы|ов)?|предмет(?:ы|ов)?)\b\s*(?P<payload>.*)$",
    re.I | re.S,
)


class ArenaPublisher:
    def __init__(self, db, bot, username):
        self.db, self.bot, self.username = db, bot, username
        self.lock = asyncio.Lock()
        self.last_edit = 0.0
        self.active_published = set()
        self.raids = RaidPublisher(db, bot, username)

    async def raid_changed(self, token):
        await self.raids.changed(token)

    def keyboard(self, row):
        buttons = [
            [
                InlineKeyboardButton(
                    text="⚔️ Открыть бой",
                    url=arena_link(self.username, "b_" + row["token"]),
                )
            ]
        ]
        if row["status"] == "pending":
            buttons += [
                [
                    InlineKeyboardButton(
                        text="✅ Принять", callback_data="ar:accept:" + row["token"]
                    ),
                    InlineKeyboardButton(
                        text="🚫 Отклонить", callback_data="ar:refuse:" + row["token"]
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ Отменить", callback_data="ar:cancel:" + row["token"]
                    )
                ],
            ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def body(self, row):
        a = await self.db.get_user(row["chat_id"], row["a_owner"])
        b = await self.db.get_user(row["chat_id"], row["b_owner"])
        an = html.escape(a["display_name"] if a else str(row["a_owner"]))
        bn = html.escape(b["display_name"] if b else str(row["b_owner"]))
        names = f"{an} × {bn}"
        state = (
            __import__("json").loads(row["state_json"]) if row["state_json"] else None
        )
        if row["status"] == "pending":
            text = f"⚔️ {names}\n" + (
                "Бой рабов: выберите бойцов в арене. Контроль доступен сразу."
                if row["mode"] == "slaves"
                else "Личная дуэль. Соперник должен принять вызов."
            )
            text += "\nНа подготовку — 3 часа. Зрители тоже могут открыть бой."
        elif row["status"] == "active":
            text = f"⚔️ {names}\nБой идёт — откройте арену для игры или просмотра."
            if row["mode"] != "wasteland":
                text += "\nНа ход — 2 минуты. Не успел — ход пропускается."
        elif row["status"] == "finished" and state:
            winner = state.get("winner")
            text = f"🏁 {names}\n" + (
                f"Победитель: {an if winner=='a' else bn}" if winner else "Ничья."
            )
            text += "\nБойцы получили опыт."
            if state.get("payout"):
                text += f" Приз: {state['payout']} ₣."
        else:
            labels = {
                "cancelled": "Вызов отменён.",
                "refused": "Вызов отклонён.",
                "expired": "Время вызова истекло.",
            }
            text = f"⚔️ {names}\n" + labels.get(row["status"], "Бой закрыт.")
        if row["stake"]:
            text += (
                f"\nСтавка каждого: {row['stake']} ₣. Комиссия с призового фонда: 10%."
            )
        return text

    async def changed(self, token):
        # Only setup/final updates are published: turn-by-turn logs stay inside the app.
        async with self.lock:
            row = await self.db.arena_get(token)
            if not row["message_id"]:
                return
            if row["status"] == "active" and token in self.active_published:
                return
            await asyncio.sleep(
                max(0, 0.5 - (asyncio.get_running_loop().time() - self.last_edit))
            )
            row = await self.db.arena_get(token)
            try:
                await self.bot.edit_message_text(
                    await self.body(row),
                    chat_id=row["chat_id"],
                    message_id=row["message_id"],
                    parse_mode="HTML",
                    reply_markup=self.keyboard(row),
                )
                if row["status"] == "active":
                    self.active_published.add(token)
                else:
                    self.active_published.discard(token)
            except TelegramRetryAfter as error:
                logging.warning("Arena edit throttled: %s", error.retry_after)
            except TelegramAPIError as error:
                if "message is not modified" not in str(error):
                    logging.warning("Could not update arena message: %s", error)
            self.last_edit = asyncio.get_running_loop().time()


def create_arena_router(db, bot, username, enabled, publisher):
    router = Router(name="arena")
    router.message.outer_middleware(TrackingMiddleware(db))

    async def offer(message, actor, target, mode, stake=0, fighter=0):
        await require_member(bot, message.chat.id, actor)
        member = await require_member(bot, message.chat.id, target)
        if member.user.is_bot:
            raise ValueError("С ботом можно играть только в Пустоши.")
        row = await db.arena_offer(message.chat.id, actor, target, mode, stake)
        try:
            if fighter:
                row = await db.arena_setup(row["token"], actor, "select", fighter)
            sent = await message.answer(
                await publisher.body(row),
                reply_markup=publisher.keyboard(row),
                parse_mode="HTML",
            )
            await db.arena_set_message(row["token"], sent.message_id)
        except Exception:
            await db.arena_setup(row["token"], actor, "cancel")
            raise
        return row

    @router.message(text_or_caption_regexp(MENU_RE))
    async def arena_menu_command(message: Message):
        if not enabled:
            await message.answer(
                "Арена отключена. Владельцу бота нужно указать WEBAPP_URL и настроить Main Mini App."
            )
            return
        actor = message.from_user.id
        chat = message.chat.id
        if message.chat.type == "private":
            selected = await db.selected_menu_chat(actor)
            if not selected:
                await message.answer("Сначала выбери чат в /menu.")
                return
            chat = (
                int(selected["chat_id"]) if not isinstance(selected, int) else selected
            )
        try:
            await require_member(bot, chat, actor)
            await db.arena_require_enabled(chat)
        except ValueError as error:
            await message.answer(str(error))
            return
        await message.answer(
            "Арена: единый персонаж во всех чатах, Пустошь и рейды.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⚔️ Открыть арену",
                            url=arena_link(username, f"menu_{chat}"),
                        )
                    ]
                ]
            ),
        )

    @router.message(text_or_caption_regexp(ITEM_TRANSFER_RE))
    async def transfer_arena_item(message: Message):
        await handle_transfers(message, db, bot)

    @router.message(text_or_caption_regexp(OFFER_RE))
    async def battle_offer(message: Message):
        if not message.from_user or message.chat.type not in {"group", "supergroup"}:
            return
        if not enabled:
            await message.answer("Арена пока отключена: нужно настроить WEBAPP_URL.")
            return
        match = OFFER_RE.match(message_content(message))
        target = await resolve_target(message, db, match["payload"])
        if not target:
            return
        if match["slave"]:
            await message.answer("Боевые рабы удалены. Вызови личного персонажа: /бой @участник.")
            return
        mode = "personal"
        target_id, _, rest = target
        try:
            stake = 0
            if rest:
                amount = re.fullmatch(r"(\d+)\s*(?:франк(?:ов|а)?|₣)?", rest, re.I)
                if not amount:
                    raise ValueError(
                        "Личный бой: /бой @участник 50 франков или ответом /бой."
                    )
                stake = int(amount[1])
            await offer(message, message.from_user.id, target_id, mode, stake)
        except ValueError as error:
            await message.answer(str(error))

    @router.callback_query(F.data.startswith("arp:"))
    async def opponent_pick(callback: CallbackQuery):
        await callback.answer("Боевые рабы удалены. Вызови личного персонажа: /бой @участник.", show_alert=True)

    @router.callback_query(F.data.startswith("ar:"))
    async def arena_callback(callback: CallbackQuery):
        if not enabled:
            await callback.answer()
            return
        _, action, token = callback.data.split(":", 2)
        try:
            row = await db.arena_get(token)
            await require_member(bot, row["chat_id"], callback.from_user.id)
            row = await db.arena_setup(token, callback.from_user.id, action)
            await callback.answer(
                "Готово. Выбери бойца через «Открыть бой»."
                if row["mode"] == "slaves" and row["status"] == "pending"
                else "Готово."
            )
            await publisher.changed(token)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)

    router.include_router(create_raid_router(db, bot, enabled, publisher.raids))
    return router
