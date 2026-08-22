from __future__ import annotations

import html
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberOwner,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    User,
)

from database import Database, utc_timestamp
from parsing import (
    command_payload,
    format_duration,
    looks_like_user_token,
    parse_duration,
    parse_duration_prefix,
    split_first,
)


GROUP_TYPES = {"group", "supergroup"}
MODERATION_RE = re.compile(r"^[!/](бан|мут|пред)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
RESTORE_RE = re.compile(r"^[!/](разбан|размут)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
CLEAR_RE = re.compile(
    r"^[!/](?:снять\s+(?:преды|обвинения)|очистить\s+репутацию)(?:@\w+)?(?:\s|$)",
    re.IGNORECASE,
)
STATS_RE = re.compile(r"^[!/](стат|стата)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
SLAVES_RE = re.compile(r"^/рабы(?:@\w+)?(?:\s|$)", re.IGNORECASE)
START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)", re.IGNORECASE)
RELEASE_RE = re.compile(r"^(?:/отпустить(?:@\w+)?|отпустить\s+раба)(?:\s|$)", re.IGNORECASE)
CHALLENGE_RE = re.compile(r"^вызов[!?.\s]*$", re.IGNORECASE)
TOP_RE = re.compile(r"^кому\s+делать\s+нехер[!?.\s]*$", re.IGNORECASE)
GNIDA_RE = re.compile(r"^(?:гнида\s+чата|кто\s+гнида\s+чата)[!?.\s]*$", re.IGNORECASE)
DUCK_RE = re.compile(r"^(?:утин\s+член|длина\s+члена\s+уточки)[!?.\s]*$", re.IGNORECASE)
HUILO_RE = re.compile(r"^хуйло[!?.\s]*$", re.IGNORECASE)
FEMBOY_RE = re.compile(r"^дима\s+фембой[!?.\s]*$", re.IGNORECASE)
BASEMENT_RE = re.compile(
    r"^(?:в\s+подвалград|забрать\s+в\s+подвалград)[!?.\s]*$", re.IGNORECASE
)
SAMOVAR_RE = re.compile(r"(?<![а-яёa-z])самовар(?![а-яёa-z])", re.IGNORECASE)


def display_name(user: User) -> str:
    return user.full_name or user.username or str(user.id)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def plain_name(row) -> str:
    if row is None:
        return "неизвестный участник"
    return html.escape(row["display_name"] or row["username"] or str(row["user_id"]))


def slave_tag(row) -> str:
    if row and row["username"]:
        return "@" + html.escape(row["username"])
    if row:
        name = html.escape(row["display_name"] or "без username")
        return f"{name} (<code>{row['user_id']}</code>)"
    return "неизвестный участник"


def slave_report(sections: list[tuple[str, list]]) -> str:
    blocks: list[str] = []
    for title, rows in sections:
        entries = "\n".join(
            f"{index}. {slave_tag(row)}" for index, row in enumerate(rows, 1)
        )
        blocks.append(f"<b>{html.escape(title)}</b>\n{entries or 'Рабов нет.'}")
    return "\n\n".join(blocks) if blocks else "Рабов нет."


class TrackingMiddleware(BaseMiddleware):
    def __init__(self, database: Database) -> None:
        self.database = database

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[object]],
        event: TelegramObject,
        data: dict,
    ) -> object:
        if isinstance(event, Message) and event.from_user and event.chat.type in GROUP_TYPES:
            user = event.from_user
            await self.database.upsert_chat(
                event.chat.id, event.chat.title or f"Чат {event.chat.id}"
            )
            await self.database.upsert_user(
                event.chat.id, user.id, user.username, display_name(user)
            )
        return await handler(event, data)


async def has_restrict_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    if isinstance(member, ChatMemberOwner):
        return True
    return isinstance(member, ChatMemberAdministrator) and bool(member.can_restrict_members)


async def ensure_admin(message: Message, bot: Bot) -> bool:
    if not message.from_user:
        await message.answer("Команда недоступна анонимным администраторам.")
        return False
    try:
        allowed = await has_restrict_rights(bot, message.chat.id, message.from_user.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        allowed = False
    if not allowed:
        await message.answer("Нужны права на блокировку участников.")
    return allowed


async def resolve_target(
    message: Message,
    database: Database,
    payload: str,
) -> tuple[int, str, str] | None:
    """Return target id, stored name and remaining payload."""
    first, rest = split_first(payload)
    replied_message = message.reply_to_message
    # In reply commands a leading number is usually a duration ("1 минута"),
    # not a numeric Telegram ID. Only an explicit @username overrides the reply.
    explicit_target = bool(first and (not replied_message or first.startswith("@")))
    if explicit_target and looks_like_user_token(first):
        row = await database.resolve_user(message.chat.id, first)
        if row:
            return int(row["user_id"]), str(row["display_name"]), rest
        if first.lstrip("-").isdigit():
            return int(first), first, rest
        await message.answer("Я ещё не видел этого @username. Ответьте командой на его сообщение.")
        return None
    if replied_message and replied_message.sender_chat:
        await message.answer(
            "Это сообщение отправлено от имени чата/канала. Telegram не раскрывает "
            "пользователя — укажите его @username отдельно."
        )
        return None
    if replied_message and replied_message.from_user:
        user = replied_message.from_user
        if user.is_bot:
            await message.answer("Команду нельзя применить к боту.")
            return None
        await database.upsert_user(
            message.chat.id, user.id, user.username, display_name(user), touch=False
        )
        return user.id, display_name(user), payload.strip()
    await message.answer("Укажите @username/ID или ответьте командой на сообщение участника.")
    return None


def challenge_keyboard(challenge_id: int) -> InlineKeyboardMarkup:
    prefix = f"rps:{challenge_id}:"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🪨", callback_data=prefix + "rock"),
                InlineKeyboardButton(text="✂️", callback_data=prefix + "scissors"),
                InlineKeyboardButton(text="📄", callback_data=prefix + "paper"),
            ],
            [InlineKeyboardButton(text="Отказаться", callback_data=prefix + "refuse")],
        ]
    )


async def challenge_text(database: Database, challenge) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    first_state = "✅" if challenge["challenger_choice"] else "⌛"
    second_state = "✅" if challenge["opponent_choice"] else "⌛"
    return (
        f"КНБ: {plain_name(challenger)} против {plain_name(opponent)}\n"
        f"{first_state} {plain_name(challenger)} · {second_state} {plain_name(opponent)}\n"
        "Выберите ход — соперник его не увидит."
    )


def create_router(database: Database) -> Router:
    router = Router(name="gnida-bot")
    router.message.middleware(TrackingMiddleware(database))
    joke_cooldowns: dict[int, float] = {}

    @router.message(F.text.regexp(START_RE))
    async def start(message: Message) -> None:
        if message.chat.type == "private":
            await message.answer(
                "Я работаю в группах: модерирую чат, веду статистику и провожу КНБ. "
                "Добавьте меня в чат и выдайте право блокировать участников.\n\n"
                "Здесь можно запросить /рабы, а администратору — /рабы @username."
            )

    @router.message(F.new_chat_members)
    async def new_members(message: Message) -> None:
        vulnerable_until = utc_timestamp() + 300
        for user in message.new_chat_members:
            if user.is_bot:
                continue
            await database.upsert_user(
                message.chat.id,
                user.id,
                user.username,
                display_name(user),
                vulnerable_until=vulnerable_until,
                touch=False,
            )

    @router.message(F.text.regexp(MODERATION_RE))
    async def moderation(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        match = MODERATION_RE.match(message.text or "")
        if not match or not message.from_user:
            return
        action = match.group(1).casefold()
        target = await resolve_target(message, database, command_payload(message.text or ""))
        if not target:
            return
        target_id, target_name, remainder = target
        if target_id == message.from_user.id:
            await message.answer("На себя эту команду применить нельзя.")
            return

        reason = remainder.strip() or "не указана"
        try:
            if action == "бан":
                await bot.ban_chat_member(message.chat.id, target_id)
                await database.record_action(
                    message.chat.id, target_id, "ban", reason, message.from_user.id
                )
                await message.answer(
                    f"🔨 {mention(target_id, target_name)} забанен. Причина: {html.escape(reason)}",
                    parse_mode="HTML",
                )
            elif action == "мут":
                duration, possible_reason = parse_duration_prefix(remainder)
                if duration:
                    reason = possible_reason or "не указана"
                else:
                    if re.match(r"^\d+(?:\s*[a-zа-яё]+)?(?:\s|$)", remainder, re.I):
                        await message.answer(
                            "Некорректное время. Примеры: 30s, 10мин, 1h, 2дня (до 366 дней)."
                        )
                        return
                    duration = parse_duration("1h")
                    reason = remainder.strip() or "не указана"
                assert duration is not None
                until = datetime.now(timezone.utc) + timedelta(seconds=duration.seconds)
                await bot.restrict_chat_member(
                    message.chat.id,
                    target_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until,
                    use_independent_chat_permissions=True,
                )
                await database.record_action(
                    message.chat.id,
                    target_id,
                    "mute",
                    reason,
                    message.from_user.id,
                    duration_seconds=duration.seconds,
                    active_until=int(until.timestamp()),
                )
                await message.answer(
                    f"🔇 {mention(target_id, target_name)} получил мут на {format_duration(duration.seconds)} "
                    f"Причина: {html.escape(reason)}",
                    parse_mode="HTML",
                )
            else:
                await database.record_action(
                    message.chat.id, target_id, "warn", reason, message.from_user.id
                )
                stats = await database.action_stats(message.chat.id, target_id)
                await message.answer(
                    f"⚠️ {mention(target_id, target_name)} получил предупреждение "
                    f"(всего: {stats['warn']}). Причина: {html.escape(reason)}",
                    parse_mode="HTML",
                )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(f"Не получилось применить действие: {html.escape(str(error))}")

    @router.message(F.text.regexp(STATS_RE))
    async def stats(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        target = await resolve_target(message, database, command_payload(message.text or ""))
        if not target:
            return
        target_id, target_name, _ = target
        result = await database.action_stats(message.chat.id, target_id)
        history = await database.action_history(message.chat.id, target_id)
        state = "в чате"
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
            status = getattr(member.status, "value", member.status)
            state = {
                "kicked": "забанен",
                "left": "вышел",
                "restricted": "ограничен",
                "member": "в чате",
                "administrator": "администратор",
                "creator": "владелец",
            }.get(status, status)
        except (TelegramBadRequest, TelegramForbiddenError):
            state = "не удалось проверить"
        if result["active_mute_until"]:
            until = datetime.fromtimestamp(result["active_mute_until"], timezone.utc)
            state += f", мут до {until.astimezone().strftime('%d.%m %H:%M')}"
        action_names = {"ban": "бан", "mute": "мут", "warn": "пред"}
        history_text = "\n".join(
            f"• {action_names[row['action_type']]}: {html.escape(row['reason'])}" for row in history
        )
        if history_text:
            history_text = "\nПоследние причины:\n" + history_text
        await message.answer(
            f"📊 {mention(target_id, target_name)}\n"
            f"Баны: {result['ban']} · муты: {result['mute']} · преды: {result['warn']}\n"
            f"Состояние: {html.escape(state)}{history_text}",
            parse_mode="HTML",
        )

    @router.message(F.text.regexp(RESTORE_RE))
    async def restore_member(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        match = RESTORE_RE.match(message.text or "")
        if not match:
            return
        action = match.group(1).casefold()
        target = await resolve_target(message, database, command_payload(message.text or ""))
        if not target:
            return
        target_id, target_name, _ = target
        try:
            if action == "разбан":
                await bot.unban_chat_member(
                    message.chat.id, target_id, only_if_banned=True
                )
                await message.answer(
                    f"🔓 {mention(target_id, target_name)} разбанен.", parse_mode="HTML"
                )
            else:
                chat = await bot.get_chat(message.chat.id)
                permissions = chat.permissions or ChatPermissions(
                    **{field: True for field in ChatPermissions.model_fields}
                )
                await bot.restrict_chat_member(
                    message.chat.id,
                    target_id,
                    permissions=permissions,
                    use_independent_chat_permissions=True,
                )
                await database.deactivate_mutes(message.chat.id, target_id)
                await message.answer(
                    f"🔊 С {mention(target_id, target_name)} снят мут.", parse_mode="HTML"
                )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(f"Не получилось снять ограничение: {html.escape(str(error))}")

    @router.message(F.text.regexp(CLEAR_RE))
    async def clear_reputation(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        match = CLEAR_RE.match(message.text or "")
        if not match:
            return
        payload = (message.text or "")[match.end() :].strip()
        target = await resolve_target(message, database, payload)
        if not target:
            return
        target_id, target_name, _ = target
        deleted = await database.clear_actions(message.chat.id, target_id)
        await message.answer(
            f"🧹 Репутация {mention(target_id, target_name)} очищена. Удалено записей: {deleted}.",
            parse_mode="HTML",
        )

    @router.message(F.text.regexp(SLAVES_RE))
    async def slaves(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        payload = command_payload(message.text or "")
        recipient_id = message.from_user.id

        if message.chat.type in GROUP_TYPES:
            if payload or (message.reply_to_message and message.reply_to_message.from_user):
                if not await ensure_admin(message, bot):
                    return
                target = await resolve_target(message, database, payload)
                if not target:
                    return
                owner_id, owner_name, _ = target
            else:
                owner_id, owner_name = message.from_user.id, display_name(message.from_user)
            rows = await database.list_slaves(message.chat.id, owner_id)
            body = (
                f"Рабы пользователя {html.escape(owner_name)}:\n"
                + slave_report([(message.chat.title or f"Чат {message.chat.id}", rows)])
            )
        elif message.chat.type == "private":
            if not payload:
                rows = await database.list_slaves_globally(message.from_user.id)
                grouped: dict[int, tuple[str, list]] = {}
                for row in rows:
                    chat_id = int(row["ownership_chat_id"])
                    title = row["chat_title"] or f"Чат {chat_id}"
                    grouped.setdefault(chat_id, (title, []))[1].append(row)
                body = "Твои рабы:\n" + slave_report(list(grouped.values()))
            else:
                token, _ = split_first(payload)
                if not looks_like_user_token(token):
                    await message.answer("Используйте: /рабы @username или /рабы ID")
                    return
                candidates = await database.resolve_users_globally(token)
                allowed_sections: list[tuple[str, list]] = []
                owner_name = token
                seen_chats: set[int] = set()
                for candidate in candidates:
                    chat_id = int(candidate["chat_id"])
                    if chat_id in seen_chats:
                        continue
                    seen_chats.add(chat_id)
                    try:
                        allowed = await has_restrict_rights(bot, chat_id, message.from_user.id)
                    except (TelegramBadRequest, TelegramForbiddenError):
                        allowed = False
                    if not allowed:
                        continue
                    owner_name = candidate["display_name"] or candidate["username"] or token
                    rows = await database.list_slaves(chat_id, int(candidate["user_id"]))
                    title = candidate["chat_title"] or f"Чат {chat_id}"
                    allowed_sections.append((title, rows))
                if not allowed_sections:
                    await message.answer(
                        "Участник не найден либо у вас нет прав на блокировку в общем чате."
                    )
                    return
                body = f"Рабы пользователя {html.escape(owner_name)}:\n" + slave_report(
                    allowed_sections
                )
        else:
            return
        try:
            await bot.send_message(recipient_id, body, parse_mode="HTML")
        except TelegramForbiddenError:
            if message.chat.type in GROUP_TYPES:
                await message.answer("Сначала откройте личку с ботом и нажмите Start.")

    @router.message(F.text.regexp(RELEASE_RE))
    async def release(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        payload = RELEASE_RE.sub("", message.text or "", count=1).strip()
        target = await resolve_target(message, database, payload)
        if not target:
            return
        target_id, target_name, _ = target
        released = await database.release_slave(message.chat.id, message.from_user.id, target_id)
        if released:
            await message.answer(
                f"🕊 {mention(target_id, target_name)} теперь свободен.", parse_mode="HTML"
            )
        else:
            await message.answer("Этот участник не ваш раб.")

    @router.message(F.text.regexp(CHALLENGE_RE))
    async def challenge(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.answer("Отправьте «Вызов» в ответ на сообщение соперника.")
            return
        opponent = message.reply_to_message.from_user
        if opponent.is_bot or opponent.id == message.from_user.id:
            await message.answer("Нужен другой живой соперник.")
            return
        await database.upsert_user(
            message.chat.id, opponent.id, opponent.username, display_name(opponent), touch=False
        )
        challenge_id = await database.create_challenge(
            message.chat.id, message.from_user.id, opponent.id
        )
        if challenge_id is None:
            await message.answer("У вас уже есть активный вызов друг с другом.")
            return
        row = await database.get_challenge(challenge_id)
        sent = await message.answer(
            await challenge_text(database, row),
            reply_markup=challenge_keyboard(challenge_id),
            parse_mode="HTML",
        )
        await database.set_challenge_message(challenge_id, sent.message_id)

    @router.callback_query(F.data.startswith("rps:"))
    async def rps_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            return
        try:
            _, raw_id, choice = callback.data.split(":", 2)
            challenge_id = int(raw_id)
        except (ValueError, TypeError):
            await callback.answer("Некорректный вызов.", show_alert=True)
            return
        challenge = await database.get_challenge(challenge_id)
        if not challenge or challenge["status"] != "active":
            await callback.answer("Этот вызов уже завершён.", show_alert=True)
            return
        if callback.from_user.id not in (challenge["challenger_id"], challenge["opponent_id"]):
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        if utc_timestamp() - challenge["created_at"] > 300:
            if await database.finish_challenge(challenge_id, "expired"):
                await callback.message.edit_text("⌛ Вызов истёк.")
            await callback.answer()
            return
        if choice == "refuse":
            is_opponent = callback.from_user.id == challenge["opponent_id"]
            if is_opponent and await database.is_vulnerable(
                challenge["chat_id"], callback.from_user.id
            ):
                await callback.answer("Первые 5 минут после входа отказаться нельзя.", show_alert=True)
                return
            if await database.finish_challenge(challenge_id, "refused"):
                await callback.message.edit_text(
                    f"🚫 {html.escape(display_name(callback.from_user))} отказался от вызова.",
                    parse_mode="HTML",
                )
            await callback.answer()
            return
        if choice not in {"rock", "paper", "scissors"}:
            await callback.answer("Неизвестный ход.", show_alert=True)
            return
        challenge = await database.choose(challenge_id, callback.from_user.id, choice)
        if challenge is None:
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        await callback.answer("Ход принят")
        if not challenge["challenger_choice"] or not challenge["opponent_choice"]:
            await callback.message.edit_text(
                await challenge_text(database, challenge),
                reply_markup=challenge_keyboard(challenge_id),
                parse_mode="HTML",
            )
            return
        if not await database.finish_challenge(challenge_id):
            return

        first = challenge["challenger_choice"]
        second = challenge["opponent_choice"]
        icons = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        first_row = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
        second_row = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
        if first == second:
            await callback.message.edit_text(
                f"🤝 Ничья: {icons[first]} — {icons[second]}. Никто не пострадал."
            )
            return
        first_wins = (first, second) in {
            ("rock", "scissors"),
            ("scissors", "paper"),
            ("paper", "rock"),
        }
        winner_id = challenge["challenger_id"] if first_wins else challenge["opponent_id"]
        loser_id = challenge["opponent_id"] if first_wins else challenge["challenger_id"]
        winner_row = first_row if first_wins else second_row
        loser_row = second_row if first_wins else first_row
        outcome, slave_id = await database.transfer_after_loss(
            challenge["chat_id"], loser_id, winner_id
        )
        if outcome == "transferred":
            slave = await database.get_user(challenge["chat_id"], slave_id)
            consequence = f"{plain_name(loser_row)} отдаёт раба {plain_name(slave)}."
        else:
            consequence = f"{plain_name(loser_row)} становится рабом победителя."
        await callback.message.edit_text(
            f"{icons[first]} — {icons[second]}\n"
            f"🏆 Победил {plain_name(winner_row)}. {consequence}",
            parse_mode="HTML",
        )

    @router.message(F.text.regexp(TOP_RE))
    async def top_owners(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES:
            return
        rows = await database.top_owners(message.chat.id)
        if not rows:
            await message.answer("Рабовладельцев пока нет.")
            return
        lines = ["Кому делать нехер:"]
        for index, row in enumerate(rows, 1):
            name = html.escape(row["display_name"] or row["username"] or str(row["owner_id"]))
            lines.append(f"{index}. {name} — {row['amount']}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    def joke_available(chat_id: int) -> bool:
        now = time.monotonic()
        previous = joke_cooldowns.get(chat_id, 0.0)
        if now - previous < 300:
            return False
        joke_cooldowns[chat_id] = now
        return True

    @router.message(F.text.regexp(GNIDA_RE))
    async def random_gnida(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not joke_available(message.chat.id):
            return
        users = await database.recent_users(message.chat.id, 20)
        if not users:
            return
        chosen = random.choice(users)
        await message.answer(
            f"{mention(chosen['user_id'], chosen['display_name'])} — это он гнида.",
            parse_mode="HTML",
        )

    @router.message(F.text.regexp(DUCK_RE))
    async def duck(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id):
            await message.answer("40 см")

    @router.message(F.text.regexp(HUILO_RE))
    async def huilo(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id):
            await message.answer("сам хуйло")

    @router.message(F.text.regexp(FEMBOY_RE))
    async def femboy(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id):
            await message.answer("бинарный")

    @router.message(F.text.regexp(BASEMENT_RE))
    async def basement(message: Message) -> None:
        sender = message.from_user
        replied_user = message.reply_to_message.from_user if message.reply_to_message else None
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not sender.username
            or sender.username.casefold() != "cheto_neveru"
            or not replied_user
            or not joke_available(message.chat.id)
        ):
            return
        await message.answer(
            f"{mention(replied_user.id, display_name(replied_user))} забран в Подвалград, "
            "продуктивной работы в шахтах.",
            parse_mode="HTML",
        )

    @router.message(F.text.regexp(SAMOVAR_RE, mode="search"))
    async def samovar(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id):
            await message.answer("Зовите Кита")

    return router
