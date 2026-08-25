from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import aiohttp
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
    URLInputFile,
    User,
)

from blackjack import full_hand, hand_total, visible_hand
from database import (
    CHALLENGE_DEADLINE_SECONDS,
    NEWCOMER_CHALLENGE_DEADLINE_SECONDS,
    PIROJOK_USERNAME,
    Database,
    utc_timestamp,
)
from parsing import (
    command_payload,
    format_duration,
    looks_like_user_token,
    parse_duration,
    parse_duration_prefix,
    split_first,
)


GROUP_TYPES = {"group", "supergroup"}
JOKE_COOLDOWN_SECONDS = 120
DERMODEMOON_COOLDOWN_SECONDS = 86400
HEAVENLY_PUNISHMENT_HOURS = 100
IMMUNE_USERNAME = "kit_kitovich23"
IMMUNITY_TEXT = "Сочные титяндры @Kit_kitovich23, настолько сочные что ему плевать."
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
CHALLENGE_RE = re.compile(
    r"^вызов(?:\s+(кнб|бл[еэ]кджек))?[!?.\s]*$", re.IGNORECASE
)
TOP_RE = re.compile(r"^кому\s+делать\s+нехер[!?.\s]*$", re.IGNORECASE)
GNIDA_RE = re.compile(
    r"(?<![а-яёa-z])(?:кто\s+гнида|гнида\s+чата)(?![а-яёa-z])", re.IGNORECASE
)
DUCK_RE = re.compile(
    r"(?<![а-яёa-z])(?:утин\s+член|длина\s+члена\s+уточки)(?![а-яёa-z])",
    re.IGNORECASE,
)
HUILO_RE = re.compile(r"(?<![а-яёa-z])хуйло(?![а-яёa-z])", re.IGNORECASE)
FEMBOY_RE = re.compile(r"(?<![а-яёa-z])дима\s+фембой(?![а-яёa-z])", re.IGNORECASE)
BASEMENT_RE = re.compile(
    r"^(?:в\s+подвалград|забрать\s+в\s+подвалград)[!?.\s]*$", re.IGNORECASE
)
BASEMENT_RELEASE_RE = re.compile(
    r"^[!/]отпустить\s+из\s+подвалграда(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
BASEMENT_LIST_RE = re.compile(r"^[!/]подвалград(?:@\w+)?[!?.\s]*$", re.IGNORECASE)
SLAP_RE = re.compile(r"^леща(?:\s|$)", re.IGNORECASE)
ART_THEFT_RE = re.compile(r"(?<![а-яёa-z])(спизжу|спиздил)(?![а-яёa-z])", re.IGNORECASE)
HEAVENLY_PUNISHMENT_RE = re.compile(
    r"^это\s+кара\s+небесная,?\s+сосунок[!?.\s]*$", re.IGNORECASE
)
DUCK_SLAPS_RE = re.compile(r"^давать\s+леща\s+10\s+лет[!?.\s]*$", re.IGNORECASE)
SLEEP_RE = re.compile(r"^усыпить[!?.\s]*$", re.IGNORECASE)
SILENCE_RE = re.compile(
    r"(?<![А-ЯЁ])(?:МОЛЧА+ТЬ(?:\s+ТВАРЬ)?|З+А+Т+К+Н+И+С+Ь+)!*(?![А-ЯЁ])"
)
LEGS_RE = re.compile(r"^скинь\s+ножки[!?.\s]*$", re.IGNORECASE)
KARGASTAN_RE = re.compile(
    r"^пусть\s+звенят\s+позолоченные\s+кранчики\s+самоваров\s+8\s+народов\.\s*"
    r"божественный\s+ебатель\s+самоваров\s+@kit_kitovich23\.\s*"
    r"выеби\s+эту\s+ньюху\s+за\s+каргастан[!?.\s]*$",
    re.IGNORECASE,
)
TRANSFER_RE = re.compile(r"^[!/]передать(?:@\w+)?(?:\s|$)", re.IGNORECASE)
CLEAR_SLAVES_RE = re.compile(r"^[!/]очистить\s+рабов[!?.\s]*$", re.IGNORECASE)
MAKE_SLAVE_REPLY_RE = re.compile(
    r"^[!/]сделать\s+рабом\s+(@\w+|-?\d+)[!?.\s]*$", re.IGNORECASE
)
MAKE_SLAVE_RE = re.compile(
    r"^[!/]сделать\s+(@\w+|-?\d+)\s+рабом\s+(@\w+|-?\d+)[!?.\s]*$",
    re.IGNORECASE,
)
METAL_RASCALS_RE = re.compile(r"^металлические\s+поганцы[!?.\s]*$", re.IGNORECASE)
PIROJOK_ESCAPE_RE = re.compile(r"^съебаться[!?.\s]*$", re.IGNORECASE)
PIROJOK_HIDE_RE = re.compile(r"^спрятаться[!?.\s]*$", re.IGNORECASE)
PIROJOK_BASEMENT_ESCAPE_RE = re.compile(
    r"^съебаться\s+с\s+подвалграда[!?.\s]*$", re.IGNORECASE
)
SAMOVAR_RE = re.compile(r"(?<![а-яёa-z])самовар(?![а-яёa-z])", re.IGNORECASE)
SAFEBOORU_API_URL = "https://safebooru.org/index.php"
SAFEBOORU_TAGS = "murder_drones rating:safe"


def message_content(message: Message) -> str:
    """Return user-entered content for both plain and media messages."""
    return message.text or message.caption or ""


def text_or_caption_regexp(pattern: re.Pattern[str], *, mode: str | None = None):
    """Build an aiogram filter that applies the same regexp to text and captions."""
    if mode is None:
        return F.text.regexp(pattern) | F.caption.regexp(pattern)
    return F.text.regexp(pattern, mode=mode) | F.caption.regexp(pattern, mode=mode)


def display_name(user: User) -> str:
    return user.full_name or user.username or str(user.id)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def user_is_immune(user: User) -> bool:
    return bool(user.username and user.username.casefold() == IMMUNE_USERNAME)


async def target_is_immune(database: Database, chat_id: int, user_id: int) -> bool:
    row = await database.get_user(chat_id, user_id)
    return bool(row and row["username"] and row["username"].casefold() == IMMUNE_USERNAME)


async def target_is_pirojok(database: Database, chat_id: int, user_id: int) -> bool:
    row = await database.get_user(chat_id, user_id)
    return bool(
        row
        and row["username"]
        and row["username"].casefold() == PIROJOK_USERNAME
    )


def is_mister_sleepy(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "mistersleeppy")


def is_cheto_neveru(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "cheto_neveru")


def is_utochka(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "utochka8")


def is_dimon_gfg(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "dimon_gfg")


def is_pirojok(user: User | None) -> bool:
    return bool(
        user and user.username and user.username.casefold() == PIROJOK_USERNAME
    )


def basement_kick_allowed(member_status: str) -> bool:
    """Only regular chat members may be randomly kicked by a basement slap."""
    return member_status not in {"administrator", "creator", "left", "kicked"}


def message_has_image(message: Message) -> bool:
    """Treat photos, image files, stickers and animations as submitted images."""
    is_image_document = bool(
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("image/")
    )
    return bool(
        message.photo or message.sticker or message.animation or is_image_document
    )


def dermodemoon_announcement_available(
    cooldowns: dict[int, float], chat_id: int, now: float | None = None
) -> bool:
    current = time.monotonic() if now is None else now
    previous = cooldowns.get(chat_id)
    if previous is not None and current - previous < DERMODEMOON_COOLDOWN_SECONDS:
        return False
    cooldowns[chat_id] = current
    return True


def silence_duration_seconds(text: str) -> int:
    return sum(1 for _ in SILENCE_RE.finditer(text)) * 180


def russian_minutes(amount: int) -> str:
    if amount % 10 == 1 and amount % 100 != 11:
        unit = "минуту"
    elif 2 <= amount % 10 <= 4 and not 12 <= amount % 100 <= 14:
        unit = "минуты"
    else:
        unit = "минут"
    return f"{amount} {unit}"


async def resolve_user_token(
    message: Message, database: Database, token: str
) -> tuple[int, str] | None:
    if not looks_like_user_token(token):
        await message.answer("Укажите @username или числовой Telegram ID.")
        return None
    row = await database.resolve_user(message.chat.id, token)
    if row:
        return int(row["user_id"]), str(row["display_name"])
    if token.lstrip("-").isdigit():
        return int(token), token
    await message.answer("Я ещё не видел этого @username в чате.")
    return None


def select_safebooru_post(payload) -> dict | None:
    if isinstance(payload, dict):
        posts = payload.get("post", [])
    elif isinstance(payload, list):
        posts = payload
    else:
        return None
    candidates: list[dict] = []
    for post in posts:
        if not isinstance(post, dict) or str(post.get("rating", "s")).casefold() not in {
            "s",
            "safe",
        }:
            continue
        url = post.get("sample_url") or post.get("file_url")
        if not url and post.get("directory") and post.get("image"):
            url = f"https://safebooru.org/images/{post['directory']}/{post['image']}"
        if not url:
            continue
        if str(url).startswith("//"):
            url = "https:" + str(url)
        extension = str(url).split("?", 1)[0].rsplit(".", 1)[-1].casefold()
        if extension not in {"jpg", "jpeg", "png", "webp"}:
            continue
        candidate = dict(post)
        candidate["selected_url"] = str(url)
        candidates.append(candidate)
    return random.choice(candidates) if candidates else None


def parse_safebooru_count(payload: str) -> int:
    try:
        root = ET.fromstring(payload)
        count = int(root.attrib.get("count", "0"))
    except (ET.ParseError, TypeError, ValueError) as error:
        raise ValueError("Safebooru returned an invalid count response") from error
    if count < 1:
        raise ValueError("Safebooru returned no matching posts")
    return count


async def fetch_random_safebooru_post(
    excluded_ids: set[int] | None = None,
) -> dict:
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "GnidaBot/1.0 (Telegram bot)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(
            SAFEBOORU_API_URL,
            params={
                "page": "dapi",
                "s": "post",
                "q": "index",
                "limit": "1",
                "pid": "0",
                "tags": SAFEBOORU_TAGS,
            },
        ) as response:
            response.raise_for_status()
            total = parse_safebooru_count(await response.text())
        excluded = set(excluded_ids or ())
        if len(excluded) >= total:
            excluded.clear()
        for _ in range(25):
            offset = random.randrange(total)
            async with session.get(
                SAFEBOORU_API_URL,
                params={
                    "page": "dapi",
                    "s": "post",
                    "q": "index",
                    "json": "1",
                    "limit": "1",
                    "pid": str(offset),
                    "tags": SAFEBOORU_TAGS,
                },
            ) as response:
                response.raise_for_status()
                post = select_safebooru_post(await response.json(content_type=None))
                post_id = int(post["id"]) if post and post.get("id") else None
                if post and post_id not in excluded:
                    return post
    raise ValueError("Safebooru returned no suitable posts")


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
        self.dermodemoon_cooldowns: dict[int, float] = {}

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
            if message_has_image(event):
                await self.database.complete_leg_requests(event.chat.id, user.id)
            if (
                user.username
                and user.username.casefold() == "dermodemoon"
                and dermodemoon_announcement_available(
                    self.dermodemoon_cooldowns, event.chat.id
                )
            ):
                await event.answer("Дермодемон в чате, становитесь раком")
        return await handler(event, data)


async def has_restrict_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    if isinstance(member, ChatMemberOwner):
        return True
    return isinstance(member, ChatMemberAdministrator) and bool(member.can_restrict_members)


async def is_chat_participant(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    status = getattr(member.status, "value", member.status)
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return status not in {"left", "kicked"}


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
    allowed_bot_id: int | None = None,
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
        if user.is_bot and user.id != allowed_bot_id:
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


def blackjack_keyboard(challenge_id: int) -> InlineKeyboardMarkup:
    prefix = f"bj:{challenge_id}:"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Мои карты", callback_data=prefix + "view")],
            [
                InlineKeyboardButton(text="➕ Ещё", callback_data=prefix + "hit"),
                InlineKeyboardButton(text="✋ Хватит", callback_data=prefix + "stand"),
            ],
            [InlineKeyboardButton(text="Отказаться", callback_data=prefix + "refuse")],
        ]
    )


async def challenge_text(database: Database, challenge) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    first_state = "✅" if challenge["challenger_choice"] else "⌛"
    second_state = "✅" if challenge["opponent_choice"] else "⌛"
    forced_text = "\n🔒 Принудительный вызов: владелец не может отказаться." if challenge["forced"] else ""
    newcomer_text = (
        "\n⏳ Если новичок не сделает ход за 5 минут, он автоматически станет рабом."
        if challenge["opponent_newcomer"]
        else ""
    )
    deadline_text = "5 минут" if challenge["opponent_newcomer"] else "3 часа"
    return (
        f"КНБ: {plain_name(challenger)} против {plain_name(opponent)}\n"
        f"{first_state} {plain_name(challenger)} · {second_state} {plain_name(opponent)}\n"
        f"Выберите ход — соперник его не увидит. На ход даётся {deadline_text}."
        f"{forced_text}{newcomer_text}"
    )


async def blackjack_text(database: Database, challenge, game) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    challenger_hand = json.loads(game["challenger_hand"])
    opponent_hand = json.loads(game["opponent_hand"])
    turn_id = int(game["turn_user_id"])

    def state(user_id: int, stood: bool) -> str:
        if stood:
            return "✋ остановился"
        return "🎯 ходит" if user_id == turn_id else "⏳ ждёт"

    forced_text = (
        "\n🔒 Принудительный вызов: владелец не может отказаться."
        if challenge["forced"]
        else ""
    )
    newcomer_text = (
        "\n⏳ Новичку даётся 5 минут на первый ход."
        if challenge["opponent_newcomer"]
        else ""
    )
    deadline_text = "5 минут" if challenge["opponent_newcomer"] else "3 часа"
    return (
        f"🎰 Мини-блэкджек: {plain_name(challenger)} против {plain_name(opponent)}\n\n"
        f"{plain_name(challenger)}: {visible_hand(challenger_hand)} · "
        f"{state(int(challenge['challenger_id']), bool(game['challenger_stood']))}\n"
        f"{plain_name(opponent)}: {visible_hand(opponent_hand)} · "
        f"{state(int(challenge['opponent_id']), bool(game['opponent_stood']))}\n\n"
        f"Свою скрытую карту можно посмотреть кнопкой. На игру даётся {deadline_text}."
        f"{forced_text}{newcomer_text}"
    )


def create_router(database: Database) -> Router:
    router = Router(name="gnida-bot")
    router.message.outer_middleware(TrackingMiddleware(database))
    joke_cooldowns: dict[tuple[int, str], float] = {}
    leg_tasks: set[asyncio.Task[None]] = set()
    challenge_tasks: set[asyncio.Task[None]] = set()
    jug_tasks: set[asyncio.Task[None]] = set()
    recent_safebooru_ids: dict[int, list[int]] = {}

    async def finish_jug_hiding(
        chat_id: int, user_id: int, hidden_until: int, bot: Bot
    ) -> None:
        await asyncio.sleep(max(0, hidden_until - utc_timestamp()))
        if not await database.finish_jug_hiding(chat_id, user_id):
            return
        user = await database.get_user(chat_id, user_id)
        name = user["display_name"] if user else str(user_id)
        try:
            await bot.send_message(
                chat_id,
                f"{mention(user_id, name)} не смог больше держать дыхание, "
                "нужен час чтобы набрать воздуха",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning(
                "Could not announce jug cooldown for %s: %s", user_id, error
            )

    def schedule_jug_hiding(
        chat_id: int, user_id: int, hidden_until: int, bot: Bot
    ) -> None:
        task = asyncio.create_task(
            finish_jug_hiding(chat_id, user_id, hidden_until, bot)
        )
        jug_tasks.add(task)
        task.add_done_callback(jug_tasks.discard)

    async def enforce_leg_request(request_id: int, bot: Bot) -> None:
        request = await database.get_leg_request(request_id)
        if not request or request["status"] not in {"pending", "enforcing"}:
            return
        if request["status"] == "pending":
            await asyncio.sleep(max(0, int(request["deadline"]) - utc_timestamp()))
            request = await database.claim_expired_leg_request(request_id)
            if not request:
                return
        chat_id = int(request["chat_id"])
        target_id = int(request["target_id"])
        if await target_is_immune(database, chat_id, target_id):
            await database.finish_leg_request(request_id, "immune")
            await bot.send_message(chat_id, IMMUNITY_TEXT)
            return
        user = await database.get_user(chat_id, target_id)
        name = user["display_name"] if user else str(target_id)
        until = datetime.now(timezone.utc) + timedelta(minutes=3)
        try:
            await bot.restrict_chat_member(
                chat_id,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
                use_independent_chat_permissions=True,
            )
            await database.record_action(
                chat_id,
                target_id,
                "mute",
                "не скинул ножки",
                int(request["requester_id"]),
                duration_seconds=180,
                active_until=int(until.timestamp()),
            )
            await database.finish_leg_request(request_id, "muted")
            await bot.send_message(
                chat_id,
                f"{mention(target_id, name)} не скинул ножки и за это просидит "
                "с кляпом 3 минуты.",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await database.finish_leg_request(request_id, "failed")
            logging.getLogger(__name__).warning(
                "Could not enforce leg request %s: %s", request_id, error
            )

    def schedule_leg_request(request_id: int, bot: Bot) -> None:
        task = asyncio.create_task(enforce_leg_request(request_id, bot))
        leg_tasks.add(task)
        task.add_done_callback(leg_tasks.discard)

    async def edit_challenge(challenge, bot: Bot, text: str) -> None:
        if not challenge["message_id"]:
            return
        try:
            await bot.edit_message_text(
                text,
                chat_id=int(challenge["chat_id"]),
                message_id=int(challenge["message_id"]),
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning(
                "Could not edit challenge %s: %s", challenge["id"], error
            )

    async def publish_game_win(
        challenge, bot: Bot, winner_id: int, loser_id: int, heading: str
    ) -> None:
        chat_id = int(challenge["chat_id"])
        winner = await database.get_user(chat_id, winner_id)
        loser = await database.get_user(chat_id, loser_id)
        outcome, affected_id = await database.transfer_after_loss(
            chat_id, loser_id, winner_id
        )
        if outcome == "freed":
            consequence = f"{plain_name(winner)} побеждает владельца и становится свободным."
        elif outcome == "no_reward":
            consequence = f"{plain_name(winner)} пока раб и не может получить собственного раба."
        elif outcome == "pirojok_cannot_own":
            consequence = "Этот кувшин слишком тесен для вас двоих."
        elif outcome == "kept":
            consequence = f"{plain_name(loser)} остаётся рабом победителя."
        elif outcome == "transferred":
            slave = await database.get_user(chat_id, affected_id)
            consequence = f"{plain_name(loser)} отдаёт раба {plain_name(slave)}."
        else:
            consequence = f"{plain_name(loser)} становится рабом победителя."
        await edit_challenge(
            challenge,
            bot,
            f"{heading}\n🏆 Победил {plain_name(winner)}. {consequence}",
        )

    async def publish_played_result(challenge, bot: Bot) -> None:
        first = challenge["challenger_choice"]
        second = challenge["opponent_choice"]
        icons = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        if first == second:
            await edit_challenge(
                challenge,
                bot,
                f"🤝 Ничья: {icons[first]} — {icons[second]}. Никто не пострадал.",
            )
            return
        first_wins = (first, second) in {
            ("rock", "scissors"),
            ("scissors", "paper"),
            ("paper", "rock"),
        }
        winner_id = int(
            challenge["challenger_id"] if first_wins else challenge["opponent_id"]
        )
        loser_id = int(
            challenge["opponent_id"] if first_wins else challenge["challenger_id"]
        )
        await publish_game_win(
            challenge, bot, winner_id, loser_id, f"{icons[first]} — {icons[second]}"
        )

    async def enforce_challenge_deadline(challenge_id: int, bot: Bot) -> None:
        challenge = await database.get_challenge(challenge_id)
        if not challenge or challenge["status"] not in {"active", "deadline"}:
            return
        if challenge["status"] == "active":
            await asyncio.sleep(max(0, int(challenge["deadline"]) - utc_timestamp()))
            challenge = await database.claim_expired_challenge(challenge_id)
            if not challenge:
                return
        if challenge["game_type"] == "blackjack":
            blackjack = await database.get_blackjack_game(challenge_id)
            first_moved = bool(blackjack and blackjack["challenger_acted"])
            second_moved = bool(blackjack and blackjack["opponent_acted"])
        else:
            first_moved = bool(challenge["challenger_choice"])
            second_moved = bool(challenge["opponent_choice"])
        if challenge["game_type"] == "rps" and first_moved and second_moved:
            await publish_played_result(challenge, bot)
        elif challenge["opponent_newcomer"] and not second_moved:
            chat_id = int(challenge["chat_id"])
            challenger_id = int(challenge["challenger_id"])
            opponent_id = int(challenge["opponent_id"])
            challenger = await database.get_user(chat_id, challenger_id)
            opponent = await database.get_user(chat_id, opponent_id)
            result = await database.force_enslave(chat_id, opponent_id, challenger_id)
            if result == "enslaved":
                text = (
                    f"⌛ {plain_name(opponent)} не ответил на вызов за 5 минут и "
                    f"становится рабом {plain_name(challenger)}."
                )
            elif result == "pirojok_cannot_own":
                text = "Этот кувшин слишком тесен для вас двоих."
            else:
                text = (
                    "⌛ Новичок не ответил на вызов, но вызывающий сам является рабом "
                    "и не может получить собственного."
                )
            await edit_challenge(challenge, bot, text)
        else:
            deadline_text = "5 минут" if challenge["opponent_newcomer"] else "3 часа"
            await edit_challenge(
                challenge,
                bot,
                f"⌛ За {deadline_text} бой не был завершён. "
                "Для обычных участников последствий нет.",
            )

    def schedule_challenge(challenge_id: int, bot: Bot) -> None:
        task = asyncio.create_task(enforce_challenge_deadline(challenge_id, bot))
        challenge_tasks.add(task)
        task.add_done_callback(challenge_tasks.discard)

    @router.startup()
    async def resume_leg_requests(bot: Bot) -> None:
        for request in await database.pending_leg_requests():
            schedule_leg_request(int(request["id"]), bot)
        for challenge in await database.pending_challenges():
            schedule_challenge(int(challenge["id"]), bot)
        for hiding in await database.pending_jug_hidings():
            schedule_jug_hiding(
                int(hiding["chat_id"]),
                int(hiding["user_id"]),
                int(hiding["hidden_until"]),
                bot,
            )

    @router.shutdown()
    async def stop_leg_timers() -> None:
        for task in tuple(leg_tasks):
            task.cancel()
        for task in tuple(challenge_tasks):
            task.cancel()
        for task in tuple(jug_tasks):
            task.cancel()

    @router.message(text_or_caption_regexp(START_RE))
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

    @router.message(text_or_caption_regexp(DUCK_SLAPS_RE))
    async def duck_slaps_for_ten_years(message: Message, bot: Bot) -> None:
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not is_utochka(message.from_user)
            or not target
        ):
            return
        if target.is_bot:
            if target.id == bot.id:
                await replied.reply(
                    "Гнида-бот будет получать утиных лещей в течении 10 лет, "
                    "ГНИДЫ СТОЛЬКО НЕ ЖИВУТ"
                )
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if user_is_immune(target):
            await replied.reply(IMMUNITY_TEXT)
            return
        await replied.reply(
            f"{mention(target.id, display_name(target))} будет получать утиных лещей "
            "в течение 10 ЛЕТ.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(SILENCE_RE, mode="search"))
    async def dimon_silence(message: Message, bot: Bot) -> None:
        duration_seconds = silence_duration_seconds(message_content(message))
        duration_minutes = duration_seconds // 60
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not is_dimon_gfg(message.from_user)
            or not target
            or target.is_bot
            or not duration_seconds
        ):
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return
        try:
            member = await bot.get_chat_member(message.chat.id, target.id)
            status = getattr(member.status, "value", member.status)
            if status in {"administrator", "creator"}:
                await message.answer("Узбагойся, это админ")
                return
            until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
                use_independent_chat_permissions=True,
            )
            await database.record_action(
                message.chat.id,
                target.id,
                "mute",
                "задавлен авторитетом Димы_гфг",
                message.from_user.id,
                duration_seconds=duration_seconds,
                active_until=int(until.timestamp()),
            )
            await message.answer(
                f"Дима_гфг задавил авторитетом {mention(target.id, display_name(target))}, "
                f"он не сможет открыть рот в течении {russian_minutes(duration_minutes)}",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(
                f"Не получилось заставить молчать: {html.escape(str(error))}"
            )

    @router.message(text_or_caption_regexp(SLEEP_RE))
    async def sleepy_mute(message: Message, bot: Bot) -> None:
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not is_mister_sleepy(message.from_user)
            or not target
            or target.is_bot
        ):
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return
        until = datetime.now(timezone.utc) + timedelta(hours=12)
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
                use_independent_chat_permissions=True,
            )
            await database.record_action(
                message.chat.id,
                target.id,
                "mute",
                "усыплён",
                message.from_user.id,
                duration_seconds=43200,
                active_until=int(until.timestamp()),
            )
            await message.answer(
                f"Сладких снов {mention(target.id, display_name(target))}.",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(f"Не получилось усыпить: {html.escape(str(error))}")

    @router.message(text_or_caption_regexp(HEAVENLY_PUNISHMENT_RE))
    async def heavenly_punishment(message: Message, bot: Bot) -> None:
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not message.from_user
            or not message.from_user.username
            or message.from_user.username.casefold() != IMMUNE_USERNAME
            or not target
            or target.is_bot
        ):
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return
        until = datetime.now(timezone.utc) + timedelta(
            hours=HEAVENLY_PUNISHMENT_HOURS
        )
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
                use_independent_chat_permissions=True,
            )
            await database.record_action(
                message.chat.id,
                target.id,
                "mute",
                "кара небесная",
                message.from_user.id,
                duration_seconds=HEAVENLY_PUNISHMENT_HOURS * 60 * 60,
                active_until=int(until.timestamp()),
            )
            await message.answer(
                f"На {mention(target.id, display_name(target))} обрушена кара небесная, "
                f"он умолкнет на {HEAVENLY_PUNISHMENT_HOURS} часов.",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(
                f"Не получилось обрушить кару: {html.escape(str(error))}"
            )

    @router.message(text_or_caption_regexp(BASEMENT_RELEASE_RE))
    async def release_from_basement(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not is_cheto_neveru(message.from_user):
            return
        text = message_content(message)
        match = BASEMENT_RELEASE_RE.match(text)
        if not match:
            return
        payload = text[match.end() :].strip()
        target = await resolve_target(
            message, database, payload, allowed_bot_id=bot.id
        )
        if not target:
            return
        target_id, target_name, _ = target
        if await database.remove_basement_member(message.chat.id, target_id):
            if target_id == bot.id:
                await message.answer(
                    "Вы выпустили гнида-бота из Подвалграда, карма очищена ✨"
                )
            else:
                await message.answer(
                    f"🚪 {mention(target_id, target_name)} выпущен из Подвалграда.",
                    parse_mode="HTML",
                )
        else:
            await message.answer("Этого участника нет в Подвалграде.")

    @router.message(text_or_caption_regexp(BASEMENT_LIST_RE))
    async def basement_list(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES:
            return
        members = await database.list_basement_members(message.chat.id)
        if not members:
            await message.answer("В Подвалграде пока никого нет.")
            return
        lines = ["Жители Подвалграда:"]
        for index, member in enumerate(members, 1):
            nickname = member["display_name"] or member["username"] or str(member["user_id"])
            lines.append(f"{index}. {html.escape(nickname)}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(text_or_caption_regexp(PIROJOK_BASEMENT_ESCAPE_RE))
    async def pirojok_basement_escape(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and is_pirojok(message.from_user):
            await message.answer("Съебаться из Подвалграда невозможно 💀")

    @router.message(text_or_caption_regexp(PIROJOK_ESCAPE_RE))
    async def pirojok_escape(message: Message) -> None:
        sender = message.from_user
        if message.chat.type not in GROUP_TYPES or not is_pirojok(sender):
            return
        owner = await database.get_owner(message.chat.id, sender.id)
        if not owner:
            return
        owner_id = int(owner["owner_id"])
        if not await database.release_slave(message.chat.id, owner_id, sender.id):
            return
        owner_name = owner["display_name"] or owner["username"] or str(owner_id)
        await message.answer(
            f"{mention(sender.id, display_name(sender))} укатился из рабства "
            f"{mention(owner_id, owner_name)}",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(PIROJOK_HIDE_RE))
    async def pirojok_hide(message: Message, bot: Bot) -> None:
        sender = message.from_user
        if message.chat.type not in GROUP_TYPES or not is_pirojok(sender):
            return
        hidden_until = await database.start_jug_hiding(message.chat.id, sender.id)
        if hidden_until is None:
            return
        schedule_jug_hiding(message.chat.id, sender.id, hidden_until, bot)
        await message.answer(
            f"{mention(sender.id, display_name(sender))} залез в кувшин",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(SLAP_RE))
    async def basement_slap(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not is_cheto_neveru(message.from_user):
            return
        text = message_content(message)
        match = SLAP_RE.match(text)
        if not match:
            return
        payload = text[match.end() :].strip()
        target = await resolve_target(
            message, database, payload, allowed_bot_id=bot.id
        )
        if not target:
            return
        target_id, target_name, _ = target
        if await target_is_immune(database, message.chat.id, target_id):
            await message.answer(IMMUNITY_TEXT)
            return
        if not await database.is_basement_member(message.chat.id, target_id):
            await message.answer("Этот участник не состоит в Подвалграде.")
            return
        if (
            await target_is_pirojok(database, message.chat.id, target_id)
            and await database.is_jug_hidden(message.chat.id, target_id)
        ):
            await message.answer(
                f"{mention(target_id, target_name)} спрятался в кувшине, "
                "вам его не достать",
                parse_mode="HTML",
            )
            return
        if target_id == bot.id:
            await message.answer(
                "Властитель Подвалграда дал леща бедному Гнида-боту, за что..."
            )
            return
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
            status = getattr(member.status, "value", member.status)
        except (TelegramBadRequest, TelegramForbiddenError):
            status = "left"
        if basement_kick_allowed(status) and random.randrange(10) == 0:
            try:
                await bot.ban_chat_member(message.chat.id, target_id)
                await bot.unban_chat_member(
                    message.chat.id, target_id, only_if_banned=True
                )
                await message.answer(
                    f"Лещ @cheto_neveru был слишком мощным и "
                    f"{mention(target_id, target_name)} вылетел из чата.",
                    parse_mode="HTML",
                )
                return
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logging.getLogger(__name__).warning("Basement kick failed: %s", error)
        await message.answer(
            f"Властитель Подвалграда дал леща {mention(target_id, target_name)}, работай раб.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(LEGS_RE))
    async def request_legs(message: Message, bot: Bot) -> None:
        sender = message.from_user
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not is_utochka(sender)
            or not target
            or target.is_bot
        ):
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return
        deadline = utc_timestamp() + 180
        request_id = await database.create_leg_request(
            message.chat.id, target.id, sender.id, deadline
        )
        schedule_leg_request(request_id, bot)
        await message.answer(
            f"{mention(target.id, display_name(target))}, у тя 3 мин, чтобы скинуть ножки, иначе мут.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(KARGASTAN_RE))
    async def kargastan_ban(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        target = await resolve_target(message, database, "")
        if not target or not message.from_user:
            return
        target_id, target_name, _ = target
        if await target_is_immune(database, message.chat.id, target_id):
            await message.answer(IMMUNITY_TEXT)
            return
        try:
            await bot.ban_chat_member(message.chat.id, target_id)
            await database.record_action(
                message.chat.id,
                target_id,
                "ban",
                "выебан за Каргастан",
                message.from_user.id,
            )
            await message.answer(
                f"🔨 {mention(target_id, target_name)} выебан за Каргастан.",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(
                f"Не получилось применить действие: {html.escape(str(error))}"
            )

    @router.message(text_or_caption_regexp(MODERATION_RE))
    async def moderation(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        text = message_content(message)
        match = MODERATION_RE.match(text)
        if not match or not message.from_user:
            return
        action = match.group(1).casefold()
        target = await resolve_target(message, database, command_payload(text))
        if not target:
            return
        target_id, target_name, remainder = target
        if await target_is_immune(database, message.chat.id, target_id):
            await message.answer(IMMUNITY_TEXT)
            return
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

    @router.message(text_or_caption_regexp(STATS_RE))
    async def stats(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        target = await resolve_target(message, database, command_payload(message_content(message)))
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

    @router.message(text_or_caption_regexp(RESTORE_RE))
    async def restore_member(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        text = message_content(message)
        match = RESTORE_RE.match(text)
        if not match:
            return
        action = match.group(1).casefold()
        target = await resolve_target(message, database, command_payload(text))
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

    @router.message(text_or_caption_regexp(CLEAR_RE))
    async def clear_reputation(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        text = message_content(message)
        match = CLEAR_RE.match(text)
        if not match:
            return
        payload = text[match.end() :].strip()
        target = await resolve_target(message, database, payload)
        if not target:
            return
        target_id, target_name, _ = target
        deleted = await database.clear_actions(message.chat.id, target_id)
        await message.answer(
            f"🧹 Репутация {mention(target_id, target_name)} очищена. Удалено записей: {deleted}.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(SLAVES_RE))
    async def slaves(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        payload = command_payload(message_content(message))
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

    @router.message(text_or_caption_regexp(RELEASE_RE))
    async def release(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        payload = RELEASE_RE.sub("", message_content(message), count=1).strip()
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

    @router.message(text_or_caption_regexp(TRANSFER_RE))
    async def transfer_slave(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        payload = command_payload(message_content(message))
        replied = message.reply_to_message
        if replied and replied.sender_chat:
            await message.answer("Нельзя определить автора сообщения от имени канала.")
            return
        if replied and replied.from_user:
            slave_user = replied.from_user
            recipient_token, extra = split_first(payload)
            if extra:
                await message.answer("Формат: /передать @получатель — ответом на сообщение раба.")
                return
            await database.upsert_user(
                message.chat.id,
                slave_user.id,
                slave_user.username,
                display_name(slave_user),
                touch=False,
            )
            slave_id, slave_name = slave_user.id, display_name(slave_user)
        else:
            slave_token, remainder = split_first(payload)
            recipient_token, extra = split_first(remainder)
            if not slave_token or not recipient_token or extra:
                await message.answer("Формат: /передать @раб @получатель")
                return
            slave = await resolve_user_token(message, database, slave_token)
            if not slave:
                return
            slave_id, slave_name = slave
        recipient = await resolve_user_token(message, database, recipient_token)
        if not recipient:
            return
        recipient_id, recipient_name = recipient
        if await target_is_immune(database, message.chat.id, slave_id):
            await message.answer(IMMUNITY_TEXT)
            return
        result = await database.transfer_slave(
            message.chat.id, message.from_user.id, slave_id, recipient_id
        )
        if result == "not_owned":
            await message.answer("Этот участник не ваш раб.")
        elif result == "recipient_is_slave":
            await message.answer("Раб не может владеть другими рабами.")
        elif result == "self":
            await message.answer("Нельзя передать человека самому себе.")
        elif result == "same_owner":
            await message.answer("Этот участник уже принадлежит вам.")
        elif result == "pirojok_cannot_own":
            await message.answer("Этот кувшин слишком тесен для вас двоих")
        else:
            await message.answer(
                f"🤝 {mention(slave_id, slave_name)} передан владельцу "
                f"{mention(recipient_id, recipient_name)}.",
                parse_mode="HTML",
            )

    @router.message(text_or_caption_regexp(CLEAR_SLAVES_RE))
    async def sleepy_clear_slaves(message: Message) -> None:
        replied = message.reply_to_message
        if (
            message.chat.type not in GROUP_TYPES
            or not is_mister_sleepy(message.from_user)
            or not replied
            or replied.sender_chat
            or not replied.from_user
        ):
            return
        target = replied.from_user
        amount = await database.release_all_slaves(message.chat.id, target.id)
        await message.answer(
            f"🕊 Все рабы {mention(target.id, display_name(target))} отпущены: {amount}.",
            parse_mode="HTML",
        )

    @router.message(
        text_or_caption_regexp(MAKE_SLAVE_REPLY_RE)
        | text_or_caption_regexp(MAKE_SLAVE_RE)
    )
    async def sleepy_make_slave(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not is_mister_sleepy(message.from_user):
            return
        text = message_content(message)
        reply_match = MAKE_SLAVE_REPLY_RE.match(text)
        full_match = MAKE_SLAVE_RE.match(text)
        replied = message.reply_to_message
        if reply_match:
            if not replied or replied.sender_chat or not replied.from_user:
                return
            slave_user = replied.from_user
            if slave_user.is_bot:
                return
            await database.upsert_user(
                message.chat.id,
                slave_user.id,
                slave_user.username,
                display_name(slave_user),
                touch=False,
            )
            slave_id, slave_name = slave_user.id, display_name(slave_user)
            owner_token = reply_match.group(1)
        elif full_match:
            slave = await resolve_user_token(message, database, full_match.group(1))
            if not slave:
                return
            slave_id, slave_name = slave
            owner_token = full_match.group(2)
        else:
            return
        owner = await resolve_user_token(message, database, owner_token)
        if not owner:
            return
        owner_id, owner_name = owner
        if await target_is_immune(database, message.chat.id, slave_id):
            await message.answer(IMMUNITY_TEXT)
            return
        result = await database.force_enslave(message.chat.id, slave_id, owner_id)
        if result == "self":
            await message.answer("Нельзя сделать участника рабом самого себя.")
        elif result == "owner_is_slave":
            await message.answer("Раб не может владеть другими рабами.")
        elif result == "pirojok_cannot_own":
            await message.answer("Этот кувшин слишком тесен для вас двоих")
        else:
            await message.answer(
                f"⛓ {mention(slave_id, slave_name)} теперь раб "
                f"{mention(owner_id, owner_name)}.",
                parse_mode="HTML",
            )

    @router.message(text_or_caption_regexp(CHALLENGE_RE))
    async def challenge(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        match = CHALLENGE_RE.match(message_content(message))
        requested_game = match.group(1).casefold() if match and match.group(1) else None
        if requested_game == "кнб":
            game_type = "rps"
        elif requested_game in {"блекджек", "блэкджек"}:
            game_type = "blackjack"
        else:
            game_type = random.choice(("rps", "blackjack"))
        if (
            message.sender_chat
            or not message.reply_to_message
            or message.reply_to_message.sender_chat
            or not message.reply_to_message.from_user
        ):
            await message.answer("Отправьте «Вызов» в ответ на сообщение соперника.")
            return
        opponent = message.reply_to_message.from_user
        if opponent.is_bot or opponent.id == message.from_user.id:
            await message.answer("Нужен другой живой соперник.")
            return
        if user_is_immune(opponent):
            await message.answer(IMMUNITY_TEXT)
            return
        challenger_present, opponent_present = await asyncio.gather(
            is_chat_participant(bot, message.chat.id, message.from_user.id),
            is_chat_participant(bot, message.chat.id, opponent.id),
        )
        if not challenger_present or not opponent_present:
            await message.answer("Оба участника вызова должны состоять в этом чате.")
            return
        await database.upsert_user(
            message.chat.id, opponent.id, opponent.username, display_name(opponent), touch=False
        )
        owner = await database.get_owner(message.chat.id, message.from_user.id)
        if owner and int(owner["owner_id"]) != opponent.id:
            owner_name = owner["display_name"] or owner["username"] or str(owner["owner_id"])
            await message.answer(
                f"Рабы могут вызывать на бой только своего владельца: {html.escape(owner_name)}.",
                parse_mode="HTML",
            )
            return
        forced = bool(
            owner
            and int(owner["owner_id"]) == opponent.id
            and await database.can_force_owner(
                message.chat.id, message.from_user.id, opponent.id
            )
        )
        opponent_newcomer = await database.is_vulnerable(message.chat.id, opponent.id)
        challenge_id = await database.create_challenge(
            message.chat.id,
            message.from_user.id,
            opponent.id,
            forced=forced,
            opponent_newcomer=opponent_newcomer,
            game_type=game_type,
        )
        if challenge_id is None:
            await message.answer("У одного из участников уже есть активный вызов.")
            return
        row = await database.get_challenge(challenge_id)
        if game_type == "blackjack":
            blackjack = await database.get_blackjack_game(challenge_id)
            body = await blackjack_text(database, row, blackjack)
            keyboard = blackjack_keyboard(challenge_id)
        else:
            body = await challenge_text(database, row)
            keyboard = challenge_keyboard(challenge_id)
        sent = await message.answer(
            body,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await database.set_challenge_message(challenge_id, sent.message_id)
        schedule_challenge(challenge_id, bot)

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
        if (
            not challenge
            or challenge["status"] != "active"
            or challenge["game_type"] != "rps"
        ):
            await callback.answer("Этот вызов уже завершён.", show_alert=True)
            return
        if await target_is_immune(
            database, int(challenge["chat_id"]), int(challenge["opponent_id"])
        ):
            if await database.finish_challenge(challenge_id, "immune"):
                await callback.message.edit_text(IMMUNITY_TEXT)
            await callback.answer()
            return
        if callback.from_user.id not in (challenge["challenger_id"], challenge["opponent_id"]):
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        if utc_timestamp() >= int(challenge["deadline"]):
            await callback.answer("Время на ход уже истекло.", show_alert=True)
            return
        if choice == "refuse":
            is_opponent = callback.from_user.id == challenge["opponent_id"]
            if is_opponent and challenge["forced"]:
                await callback.answer(
                    "Это принудительный вызов — владелец не может отказаться.",
                    show_alert=True,
                )
                return
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
        await publish_played_result(challenge, bot)

    @router.callback_query(F.data.startswith("bj:"))
    async def blackjack_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            return
        try:
            _, raw_id, action = callback.data.split(":", 2)
            challenge_id = int(raw_id)
        except (ValueError, TypeError):
            await callback.answer("Некорректный вызов.", show_alert=True)
            return
        challenge = await database.get_challenge(challenge_id)
        if (
            not challenge
            or challenge["status"] != "active"
            or challenge["game_type"] != "blackjack"
        ):
            await callback.answer("Этот вызов уже завершён.", show_alert=True)
            return
        if await target_is_immune(
            database, int(challenge["chat_id"]), int(challenge["opponent_id"])
        ):
            if await database.finish_challenge(challenge_id, "immune"):
                await callback.message.edit_text(IMMUNITY_TEXT)
            await callback.answer()
            return
        participant_ids = {
            int(challenge["challenger_id"]),
            int(challenge["opponent_id"]),
        }
        if callback.from_user.id not in participant_ids:
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        if utc_timestamp() >= int(challenge["deadline"]):
            await callback.answer("Время на ход уже истекло.", show_alert=True)
            return
        if action == "refuse":
            is_opponent = callback.from_user.id == challenge["opponent_id"]
            if is_opponent and challenge["forced"]:
                await callback.answer(
                    "Это принудительный вызов — владелец не может отказаться.",
                    show_alert=True,
                )
                return
            if is_opponent and await database.is_vulnerable(
                challenge["chat_id"], callback.from_user.id
            ):
                await callback.answer(
                    "Первые 5 минут после входа отказаться нельзя.", show_alert=True
                )
                return
            if await database.finish_challenge(challenge_id, "refused"):
                await callback.message.edit_text(
                    f"🚫 {html.escape(display_name(callback.from_user))} "
                    "отказался от вызова.",
                    parse_mode="HTML",
                )
            await callback.answer()
            return
        game = await database.get_blackjack_game(challenge_id)
        if not game:
            await callback.answer("Партия не найдена.", show_alert=True)
            return
        if action == "view":
            column = (
                "challenger_hand"
                if callback.from_user.id == challenge["challenger_id"]
                else "opponent_hand"
            )
            cards = json.loads(game[column])
            await callback.answer(
                f"Твои карты: {full_hand(cards)}\nСумма: {hand_total(cards)}",
                show_alert=True,
            )
            return
        result = await database.blackjack_action(
            challenge_id, callback.from_user.id, action
        )
        if result["status"] == "not_turn":
            await callback.answer("Сейчас ход соперника.", show_alert=True)
            return
        if result["status"] in {"inactive", "invalid", "stood"}:
            await callback.answer("Этот ход уже недоступен.", show_alert=True)
            return
        if result["status"] == "not_participant":
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        await callback.answer("Карта выдана" if action == "hit" else "Остановился")
        if result["status"] == "updated":
            updated_challenge = await database.get_challenge(challenge_id)
            updated_game = await database.get_blackjack_game(challenge_id)
            await callback.message.edit_text(
                await blackjack_text(database, updated_challenge, updated_game),
                reply_markup=blackjack_keyboard(challenge_id),
                parse_mode="HTML",
            )
            return
        challenger = await database.get_user(
            int(challenge["chat_id"]), int(challenge["challenger_id"])
        )
        opponent = await database.get_user(
            int(challenge["chat_id"]), int(challenge["opponent_id"])
        )
        challenger_hand = result["challenger_hand"]
        opponent_hand = result["opponent_hand"]
        heading = (
            "БЛЕК ДЖЕК!!!\n"
            f"{plain_name(challenger)}: {full_hand(challenger_hand)} = "
            f"{hand_total(challenger_hand)}\n"
            f"{plain_name(opponent)}: {full_hand(opponent_hand)} = "
            f"{hand_total(opponent_hand)}\n"
            f"Итог: {html.escape(str(result['reason']))}."
        )
        await publish_game_win(
            challenge,
            bot,
            int(result["winner_id"]),
            int(result["loser_id"]),
            heading,
        )

    @router.message(text_or_caption_regexp(TOP_RE))
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

    def joke_available(chat_id: int, command: str) -> bool:
        now = time.monotonic()
        key = (chat_id, command)
        previous = joke_cooldowns.get(key, 0.0)
        if now - previous < JOKE_COOLDOWN_SECONDS:
            return False
        joke_cooldowns[key] = now
        return True

    @router.message(text_or_caption_regexp(METAL_RASCALS_RE))
    async def metal_rascals(message: Message) -> None:
        sender = message.from_user
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not sender.username
            or sender.username.casefold() != "olmus23"
        ):
            return
        try:
            recent_ids = recent_safebooru_ids.setdefault(message.chat.id, [])
            post = await fetch_random_safebooru_post(set(recent_ids))
            post_id = post.get("id")
            if post_id:
                recent_ids.append(int(post_id))
                del recent_ids[:-10]
            caption = "Металлические поганцы"
            if post_id:
                caption += (
                    f' · <a href="https://safebooru.org/index.php?page=post&amp;s=view&amp;id='
                    f'{int(post_id)}">Safebooru #{int(post_id)}</a>'
                )
            image = URLInputFile(
                post["selected_url"],
                headers={"User-Agent": "GnidaBot/1.0 (Telegram bot)"},
                filename=f"safebooru_{post_id or 'art'}.jpg",
                timeout=30,
            )
            await message.answer_photo(image, caption=caption, parse_mode="HTML")
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            TelegramBadRequest,
            TelegramForbiddenError,
            ValueError,
        ) as error:
            logging.getLogger(__name__).warning("Safebooru request failed: %s", error)
            await message.answer("Safebooru сейчас не отдал картинку. Попробуй позже.")

    @router.message(text_or_caption_regexp(ART_THEFT_RE, mode="search"))
    async def art_theft_counter(message: Message) -> None:
        sender = message.from_user
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not sender.username
            or sender.username.casefold() != "pirojoksostajem"
        ):
            return
        count = await database.increment_counter(message.chat.id, "stolen_art")
        responses = (
            f"Спизжено {count} артов, ваша коллекция растёт милорд",
            f"Спизжено {count} артов, галерея будет заполнена",
            f"Спизжено {count} артов, куда тебе столько?",
            f"Спизжено {count} артов, одна порнуха на уме",
        )
        await message.answer(random.choice(responses))

    @router.message(text_or_caption_regexp(GNIDA_RE, mode="search"))
    async def random_gnida(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not joke_available(message.chat.id, "gnida"):
            return
        users = await database.recent_users(message.chat.id, 20)
        if not users:
            return
        chosen = random.choice(users)
        await message.answer(
            f"{mention(chosen['user_id'], chosen['display_name'])} — это он гнида.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(DUCK_RE, mode="search"))
    async def duck(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id, "duck"):
            await message.answer("40 см")

    @router.message(text_or_caption_regexp(HUILO_RE, mode="search"))
    async def huilo(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id, "huilo"):
            await message.answer("сам хуйло")

    @router.message(text_or_caption_regexp(FEMBOY_RE, mode="search"))
    async def femboy(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id, "femboy"):
            await message.answer("бинарный")

    @router.message(text_or_caption_regexp(BASEMENT_RE))
    async def basement(message: Message, bot: Bot) -> None:
        sender = message.from_user
        replied_user = message.reply_to_message.from_user if message.reply_to_message else None
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not sender.username
            or sender.username.casefold() != "cheto_neveru"
            or not replied_user
        ):
            return
        if replied_user.is_bot and replied_user.id != bot.id:
            return
        if user_is_immune(replied_user):
            await message.answer(IMMUNITY_TEXT)
            return
        await database.upsert_user(
            message.chat.id,
            replied_user.id,
            replied_user.username,
            display_name(replied_user),
            touch=False,
        )
        await database.add_basement_member(
            message.chat.id, replied_user.id, sender.id
        )
        if replied_user.id == bot.id:
            await message.answer(
                "Вы забрали бедного гнида-бота в Подвалград, вы чудовище 😢"
            )
        else:
            await message.answer(
                f"{mention(replied_user.id, display_name(replied_user))} забран в Подвалград, "
                "продуктивной работы в шахтах.",
                parse_mode="HTML",
            )

    @router.message(text_or_caption_regexp(SAMOVAR_RE, mode="search"))
    async def samovar(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id, "samovar"):
            await message.answer("Зовите Кита")

    return router
