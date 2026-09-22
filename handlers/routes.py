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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

import aiohttp
from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberOwner,
    ChatPermissions,
    FSInputFile,
    InlineQuery,
    InlineQueryResultArticle,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputTextMessageContent,
    Message,
    TelegramObject,
    URLInputFile,
    User,
)

from blackjack import full_hand, hand_total, visible_hand
from checkers import BLACK, WHITE, EMPTY, legal_moves as legal_checkers_moves
from custom_commands import (
    CUSTOM_COMMAND_OWNER_ID,
    MAX_RESPONSE_LENGTH,
    MAX_RESPONSES_PER_OUTCOME,
    MAX_TRIGGER_LENGTH,
    command_responses,
    normalize_custom_trigger,
    parse_response_lines,
    render_custom_template,
    template_placeholders,
)
from database import (
    BUYOUT_COST_FRANCS,
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
RANDOM_PHRASE_COOLDOWN_SECONDS = 5 * 60
HEAVENLY_PUNISHMENT_HOURS = 100
PISKA_MUTE_SECONDS = 24 * 60 * 60
CAPTCHA_TIMEOUT_SECONDS = 30
CAPTCHA_MAX_ATTEMPTS = 3
DEATH_NOTE_SECONDS = 40
DEATH_NOTE_CLOCKS = {40: "🕛", 30: "🕒", 20: "🕕", 10: "🕘"}
CAPTCHA_EMOJI_NAMES = {
    "🐸": "лягушку",
    "🍉": "арбуз",
    "🚲": "велосипед",
    "🦊": "лису",
    "🎲": "кубик",
    "🌵": "кактус",
    "🪁": "воздушного змея",
    "🍩": "пончик",
    "🦖": "динозавра",
    "🎈": "воздушный шар",
}
CAPTCHA_EMOJIS = tuple(CAPTCHA_EMOJI_NAMES)
MOSCOW_TZ = timezone(timedelta(hours=3), name="MSK")
DAILY_GROUP_MESSAGES = (
    (0, 0, "Спокойной ночи гниды"),
    (10, 0, "Утречка гниды"),
)
BASEMENT_RANKS = {
    1: ("⛏️", "Шахтёр", "Шахтёры"),
    2: ("👁️", "Надзиратель", "Надзиратели"),
    3: ("🚂", "Мге браток", "Мге братки"),
    4: ("👑", "Заместитель короля", "Заместители короля"),
}
BASEMENT_DEPUTY_RANK = 4
BASEMENT_RULER_RANK = 5
BUSINESS_META = {
    "brothel": {
        "emoji": "🏩",
        "name": "Бордель",
        "producer": "Куртизанка",
        "leader": "Управляющий",
        "assign": "Назначить куртизанкой",
    },
    "field": {
        "emoji": "🌾",
        "name": "Хлопковое поле",
        "producer": "Сборщик",
        "leader": "Надзиратель",
        "assign": "Назначить сборщиком",
    },
}
RANDOM_CHAT_PHRASES = (
    "У чела сверху писька маленькая ☝️",
    "Хей, давно не видел тебя на сайте сочныефембойчики.ком 💌",
    "У МЕНЯ ГОРМОНАЛЬНЫЙ ШТОРМ, ГОНИТЕ АРТЫ!!! 🌪️",
    "Мммм, пахнет тухлятиной и детским маслом 🧴",
    "В чате обнаружен избыток гнид. Продолжаем наблюдение 🧪",
    "Срочно: самовар опять ведёт себя подозрительно ☕",
    "Не молчите, я уже начал думать за вас 🧠",
    "Кому-то пора потрогать траву. Или хотя бы ковёр 🌱",
    "Бот провёл анализ. Результат: вы странные 📊",
    "Я не осуждаю. Я фиксирую 📋",
    "Кто выключил интеллект на техническое обслуживание? 🔧",
    "В чате замечен редкий вид: человек с мнением 🦜",
    "Осторожно, сверху может упасть кринж 🪂",
    "Сегодня разрешается быть гнидой, но умеренно 🐛",
    "Самовар закипел. Кит где-то рядом ☕",
    "Ваша аура была проверена. Результат засекречен 🔒",
    "Не кормите чат после полуночи 🍞",
    "Тут кто-нибудь вообще трогал реальность сегодня? 🌍",
    "Система сообщает: уровень шизы в норме 📈",
    "В воздухе пахнет новым конфликтом и дошираком 🍜",
    "Кажется, кто-то забыл закрыть портал в Подвалград 🚪",
    "Улыбнитесь, вас мысленно осудили 🙂",
    "Бот напоминает: сильные тоже иногда пишут глупости 💪",
    "У кого-то клавиатура работает быстрее мозга ⌨️",
    "Пожалуйста, не пугайте новичков. Пока что 👶",
    "Если молчать достаточно долго, можно стать легендой 🤫",
    "Я не знаю, что происходит, но мне нравится 🤖",
    "Время для важного вопроса: где самовар? ☕",
    "Бот требует одну смешную мысль с каждого 🎟️",
    "Кто-то наверху явно проиграл спор с эволюцией 🧬",
    "Местный уровень адекватности: декоративный 🪴",
    "Внимание, фембой-радар издаёт подозрительные звуки 📡",
    "Не переживайте, хуже уже было. Наверное 🫠",
    "По документам вы все нормальные. По сообщениям — нет 📁",
    "Кажется, в этом чате завелась интеллектуальная плесень 🍄",
    "Срочно вызывайте эксперта по бесполезным диалогам 📞",
    "Если бы кринж был валютой, вы бы жили богато 💰",
    "Гнида-бот посмотрел на чат и тихо вздохнул 😮‍💨",
    "Срочное объявление: ваши мысли опять без очереди 🧾",
    "Я пришёл проверить, не стали ли вы нормальными. Не стали 🧍",
    "Ваше сообщение принято в отдел странных решений 📬",
    "Пожалуйста, не шепчите при самоваре, он всё слышит ☕",
    "Я бы пошутил, но чат уже справился без меня 🎭",
    "Внимание: обнаружен человек с подозрительно хорошим настроением 🚨",
    "Где-то рядом плачет один непрочитанный учебник 📚",
    "Ваша репутация была сохранена в папке «непонятно» 📁",
    "Пахнет новым мемом и старой ошибкой сервера 🖥️",
    "Если это шутка, то я её уважаю. Немного 🤏",
    "Кто-то опять выпустил мысли без намордника 🐕",
    "В чате идёт тихая борьба за звание главного странного 🏆",
    "Я не сплю. Я просто очень внимательно молчу 🌚",
    "Кто украл атмосферу и заменил её кринжом? 🧯",
    "Сейчас бы лечь, но сначала ещё немного позора 🛏️",
    "Где-то вдалеке грустит один здравый смысл 🌫️",
    "Уровень загадочности сообщения: холодильник в лесу 🧊",
    "Бот рекомендует сделать паузу и посмотреть в стену 🧱",
    "Кто-то здесь определённо работает на хаос 🌀",
    "Секунду тишины в память о нормальном диалоге 🕯️",
    "Вас заметили. Притворяйтесь естественно 🕴️",
    "Если чат затих — значит, все одновременно думают ерунду 💭",
    "Я не хочу никого обвинять, но виноваты вы 🫵",
    "Осторожно, тут можно случайно получить мнение 🗣️",
    "У самовара сегодня тяжёлый день, не давите на него ☕",
    "Кажется, кто-то перепутал чат с дневником 📝",
    "Я видел вещи, которые вам лучше не отправлять 👁️",
    "Ваше присутствие было зарегистрировано как событие 🎫",
    "Не переживайте, бот тоже не понял последнее сообщение 🤝",
    "Я бы ушёл, но я буквально программа 🤖",
    "Чат проверен на адекватность. Проверка сдалась 🏳️",
    "Вам идёт этот хаос, честно говоря 🎀",
    "Кто-то снова доказал, что интернет — это привилегия 🌐",
)
IMMUNE_USERNAME = "kit_kitovich23"
IMMUNITY_TEXT = "Сочные титяндры @Kit_kitovich23, настолько сочные что ему плевать."
SLEEPY_BLOCKED_ATTACKERS = {"cheto_neveru", "kit_kitovich23"}
SLEEPY_PROTECTION_TEXT = "Не трожь отца!"
MODERATION_RE = re.compile(r"^[!/](бан|мут|пред)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
RESTORE_RE = re.compile(r"^[!/](разбан|размут)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
CLEAR_RE = re.compile(
    r"^[!/](?:снять\s+(?:преды|обвинения)|очистить\s+репутацию)(?:@\w+)?(?:\s|$)",
    re.IGNORECASE,
)
STATS_RE = re.compile(r"^[!/](стат|стата)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
FRANCS_RE = re.compile(r"^[!/](?:франки|francs)(?:@\w+)?[!?.\s]*$", re.IGNORECASE)
CUSTOM_COMMAND_CREATE_RE = re.compile(
    r"^/команда(?:@\w+)?\s+создать[!?.\s]*$", re.IGNORECASE
)
CUSTOM_COMMAND_DELETE_RE = re.compile(
    r"^/команда(?:@\w+)?\s+удалить\s+(.+?)\s*$", re.IGNORECASE | re.DOTALL
)
CUSTOM_COMMAND_HELP_RE = re.compile(
    r"^/команда(?:@\w+)?(?:\s+помощь)?[!?.\s]*$", re.IGNORECASE
)
CUSTOM_COMMAND_LIST_RE = re.compile(r"^/команды(?:@\w+)?[!?.\s]*$", re.IGNORECASE)
FRANC_TRANSFER_RE = re.compile(r"^[!/]перевести(?:@\w+)?(?:\s|$)", re.IGNORECASE)
BUSINESS_SUMMARY_RE = re.compile(
    r"^[!/]?(?:бордель|хлопковое\s+поле)(?:@\w+)?[!?.\s]*$",
    re.IGNORECASE,
)
ENTERPRISE_STATS_RE = re.compile(
    r"^(?:[!/])?стата\s+предприятий[!?.\s]*$", re.IGNORECASE
)
SLAVES_RE = re.compile(r"^/рабы(?:@\w+)?(?:\s|$)", re.IGNORECASE)
SLAVE_MENU_RE = re.compile(r"^/(?:меню|menu)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)", re.IGNORECASE)
TOP_DONORS_RE = re.compile(
    r"^/(?:топ(?:@\w+)?\s+донатеров|top_donors(?:@\w+)?)[!?.\s]*$",
    re.IGNORECASE,
)
CHAT_RE = re.compile(r"^/чат(?:@\w+)?(?:\s|$)", re.IGNORECASE)
RELEASE_RE = re.compile(r"^(?:/отпустить(?:@\w+)?|отпустить\s+раба)(?:\s|$)", re.IGNORECASE)
CHALLENGE_RE = re.compile(
    r"^вызов(?:\s+(кнб|бл[еэ]кджек|шашки))?[!?.\s]*$", re.IGNORECASE
)
GAME_RE = re.compile(
    r"^игра\s+(кнб|бл[еэ]кджек|шашки|рандом)[!?.\s]*$", re.IGNORECASE
)
TOP_RE = re.compile(r"^кому\s+делать\s+нехер[!?.\s]*$", re.IGNORECASE)
GNIDA_RE = re.compile(
    r"(?<![а-яёa-z])(?:кто\s+гнида|гнида\s+чата)(?![а-яёa-z])", re.IGNORECASE
)
RANDOM_PHRASE_RE = re.compile(
    r"^(?:гнида(?:\s*-\s*|\s+)?бот|гнида|бот)\s*,?\s*"
    r"(?:скажи|расскажи)\s+(?:ч[её]\s*-?\s*то|что\s*-?\s*то|"
    r"ч[её]\s*-?\s*нибудь|что\s*-?\s*нибудь)[!?.\s]*$",
    re.IGNORECASE,
)
DUCK_RE = re.compile(
    r"(?<![а-яёa-z])(?:утин\s+член|длина\s+члена\s+уточки)(?![а-яёa-z])",
    re.IGNORECASE,
)
HUILO_RE = re.compile(r"(?<![а-яёa-z])хуйло(?![а-яёa-z])", re.IGNORECASE)
FEMBOY_RE = re.compile(r"(?<![а-яёa-z])дима\s+фембой(?![а-яёa-z])", re.IGNORECASE)
LIES_RE = re.compile(
    r"^(?:гнида(?:\s*-\s*|\s+)?бот|гнида|бот)\s*,?\s*"
    r"(?:он\s+)?пиздит[!?.\s]*$",
    re.IGNORECASE,
)
BASEMENT_RE = re.compile(
    r"^(?:в\s+подвалград|забрать\s+в\s+подвалград)[!?.\s]*$", re.IGNORECASE
)
BASEMENT_RELEASE_RE = re.compile(
    r"^(?:[!/])?отпустить\s+из\s+подвалграда(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
BASEMENT_LIST_RE = re.compile(r"^[!/]подвалград(?:@\w+)?[!?.\s]*$", re.IGNORECASE)
SLAP_RE = re.compile(r"^леща(?:\s|$)", re.IGNORECASE)
BASEMENT_PROMOTE_RE = re.compile(r"^повысить(?:@\w+)?(?:\s|$)", re.IGNORECASE)
BASEMENT_DEMOTE_RE = re.compile(r"^понизить(?:@\w+)?(?:\s|$)", re.IGNORECASE)
TRAIN_RE = re.compile(r"^в\s+п[ао]ровозик[!?.\s]*$", re.IGNORECASE)
BUSINESS_ASSIGN_RE = re.compile(
    r"^в\s+(бордель|хлопковое\s+поле)(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
SELL_RE = re.compile(r"^продать[!?.\s]*$", re.IGNORECASE)
WHIP_RE = re.compile(r"^(?:хлыст|кнут|удар\s+кнутом)[!?.\s]*$", re.IGNORECASE)
ART_THEFT_RE = re.compile(r"(?<![а-яёa-z])(спизжу|спиздил)(?![а-яёa-z])", re.IGNORECASE)
HEAVENLY_PUNISHMENT_RE = re.compile(
    r"^это\s+кара\s+небесная,?\s+сосунок[!?.\s]*$", re.IGNORECASE
)
DUCK_SLAPS_RE = re.compile(r"^давать\s+леща\s+10\s+лет[!?.\s]*$", re.IGNORECASE)
SLEEP_RE = re.compile(r"^усыпить[!?.\s]*$", re.IGNORECASE)
SILENCE_RE = re.compile(
    r"(?<![А-ЯЁ])(?:МОЛЧА+ТЬ(?:\s+ТВАРЬ)?|З+А+Т+К+Н+И+С+Ь+)!*(?![А-ЯЁ])"
)
PISKA_MUTE_RE = re.compile(r"^!+\s*писька\s+в\s+рот!*\s*$", re.IGNORECASE)
DEATH_NOTE_RE = re.compile(
    r"^записать\s+в\s+тетрадь(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
DEATH_NOTE_ERASE_RE = re.compile(
    r"^-?\s*стереть\s+имя(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
LEGS_RE = re.compile(r"^скинь\s+ножки[!?.\s]*$", re.IGNORECASE)
KARGASTAN_RE = re.compile(
    r"^пусть\s+звенят\s+позолоченные\s+кранчики\s+самоваров\s+8\s+народов\.\s*"
    r"божественный\s+ебатель\s+самоваров\s+@kit_kitovich23\.\s*"
    r"выеби\s+эту\s+ньюху\s+за\s+каргастан[!?.\s]*$",
    re.IGNORECASE,
)
TRANSFER_RE = re.compile(r"^[!/]передать(?:@\w+)?(?:\s|$)", re.IGNORECASE)
SLAVE_PRIORITY_RE = re.compile(
    r"^[!/](приоритет|снять\s+приоритет)(?:@\w+)?(?:\s|$)", re.IGNORECASE
)
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
PISYA_RE = re.compile(r"^пися[!?.\s]*$", re.IGNORECASE)
POPA_RE = re.compile(r"^попа[!?.\s]*$", re.IGNORECASE)


class CustomCommandForm(StatesGroup):
    trigger = State()
    cost = State()
    chance = State()
    exclusive = State()
    successes = State()
    failures = State()


class CustomCommandEdit(StatesGroup):
    value = State()


GNIDA_REPLY_INSULT_RE = re.compile(
    r"^(?:ты\s+гнида|гнида\s+бот(?:у)?\s*[-—:]?\s*ты\s+гнида)[!?.\s]*$",
    re.IGNORECASE,
)
GNIDA_DIRECT_INSULT_RE = re.compile(
    r"^гнида\s+бот\s+гнида[!?.\s]*$", re.IGNORECASE
)
GNIDA_REPLY_MEOW_RE = re.compile(
    r"^(?:гнида\s+бот(?:у)?\s*[-—:]?\s*)?мяукни[!?.\s]*$",
    re.IGNORECASE,
)
GNIDA_DIRECT_MEOW_RE = re.compile(
    r"^гнида(?:\s+бот)?\s*[-—:]?\s*(?:мяукни|мяукай)[!?.\s]*$",
    re.IGNORECASE,
)
MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
GNIDA_VIDEO_PATH = MEDIA_DIR / "Gnida.mp4"
MEOW_AUDIO_PATH = MEDIA_DIR / "Meow-voice.ogg"
SAFEBOORU_API_URL = "https://safebooru.org/index.php"
SAFEBOORU_TAGS = "murder_drones rating:safe"
INLINE_GAME_OPTIONS = {
    "random": ("Случайный вызов", "🎲"),
    "rps": ("Камень, ножницы, бумага", "🪨"),
    "blackjack": ("Мини-блэкджек", "🎰"),
    "checkers": ("Шашки", "⚫"),
}


def inline_game_types(query: str) -> list[str]:
    normalized = query.casefold().strip()
    if "кнб" in normalized or "камень" in normalized:
        return ["rps"]
    if "блек" in normalized or "блэк" in normalized:
        return ["blackjack"]
    if "шаш" in normalized:
        return ["checkers"]
    if "случ" in normalized or "рандом" in normalized:
        return ["random"]
    return ["random", "rps", "blackjack", "checkers"]


def next_daily_group_message(
    now: datetime | None = None,
) -> tuple[datetime, str]:
    current = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
    candidates: list[tuple[datetime, str]] = []
    for hour, minute, text in DAILY_GROUP_MESSAGES:
        scheduled = current.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if scheduled < current:
            scheduled += timedelta(days=1)
        candidates.append((scheduled, text))
    return min(candidates, key=lambda item: item[0])


def random_message_service_day(now: datetime | None = None) -> str:
    """Return the Moscow date for a 07:00–02:00 random-message window."""
    current = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
    if current.hour < 2:
        current -= timedelta(days=1)
    return current.date().isoformat()


def random_message_window(service_day: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(service_day).replace(
        hour=7,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=MOSCOW_TZ,
    )
    return start, start + timedelta(hours=19)


def random_message_schedule_times(service_day: str, count: int | None = None) -> list[int]:
    """Pick one to three distinct minute slots between 07:00 and 02:00 MSK."""
    start, _ = random_message_window(service_day)
    amount = count if count is not None else random.randint(1, 3)
    if not 1 <= amount <= 3:
        raise ValueError("Random message count must be between 1 and 3")
    # Leave the fixed 10:00 and 00:00 greetings alone.
    available_minutes = [minute for minute in range(19 * 60) if minute not in {180, 1020}]
    minutes = random.sample(available_minutes, amount)
    return sorted(int((start + timedelta(minutes=minute)).timestamp()) for minute in minutes)


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


def is_reply_to_bot(message: Message, bot: Bot) -> bool:
    replied = message.reply_to_message
    return bool(replied and replied.from_user and replied.from_user.id == bot.id)


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


def sleepy_attack_is_blocked(
    attacker: User | None, target_username: str | None
) -> bool:
    return bool(
        attacker
        and attacker.username
        and attacker.username.casefold() in SLEEPY_BLOCKED_ATTACKERS
        and target_username
        and target_username.casefold() == "mistersleeppy"
    )


async def stored_sleepy_attack_is_blocked(
    database: Database, chat_id: int, attacker: User | None, target_id: int
) -> bool:
    if not attacker or not attacker.username:
        return False
    if attacker.username.casefold() not in SLEEPY_BLOCKED_ATTACKERS:
        return False
    target = await database.get_user(chat_id, target_id)
    return sleepy_attack_is_blocked(
        attacker, target["username"] if target else None
    )


def is_cheto_neveru(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "cheto_neveru")


def basement_rank_name(rank: int) -> str:
    return BASEMENT_RANKS[rank][1]


async def basement_actor_rank(
    database: Database, chat_id: int, user: User | None
) -> int | None:
    if is_cheto_neveru(user):
        return BASEMENT_RULER_RANK
    if not user:
        return None
    return await database.basement_member_rank(chat_id, user.id)


def is_utochka(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "utochka8")


def is_dimon_gfg(user: User | None) -> bool:
    return bool(user and user.username and user.username.casefold() == "dimon_gfg")


def is_pirojok(user: User | None) -> bool:
    return bool(
        user and user.username and user.username.casefold() == PIROJOK_USERNAME
    )


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


def message_has_relayable_media(message: Message) -> bool:
    return any(
        getattr(message, field, None)
        for field in (
            "animation",
            "audio",
            "document",
            "photo",
            "sticker",
            "video",
            "video_note",
            "voice",
        )
    )


def media_accepts_caption(message: Message) -> bool:
    return any(
        getattr(message, field, None)
        for field in ("animation", "audio", "document", "photo", "video", "voice")
    )


def silence_duration_seconds(text: str) -> int:
    return sum(1 for _ in SILENCE_RE.finditer(text)) * 180


def art_theft_count(text: str) -> int:
    return sum(1 for _ in ART_THEFT_RE.finditer(text))


def death_note_countdown_text(name: str, seconds_left: int) -> str:
    clock = DEATH_NOTE_CLOCKS[seconds_left]
    safe_name = html.escape(name)
    phrases = {
        40: f"Имя {safe_name} записано в тетрадь. 🍎",
        30: "Яблоки уже готовы. 🍎",
        20: "Имя не исчезает.",
        10: "Синигами наблюдает.",
    }
    return f"{clock} Осталось {seconds_left} секунд.\n{phrases[seconds_left]}"


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
    priority = "⭐ " if row and "transfer_priority" in row.keys() and row["transfer_priority"] else ""
    if row:
        # A username can be changed and later reused by a different account.
        # Link by the immutable Telegram ID, so stale usernames cannot make
        # two different slaves look like one person.
        name = "@" + str(row["username"]) if row["username"] else (
            row["display_name"] or "без username"
        )
        return f"{priority}{mention(int(row['user_id']), name)} (<code>{row['user_id']}</code>)"
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
            # Settle the past interval before refreshing last_seen: a new post starts
            # the next active shift and cannot retroactively pay an inactive one.
            settle_businesses = getattr(self.database, "settle_businesses_for_user", None)
            if settle_businesses:
                await settle_businesses(user.id)
            await self.database.upsert_user(
                event.chat.id, user.id, user.username, display_name(user)
            )
            if message_has_image(event):
                await self.database.complete_leg_requests(event.chat.id, user.id)
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


async def slavery_challenge_block_reason(
    database: Database, chat_id: int, challenger_id: int, opponent_id: int
) -> str | None:
    """Return a rule violation when a non-friendly game risks someone else's slave."""
    challenger_owner, opponent_owner = await asyncio.gather(
        database.get_owner(chat_id, challenger_id),
        database.get_owner(chat_id, opponent_id),
    )
    challenger_owner_id = int(challenger_owner["owner_id"]) if challenger_owner else None
    opponent_owner_id = int(opponent_owner["owner_id"]) if opponent_owner else None
    if challenger_owner_id is not None and opponent_id != challenger_owner_id:
        if opponent_owner_id != challenger_owner_id:
            return "Раб может играть только с владельцем или с рабом того же владельца."
    if opponent_owner_id is not None and challenger_id != opponent_owner_id:
        if challenger_owner_id != opponent_owner_id:
            return "Нельзя вызывать чужого раба: играть с ним может только его владелец."
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


def challenge_offer_keyboard(challenge_id: int, prefix: str) -> InlineKeyboardMarkup:
    """Buttons shown before a game is allowed to start."""
    callback_prefix = f"{prefix}:{challenge_id}:"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять", callback_data=callback_prefix + "accept"
                ),
                InlineKeyboardButton(
                    text="🚫 Отклонить", callback_data=callback_prefix + "refuse"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩ Отменить вызов", callback_data=callback_prefix + "cancel"
                )
            ],
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


def checkers_keyboard(challenge_id: int, challenge, game) -> InlineKeyboardMarkup:
    board = json.loads(game["board"])
    turn_user_id = int(game["turn_user_id"])
    color = (
        BLACK
        if turn_user_id == int(challenge["challenger_id"])
        else WHITE
    )
    selected = (
        int(game["selected_square"])
        if game["selected_square"] is not None
        else None
    )
    chain_square = (
        int(game["chain_square"])
        if game["chain_square"] is not None
        else None
    )
    moves = legal_checkers_moves(board, color, forced_from=chain_square)
    destinations = {
        move.destination for move in moves.get(selected, [])
    } if selected is not None else set()
    symbols = {"b": "⚫", "w": "⚪", "B": "♛", "W": "♕"}
    rows: list[list[InlineKeyboardButton]] = []
    for row in range(8):
        buttons: list[InlineKeyboardButton] = []
        for column in range(8):
            square = row * 8 + column
            if square == selected:
                label = "🔘"
            elif square in destinations:
                label = "✦"
            elif board[square] != EMPTY:
                label = symbols[board[square]]
            elif (row + column) % 2:
                label = "·"
            else:
                label = "\u00a0"
            callback_action = str(square) if (row + column) % 2 else "noop"
            buttons.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"ck:{challenge_id}:{callback_action}",
                )
            )
        rows.append(buttons)
    rows.append(
        [
            InlineKeyboardButton(
                text="Отказаться", callback_data=f"ck:{challenge_id}:refuse"
            ),
            InlineKeyboardButton(
                text="🏳 Сдаться", callback_data=f"ck:{challenge_id}:resign"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def challenge_text(database: Database, challenge) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    first_state = "✅" if challenge["challenger_choice"] else "⌛"
    second_state = "✅" if challenge["opponent_choice"] else "⌛"
    forced_text = "\n🔒 Принудительный вызов: владелец не может отказаться." if challenge["forced"] else ""
    deadline_text = "3 часа"
    friendly_text = (
        "\n🎮 Дружеская игра: результат не влияет на рабство."
        if challenge["friendly"]
        else ""
    )
    return (
        f"КНБ: {plain_name(challenger)} против {plain_name(opponent)}\n"
        f"{first_state} {plain_name(challenger)} · {second_state} {plain_name(opponent)}\n"
        f"Выберите ход — соперник его не увидит. На ход даётся {deadline_text}."
        f"{forced_text}{friendly_text}"
    )


async def challenge_offer_text(database: Database, challenge) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    game_name = {
        "rps": "КНБ",
        "blackjack": "мини-блэкджек",
        "checkers": "шашки",
    }[str(challenge["game_type"])]
    deadline_text = "5 минут" if challenge["opponent_newcomer"] else "3 часа"
    forced_text = (
        "\n🔒 Принудительный вызов: владелец не может отказаться."
        if challenge["forced"]
        else ""
    )
    newcomer_text = (
        "\n⏳ Новичок не может отказаться; если не примет вызов за 5 минут, "
        "станет рабом вызывающего."
        if challenge["opponent_newcomer"]
        else ""
    )
    friendly_text = (
        "\n🎮 Дружеская игра: результат не влияет на рабство."
        if challenge["friendly"]
        else ""
    )
    return (
        f"🎮 {plain_name(challenger)} вызывает {plain_name(opponent)} "
        f"на {game_name}.\n"
        f"{plain_name(opponent)}, прими или отклони вызов. "
        f"На ответ даётся {deadline_text}."
        f"{forced_text}{newcomer_text}{friendly_text}"
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
    deadline_text = "3 часа"
    friendly_text = (
        "\n🎮 Дружеская игра: результат не влияет на рабство."
        if challenge["friendly"]
        else ""
    )
    return (
        f"🎰 Мини-блэкджек: {plain_name(challenger)} против {plain_name(opponent)}\n\n"
        f"{plain_name(challenger)}: {visible_hand(challenger_hand)} · "
        f"{state(int(challenge['challenger_id']), bool(game['challenger_stood']))}\n"
        f"{plain_name(opponent)}: {visible_hand(opponent_hand)} · "
        f"{state(int(challenge['opponent_id']), bool(game['opponent_stood']))}\n\n"
        f"Свою скрытую карту можно посмотреть кнопкой. На игру даётся {deadline_text}."
        f"{forced_text}{friendly_text}"
    )


async def checkers_text(database: Database, challenge, game) -> str:
    challenger = await database.get_user(challenge["chat_id"], challenge["challenger_id"])
    opponent = await database.get_user(challenge["chat_id"], challenge["opponent_id"])
    turn_id = int(game["turn_user_id"])
    turn = challenger if turn_id == int(challenge["challenger_id"]) else opponent
    turn_symbol = "⚫" if turn_id == int(challenge["challenger_id"]) else "⚪"
    forced_text = (
        "\n🔒 Принудительный вызов: владелец не может отказаться."
        if challenge["forced"]
        else ""
    )
    chain_text = (
        "\n⚔️ Нужно продолжить взятие выбранной шашкой."
        if game["chain_square"] is not None
        else ""
    )
    friendly_text = (
        "\n🎮 Дружеская игра: результат не влияет на рабство."
        if challenge["friendly"]
        else ""
    )
    return (
        "Шашки\n\n"
        f"Играют: {plain_name(challenger)} ⚫ · {plain_name(opponent)} ⚪\n"
        f"Ходит: {plain_name(turn)} {turn_symbol}\n"
        "На ход даётся 3 часа."
        f"{chain_text}{forced_text}{friendly_text}"
    )


def create_router(
    database: Database,
    *,
    kargassia_chat_id: int | None = None,
    yookassa_shop_id: str | None = None,
    yookassa_secret_key: str | None = None,
    yookassa_return_url: str | None = None,
) -> Router:
    router = Router(name="gnida-bot")
    router.message.outer_middleware(TrackingMiddleware(database))
    joke_cooldowns: dict[tuple[int, str], float] = {}
    leg_tasks: set[asyncio.Task[None]] = set()
    challenge_tasks: set[asyncio.Task[None]] = set()
    jug_tasks: set[asyncio.Task[None]] = set()
    captcha_tasks: set[asyncio.Task[None]] = set()
    death_note_tasks: set[asyncio.Task[None]] = set()
    daily_message_tasks: set[asyncio.Task[None]] = set()
    donation_tasks: set[asyncio.Task[None]] = set()
    donation_sync_lock = asyncio.Lock()
    recent_safebooru_ids: dict[int, list[int]] = {}
    challenge_edit_lock = asyncio.Lock()
    checkers_render_lock = asyncio.Lock()
    last_challenge_edit_at = 0.0

    def slave_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(text="👥 Мои рабы", callback_data="sm:slaves"),
                InlineKeyboardButton(text="⭐ Приоритет", callback_data="sm:priority"),
            ],
            [
                InlineKeyboardButton(text="🎮 Статистика игр", callback_data="sm:games"),
                InlineKeyboardButton(text="📖 Гайд", callback_data="sm:guide"),
            ],
            [
                InlineKeyboardButton(text="💰 Франки", callback_data="sm:francs"),
                InlineKeyboardButton(text="🏢 Предприятия", callback_data="sm:business"),
            ],
            [
                InlineKeyboardButton(text="🧰 Подработка", callback_data="sm:work"),
                InlineKeyboardButton(text="🔓 Выкупиться", callback_data="sm:buyout"),
            ],
            [InlineKeyboardButton(text="💜 Поддержать", callback_data="sm:support")],
        ]
        if user_id == CUSTOM_COMMAND_OWNER_ID:
            buttons.append(
                [InlineKeyboardButton(text="⚙️ Кастомные команды", callback_data="sm:custom")]
            )
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def captcha_keyboard(captcha_id: int, correct_emoji: str) -> InlineKeyboardMarkup:
        choices = [correct_emoji] + random.sample(
            [emoji for emoji in CAPTCHA_EMOJIS if emoji != correct_emoji], 3
        )
        random.shuffle(choices)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=emoji, callback_data=f"cp:{captcha_id}:{emoji}"
                    )
                    for emoji in choices
                ]
            ]
        )

    async def restore_default_permissions(bot: Bot, chat_id: int, user_id: int) -> None:
        chat = await bot.get_chat(chat_id)
        permissions = chat.permissions or ChatPermissions(
            **{field: True for field in ChatPermissions.model_fields}
        )
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=permissions,
            use_independent_chat_permissions=True,
        )

    async def delete_captcha_message(captcha, bot: Bot) -> None:
        if not captcha["message_id"]:
            return
        try:
            await bot.delete_message(
                int(captcha["chat_id"]), int(captcha["message_id"])
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning(
                "Could not delete captcha %s: %s", captcha["id"], error
            )

    async def delete_join_message(captcha, bot: Bot) -> None:
        """Remove Telegram's service message only when the captcha was not passed."""
        if not captcha["join_message_id"]:
            return
        try:
            await bot.delete_message(
                int(captcha["chat_id"]), int(captcha["join_message_id"])
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning(
                "Could not delete join message for captcha %s: %s", captcha["id"], error
            )

    async def remove_captcha_user(captcha, bot: Bot, reason: str) -> None:
        chat_id = int(captcha["chat_id"])
        user_id = int(captcha["user_id"])
        try:
            await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            await database.finish_captcha(int(captcha["id"]), reason)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await database.finish_captcha(int(captcha["id"]), "failed")
            logging.getLogger(__name__).warning(
                "Could not remove captcha user %s: %s", user_id, error
            )
        await delete_captcha_message(captcha, bot)
        await delete_join_message(captcha, bot)

    async def enforce_captcha(captcha_id: int, bot: Bot) -> None:
        captcha = await database.get_captcha(captcha_id)
        if not captcha or captcha["status"] not in {"pending", "enforcing"}:
            return
        if captcha["status"] == "pending":
            await asyncio.sleep(max(0, int(captcha["deadline"]) - utc_timestamp()))
            captcha = await database.claim_expired_captcha(captcha_id)
            if not captcha:
                return
        await remove_captcha_user(captcha, bot, "expired")

    def schedule_captcha(captcha_id: int, bot: Bot) -> None:
        task = asyncio.create_task(enforce_captcha(captcha_id, bot))
        captcha_tasks.add(task)
        task.add_done_callback(captcha_tasks.discard)

    async def death_note_name(entry) -> str:
        target = await database.get_user(
            int(entry["chat_id"]), int(entry["target_id"])
        )
        if target:
            return str(target["display_name"] or target["username"] or target["user_id"])
        return str(entry["target_id"])

    async def edit_death_note(entry, bot: Bot, text: str) -> bool:
        if not entry["message_id"]:
            return False
        try:
            await bot.edit_message_text(
                text,
                chat_id=int(entry["chat_id"]),
                message_id=int(entry["message_id"]),
                parse_mode="HTML",
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning(
                "Could not update death note entry %s: %s", entry["id"], error
            )
            return False

    async def enforce_death_note(entry_id: int, bot: Bot) -> None:
        entry = await database.get_death_note_entry(entry_id)
        if not entry or entry["status"] not in {"pending", "enforcing"}:
            return
        if entry["status"] == "pending":
            for seconds_left in (30, 20, 10):
                checkpoint = int(entry["deadline"]) - seconds_left
                wait_seconds = checkpoint - utc_timestamp()
                if wait_seconds <= 0:
                    continue
                await asyncio.sleep(wait_seconds)
                entry = await database.get_death_note_entry(entry_id)
                if not entry or entry["status"] != "pending":
                    return
                await edit_death_note(
                    entry,
                    bot,
                    death_note_countdown_text(
                        await death_note_name(entry), seconds_left
                    ),
                )
            wait_seconds = int(entry["deadline"]) - utc_timestamp()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            entry = await database.claim_expired_death_note_entry(entry_id)
            if not entry:
                return
        try:
            await bot.ban_chat_member(int(entry["chat_id"]), int(entry["target_id"]))
            await database.record_action(
                int(entry["chat_id"]),
                int(entry["target_id"]),
                "ban",
                "записан в тетрадь",
                int(entry["author_id"]),
            )
            await database.finish_death_note_entry(int(entry["id"]), "banned")
            name = html.escape(await death_note_name(entry))
            await edit_death_note(
                entry, bot, f"☠️ Имя {name} было записано в тетрадь. 🍎"
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await database.finish_death_note_entry(int(entry["id"]), "failed")
            await edit_death_note(
                entry,
                bot,
                "🍎 Тетрадь не сработала: " + html.escape(str(error)),
            )

    def schedule_death_note(entry_id: int, bot: Bot) -> None:
        task = asyncio.create_task(enforce_death_note(entry_id, bot))
        death_note_tasks.add(task)

        def finish_task(completed: asyncio.Task[None]) -> None:
            death_note_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Death note task %s failed.", entry_id
                )

        task.add_done_callback(finish_task)

    def slave_menu_back_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="← Меню", callback_data="sm:home")]]
        )

    def slave_menu_support() -> tuple[str, InlineKeyboardMarkup]:
        return (
            "<b>💜 Поддержать Гнида-бота</b>\n"
            "Выбери сумму. Оплата откроется на защищённой странице ЮKassa; "
            "бот не получает данные карты.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="50 ₽", callback_data="sm:donate:50"),
                        InlineKeyboardButton(text="100 ₽", callback_data="sm:donate:100"),
                    ],
                    [
                        InlineKeyboardButton(text="250 ₽", callback_data="sm:donate:250"),
                        InlineKeyboardButton(text="500 ₽", callback_data="sm:donate:500"),
                    ],
                    [InlineKeyboardButton(text="← Меню", callback_data="sm:home")],
                ]
            ),
        )

    async def create_yookassa_donation(amount: int, user: User) -> str:
        if not yookassa_shop_id or not yookassa_secret_key:
            raise RuntimeError("ЮKassa не настроена")
        confirmation: dict[str, str] = {"type": "redirect"}
        if yookassa_return_url:
            confirmation["return_url"] = yookassa_return_url
        payload = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "capture": True,
            "confirmation": confirmation,
            "description": f"Добровольная поддержка Гнида-бота от пользователя {user.id}",
            "metadata": {"telegram_user_id": str(user.id), "kind": "donation"},
        }
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                headers={
                    "Idempotence-Key": str(uuid4()),
                    "Authorization": aiohttp.encode_basic_auth(
                        yookassa_shop_id, yookassa_secret_key
                    ),
                },
            ) as response:
                response.raise_for_status()
                payment = await response.json()
        confirmation_result = payment.get("confirmation") or {}
        url = (
            confirmation_result.get("confirmation_url")
            if isinstance(confirmation_result, dict) else None
        )
        payment_id = payment.get("id")
        if (
            not isinstance(url, str) or not url.startswith("https://")
            or not isinstance(payment_id, str) or not payment_id
        ):
            raise RuntimeError("ЮKassa не вернула данные для оплаты")
        await database.record_donation_payment(
            payment_id, user.id, amount * 100, user.username, user.full_name,
        )
        return url

    async def sync_pending_donations(limit: int = 20) -> bool:
        if not yookassa_shop_id or not yookassa_secret_key:
            return False
        async with donation_sync_lock:
            pending = await database.pending_donations(limit)
            if not pending:
                return True
            timeout = aiohttp.ClientTimeout(total=8)
            semaphore = asyncio.Semaphore(5)
            auth_header = aiohttp.encode_basic_auth(
                yookassa_shop_id, yookassa_secret_key
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async def check_one(row) -> bool:
                    async with semaphore:
                        payment_id = str(row["payment_id"])
                        try:
                            async with session.get(
                                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                                headers={"Authorization": auth_header},
                            ) as response:
                                response.raise_for_status()
                                payment = await response.json()
                            if not isinstance(payment, dict):
                                raise ValueError("Invalid payment response")
                            if payment.get("id") != payment_id:
                                raise ValueError("Payment ID mismatch")
                            metadata = payment.get("metadata") or {}
                            amount = payment.get("amount") or {}
                            if (
                                not isinstance(metadata, dict)
                                or not isinstance(amount, dict)
                                or metadata.get("kind") != "donation"
                                or metadata.get("telegram_user_id") != str(row["user_id"])
                                or amount.get("currency") != "RUB"
                                or Decimal(str(amount.get("value"))) * 100
                                != int(row["amount_kopecks"])
                            ):
                                raise ValueError("Payment details mismatch")
                            status = payment.get("status")
                            if status in {"succeeded", "canceled"}:
                                await database.set_donation_status(payment_id, status)
                            return True
                        except (
                            aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                            InvalidOperation, TypeError,
                        ) as error:
                            logging.getLogger(__name__).warning(
                                "Could not verify donation %s: %s", payment_id, error
                            )
                            return False

                return all(await asyncio.gather(*(check_one(row) for row in pending)))

    async def sync_donations_loop() -> None:
        while True:
            try:
                await sync_pending_donations(50)
            except Exception:
                logging.getLogger(__name__).exception("Donation sync failed")
            await asyncio.sleep(120)

    async def slave_menu_home(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        await database.settle_businesses_for_user(user_id)
        slaves, owners = await asyncio.gather(
            database.list_slaves_globally(user_id),
            database.list_owners_globally(user_id),
        )
        if slaves and owners:
            status = "раб и рабовладелец"
        elif slaves:
            status = "рабовладелец"
        elif owners:
            status = "раб"
        else:
            status = "свободен"
        owner_lines = "\n".join(
            f"• @{html.escape(row['username']) if row['username'] else html.escape(row['display_name'] or str(row['owner_id']))}"
            f" · {html.escape(row['chat_title'] or 'неизвестный чат')}"
            for row in owners[:5]
        )
        owner_text = f"\nВладельцы:\n{owner_lines}" if owner_lines else ""
        balances = await database.list_franc_balances(user_id)
        francs = sum(int(row["balance"]) for row in balances)
        return (
            "<b>Рабовладение</b>\n"
            f"Статус: <b>{status}</b>\n"
            f"Твоих рабов: {len(slaves)}\n"
            f"Франки: <b>{francs} ₣</b>{owner_text}\n\n"
            "Выбери раздел.",
            slave_menu_keyboard(user_id),
        )

    async def slave_menu_slaves(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        rows = await database.list_slaves_globally(user_id)
        grouped: dict[int, tuple[str, list]] = {}
        for row in rows:
            chat_id = int(row["ownership_chat_id"])
            title = row["chat_title"] or f"Чат {chat_id}"
            grouped.setdefault(chat_id, (title, []))[1].append(row)
        return (
            "<b>Твои рабы</b>\n" + slave_report(list(grouped.values())),
            slave_menu_back_keyboard(),
        )

    async def slave_menu_priority(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        rows = await database.list_slaves_globally(user_id)
        if not rows:
            return "<b>Приоритет рабов</b>\nРабов нет.", slave_menu_back_keyboard()
        buttons: list[list[InlineKeyboardButton]] = []
        for row in rows:
            label = "★ " if row["transfer_priority"] else "☆ "
            label += (
                "@" + row["username"]
                if row["username"]
                else row["display_name"] or str(row["user_id"])
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=label[:60],
                        callback_data=f"sm:p:{row['ownership_chat_id']}:{row['user_id']}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="← Меню", callback_data="sm:home")])
        return (
            "<b>Приоритет рабов</b>\n"
            "★ — передаётся последним при проигрыше. Нажми на раба, чтобы включить или снять приоритет.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def slave_menu_games(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        stats = await database.game_stats_for_user(user_id)
        return (
            "<b>Статистика мини-игр</b>\n"
            f"Всего: {stats['total'] or 0} · завершено: {stats['finished'] or 0} · активно: {stats['active'] or 0}\n"
            f"Победы: {stats['wins'] or 0} · поражения: {stats['losses'] or 0} · ничьи: {stats['draws'] or 0}\n"
            f"КНБ: {stats['rps'] or 0} · блэкджек: {stats['blackjack'] or 0} · шашки: {stats['checkers'] or 0}",
            slave_menu_back_keyboard(),
        )

    def slave_menu_guide() -> tuple[str, InlineKeyboardMarkup]:
        return (
            "<b>Краткий гайд по рабству</b>\n"
            "• «Вызов» ответом на сообщение запускает игру с последствиями; «Игра …» — без рабства.\n"
            "• Проигравший без рабов становится рабом победителя. Если у проигравшего есть рабы, передаётся один из них.\n"
            "• ⭐ Приоритетный раб передаётся последним. Это не делает его неуязвимым.\n"
            "• Раб не может иметь рабов и может вызывать только своего владельца. Победа над владельцем освобождает раба.\n"
            "• /рабы в личке показывает список, а /приоритет @юзер меняет приоритет текстовой командой.",
            slave_menu_back_keyboard(),
        )

    async def slave_menu_francs(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        await database.settle_businesses_for_user(user_id)
        balances = await database.list_franc_balances(user_id)
        if not balances:
            text = "<b>💰 Франки</b>\nУ тебя пока 0 ₣. Подработай в предприятии или заведи рабов."
        else:
            total = sum(int(row["balance"]) for row in balances)
            lines = [f"<b>💰 Франки</b>\nВсего: <b>{total} ₣</b>"]
            for row in balances[:10]:
                title = html.escape(row["chat_title"] or f"Чат {row['chat_id']}")
                lines.append(f"• {title}: {int(row['balance'])} ₣")
            text = "\n".join(lines)
        return text, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎭 Доступные команды", callback_data="sm:offers:0")],
            [InlineKeyboardButton(text="← Меню", callback_data="sm:home")],
        ])

    async def slave_menu_custom_offers(
        user_id: int, bot: Bot, page: int = 0
    ) -> tuple[str, InlineKeyboardMarkup]:
        rows = await database.list_available_custom_commands(user_id)
        membership: dict[int, bool] = {}
        for row in rows:
            chat_id = int(row["chat_id"])
            if chat_id not in membership:
                membership[chat_id] = await is_chat_participant(bot, chat_id, user_id)
        available = [row for row in rows if membership[int(row["chat_id"])]]
        page_size = 8
        page_count = max(1, (len(available) + page_size - 1) // page_size)
        page = max(0, min(page, page_count - 1))
        if available:
            lines = [
                f"<b>🎭 Доступные команды</b> · {len(available)} шт. · "
                f"стр. {page + 1}/{page_count}",
                "Напиши фразу в указанном чате. Ответ выбирается случайно.",
            ]
            previous_chat_id: int | None = None
            for row in available[page * page_size:(page + 1) * page_size]:
                chat_id = int(row["chat_id"])
                if chat_id != previous_chat_id:
                    lines.append(
                        f"\n<b>{html.escape(str(row['chat_title'] or f'Чат {chat_id}'))}</b>"
                    )
                    previous_chat_id = chat_id
                lines.append(
                    f"• {html.escape(str(row['trigger']))} — "
                    f"{int(row['cost'])} ₣ · успех {int(row['success_chance'])}%"
                )
            body = "\n".join(lines)
        else:
            body = (
                "<b>🎭 Доступные команды</b>\n"
                "Пока нет команд для твоих чатов. Когда они появятся, увидишь их здесь."
            )
        buttons: list[list[InlineKeyboardButton]] = []
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"sm:offers:{page - 1}"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"sm:offers:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        buttons.append([InlineKeyboardButton(text="← Франки", callback_data="sm:francs")])
        return body, InlineKeyboardMarkup(inline_keyboard=buttons)

    async def slave_menu_businesses(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        await database.settle_businesses_for_user(user_id)
        businesses, slaves = await asyncio.gather(
            database.list_owned_businesses(user_id),
            database.list_slaves_globally(user_id),
        )
        buttons: list[list[InlineKeyboardButton]] = []
        for business in businesses:
            meta = BUSINESS_META[str(business["business_type"])]
            title = business["chat_title"] or f"Чат {business['chat_id']}"
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{meta['emoji']} {title}"[:60],
                        callback_data=f"sm:bd:{business['chat_id']}",
                    )
                ]
            )
        creation_chats: dict[int, str] = {}
        if not businesses:
            for slave in slaves:
                chat_id = int(slave["ownership_chat_id"])
                creation_chats[chat_id] = slave["chat_title"] or f"Чат {chat_id}"
        for chat_id, title in creation_chats.items():
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"➕ Создать · {title}"[:60],
                        callback_data=f"sm:bc:{chat_id}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="← Меню", callback_data="sm:home")])
        if businesses:
            text = "<b>🏢 Твои предприятия</b>\nВыбери предприятие для управления."
        elif creation_chats:
            text = "<b>🏢 Предприятия</b>\nВыбери чат и открой первое предприятие."
        else:
            text = "<b>🏢 Предприятия</b>\nДля открытия предприятия нужен хотя бы один раб."
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)

    async def slave_menu_business_type(
        user_id: int, chat_id: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        slaves = await database.list_slaves(chat_id, user_id)
        if not slaves:
            return "<b>🏢 Предприятия</b>\nВ этом чате у тебя больше нет рабов.", slave_menu_back_keyboard()
        return (
            "<b>Выбери предприятие</b>\nПока можно открыть только одно предприятие. Оно будет работать в этом чате.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏩 Бордель", callback_data=f"sm:bn:{chat_id}:brothel"
                        ),
                        InlineKeyboardButton(
                            text="🌾 Хлопковое поле", callback_data=f"sm:bn:{chat_id}:field"
                        ),
                    ],
                    [InlineKeyboardButton(text="← Предприятия", callback_data="sm:business")],
                ]
            ),
        )

    async def slave_menu_business_detail(
        user_id: int, chat_id: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        await database.settle_business(chat_id, user_id)
        business = await database.get_business(chat_id, user_id)
        if not business:
            return await slave_menu_businesses(user_id)
        workers = await database.list_business_slaves(chat_id, user_id)
        meta = BUSINESS_META[str(business["business_type"])]
        producer_role = "courtesan" if business["business_type"] == "brothel" else "collector"
        leader_role = "manager" if business["business_type"] == "brothel" else "overseer"
        producers = sum(row["role"] == producer_role for row in workers)
        leaders = sum(row["role"] == leader_role for row in workers)
        unassigned = sum(row["role"] is None for row in workers)
        title = html.escape(business["chat_title"] or f"Чат {chat_id}")
        text = (
            f"<b>{meta['emoji']} {meta['name']}</b>\n"
            f"Чат: {title}\n"
            f"{meta['producer']}: {producers} · {meta['leader']}: {leaders}\n"
            f"Не назначены: {unassigned}\n\n"
            "Владелец получает доход каждый час. Активные работники получают 1 ₣ "
            "раз в 6 часов, управляющие и надзиратели — раз в 12 часов. "
            "Неактивные больше суток не получают зарплату, но дают пониженный доход."
        )
        return (
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="👥 Работники", callback_data=f"sm:bw:{chat_id}"
                        )
                    ],
                    [InlineKeyboardButton(text="← Предприятия", callback_data="sm:business")],
                ]
            ),
        )

    async def enterprise_stats_list(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
        businesses = await database.list_chat_businesses(chat_id)
        for business in businesses:
            await database.settle_business(chat_id, int(business["owner_id"]))
        if not businesses:
            return (
                "<b>🏢 Стата предприятий</b>\nВ этом чате пока нет предприятий.",
                InlineKeyboardMarkup(inline_keyboard=[]),
            )
        buttons: list[list[InlineKeyboardButton]] = []
        for business in businesses:
            meta = BUSINESS_META[str(business["business_type"])]
            owner_name = (
                "@" + str(business["username"])
                if business["username"]
                else str(business["display_name"] or business["owner_id"])
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{meta['emoji']} {meta['name']} · {owner_name}"[:60],
                        callback_data=f"es:{chat_id}:{business['owner_id']}",
                    )
                ]
            )
        return (
            "<b>🏢 Стата предприятий</b>\n"
            "Нажми на предприятие: покажу состав и доход владельца за вчера и 7 завершённых дней.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def enterprise_stats_list_for_user(
        user_id: int,
    ) -> tuple[str, InlineKeyboardMarkup]:
        businesses = await database.list_visible_businesses(user_id)
        for business in businesses:
            await database.settle_business(
                int(business["chat_id"]), int(business["owner_id"])
            )
        if not businesses:
            return (
                "<b>🏢 Стата предприятий</b>\n"
                "Я пока не знаю предприятий из твоих чатов.",
                InlineKeyboardMarkup(inline_keyboard=[]),
            )
        buttons: list[list[InlineKeyboardButton]] = []
        for business in businesses:
            meta = BUSINESS_META[str(business["business_type"])]
            owner_name = (
                "@" + str(business["username"])
                if business["username"]
                else str(business["display_name"] or business["owner_id"])
            )
            chat_title = str(business["chat_title"] or "Чат")
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{meta['emoji']} {chat_title} · {owner_name}"[:60],
                        callback_data=f"es:{business['chat_id']}:{business['owner_id']}",
                    )
                ]
            )
        return (
            "<b>🏢 Стата предприятий</b>\n"
            "Предприятия из чатов, где бот тебя видел. Нажми на любое для подробностей.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def enterprise_stats_detail(
        chat_id: int, owner_id: int
    ) -> tuple[str, InlineKeyboardMarkup] | None:
        await database.settle_business(chat_id, owner_id)
        business = await database.get_business(chat_id, owner_id)
        if not business:
            return None
        workers, periods = await asyncio.gather(
            database.list_business_slaves(chat_id, owner_id),
            database.business_income_periods(chat_id, owner_id),
        )
        yesterday_income, week_income = periods
        business_type = str(business["business_type"])
        meta = BUSINESS_META[business_type]
        producer_role = "courtesan" if business_type == "brothel" else "collector"
        leader_role = "manager" if business_type == "brothel" else "overseer"
        producers = sum(worker["role"] == producer_role for worker in workers)
        leaders = sum(worker["role"] == leader_role for worker in workers)
        unassigned = len(workers) - producers - leaders
        owner_name = (
            "@" + html.escape(str(business["username"]))
            if business["username"]
            else html.escape(str(business["display_name"] or owner_id))
        )
        return (
            f"<b>{meta['emoji']} {meta['name']}</b>\n"
            f"Владелец: {owner_name}\n"
            f"{meta['producer']}: <b>{producers}</b> · {meta['leader']}: <b>{leaders}</b>\n"
            f"Не назначены: {unassigned}\n\n"
            f"💰 Доход владельца вчера: <b>{yesterday_income} ₣</b>\n"
            f"📈 Доход владельца за 7 завершённых дней: <b>{week_income} ₣</b>\n\n"
            "История доходов считается с момента подключения этой статистики.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Все предприятия", callback_data=f"es:{chat_id}:list")]
                ]
            ),
        )

    async def slave_menu_business_workers(
        user_id: int, chat_id: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        business = await database.get_business(chat_id, user_id)
        if not business:
            return await slave_menu_businesses(user_id)
        meta = BUSINESS_META[str(business["business_type"])]
        role_labels = {
            None: "➖ Не назначен",
            "courtesan": "💃 Куртизанка",
            "manager": "💼 Управляющий",
            "collector": "🧺 Сборщик",
            "overseer": "🪢 Надзиратель",
        }
        workers = await database.list_business_slaves(chat_id, user_id)
        buttons: list[list[InlineKeyboardButton]] = []
        for worker in workers:
            name = worker["username"] and f"@{worker['username']}" or worker["display_name"] or str(worker["user_id"])
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{role_labels[worker['role']]} · {name}"[:60],
                        callback_data=f"sm:bs:{chat_id}:{worker['user_id']}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="← Предприятие", callback_data=f"sm:bd:{chat_id}")])
        return (
            f"<b>{meta['emoji']} Работники</b>\nНажми на раба, чтобы назначить, повысить или снять с работы.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def slave_menu_business_worker(
        user_id: int, chat_id: int, worker_id: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        business = await database.get_business(chat_id, user_id)
        workers = await database.list_business_slaves(chat_id, user_id)
        worker = next((row for row in workers if int(row["user_id"]) == worker_id), None)
        if not business or not worker:
            return await slave_menu_businesses(user_id)
        meta = BUSINESS_META[str(business["business_type"])]
        producer_role = "courtesan" if business["business_type"] == "brothel" else "collector"
        leader_role = "manager" if business["business_type"] == "brothel" else "overseer"
        name = worker["username"] and "@" + html.escape(worker["username"]) or html.escape(worker["display_name"] or str(worker_id))
        role = worker["role"]
        buttons: list[list[InlineKeyboardButton]] = []
        if role is None:
            buttons.append([InlineKeyboardButton(text=meta["assign"], callback_data=f"sm:br:{chat_id}:{worker_id}:{producer_role}")])
        elif role == producer_role:
            buttons.append([InlineKeyboardButton(text=f"⬆️ Повысить до «{meta['leader']}»", callback_data=f"sm:br:{chat_id}:{worker_id}:{leader_role}")])
            buttons.append([InlineKeyboardButton(text="🚪 Снять с работы", callback_data=f"sm:br:{chat_id}:{worker_id}:none")])
        else:
            buttons.append([InlineKeyboardButton(text=f"⬇️ Понизить до «{meta['producer']}»", callback_data=f"sm:br:{chat_id}:{worker_id}:{producer_role}")])
            buttons.append([InlineKeyboardButton(text="🚪 Снять с работы", callback_data=f"sm:br:{chat_id}:{worker_id}:none")])
        buttons.append([InlineKeyboardButton(text="← Работники", callback_data=f"sm:bw:{chat_id}")])
        role_labels = {
            None: "не назначен",
            "courtesan": "Куртизанка",
            "manager": "Управляющий",
            "collector": "Сборщик",
            "overseer": "Надзиратель",
        }
        current = role_labels.get(role, "не назначен")
        return (
            f"<b>{meta['emoji']} {name}</b>\nТекущая роль: {html.escape(current)}",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def slave_menu_work(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        businesses = await database.list_available_businesses(user_id)
        if not businesses:
            return "<b>🧰 Подработка</b>\nПодходящих предприятий пока нет.", slave_menu_back_keyboard()
        buttons: list[list[InlineKeyboardButton]] = []
        for business in businesses[:20]:
            meta = BUSINESS_META[str(business["business_type"])]
            owner = business["username"] and "@" + business["username"] or business["display_name"] or str(business["owner_id"])
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{meta['emoji']} {owner}"[:60],
                        callback_data=f"sm:job:{business['chat_id']}:{business['owner_id']}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="← Меню", callback_data="sm:home")])
        return (
            "<b>🧰 Подработка</b>\nВыбери предприятие. Одна смена доступна раз в час.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def slave_menu_buyout(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        await database.settle_businesses_for_user(user_id)
        owners = await database.list_owners_globally(user_id)
        if not owners:
            return "<b>🔓 Выкуп</b>\nТы свободен.", slave_menu_back_keyboard()
        buttons: list[list[InlineKeyboardButton]] = []
        for owner in owners:
            owner_name = owner["username"] and "@" + owner["username"] or owner["display_name"] or str(owner["owner_id"])
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🔓 Выкупиться у {owner_name} · {BUYOUT_COST_FRANCS} ₣"[:60],
                        callback_data=f"sm:buy:{owner['chat_id']}:{owner['owner_id']}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(text="← Меню", callback_data="sm:home")])
        return (
            f"<b>🔓 Выкуп из рабства</b>\nКаждый выкуп стоит {BUYOUT_COST_FRANCS} ₣.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def send_daily_group_messages(bot: Bot) -> None:
        assert kargassia_chat_id is not None
        while True:
            scheduled, text = next_daily_group_message()
            delay = max(0.0, (scheduled - datetime.now(MOSCOW_TZ)).total_seconds())
            await asyncio.sleep(delay)
            try:
                await bot.send_message(kargassia_chat_id, text)
            except TelegramAPIError as error:
                logging.getLogger(__name__).warning(
                    "Could not send scheduled group message: %s", error
                )

    async def send_random_group_messages(bot: Bot) -> None:
        """Send 1–3 persistent, non-repeating chat phrases in each Moscow window."""
        assert kargassia_chat_id is not None
        while True:
            now = datetime.now(MOSCOW_TZ)
            if 2 <= now.hour < 7:
                next_start = now.replace(hour=7, minute=0, second=0, microsecond=0)
                await asyncio.sleep((next_start - now).total_seconds())
                continue

            service_day = random_message_service_day(now)
            await database.get_or_create_random_message_schedule(
                kargassia_chat_id,
                service_day,
                random_message_schedule_times(service_day),
            )
            await database.skip_expired_random_messages(
                kargassia_chat_id, service_day, utc_timestamp()
            )
            scheduled = await database.next_pending_random_message(
                kargassia_chat_id, service_day
            )
            if scheduled is None:
                _, window_end = random_message_window(service_day)
                now = datetime.now(MOSCOW_TZ)
                next_start = (
                    window_end
                    if now < window_end
                    else window_end.replace(hour=7) + timedelta(days=1)
                )
                await asyncio.sleep(max(1, (next_start - now).total_seconds()))
                continue

            delay = int(scheduled["scheduled_at"]) - utc_timestamp()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
            claimed = await database.claim_random_message(int(scheduled["id"]))
            if not claimed:
                continue
            phrase = await database.take_random_phrase(
                kargassia_chat_id, RANDOM_CHAT_PHRASES
            )
            try:
                await bot.send_message(kargassia_chat_id, phrase)
            except TelegramAPIError as error:
                await database.finish_random_message(int(claimed["id"]), "failed")
                logging.getLogger(__name__).warning(
                    "Could not send random chat phrase: %s", error
                )
            else:
                await database.finish_random_message(int(claimed["id"]), "sent")

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

    async def edit_challenge(
        challenge,
        bot: Bot,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        nonlocal last_challenge_edit_at
        inline_message_id = challenge["inline_message_id"]
        if not inline_message_id and not challenge["message_id"]:
            return False
        # Several expired challenges can be resumed immediately after a restart.
        # Telegram limits editMessageText aggressively in a single group, so serialize
        # these edits and obey the retry interval returned by the API.
        async with challenge_edit_lock:
            pause = 0.3 - (time.monotonic() - last_challenge_edit_at)
            if pause > 0:
                await asyncio.sleep(pause)
            for attempt in range(3):
                try:
                    if inline_message_id:
                        await bot.edit_message_text(
                            text,
                            inline_message_id=str(inline_message_id),
                            reply_markup=reply_markup,
                            parse_mode="HTML",
                        )
                    else:
                        await bot.edit_message_text(
                            text,
                            chat_id=int(challenge["chat_id"]),
                            message_id=int(challenge["message_id"]),
                            reply_markup=reply_markup,
                            parse_mode="HTML",
                        )
                    last_challenge_edit_at = time.monotonic()
                    return True
                except TelegramRetryAfter as error:
                    last_challenge_edit_at = time.monotonic()
                    delay = max(1, int(error.retry_after))
                    logging.getLogger(__name__).warning(
                        "Challenge %s hit Telegram flood control; retrying in %s s.",
                        challenge["id"],
                        delay,
                    )
                    if attempt < 2:
                        await asyncio.sleep(delay)
                        continue
                except TelegramBadRequest as error:
                    detail = str(error).casefold()
                    if "message is not modified" in detail:
                        return True
                    if "message to edit not found" in detail:
                        await database.mark_challenge_unavailable(int(challenge["id"]))
                    logging.getLogger(__name__).warning(
                        "Could not edit challenge %s: %s", challenge["id"], error
                    )
                    return False
                except TelegramForbiddenError as error:
                    await database.mark_challenge_unavailable(int(challenge["id"]))
                    logging.getLogger(__name__).warning(
                        "Could not edit challenge %s: %s", challenge["id"], error
                    )
                    return False
            logging.getLogger(__name__).warning(
                "Could not edit challenge %s after Telegram retry attempts.",
                challenge["id"],
            )
            return False

    async def active_challenge_view(challenge):
        """Build the first playable screen after an opponent accepts an offer."""
        challenge_id = int(challenge["id"])
        if challenge["game_type"] == "blackjack":
            game = await database.get_blackjack_game(challenge_id)
            return await blackjack_text(database, challenge, game), blackjack_keyboard(
                challenge_id
            )
        if challenge["game_type"] == "checkers":
            game = await database.get_checkers_game(challenge_id)
            return await checkers_text(database, challenge, game), checkers_keyboard(
                challenge_id, challenge, game
            )
        return await challenge_text(database, challenge), challenge_keyboard(challenge_id)

    async def accept_pending_challenge(
        challenge, callback: CallbackQuery, bot: Bot
    ) -> bool:
        if callback.from_user.id != int(challenge["opponent_id"]):
            await callback.answer("Этот вызов адресован другому участнику.", show_alert=True)
            return False
        if utc_timestamp() >= int(challenge["deadline"]):
            await callback.answer("Время на принятие уже истекло.", show_alert=True)
            return False
        accepted = await database.accept_challenge(
            int(challenge["id"]), callback.from_user.id
        )
        if not accepted:
            await callback.answer("Этот вызов уже недоступен.", show_alert=True)
            return False
        text, keyboard = await active_challenge_view(accepted)
        if not await edit_challenge(accepted, bot, text, keyboard):
            await database.finish_challenge(int(accepted["id"]), "failed")
            await callback.answer("Не удалось открыть игру.", show_alert=True)
            return False
        await callback.answer("Вызов принят")
        return True

    async def refuse_pending_challenge(challenge, callback: CallbackQuery, bot: Bot) -> bool:
        if callback.from_user.id != int(challenge["opponent_id"]):
            await callback.answer("Этот вызов адресован другому участнику.", show_alert=True)
            return False
        if utc_timestamp() >= int(challenge["deadline"]):
            await callback.answer("Время на принятие уже истекло.", show_alert=True)
            return False
        if challenge["forced"]:
            await callback.answer(
                "Это принудительный вызов — владелец не может отказаться.",
                show_alert=True,
            )
            return False
        if challenge["opponent_newcomer"]:
            await callback.answer("Первые 5 минут после входа отказаться нельзя.", show_alert=True)
            return False
        if await database.finish_challenge(int(challenge["id"]), "refused"):
            await edit_challenge(
                challenge,
                bot,
                f"🚫 {html.escape(display_name(callback.from_user))} отказался от вызова.",
            )
        await callback.answer()
        return True

    async def cancel_pending_challenge(challenge, callback: CallbackQuery, bot: Bot) -> bool:
        if callback.from_user.id != int(challenge["challenger_id"]):
            await callback.answer("Отменить вызов может только его автор.", show_alert=True)
            return False
        if not await database.cancel_challenge_offer(
            int(challenge["id"]), callback.from_user.id
        ):
            await callback.answer("Этот вызов уже недоступен.", show_alert=True)
            return False
        await edit_challenge(
            challenge,
            bot,
            f"↩ {html.escape(display_name(callback.from_user))} отменил вызов.",
        )
        await callback.answer("Вызов отменён")
        return True

    async def render_checkers(challenge_id: int, bot: Bot) -> bool:
        """Render only the newest persisted checker position.

        Callbacks can arrive almost simultaneously. Rendering from a snapshot taken
        before another callback finishes can otherwise put an old turn back on screen.
        """
        async with checkers_render_lock:
            challenge = await database.get_challenge(challenge_id)
            if (
                not challenge
                or challenge["status"] != "active"
                or challenge["game_type"] != "checkers"
            ):
                return False
            game = await database.get_checkers_game(challenge_id)
            if not game:
                return False
            return await edit_challenge(
                challenge,
                bot,
                await checkers_text(database, challenge, game),
                reply_markup=checkers_keyboard(challenge_id, challenge, game),
            )

    async def publish_game_win(
        challenge, bot: Bot, winner_id: int, loser_id: int, heading: str
    ) -> None:
        chat_id = int(challenge["chat_id"])
        winner = await database.get_user(chat_id, winner_id)
        loser = await database.get_user(chat_id, loser_id)
        if challenge["friendly"]:
            await edit_challenge(
                challenge,
                bot,
                f"{heading}\n🏆 Победил {plain_name(winner)}. "
                "Дружеская игра — рабство не изменилось.",
            )
            return
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
        elif outcome == "protected_slave":
            consequence = f"{plain_name(loser)} остаётся у своего владельца."
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
            await database.record_challenge_result(int(challenge["id"]), None)
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
        await database.record_challenge_result(int(challenge["id"]), winner_id)
        await publish_game_win(
            challenge, bot, winner_id, loser_id, f"{icons[first]} — {icons[second]}"
        )

    async def enforce_challenge_deadline(challenge_id: int, bot: Bot) -> None:
        while True:
            challenge = await database.get_challenge(challenge_id)
            if not challenge or challenge["status"] not in {
                "pending",
                "active",
                "deadline",
                "pending_deadline",
            }:
                return
            if challenge["status"] in {"deadline", "pending_deadline"}:
                break
            await asyncio.sleep(max(0, int(challenge["deadline"]) - utc_timestamp()))
            challenge = await database.claim_expired_challenge(challenge_id)
            if challenge:
                break
        if challenge["status"] in {"pending", "pending_deadline"}:
            if challenge["opponent_newcomer"]:
                chat_id = int(challenge["chat_id"])
                challenger_id = int(challenge["challenger_id"])
                opponent_id = int(challenge["opponent_id"])
                challenger = await database.get_user(chat_id, challenger_id)
                opponent = await database.get_user(chat_id, opponent_id)
                result = await database.force_enslave(chat_id, opponent_id, challenger_id)
                if result == "enslaved":
                    text = (
                        f"⌛ {plain_name(opponent)} не принял вызов за 5 минут и "
                        f"становится рабом {plain_name(challenger)}."
                    )
                elif result == "pirojok_cannot_own":
                    text = "Этот кувшин слишком тесен для вас двоих."
                else:
                    text = (
                        "⌛ Новичок не принял вызов, но вызывающий сам является рабом "
                        "и не может получить собственного."
                    )
            else:
                text = "⌛ За 3 часа вызов не был принят. Последствий нет."
            await edit_challenge(challenge, bot, text)
            return
        if challenge["game_type"] == "blackjack":
            blackjack = await database.get_blackjack_game(challenge_id)
            first_moved = bool(blackjack and blackjack["challenger_acted"])
            second_moved = bool(blackjack and blackjack["opponent_acted"])
        elif challenge["game_type"] == "checkers":
            checkers = await database.get_checkers_game(challenge_id)
            first_moved = bool(checkers and checkers["challenger_acted"])
            second_moved = bool(checkers and checkers["opponent_acted"])
        else:
            first_moved = bool(challenge["challenger_choice"])
            second_moved = bool(challenge["opponent_choice"])
        if challenge["game_type"] == "rps" and first_moved and second_moved:
            await publish_played_result(challenge, bot)
        else:
            await edit_challenge(
                challenge,
                bot,
                "⌛ За 3 часа бой не был завершён. Последствий нет.",
            )

    def schedule_challenge(challenge_id: int, bot: Bot) -> None:
        task = asyncio.create_task(enforce_challenge_deadline(challenge_id, bot))
        challenge_tasks.add(task)

        def finish_task(completed: asyncio.Task[None]) -> None:
            challenge_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Challenge deadline task %s failed.", challenge_id
                )

        task.add_done_callback(finish_task)

    @router.startup()
    async def resume_leg_requests(bot: Bot) -> None:
        for request in await database.pending_leg_requests():
            schedule_leg_request(int(request["id"]), bot)
        for captcha in await database.pending_captchas():
            schedule_captcha(int(captcha["id"]), bot)
        for entry in await database.pending_death_note_entries():
            schedule_death_note(int(entry["id"]), bot)
        for challenge in await database.pending_challenges():
            schedule_challenge(int(challenge["id"]), bot)
        for hiding in await database.pending_jug_hidings():
            schedule_jug_hiding(
                int(hiding["chat_id"]),
                int(hiding["user_id"]),
                int(hiding["hidden_until"]),
                bot,
            )
        if kargassia_chat_id is not None:
            task = asyncio.create_task(send_daily_group_messages(bot))
            daily_message_tasks.add(task)
            task.add_done_callback(daily_message_tasks.discard)
            task = asyncio.create_task(send_random_group_messages(bot))
            daily_message_tasks.add(task)
            task.add_done_callback(daily_message_tasks.discard)
        if yookassa_shop_id and yookassa_secret_key:
            task = asyncio.create_task(sync_donations_loop())
            donation_tasks.add(task)
            task.add_done_callback(donation_tasks.discard)

    @router.shutdown()
    async def stop_leg_timers() -> None:
        for task in tuple(leg_tasks):
            task.cancel()
        for task in tuple(challenge_tasks):
            task.cancel()
        for task in tuple(jug_tasks):
            task.cancel()
        for task in tuple(captcha_tasks):
            task.cancel()
        for task in tuple(death_note_tasks):
            task.cancel()
        for task in tuple(daily_message_tasks):
            task.cancel()
        for task in tuple(donation_tasks):
            task.cancel()

    def custom_command_owner(message: Message) -> bool:
        return bool(
            message.from_user and message.from_user.id == CUSTOM_COMMAND_OWNER_ID
        )

    async def custom_commands_menu(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
        rows = await database.list_all_custom_commands()
        page_size = 8
        page_count = max(1, (len(rows) + page_size - 1) // page_size)
        page = max(0, min(page, page_count - 1))
        buttons = [
            [InlineKeyboardButton(
                text=f"{row['chat_title'] or row['chat_id']} · {row['trigger']}"[:60],
                callback_data=f"cc:detail:{row['id']}",
            )]
            for row in rows[page * page_size:(page + 1) * page_size]
        ]
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"cc:list:{page - 1}"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"cc:list:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        buttons.append([InlineKeyboardButton(text="➕ Создать команду", callback_data="cc:chats")])
        buttons.append([InlineKeyboardButton(text="← Главное меню", callback_data="sm:home")])
        return (
            f"<b>⚙️ Кастомные команды</b> · {len(rows)} шт. · стр. {page + 1}/{page_count}\n"
            "Выбери команду для настройки." if rows else
            "<b>⚙️ Кастомные команды</b>\nПока команд нет. Нажми «Создать команду».",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def custom_command_chats_menu(bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
        chats = await database.list_custom_command_chats(CUSTOM_COMMAND_OWNER_ID)
        buttons = []
        for chat in chats:
            if await is_chat_participant(bot, int(chat["chat_id"]), CUSTOM_COMMAND_OWNER_ID):
                buttons.append([InlineKeyboardButton(
                    text=str(chat["title"])[:60],
                    callback_data=f"cc:new:{chat['chat_id']}",
                )])
        buttons.append([InlineKeyboardButton(text="← Команды", callback_data="cc:list:0")])
        return (
            "<b>➕ Новая команда</b>\nВыбери чат, где она будет работать."
            if len(buttons) > 1 else
            "<b>➕ Новая команда</b>\nНе нашёл общего чата. Напиши в нужном чате /команда создать.",
            InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def custom_command_detail(command_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await database.get_custom_command_by_id(command_id)
        if row is None:
            return None
        successes = command_responses(row, "success_responses")
        failures = command_responses(row, "failure_responses")
        exclusive = (
            f"{html.escape('@' + str(row['exclusive_username']))} "
            f"(ID {row['exclusive_user_id']})"
            if row["exclusive_username"] else
            f"ID {row['exclusive_user_id']}"
            if row["exclusive_user_id"] is not None else "все"
        )
        body = (
            f"<b>⚙️ {html.escape(str(row['trigger']))}</b>\n"
            f"Чат: {html.escape(str(row['chat_title'] or row['chat_id']))}\n"
            f"Цена: <b>{row['cost']} ₣</b> · Успех: <b>{row['success_chance']}%</b>\n"
            f"Доступ: {exclusive}\n"
            f"Ответов: успех {len(successes)}, неудача {len(failures)}\n\n"
            "Нажми на настройку, которую хочешь изменить."
        )
        buttons = [
            [InlineKeyboardButton(text="💰 Цена", callback_data=f"cc:edit:{command_id}:cost"),
             InlineKeyboardButton(text="🎲 Шанс", callback_data=f"cc:edit:{command_id}:chance")],
            [InlineKeyboardButton(text="👤 Доступ", callback_data=f"cc:edit:{command_id}:exclusive"),
             InlineKeyboardButton(text="✏️ Фраза", callback_data=f"cc:edit:{command_id}:trigger")],
            [InlineKeyboardButton(text=f"✅ Успехи ({len(successes)})", callback_data=f"cc:out:{command_id}:s:0"),
             InlineKeyboardButton(text=f"❌ Неудачи ({len(failures)})", callback_data=f"cc:out:{command_id}:f:0")],
            [InlineKeyboardButton(text="🗑 Удалить команду", callback_data=f"cc:delete:{command_id}")],
            [InlineKeyboardButton(text="← Все команды", callback_data="cc:list:0")],
        ]
        return body, InlineKeyboardMarkup(inline_keyboard=buttons)

    async def custom_command_outcomes(
        command_id: int, outcome: str, page: int = 0
    ) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await database.get_custom_command_by_id(command_id)
        if row is None:
            return None
        field = "success_responses" if outcome == "s" else "failure_responses"
        responses = command_responses(row, field)
        page_size = 5
        page_count = max(1, (len(responses) + page_size - 1) // page_size)
        page = max(0, min(page, page_count - 1))
        title = "✅ Успехи" if outcome == "s" else "❌ Неудачи"
        buttons = [
            [InlineKeyboardButton(
                text=f"{index + 1}. {responses[index]}"[:60],
                callback_data=f"cc:resp:{command_id}:{outcome}:{index}",
            )]
            for index in range(page * page_size, min((page + 1) * page_size, len(responses)))
        ]
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"cc:out:{command_id}:{outcome}:{page - 1}"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"cc:out:{command_id}:{outcome}:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        buttons.append([InlineKeyboardButton(text="➕ Добавить вариант", callback_data=f"cc:add:{command_id}:{outcome}")])
        buttons.append([InlineKeyboardButton(text="← Команда", callback_data=f"cc:detail:{command_id}")])
        body = (
            f"<b>{title}</b> · {html.escape(str(row['trigger']))}\n"
            f"Вариантов: {len(responses)} · стр. {page + 1}/{page_count}\n"
            "Нажми на вариант для изменения или удаления."
        )
        return body, InlineKeyboardMarkup(inline_keyboard=buttons)

    async def custom_command_response_detail(
        command_id: int, outcome: str, index: int
    ) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await database.get_custom_command_by_id(command_id)
        if row is None:
            return None
        field = "success_responses" if outcome == "s" else "failure_responses"
        responses = command_responses(row, field)
        if not 0 <= index < len(responses):
            return None
        title = "успеха" if outcome == "s" else "неудачи"
        return (
            f"<b>Вариант {title} №{index + 1}</b>\n\n"
            f"{html.escape(responses[index])}",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"cc:editresp:{command_id}:{outcome}:{index}"),
                 InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cc:delresp:{command_id}:{outcome}:{index}")],
                [InlineKeyboardButton(text="← К вариантам", callback_data=f"cc:out:{command_id}:{outcome}:{index // 5}")],
            ]),
        )

    async def reject_non_owner(message: Message) -> bool:
        if custom_command_owner(message):
            return False
        await message.answer("Конструктор команд доступен только владельцу бота.")
        return True

    async def wizard_text(message: Message, state: FSMContext) -> str | None:
        value = message_content(message).strip()
        if value.casefold() in {"/отмена", "отмена"}:
            await state.clear()
            await message.answer("Действие отменено.")
            return None
        if not value:
            await message.answer("Пришли значение обычным текстовым сообщением.")
            return None
        return value

    @router.message(text_or_caption_regexp(CUSTOM_COMMAND_CREATE_RE))
    async def custom_command_create(message: Message, state: FSMContext, bot: Bot) -> None:
        if await reject_non_owner(message):
            return
        if message.chat.type == "private":
            body, keyboard = await custom_command_chats_menu(bot)
            await message.answer(body, reply_markup=keyboard, parse_mode="HTML")
            return
        if message.chat.type not in GROUP_TYPES:
            return
        await state.clear()
        await state.set_state(CustomCommandForm.trigger)
        await state.update_data(chat_id=message.chat.id)
        await message.answer(
            "Шаг 1/6. Напиши фразу-команду, например: <code>Послать отряд омона</code>\n\n"
            "Регистр и знаки !?. в конце при вызове не важны. Для отмены: /отмена",
            parse_mode="HTML",
        )

    @router.message(CustomCommandForm.trigger)
    async def custom_command_trigger(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        trigger_key = normalize_custom_trigger(value)
        if not trigger_key or len(value) > MAX_TRIGGER_LENGTH or value.startswith("/"):
            await message.answer(
                f"Фраза должна быть короче {MAX_TRIGGER_LENGTH + 1} символов и не начинаться с /."
            )
            return
        await state.update_data(trigger=value.strip(), trigger_key=trigger_key)
        await state.set_state(CustomCommandForm.cost)
        await message.answer("Шаг 2/6. Сколько франков стоит попытка? Напиши целое число от 0 до 1 000 000.")

    @router.message(CustomCommandForm.cost)
    async def custom_command_cost(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        try:
            cost = int(value.replace(" ", ""))
        except ValueError:
            cost = -1
        if not 0 <= cost <= 1_000_000:
            await message.answer("Нужно целое число от 0 до 1 000 000.")
            return
        await state.update_data(cost=cost)
        await state.set_state(CustomCommandForm.chance)
        await message.answer("Шаг 3/6. Укажи шанс успеха целым числом от 0 до 100 (без знака %).")

    @router.message(CustomCommandForm.chance)
    async def custom_command_chance(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        try:
            chance = int(value.removesuffix("%").strip())
        except ValueError:
            chance = -1
        if not 0 <= chance <= 100:
            await message.answer("Шанс должен быть целым числом от 0 до 100.")
            return
        await state.update_data(success_chance=chance)
        await state.set_state(CustomCommandForm.exclusive)
        await message.answer(
            "Шаг 4/6. Кто сможет вызывать команду?\n"
            "Напиши <code>нет</code>, чтобы разрешить всем, либо @username/Telegram ID одного пользователя.",
            parse_mode="HTML",
        )

    @router.message(CustomCommandForm.exclusive)
    async def custom_command_exclusive(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        data = await state.get_data()
        chat_id = int(data["chat_id"])
        exclusive_user_id: int | None = None
        if value.casefold() not in {"нет", "-", "все", "всем"}:
            row = await database.resolve_user(chat_id, value)
            if row:
                exclusive_user_id = int(row["user_id"])
            elif value.lstrip("-").isdigit():
                exclusive_user_id = int(value)
            else:
                await message.answer(
                    "Я ещё не видел этого @username в чате. Пришли числовой Telegram ID или «нет»."
                )
                return
        await state.update_data(exclusive_user_id=exclusive_user_id)
        await state.set_state(CustomCommandForm.successes)
        await message.answer(
            "Шаг 5/6. Пришли варианты УСПЕХА — каждый с новой строки (до 20).\n\n"
            "Метки: <code>{actor}</code> — автор команды, <code>{target}</code> — пользователь из ответа "
            "или случайный из последних 50, <code>{random}</code> — отдельный случайный участник. "
            "Также работают (тег1), (тег2), (тег) и (рандомный тег).",
            parse_mode="HTML",
        )

    @router.message(CustomCommandForm.successes)
    async def custom_command_successes(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        responses = parse_response_lines(value)
        if responses is None:
            await message.answer("Нужно от 1 до 20 непустых строк, не длиннее 1000 символов каждая.")
            return
        await state.update_data(success_responses=responses)
        await state.set_state(CustomCommandForm.failures)
        await message.answer(
            "Шаг 6/6. Пришли варианты НЕУДАЧИ — каждый с новой строки. "
            "Если шанс успеха 100%, можно написать «нет»."
        )

    @router.message(CustomCommandForm.failures)
    async def custom_command_failures(message: Message, state: FSMContext) -> None:
        value = await wizard_text(message, state)
        if value is None:
            return
        data = await state.get_data()
        responses = parse_response_lines(value, allow_empty=True)
        if responses is None:
            await message.answer("Нужно до 20 непустых строк, не длиннее 1000 символов каждая.")
            return
        if int(data["success_chance"]) < 100 and not responses:
            await message.answer("При шансе ниже 100% нужен хотя бы один вариант неудачи.")
            return
        await database.save_custom_command(
            int(data["chat_id"]),
            str(data["trigger"]),
            str(data["trigger_key"]),
            int(data["cost"]),
            int(data["success_chance"]),
            list(data["success_responses"]),
            responses,
            data.get("exclusive_user_id"),
            CUSTOM_COMMAND_OWNER_ID,
        )
        await state.clear()
        command_row = await database.get_custom_command(int(data["chat_id"]), str(data["trigger_key"]))
        await message.answer(
            "✅ Команда сохранена. Теперь напиши в чат: "
            f"<code>{html.escape(str(data['trigger']))}</code>\n"
            "Повторное создание с той же фразой обновит её настройки.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Настроить", callback_data=f"cc:detail:{command_row['id']}")]
            ]) if message.chat.type == "private" and command_row else None,
        )

    @router.message(text_or_caption_regexp(CUSTOM_COMMAND_LIST_RE))
    async def custom_command_list(message: Message, bot: Bot) -> None:
        if await reject_non_owner(message):
            return
        body, keyboard = await custom_commands_menu()
        if message.chat.type == "private":
            await message.answer(body, reply_markup=keyboard, parse_mode="HTML")
        elif message.chat.type in GROUP_TYPES:
            try:
                await bot.send_message(CUSTOM_COMMAND_OWNER_ID, body, reply_markup=keyboard, parse_mode="HTML")
                await message.answer("⚙️ Меню команд отправлено тебе в личку.")
            except TelegramForbiddenError:
                await message.answer("Открой личку с ботом, нажми Start и напиши /команды.")

    @router.message(text_or_caption_regexp(CUSTOM_COMMAND_DELETE_RE))
    async def custom_command_delete(message: Message) -> None:
        if await reject_non_owner(message):
            return
        if message.chat.type not in GROUP_TYPES:
            await message.answer("Для удаления из лички открой /команды и выбери нужную команду.")
            return
        match = CUSTOM_COMMAND_DELETE_RE.match(message_content(message))
        trigger_key = normalize_custom_trigger(match.group(1) if match else "")
        deleted = await database.delete_custom_command(message.chat.id, trigger_key)
        await message.answer("Команда удалена." if deleted else "Такой команды в этом чате нет.")

    @router.message(text_or_caption_regexp(CUSTOM_COMMAND_HELP_RE))
    async def custom_command_help(message: Message) -> None:
        if await reject_non_owner(message):
            return
        await message.answer(
            "<b>Конструктор команд</b>\n"
            "/команды — меню всех команд в личке\n"
            "/команда создать — создать команду\n"
            "В меню можно менять цену, шанс, доступ, фразу и ответы по одному.\n"
            "/отмена — выйти из мастера создания\n\n"
            "Вызов — точная фраза без учёта регистра и конечных !?.",
            parse_mode="HTML",
        )

    @router.message(CustomCommandEdit.value)
    async def custom_command_edit_value(message: Message, state: FSMContext) -> None:
        if not custom_command_owner(message) or message.chat.type != "private":
            return
        value = await wizard_text(message, state)
        if value is None:
            return
        data = await state.get_data()
        command_id = int(data["command_id"])
        row = await database.get_custom_command_by_id(command_id)
        if row is None:
            await state.clear()
            await message.answer("Команда уже удалена.")
            return
        field = str(data["field"])
        if field == "response":
            if "\n" in value or len(value) > MAX_RESPONSE_LENGTH:
                await message.answer(f"Пришли один вариант одним сообщением до {MAX_RESPONSE_LENGTH} символов.")
                return
            result = await database.modify_custom_command_response(
                command_id, str(data["outcome"]), str(data["action"]),
                index=data.get("index"), text=value,
            )
        elif field == "cost":
            try:
                parsed = int(value.replace(" ", ""))
            except ValueError:
                parsed = -1
            result = await database.update_custom_command_setting(command_id, "cost", parsed)
        elif field == "chance":
            try:
                parsed = int(value.removesuffix("%").strip())
            except ValueError:
                parsed = -1
            result = await database.update_custom_command_setting(command_id, "success_chance", parsed)
        elif field == "exclusive":
            if value.casefold() in {"нет", "-", "все", "всем"}:
                exclusive_id = None
            else:
                user = await database.resolve_user(int(row["chat_id"]), value)
                if user:
                    exclusive_id = int(user["user_id"])
                elif value.isdigit():
                    exclusive_id = int(value)
                else:
                    await message.answer("Не знаю этот @username в чате. Пришли Telegram ID или «нет».")
                    return
            result = await database.update_custom_command_setting(
                command_id, "exclusive_user_id", exclusive_id
            )
        elif field == "trigger":
            result = await database.update_custom_command_setting(command_id, "trigger", value)
        else:
            await state.clear()
            return
        errors = {
            "invalid": "Значение не подходит. Проверь формат и попробуй ещё раз.",
            "exists": "Команда с такой фразой уже есть в этом чате. Выбери другую.",
            "needs_failure": "Сначала добавь хотя бы один вариант неудачи, затем снижай шанс ниже 100%.",
            "limit": "Уже есть 20 вариантов. Удали один перед добавлением нового.",
        }
        if result != "updated":
            if result == "not_found":
                await state.clear()
            await message.answer(errors.get(result, "Не удалось изменить команду."))
            return
        if field == "response":
            view = await custom_command_outcomes(
                command_id, "s" if data["outcome"] == "success" else "f"
            )
            if data["action"] == "add":
                await message.answer(
                    "✅ Вариант добавлен. Пришли следующий отдельным сообщением "
                    "или нажми «Готово».",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="✅ Готово · к вариантам",
                            callback_data=(
                                f"cc:out:{command_id}:"
                                f"{'s' if data['outcome'] == 'success' else 'f'}:0"
                            ),
                        )],
                    ]),
                )
                return
        else:
            view = await custom_command_detail(command_id)
        await state.clear()
        if view:
            await message.answer("✅ Сохранено.\n\n" + view[0], reply_markup=view[1], parse_mode="HTML")

    @router.callback_query(F.data.startswith("cc:"))
    async def custom_command_menu_callback(
        callback: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        if (
            not callback.from_user
            or callback.from_user.id != CUSTOM_COMMAND_OWNER_ID
            or not callback.message
            or callback.message.chat.type != "private"
            or not callback.data
        ):
            await callback.answer("Это меню доступно только владельцу бота.", show_alert=True)
            return
        parts = callback.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action not in {"new", "add", "edit", "editresp"}:
            await state.clear()
        view: tuple[str, InlineKeyboardMarkup] | None = None
        notice: str | None = None
        try:
            if action == "list":
                view = await custom_commands_menu(int(parts[2]))
            elif action == "chats":
                view = await custom_command_chats_menu(bot)
            elif action == "new":
                chat_id = int(parts[2])
                allowed = any(
                    int(chat["chat_id"]) == chat_id
                    for chat in await database.list_custom_command_chats(CUSTOM_COMMAND_OWNER_ID)
                ) and await is_chat_participant(bot, chat_id, CUSTOM_COMMAND_OWNER_ID)
                if not allowed:
                    await callback.answer("Этот чат недоступен.", show_alert=True)
                    return
                await state.clear()
                await state.set_state(CustomCommandForm.trigger)
                await state.update_data(chat_id=chat_id)
                view = (
                    "<b>Шаг 1/6</b> · Напиши фразу новой команды одним сообщением.\n"
                    "Для отмены: /отмена",
                    InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="← Команды", callback_data="cc:list:0")]
                    ]),
                )
            elif action == "detail":
                view = await custom_command_detail(int(parts[2]))
            elif action == "out" and parts[3] in {"s", "f"}:
                view = await custom_command_outcomes(int(parts[2]), parts[3], int(parts[4]))
            elif action == "resp" and parts[3] in {"s", "f"}:
                view = await custom_command_response_detail(int(parts[2]), parts[3], int(parts[4]))
            elif action in {"add", "edit", "editresp"}:
                command_id = int(parts[2])
                row = await database.get_custom_command_by_id(command_id)
                if row is None:
                    notice = "Команда уже удалена."
                else:
                    if action == "edit":
                        field = parts[3]
                        if field not in {"cost", "chance", "exclusive", "trigger"}:
                            raise ValueError
                        prompts = {
                            "cost": "Напиши новую цену в франках (0–1 000 000).",
                            "chance": "Напиши новый шанс успеха (0–100%).",
                            "exclusive": "Пришли Telegram ID, известный боту @username или «нет» для всех.",
                            "trigger": "Напиши новую фразу команды (до 80 символов).",
                        }
                        prompt = prompts[field]
                    else:
                        outcome = "success" if parts[3] == "s" else "failure"
                        if parts[3] not in {"s", "f"}:
                            raise ValueError
                        index = int(parts[4]) if action == "editresp" else None
                        responses = command_responses(
                            row, "success_responses" if outcome == "success" else "failure_responses"
                        )
                        if index is not None and not 0 <= index < len(responses):
                            raise ValueError
                        if action == "add" and len(responses) >= MAX_RESPONSES_PER_OUTCOME:
                            await callback.answer("Уже есть 20 вариантов. Удали один перед добавлением.", show_alert=True)
                            return
                        prompt = (
                            "Пришли новый вариант одним сообщением (до 1000 символов).\n"
                            "Метки: {actor}, {target}, {random}."
                            if action == "editresp" else
                            "Пришли вариант одним сообщением (до 1000 символов). "
                            "Затем можно присылать следующие по одному.\n"
                            "Метки: {actor}, {target}, {random}."
                        )
                    await state.clear()
                    await state.set_state(CustomCommandEdit.value)
                    if action == "edit":
                        await state.update_data(command_id=command_id, field=field)
                    else:
                        await state.update_data(
                            command_id=command_id, field="response", outcome=outcome,
                            action="edit" if action == "editresp" else "add", index=index,
                        )
                    await callback.message.answer(prompt + "\nДля отмены: /отмена")
                    await callback.answer()
                    return
            elif action == "delresp" and parts[3] in {"s", "f"}:
                command_id, index = int(parts[2]), int(parts[4])
                outcome = "success" if parts[3] == "s" else "failure"
                result = await database.modify_custom_command_response(
                    command_id, outcome, "delete", index=index
                )
                notice = {
                    "updated": "Вариант удалён.",
                    "last_required": "Последний обязательный вариант удалять нельзя.",
                }.get(result, "Вариант уже недоступен.")
                view = await custom_command_outcomes(command_id, parts[3])
            elif action == "delete":
                command_id = int(parts[2])
                row = await database.get_custom_command_by_id(command_id)
                if row:
                    view = (
                        f"Удалить команду <b>{html.escape(str(row['trigger']))}</b>?",
                        InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"cc:confirm:{command_id}")],
                            [InlineKeyboardButton(text="← Отмена", callback_data=f"cc:detail:{command_id}")],
                        ]),
                    )
            elif action == "confirm":
                deleted = await database.delete_custom_command_by_id(int(parts[2]))
                notice = "Команда удалена." if deleted else "Команда уже удалена."
                view = await custom_commands_menu()
            else:
                raise ValueError
        except (ValueError, IndexError):
            await callback.answer("Кнопка устарела или повреждена.", show_alert=True)
            return
        if view is None:
            view = await custom_commands_menu()
            notice = notice or "Команда уже удалена."
        try:
            await callback.message.edit_text(view[0], reply_markup=view[1], parse_mode="HTML")
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).casefold():
                await callback.message.answer(view[0], reply_markup=view[1], parse_mode="HTML")
        await callback.answer(notice)

    @router.message(text_or_caption_regexp(START_RE))
    async def start(message: Message) -> None:
        if message.chat.type == "private":
            await message.answer(
                "<b>Привет! Я Гнида-бот.</b> Вот что можно делать в чате:\n\n"
                "🎮 <b>Игры:</b> ответь на сообщение «Игра кнб», «Игра блекджек» "
                "или «Игра шашки» — без последствий. «Вызов» запускает игру "
                "с последствиями для рабства.\n"
                "👥 <b>Рабство:</b> /рабы показывает твоих рабов, /меню — статус, "
                "приоритет, статистику игр и гайд.\n"
                "💰 <b>Франки:</b> зарабатывай на предприятиях, подрабатывай, "
                "выкупайся из рабства и трать валюту на доступные кастомные команды. "
                "Их список — в разделе «Франки».\n"
                "😄 <b>Рофлы:</b> попробуй «пися», «попа» или «кто гнида».\n\n"
                "Открой меню, чтобы посмотреть всё подробнее.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Открыть меню", callback_data="sm:home")]
                ]),
            )

    @router.message(text_or_caption_regexp(TOP_DONORS_RE))
    async def top_donors(message: Message) -> None:
        if not message.from_user or message.chat.type not in {*GROUP_TYPES, "private"}:
            return
        try:
            fresh = (
                not donation_sync_lock.locked()
                and await sync_pending_donations(5)
            )
        except Exception:
            logging.getLogger(__name__).exception("Could not refresh donor leaderboard")
            fresh = False
        donors = await database.top_donors(10)
        if not donors:
            body = "🏆 Донатов пока нет. Первое место свободно!"
        else:
            lines = ["<b>🏆 Топ донатеров</b>"]
            for position, donor in enumerate(donors, start=1):
                name = donor["username"] or donor["display_name"] or str(donor["user_id"])
                kopecks = int(donor["total_kopecks"])
                amount = (
                    str(kopecks // 100) if kopecks % 100 == 0
                    else f"{kopecks // 100},{kopecks % 100:02d}"
                )
                lines.append(f"{position}. {html.escape(str(name))} — {amount} ₽")
            body = "\n".join(lines)
        if not yookassa_shop_id or not yookassa_secret_key:
            body += "\n\n⚠️ ЮKassa не настроена: новые платежи не проверяются."
        elif not fresh:
            body += "\n\n⚠️ Не удалось проверить часть новых платежей. Топ обновится позже."
        await message.answer(body, parse_mode="HTML")

    @router.message(text_or_caption_regexp(SLAVE_MENU_RE))
    async def slave_menu(message: Message) -> None:
        if message.chat.type != "private" or not message.from_user:
            return
        body, keyboard = await slave_menu_home(message.from_user.id)
        await message.answer(body, reply_markup=keyboard, parse_mode="HTML")

    @router.message(text_or_caption_regexp(FRANCS_RE))
    async def francs(message: Message) -> None:
        if not message.from_user:
            return
        if message.chat.type == "private":
            body, keyboard = await slave_menu_francs(message.from_user.id)
            await message.answer(body, reply_markup=keyboard, parse_mode="HTML")
            return
        if message.chat.type not in GROUP_TYPES:
            return
        await database.settle_businesses_for_user(message.from_user.id)
        balance = await database.franc_balance(message.chat.id, message.from_user.id)
        await message.answer(f"💰 Твой баланс: <b>{balance} ₣</b>", parse_mode="HTML")

    @router.message(text_or_caption_regexp(BUSINESS_SUMMARY_RE))
    async def business_summary(message: Message) -> None:
        """Show a compact public summary of the sender's enterprise in this chat."""
        if not message.from_user:
            return
        text = message_content(message)
        requested_type = "brothel" if "бордель" in text.casefold() else "field"
        if message.chat.type == "private":
            businesses = await database.list_owned_businesses(message.from_user.id)
            business = next(
                (row for row in businesses if row["business_type"] == requested_type), None
            )
            if not business:
                await message.answer("Такого предприятия у тебя пока нет.")
                return
            body, keyboard = await slave_menu_business_detail(
                message.from_user.id, int(business["chat_id"])
            )
            await message.answer(body, reply_markup=keyboard, parse_mode="HTML")
            return
        if message.chat.type not in GROUP_TYPES:
            return
        await database.settle_business(message.chat.id, message.from_user.id)
        business = await database.get_business(message.chat.id, message.from_user.id)
        if not business or business["business_type"] != requested_type:
            return
        workers = await database.list_business_slaves(message.chat.id, message.from_user.id)
        meta = BUSINESS_META[requested_type]
        producer_role = "courtesan" if requested_type == "brothel" else "collector"
        leader_role = "manager" if requested_type == "brothel" else "overseer"
        producers = sum(row["role"] == producer_role for row in workers)
        leaders = sum(row["role"] == leader_role for row in workers)
        balance = await database.franc_balance(message.chat.id, message.from_user.id)
        await message.answer(
            f"<b>{meta['emoji']} {meta['name']}</b>\n"
            f"{meta['producer']}: <b>{producers}</b> · {meta['leader']}: <b>{leaders}</b>\n"
            f"💰 Баланс владельца: <b>{balance} ₣</b>\n"
            "Подробное управление — в личке через /меню.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(FRANC_TRANSFER_RE))
    async def transfer_francs(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        text = message_content(message)
        match = FRANC_TRANSFER_RE.match(text)
        if not match:
            return
        target = await resolve_target(message, database, text[match.end() :].strip())
        if not target:
            return
        target_id, target_name, amount_text = target
        amount_token, _ = split_first(amount_text)
        if not amount_token or not amount_token.isdigit():
            await message.answer("Укажи целое число франков после участника.")
            return
        amount = int(amount_token)
        await asyncio.gather(
            database.settle_businesses_for_user(message.from_user.id),
            database.settle_businesses_for_user(target_id),
        )
        result = await database.transfer_francs(
            message.chat.id, message.from_user.id, target_id, amount
        )
        if result == "transferred":
            await message.answer(
                f"💸 {mention(message.from_user.id, display_name(message.from_user))} "
                f"перевёл {mention(target_id, target_name)} <b>{amount} ₣</b>.",
                parse_mode="HTML",
            )
        elif result == "insufficient":
            await message.answer("Недостаточно франков.")
        elif result == "self":
            await message.answer("Себе переводить не нужно.")
        else:
            await message.answer("Сумма должна быть больше нуля.")

    @router.message(text_or_caption_regexp(ENTERPRISE_STATS_RE))
    async def enterprise_stats(message: Message) -> None:
        if message.chat.type in GROUP_TYPES:
            body, keyboard = await enterprise_stats_list(message.chat.id)
        elif message.chat.type == "private" and message.from_user:
            body, keyboard = await enterprise_stats_list_for_user(message.from_user.id)
        else:
            return
        await message.answer(body, reply_markup=keyboard, parse_mode="HTML")

    @router.message(text_or_caption_regexp(BUSINESS_ASSIGN_RE))
    async def assign_business_worker(message: Message) -> None:
        sender = message.from_user
        if message.chat.type not in GROUP_TYPES or not sender:
            return
        text = message_content(message)
        match = BUSINESS_ASSIGN_RE.match(text)
        if not match:
            return
        business_type = "brothel" if match.group(1).casefold() == "бордель" else "field"
        business = await database.get_business(message.chat.id, sender.id)
        if not business or business["business_type"] != business_type:
            await message.answer("У тебя нет такого предприятия в этом чате.")
            return
        target = await resolve_target(message, database, text[match.end() :].strip())
        if not target:
            return
        target_id, target_name, _ = target
        producer_role = "courtesan" if business_type == "brothel" else "collector"
        leader_role = "manager" if business_type == "brothel" else "overseer"
        current = await database.business_worker_role(message.chat.id, sender.id, target_id)
        if current == leader_role:
            await message.answer(
                f"{mention(target_id, target_name)} уже {BUSINESS_META[business_type]['leader'].lower()}.",
                parse_mode="HTML",
            )
            return
        result = await database.set_business_worker_role(
            message.chat.id, sender.id, target_id, producer_role
        )
        if result != "updated":
            await message.answer("В предприятие можно назначить только своего раба.")
            return
        if current == producer_role:
            await message.answer(
                f"{mention(target_id, target_name)} уже назначен: "
                f"{BUSINESS_META[business_type]['producer'].lower()}.",
                parse_mode="HTML",
            )
            return
        await message.answer(
            f"{BUSINESS_META[business_type]['emoji']} {mention(target_id, target_name)} назначен: "
            f"{BUSINESS_META[business_type]['producer'].lower()}.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(SELL_RE))
    async def business_sell(message: Message) -> None:
        replied = message.reply_to_message
        sender = message.from_user
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not target
            or target.is_bot
        ):
            return
        owner = await database.get_owner(message.chat.id, sender.id)
        owner_id = sender.id if not owner else int(owner["owner_id"])
        business = await database.get_business(message.chat.id, owner_id)
        if not business or business["business_type"] != "brothel":
            return
        if sender.id != owner_id and await database.business_worker_role(
            message.chat.id, owner_id, sender.id
        ) != "manager":
            return
        if await database.business_worker_role(message.chat.id, owner_id, target.id) != "courtesan":
            return
        target_mention = mention(target.id, display_name(target))
        await message.answer(
            random.choice(
                (
                    f"💥 После жаркой ночи с клиентом у {target_mention} отваливаются ноги.",
                    f"📖 {target_mention} почувствовал себя персонажем хентай-манги.",
                    f"🔥 Эта куртизанка в ударе. {target_mention} столько клиентов обслужила, что вам и не снилось.",
                )
            ),
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(WHIP_RE))
    async def business_whip(message: Message) -> None:
        replied = message.reply_to_message
        sender = message.from_user
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or not target
            or target.is_bot
        ):
            return
        owner = await database.get_owner(message.chat.id, sender.id)
        owner_id = sender.id if not owner else int(owner["owner_id"])
        business = await database.get_business(message.chat.id, owner_id)
        if not business or business["business_type"] != "field":
            return
        if sender.id != owner_id and await database.business_worker_role(
            message.chat.id, owner_id, sender.id
        ) != "overseer":
            return
        if await database.business_worker_role(message.chat.id, owner_id, target.id) != "collector":
            return
        target_mention = mention(target.id, display_name(target))
        await message.answer(
            random.choice(
                (
                    f"🪢 {target_mention} получил хлыст. Хлопок сам себя не соберёт.",
                    f"🌾 {target_mention} услышал свист кнута и внезапно вспомнил о норме.",
                    f"⚡ Надзиратель щёлкнул кнутом рядом с {target_mention} — работа закипела.",
                )
            ),
            parse_mode="HTML",
        )

    @router.callback_query(F.data.startswith("sm:"))
    async def slave_menu_callback(callback: CallbackQuery, bot: Bot) -> None:
        if (
            not callback.from_user
            or not callback.message
            or callback.message.chat.type != "private"
            or not callback.data
        ):
            await callback.answer()
            return

        action = callback.data[3:]
        user_id = callback.from_user.id
        notice: str | None = None
        if action == "home":
            body, keyboard = await slave_menu_home(user_id)
        elif action == "custom" and user_id == CUSTOM_COMMAND_OWNER_ID:
            body, keyboard = await custom_commands_menu()
        elif action == "slaves":
            body, keyboard = await slave_menu_slaves(user_id)
        elif action == "priority":
            body, keyboard = await slave_menu_priority(user_id)
        elif action == "games":
            body, keyboard = await slave_menu_games(user_id)
        elif action == "guide":
            body, keyboard = slave_menu_guide()
        elif action == "support":
            body, keyboard = slave_menu_support()
        elif action.startswith("donate:"):
            try:
                amount = int(action.split(":", 1)[1])
            except ValueError:
                await callback.answer("Некорректная сумма.", show_alert=True)
                return
            if amount not in {50, 100, 250, 500}:
                await callback.answer("Недоступная сумма.", show_alert=True)
                return
            if callback.from_user is None:
                await callback.answer()
                return
            try:
                payment_url = await create_yookassa_donation(amount, callback.from_user)
            except RuntimeError as error:
                notice = str(error)
                body, keyboard = slave_menu_support()
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                logging.getLogger(__name__).warning("Could not create YooKassa payment: %s", error)
                notice = "Не удалось создать платёж. Попробуй позже."
                body, keyboard = slave_menu_support()
            else:
                body = (
                    f"<b>💜 Поддержка на {amount} ₽</b>\n"
                    "Нажми кнопку ниже: оплата пройдёт на странице ЮKassa. Спасибо!"
                )
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"Оплатить {amount} ₽", url=payment_url)],
                        [InlineKeyboardButton(text="← Поддержка", callback_data="sm:support")],
                    ]
                )
        elif action == "francs":
            body, keyboard = await slave_menu_francs(user_id)
        elif action.startswith("offers:"):
            try:
                page = int(action.split(":", 1)[1])
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            body, keyboard = await slave_menu_custom_offers(user_id, bot, page)
        elif action == "business":
            body, keyboard = await slave_menu_businesses(user_id)
        elif action.startswith("bc:"):
            try:
                _, raw_chat_id = action.split(":", 1)
                chat_id = int(raw_chat_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            body, keyboard = await slave_menu_business_type(user_id, chat_id)
        elif action.startswith("bn:"):
            try:
                _, raw_chat_id, business_type = action.split(":", 2)
                chat_id = int(raw_chat_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            if business_type not in BUSINESS_META:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            result = await database.create_business(chat_id, user_id, business_type)
            if result == "created":
                notice = "Предприятие открыто."
                body, keyboard = await slave_menu_business_detail(user_id, chat_id)
            elif result == "exists":
                body, keyboard = await slave_menu_business_detail(user_id, chat_id)
            else:
                notice = "Для предприятия нужен хотя бы один раб."
                body, keyboard = await slave_menu_businesses(user_id)
        elif action.startswith("bd:"):
            try:
                _, raw_chat_id = action.split(":", 1)
                chat_id = int(raw_chat_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            body, keyboard = await slave_menu_business_detail(user_id, chat_id)
        elif action.startswith("bw:"):
            try:
                _, raw_chat_id = action.split(":", 1)
                chat_id = int(raw_chat_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            body, keyboard = await slave_menu_business_workers(user_id, chat_id)
        elif action.startswith("bs:"):
            try:
                _, raw_chat_id, raw_worker_id = action.split(":", 2)
                chat_id, worker_id = int(raw_chat_id), int(raw_worker_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            body, keyboard = await slave_menu_business_worker(user_id, chat_id, worker_id)
        elif action.startswith("br:"):
            try:
                _, raw_chat_id, raw_worker_id, role = action.split(":", 3)
                chat_id, worker_id = int(raw_chat_id), int(raw_worker_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            result = await database.set_business_worker_role(
                chat_id, user_id, worker_id, None if role == "none" else role
            )
            if result == "updated":
                notice = "Роль обновлена."
            elif result == "removed":
                notice = "Раб снят с работы."
            else:
                notice = "Этот раб или предприятие больше недоступны."
            body, keyboard = await slave_menu_business_worker(user_id, chat_id, worker_id)
        elif action == "work":
            body, keyboard = await slave_menu_work(user_id)
        elif action.startswith("job:"):
            try:
                _, raw_chat_id, raw_owner_id = action.split(":", 2)
                chat_id, owner_id = int(raw_chat_id), int(raw_owner_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            await database.settle_business(chat_id, owner_id)
            result, worker_pay, owner_pay, cooldown_until = await database.work_at_business(
                chat_id, owner_id, user_id
            )
            body, keyboard = await slave_menu_work(user_id)
            if result == "worked":
                notice = f"Смена завершена: +{worker_pay} ₣."
            elif result == "inactive_slave":
                notice = "Смена засчитана владельцу, но раб не писал в этом чате больше суток: зарплаты нет."
                body = (
                    f"✅ <b>Смена завершена</b>\nТы получил: {worker_pay} ₣\n"
                    f"Владелец получил: {owner_pay} ₣\n\n{body}"
                )
            elif result == "cooldown":
                until = datetime.fromtimestamp(int(cooldown_until), MOSCOW_TZ).strftime("%H:%M")
                notice = f"Следующая смена после {until} МСК."
            elif result == "own_business":
                notice = "В собственном предприятии подработка не нужна."
            else:
                notice = "Предприятие больше недоступно."
        elif action == "buyout":
            body, keyboard = await slave_menu_buyout(user_id)
        elif action.startswith("buy:"):
            try:
                _, raw_chat_id, raw_owner_id = action.split(":", 2)
                chat_id, owner_id = int(raw_chat_id), int(raw_owner_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            await database.settle_businesses_for_user(user_id)
            result = await database.buyout_slave(chat_id, owner_id, user_id)
            body, keyboard = await slave_menu_buyout(user_id)
            if result == "released":
                notice = "Выкуп успешен. Ты свободен."
                body = f"✅ <b>Свобода за {BUYOUT_COST_FRANCS} ₣</b>\n\n{body}"
            elif result == "insufficient":
                notice = f"Нужно {BUYOUT_COST_FRANCS} ₣."
            else:
                notice = "Эта связь рабства уже изменилась."
        elif action.startswith("p:"):
            try:
                _, raw_chat_id, raw_slave_id = action.split(":", 2)
                chat_id, slave_id = int(raw_chat_id), int(raw_slave_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            owner = await database.get_owner(chat_id, slave_id)
            if not owner or int(owner["owner_id"]) != user_id:
                await callback.answer("Этот участник больше не ваш раб.", show_alert=True)
                return
            enabled = not bool(owner["transfer_priority"])
            result = await database.set_slave_priority(chat_id, user_id, slave_id, enabled)
            if result == "updated":
                notice = "Приоритет включён." if enabled else "Приоритет снят."
            else:
                notice = "Список уже изменился, обновлён."
            body, keyboard = await slave_menu_priority(user_id)
        else:
            await callback.answer("Неизвестный раздел.", show_alert=True)
            return

        try:
            await callback.message.edit_text(body, reply_markup=keyboard, parse_mode="HTML")
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).casefold():
                await callback.message.answer(body, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer(notice or "")

    @router.callback_query(F.data.startswith("es:"))
    async def enterprise_stats_callback(callback: CallbackQuery) -> None:
        if not callback.data or not callback.message or not callback.from_user:
            await callback.answer()
            return
        try:
            _, raw_chat_id, raw_owner_id = callback.data.split(":", 2)
            chat_id = int(raw_chat_id)
        except ValueError:
            await callback.answer("Некорректная кнопка.", show_alert=True)
            return
        is_group = callback.message.chat.type in GROUP_TYPES
        is_private = callback.message.chat.type == "private"
        if not is_group and not is_private:
            await callback.answer()
            return
        if is_group and chat_id != callback.message.chat.id:
            await callback.answer("Эта статистика относится к другому чату.", show_alert=True)
            return
        if is_private and not await database.user_knows_chat(callback.from_user.id, chat_id):
            await callback.answer("Этот чат недоступен в твоей статистике.", show_alert=True)
            return
        if raw_owner_id == "list":
            if is_group:
                body, keyboard = await enterprise_stats_list(chat_id)
            else:
                body, keyboard = await enterprise_stats_list_for_user(callback.from_user.id)
        else:
            try:
                owner_id = int(raw_owner_id)
            except ValueError:
                await callback.answer("Некорректная кнопка.", show_alert=True)
                return
            result = await enterprise_stats_detail(chat_id, owner_id)
            if result is None:
                await callback.answer("Предприятие больше не существует.", show_alert=True)
                return
            body, keyboard = result
        try:
            await callback.message.edit_text(body, reply_markup=keyboard, parse_mode="HTML")
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).casefold():
                await callback.message.answer(body, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    @router.message(F.new_chat_members)
    async def new_members(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES:
            return
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
            try:
                member = await bot.get_chat_member(message.chat.id, user.id)
                if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
                    continue
                await bot.restrict_chat_member(
                    message.chat.id,
                    user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    use_independent_chat_permissions=True,
                )
                correct_emoji = random.choice(CAPTCHA_EMOJIS)
                captcha_id = await database.create_captcha(
                    message.chat.id,
                    user.id,
                    correct_emoji,
                    utc_timestamp() + CAPTCHA_TIMEOUT_SECONDS,
                )
                await database.set_captcha_join_message(captcha_id, message.message_id)
                sent = await message.answer(
                    f"Проверка: нажми на {CAPTCHA_EMOJI_NAMES[correct_emoji]}",
                    reply_markup=captcha_keyboard(captcha_id, correct_emoji),
                )
                await database.set_captcha_message(captcha_id, sent.message_id)
                schedule_captcha(captcha_id, bot)
            except TelegramAPIError as error:
                logging.getLogger(__name__).warning(
                    "Could not create captcha for %s: %s", user.id, error
                )
                try:
                    await restore_default_permissions(bot, message.chat.id, user.id)
                except TelegramAPIError:
                    pass

    @router.callback_query(F.data.startswith("cp:"))
    async def captcha_answer(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            await callback.answer()
            return
        try:
            _, raw_captcha_id, emoji = callback.data.split(":", 2)
            captcha_id = int(raw_captcha_id)
        except (TypeError, ValueError):
            await callback.answer("Капча повреждена.", show_alert=True)
            return
        captcha = await database.get_captcha(captcha_id)
        if not captcha or int(captcha["chat_id"]) != callback.message.chat.id:
            await callback.answer("Капча уже неактивна.", show_alert=True)
            return
        result, remaining = await database.submit_captcha(
            captcha_id, callback.from_user.id, emoji, CAPTCHA_MAX_ATTEMPTS
        )
        if result == "not_owner":
            await callback.answer("Это не твоя капча.", show_alert=True)
            return
        if result == "retry":
            await callback.answer(f"Неверно. Осталось попыток: {remaining}.", show_alert=True)
            return
        if result == "passed":
            try:
                await restore_default_permissions(
                    bot, int(captcha["chat_id"]), callback.from_user.id
                )
            except TelegramAPIError as error:
                logging.getLogger(__name__).warning(
                    "Could not lift captcha restriction for %s: %s",
                    callback.from_user.id,
                    error,
                )
                await callback.answer("Не удалось снять ограничение, попробуй позже.", show_alert=True)
                return
            await delete_captcha_message(captcha, bot)
            await callback.answer("✅ Проверка пройдена")
            return
        if result == "failed":
            await callback.answer("Попытки закончились.", show_alert=True)
            await remove_captcha_user(captcha, bot, "failed")
            return
        if result == "expired":
            claimed = await database.claim_expired_captcha(captcha_id)
            if claimed:
                await remove_captcha_user(claimed, bot, "expired")
            await callback.answer("Время вышло.", show_alert=True)
            return
        await callback.answer("Капча уже неактивна.", show_alert=True)

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
        if sleepy_attack_is_blocked(message.from_user, target.username):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
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
        sender_rank = await basement_actor_rank(
            database, message.chat.id, message.from_user
        )
        if (
            message.chat.type not in GROUP_TYPES
            or sender_rank is None
            or sender_rank < BASEMENT_DEPUTY_RANK
        ):
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
        lines = ["🏚️ Подвалград"]
        for rank, (emoji, _, plural_name) in BASEMENT_RANKS.items():
            residents = [member for member in members if int(member["rank"]) == rank]
            if not residents:
                continue
            lines.extend(("", f"{emoji} {plural_name}:"))
            for member in residents:
                nickname = (
                    member["display_name"]
                    or member["username"]
                    or str(member["user_id"])
                )
                lines.append(f"• {html.escape(nickname)}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(
        text_or_caption_regexp(BASEMENT_PROMOTE_RE)
        | text_or_caption_regexp(BASEMENT_DEMOTE_RE)
    )
    async def change_basement_rank(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        text = message_content(message)
        is_promotion = bool(BASEMENT_PROMOTE_RE.match(text))
        match = BASEMENT_PROMOTE_RE.match(text) or BASEMENT_DEMOTE_RE.match(text)
        if not match:
            return
        target = await resolve_target(
            message,
            database,
            text[match.end() :].strip(),
            allowed_bot_id=bot.id,
        )
        if not target:
            return
        target_id, target_name, _ = target
        if not is_cheto_neveru(message.from_user):
            business = await database.get_business(message.chat.id, message.from_user.id)
            if not business:
                return
            business_type = str(business["business_type"])
            meta = BUSINESS_META[business_type]
            producer_role = "courtesan" if business_type == "brothel" else "collector"
            leader_role = "manager" if business_type == "brothel" else "overseer"
            current = await database.business_worker_role(
                message.chat.id, message.from_user.id, target_id
            )
            if is_promotion:
                next_role = (
                    producer_role
                    if current is None
                    else leader_role
                    if current == producer_role
                    else None
                )
            else:
                next_role = producer_role if current == leader_role else None
            if next_role is None and (
                (is_promotion and current == leader_role)
                or (not is_promotion and current is None)
            ):
                await message.answer(
                    f"⚠️ {mention(target_id, target_name)} уже на предельной роли.",
                    parse_mode="HTML",
                )
                return
            result = await database.set_business_worker_role(
                message.chat.id, message.from_user.id, target_id, next_role
            )
            if result not in {"updated", "removed"}:
                await message.answer(
                    "Повышать и понижать можно только собственных рабов этого предприятия."
                )
                return
            previous_name = (
                "не назначен"
                if current is None
                else meta["producer"] if current == producer_role else meta["leader"]
            )
            next_name = (
                "не назначен"
                if next_role is None
                else meta["producer"]
                if next_role == producer_role
                else meta["leader"]
            )
            arrow = "⬆️" if is_promotion else "⬇️"
            await message.answer(
                f"{arrow} {mention(target_id, target_name)}: {previous_name} → {next_name}.",
                parse_mode="HTML",
            )
            return
        changed = await database.change_basement_rank(
            message.chat.id, target_id, 1 if is_promotion else -1
        )
        if changed is None:
            await message.answer("Этот участник не состоит в Подвалграде.")
            return
        previous, updated = changed
        target_mention = mention(target_id, target_name)
        if previous == updated:
            await message.answer(
                f"⚠️ {target_mention} уже {basement_rank_name(updated)}.",
                parse_mode="HTML",
            )
            return
        arrow = "⬆️" if is_promotion else "⬇️"
        await message.answer(
            f"{arrow} {target_mention}: {basement_rank_name(previous)} → "
            f"{basement_rank_name(updated)}.",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(PIROJOK_BASEMENT_ESCAPE_RE))
    async def pirojok_basement_escape(message: Message) -> None:
        sender = message.from_user
        if message.chat.type not in GROUP_TYPES or not is_pirojok(sender):
            return
        result, _ = await database.escape_basement_with_cooldown(
            message.chat.id, sender.id
        )
        if result != "escaped":
            return
        await message.answer(
            f"{mention(sender.id, display_name(sender))} укатился из Подвалграда, "
            "но я уверен скоро туда вернётся",
            parse_mode="HTML",
        )

    @router.message(text_or_caption_regexp(CHAT_RE))
    async def sleepy_chat(message: Message, bot: Bot) -> None:
        if not is_mister_sleepy(message.from_user):
            return
        payload = command_payload(message_content(message))
        if kargassia_chat_id is None:
            await message.answer("Не задан KARGASSIA_CHAT_ID.")
            return
        source_message: Message | None = None
        replace_caption = False
        if message.caption is not None and message_has_relayable_media(message):
            source_message = message
            replace_caption = True
        elif (
            message.reply_to_message
            and message_has_relayable_media(message.reply_to_message)
        ):
            source_message = message.reply_to_message
            replace_caption = bool(payload and media_accepts_caption(source_message))
        if not payload and source_message is None:
            await message.answer("Напиши текст после /чат или приложи медиа.")
            return
        try:
            if source_message is not None:
                copy_arguments = {
                    "chat_id": kargassia_chat_id,
                    "from_chat_id": source_message.chat.id,
                    "message_id": source_message.message_id,
                }
                if replace_caption:
                    copy_arguments["caption"] = payload
                await bot.copy_message(**copy_arguments)
                if payload and not replace_caption:
                    await bot.send_message(kargassia_chat_id, payload)
            else:
                await bot.send_message(kargassia_chat_id, payload)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await message.answer(
                f"Не получилось отправить сообщение в Каргассию: "
                f"{html.escape(str(error))}"
            )

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
        sender_rank = await basement_actor_rank(
            database, message.chat.id, message.from_user
        )
        if message.chat.type not in GROUP_TYPES or sender_rank is None or sender_rank < 2:
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
        if await stored_sleepy_attack_is_blocked(
            database, message.chat.id, message.from_user, target_id
        ):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
        if await target_is_immune(database, message.chat.id, target_id):
            await message.answer(IMMUNITY_TEXT)
            return
        target_rank = await database.basement_member_rank(message.chat.id, target_id)
        if target_rank is None:
            await message.answer("Этот участник не состоит в Подвалграде.")
            return
        if sender_rank < target_rank:
            await message.answer(
                f"⛔ Нельзя дать леща {mention(target_id, target_name)}: "
                "у него ранг выше.",
                parse_mode="HTML",
            )
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
            if is_cheto_neveru(message.from_user):
                await message.answer(
                    "👋 Властитель Подвалграда дал леща бедному Гнида-боту, за что..."
                )
            else:
                await message.answer("👋 Гнида-бот получил леща и ничего не понял.")
            return
        if is_cheto_neveru(message.from_user):
            text = (
                f"👑 Властитель Подвалграда дал леща "
                f"{mention(target_id, target_name)}, работай раб."
            )
        else:
            text = (
                f"👋 {mention(message.from_user.id, display_name(message.from_user))} "
                f"дал леща {mention(target_id, target_name)}. Работай в шахтах."
            )
        await message.answer(text, parse_mode="HTML")

    @router.message(text_or_caption_regexp(TRAIN_RE))
    async def basement_train(message: Message) -> None:
        sender_rank = await basement_actor_rank(
            database, message.chat.id, message.from_user
        )
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if (
            message.chat.type not in GROUP_TYPES
            or sender_rank is None
            or sender_rank < 3
            or not target
            or target.is_bot
        ):
            return
        if sleepy_attack_is_blocked(message.from_user, target.username):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return
        target_rank = await database.basement_member_rank(message.chat.id, target.id)
        if target_rank is not None and sender_rank < target_rank:
            await message.answer(
                f"⛔ Нельзя отправить {mention(target.id, display_name(target))} в паровозик: "
                "у него ранг выше.",
                parse_mode="HTML",
            )
            return
        target_mention = mention(target.id, display_name(target))
        await message.answer(
            random.choice(
                (
                    f"🚂 {target_mention} отпоровозили, советую сходить к проктологу.",
                    f"🚃 Этого чела {target_mention} поровозили всю ночь и весь день.",
                    f"🫣 {target_mention}, не бойся, больно только в первый раз.",
                    f"🍞 {target_mention} принял роль хлеба.",
                )
            ),
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
        if await stored_sleepy_attack_is_blocked(
            database, message.chat.id, message.from_user, target_id
        ):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
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

    @router.message(text_or_caption_regexp(DEATH_NOTE_RE))
    async def write_death_note(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        if not message.from_user:
            return
        text = message_content(message)
        match = DEATH_NOTE_RE.match(text)
        if not match:
            return
        target = await resolve_target(message, database, text[match.end() :].strip())
        if not target:
            return
        target_id, target_name, _ = target
        if target_id == message.from_user.id:
            await message.answer("На себя эту команду применить нельзя.")
            return
        if await stored_sleepy_attack_is_blocked(
            database, message.chat.id, message.from_user, target_id
        ):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
        if await target_is_immune(database, message.chat.id, target_id):
            await message.answer(IMMUNITY_TEXT)
            return
        entry_id = await database.create_death_note_entry(
            message.chat.id,
            target_id,
            message.from_user.id,
            utc_timestamp() + DEATH_NOTE_SECONDS,
        )
        if entry_id is None:
            await message.answer("Это имя уже записано в тетрадь.")
            return
        sent = await message.answer(
            death_note_countdown_text(target_name, DEATH_NOTE_SECONDS),
            parse_mode="HTML",
        )
        await database.set_death_note_message(entry_id, sent.message_id)
        schedule_death_note(entry_id, bot)

    @router.message(text_or_caption_regexp(DEATH_NOTE_ERASE_RE))
    async def erase_death_note(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        text = message_content(message)
        match = DEATH_NOTE_ERASE_RE.match(text)
        if not match:
            return
        replied = message.reply_to_message
        if (
            replied
            and replied.from_user
            and replied.from_user.id == bot.id
            and getattr(replied, "message_id", None)
        ):
            entry = await database.cancel_death_note_by_message(
                message.chat.id, replied.message_id
            )
        else:
            target = await resolve_target(message, database, text[match.end() :].strip())
            if not target:
                return
            entry = await database.cancel_death_note_by_target(
                message.chat.id, target[0]
            )
        if not entry:
            await message.answer("В тетради такого имени нет.")
            return
        name = html.escape(await death_note_name(entry))
        result_text = f"🍎 Имя {name} стёрто из тетради. Сегодня ему повезло."
        if not await edit_death_note(entry, bot, result_text):
            await message.answer(result_text, parse_mode="HTML")

    @router.message(text_or_caption_regexp(PISKA_MUTE_RE))
    async def piska_mute(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not await ensure_admin(message, bot):
            return
        replied = message.reply_to_message
        target = replied.from_user if replied and not replied.sender_chat else None
        if not target or target.is_bot or not message.from_user:
            return
        await database.upsert_user(
            message.chat.id,
            target.id,
            target.username,
            display_name(target),
            touch=False,
        )
        if sleepy_attack_is_blocked(message.from_user, target.username):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
        if user_is_immune(target):
            await message.answer(IMMUNITY_TEXT)
            return

        until = datetime.now(timezone.utc) + timedelta(seconds=PISKA_MUTE_SECONDS)
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
                "засунули письку в рот",
                message.from_user.id,
                duration_seconds=PISKA_MUTE_SECONDS,
                active_until=int(until.timestamp()),
            )
            await message.answer(
                f"{mention(target.id, display_name(target))} засунули письку в рот, "
                "чтобы прийти в себя ему понадобятся сутки 🤭",
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
        if await stored_sleepy_attack_is_blocked(
            database, message.chat.id, message.from_user, target_id
        ):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
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
            recipient_user = replied.from_user
            slave_token, extra = split_first(payload)
            if not slave_token or extra:
                await message.answer(
                    "Формат ответом: /передать @раб — ответьте на сообщение нового владельца."
                )
                return
            if recipient_user.is_bot:
                await message.answer("Нельзя передать раба боту.")
                return
            await database.upsert_user(
                message.chat.id,
                recipient_user.id,
                recipient_user.username,
                display_name(recipient_user),
                touch=False,
            )
            slave = await resolve_user_token(message, database, slave_token)
            if not slave:
                return
            slave_id, slave_name = slave
            recipient = (recipient_user.id, display_name(recipient_user))
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
            if recipient_token.casefold() in {"мне", "себе"}:
                recipient = (message.from_user.id, display_name(message.from_user))
            else:
                recipient = await resolve_user_token(message, database, recipient_token)
            if not recipient:
                return
        recipient_id, recipient_name = recipient
        if await stored_sleepy_attack_is_blocked(
            database, message.chat.id, message.from_user, slave_id
        ):
            await message.answer(SLEEPY_PROTECTION_TEXT)
            return
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

    @router.message(text_or_caption_regexp(SLAVE_PRIORITY_RE))
    async def set_slave_priority(message: Message) -> None:
        if not message.from_user:
            return
        text = message_content(message)
        match = SLAVE_PRIORITY_RE.match(text)
        if not match:
            return
        enabled = match.group(1).casefold() == "приоритет"
        if message.chat.type == "private":
            token, extra = split_first(text[match.end() :].strip())
            if not token or extra:
                await message.answer("В личке: /приоритет @раб или /снять приоритет @раб.")
                return
            candidates = await database.resolve_users_globally(token)
            updated = 0
            unchanged = 0
            for candidate in candidates:
                chat_id = int(candidate["chat_id"])
                slave_id = int(candidate["user_id"])
                ownership = await database.get_owner(chat_id, slave_id)
                if not ownership or int(ownership["owner_id"]) != message.from_user.id:
                    continue
                result = await database.set_slave_priority(
                    chat_id, message.from_user.id, slave_id, enabled
                )
                if result == "updated":
                    updated += 1
                elif result == "unchanged":
                    unchanged += 1
            if updated:
                state = "выставлен" if enabled else "снят"
                await message.answer(f"Приоритет {state} в чатах: {updated}.")
            elif unchanged:
                await message.answer("Приоритет уже установлен." if enabled else "Приоритет уже снят.")
            else:
                await message.answer("Этот участник не ваш раб или бот ещё не видел его в чате.")
            return
        if message.chat.type not in GROUP_TYPES:
            return
        target = await resolve_target(message, database, text[match.end() :].strip())
        if not target:
            return
        target_id, target_name, _ = target
        result = await database.set_slave_priority(
            message.chat.id, message.from_user.id, target_id, enabled
        )
        if result == "not_owned":
            await message.answer("Этот участник не ваш раб.")
        elif result == "unchanged":
            await message.answer("Приоритет уже установлен." if enabled else "Приоритет уже снят.")
        elif enabled:
            await message.answer(
                f"⭐ {mention(target_id, target_name)} теперь будет передаваться последним.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"Приоритет {mention(target_id, target_name)} снят.", parse_mode="HTML"
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

    @router.inline_query()
    async def inline_challenge_query(inline_query: InlineQuery) -> None:
        if kargassia_chat_id is not None:
            await database.upsert_user(
                kargassia_chat_id,
                inline_query.from_user.id,
                inline_query.from_user.username,
                display_name(inline_query.from_user),
                touch=False,
            )
        creator_name = display_name(inline_query.from_user)
        results: list[InlineQueryResultArticle] = []
        for game_type in inline_game_types(inline_query.query):
            title, icon = INLINE_GAME_OPTIONS[game_type]
            game_label = (
                "случайную мини-игру" if game_type == "random" else title
            )
            results.append(
                InlineQueryResultArticle(
                    id=f"{inline_query.from_user.id}:{game_type}",
                    title=title,
                    description="Отправить вызов в текущий чат",
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"{icon} {creator_name} предлагает сыграть в {game_label}.\n"
                            "Соперник, нажми «Принять вызов»."
                        )
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Принять вызов",
                                    callback_data=(
                                        f"ia:{inline_query.from_user.id}:{game_type}"
                                    ),
                                )
                            ]
                        ]
                    ),
                )
            )
        await inline_query.answer(results, cache_time=0, is_personal=True)

    @router.callback_query(F.data.startswith("ia:"))
    async def accept_inline_challenge(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.inline_message_id:
            await callback.answer("Этот вызов нужно отправить через inline-режим.")
            return
        try:
            _, raw_challenger_id, requested_game = callback.data.split(":", 2)
            challenger_id = int(raw_challenger_id)
        except (TypeError, ValueError):
            await callback.answer("Некорректный вызов.", show_alert=True)
            return
        if requested_game not in INLINE_GAME_OPTIONS:
            await callback.answer("Неизвестная игра.", show_alert=True)
            return
        if callback.from_user.id == challenger_id:
            await callback.answer("Нельзя принять собственный вызов.", show_alert=True)
            return
        if kargassia_chat_id is None:
            await callback.answer(
                "Не задан KARGASSIA_CHAT_ID.", show_alert=True
            )
            return
        challenger_present, opponent_present = await asyncio.gather(
            is_chat_participant(bot, kargassia_chat_id, challenger_id),
            is_chat_participant(bot, kargassia_chat_id, callback.from_user.id),
        )
        if not challenger_present or not opponent_present:
            await callback.answer(
                "Оба игрока должны состоять в Каргассии.", show_alert=True
            )
            return
        try:
            challenger_member = await bot.get_chat_member(
                kargassia_chat_id, challenger_id
            )
            challenger_user = challenger_member.user
        except (TelegramBadRequest, TelegramForbiddenError):
            await callback.answer(
                "Не удалось проверить создателя вызова.", show_alert=True
            )
            return
        opponent = callback.from_user
        await asyncio.gather(
            database.upsert_user(
                kargassia_chat_id,
                challenger_user.id,
                challenger_user.username,
                display_name(challenger_user),
                touch=False,
            ),
            database.upsert_user(
                kargassia_chat_id,
                opponent.id,
                opponent.username,
                display_name(opponent),
                touch=False,
            ),
        )
        if sleepy_attack_is_blocked(challenger_user, opponent.username):
            await callback.answer(SLEEPY_PROTECTION_TEXT, show_alert=True)
            return
        if user_is_immune(opponent):
            await callback.answer(IMMUNITY_TEXT, show_alert=True)
            return
        block_reason = await slavery_challenge_block_reason(
            database, kargassia_chat_id, challenger_id, opponent.id
        )
        if block_reason:
            await callback.answer(
                block_reason,
                show_alert=True,
            )
            return
        owner = await database.get_owner(kargassia_chat_id, challenger_id)
        forced = bool(
            owner
            and int(owner["owner_id"]) == opponent.id
            and await database.can_force_owner(
                kargassia_chat_id, challenger_id, opponent.id
            )
        )
        game_type = (
            random.choice(("rps", "blackjack", "checkers"))
            if requested_game == "random"
            else requested_game
        )
        challenge_id = await database.create_challenge(
            kargassia_chat_id,
            challenger_id,
            opponent.id,
            forced=forced,
            game_type=game_type,
        )
        if challenge_id is None:
            await callback.answer(
                "У одного из игроков уже есть активный вызов.", show_alert=True
            )
            return
        await database.set_challenge_inline_message(
            challenge_id, callback.inline_message_id
        )
        challenge = await database.get_challenge(challenge_id)
        if game_type == "blackjack":
            game = await database.get_blackjack_game(challenge_id)
            text = await blackjack_text(database, challenge, game)
            keyboard = blackjack_keyboard(challenge_id)
        elif game_type == "checkers":
            game = await database.get_checkers_game(challenge_id)
            text = await checkers_text(database, challenge, game)
            keyboard = checkers_keyboard(challenge_id, challenge, game)
        else:
            text = await challenge_text(database, challenge)
            keyboard = challenge_keyboard(challenge_id)
        if not await edit_challenge(challenge, bot, text, keyboard):
            await database.finish_challenge(challenge_id, "failed")
            await callback.answer(
                "Не удалось открыть игру в этом сообщении.", show_alert=True
            )
            return
        schedule_challenge(challenge_id, bot)
        await callback.answer("Вызов принят")

    @router.message(
        text_or_caption_regexp(CHALLENGE_RE) | text_or_caption_regexp(GAME_RE)
    )
    async def challenge(message: Message, bot: Bot) -> None:
        if message.chat.type not in GROUP_TYPES or not message.from_user:
            return
        content = message_content(message)
        game_match = GAME_RE.match(content)
        match = game_match or CHALLENGE_RE.match(content)
        friendly = game_match is not None
        requested_game = match.group(1).casefold() if match and match.group(1) else None
        if requested_game == "кнб":
            game_type = "rps"
        elif requested_game in {"блекджек", "блэкджек"}:
            game_type = "blackjack"
        elif requested_game == "шашки":
            game_type = "checkers"
        else:
            game_type = random.choice(("rps", "blackjack", "checkers"))
        if (
            message.sender_chat
            or not message.reply_to_message
            or message.reply_to_message.sender_chat
            or not message.reply_to_message.from_user
        ):
            command_name = "Игру" if friendly else "Вызов"
            await message.answer(
                f"Отправьте «{command_name}» в ответ на сообщение соперника."
            )
            return
        opponent = message.reply_to_message.from_user
        if opponent.is_bot or opponent.id == message.from_user.id:
            await message.answer("Нужен другой живой соперник.")
            return
        if not friendly and sleepy_attack_is_blocked(message.from_user, opponent.username):
            await message.answer(SLEEPY_PROTECTION_TEXT)
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
        if not friendly:
            block_reason = await slavery_challenge_block_reason(
                database, message.chat.id, message.from_user.id, opponent.id
            )
            if block_reason:
                await message.answer(block_reason)
                return
        owner = await database.get_owner(message.chat.id, message.from_user.id)
        forced = bool(
            not friendly
            and owner
            and int(owner["owner_id"]) == opponent.id
            and await database.can_force_owner(
                message.chat.id, message.from_user.id, opponent.id
            )
        )
        opponent_newcomer = bool(
            not friendly and await database.is_vulnerable(message.chat.id, opponent.id)
        )
        challenge_id = await database.create_challenge(
            message.chat.id,
            message.from_user.id,
            opponent.id,
            forced=forced,
            opponent_newcomer=opponent_newcomer,
            game_type=game_type,
            friendly=friendly,
            awaiting_acceptance=True,
        )
        if challenge_id is None:
            await message.answer("У одного из участников уже есть активный вызов.")
            return
        row = await database.get_challenge(challenge_id)
        prefix = {"rps": "rps", "blackjack": "bj", "checkers": "ck"}[game_type]
        body = await challenge_offer_text(database, row)
        keyboard = challenge_offer_keyboard(challenge_id, prefix)
        sent = await message.answer(
            body,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await database.set_challenge_message(challenge_id, sent.message_id)
        schedule_challenge(challenge_id, bot)

    @router.callback_query(F.data.startswith("rps:"))
    async def rps_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data:
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
            or challenge["status"] not in {"pending", "active"}
            or challenge["game_type"] != "rps"
        ):
            await callback.answer("Этот вызов уже завершён.", show_alert=True)
            return
        if await target_is_immune(
            database, int(challenge["chat_id"]), int(challenge["opponent_id"])
        ):
            if await database.finish_challenge(challenge_id, "immune"):
                await edit_challenge(challenge, bot, IMMUNITY_TEXT)
            await callback.answer()
            return
        if callback.from_user.id not in (challenge["challenger_id"], challenge["opponent_id"]):
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        if challenge["status"] == "pending":
            if choice == "accept":
                await accept_pending_challenge(challenge, callback, bot)
            elif choice == "refuse":
                await refuse_pending_challenge(challenge, callback, bot)
            elif choice == "cancel":
                await cancel_pending_challenge(challenge, callback, bot)
            else:
                await callback.answer("Сначала примите вызов.", show_alert=True)
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
                await edit_challenge(
                    challenge,
                    bot,
                    f"🚫 {html.escape(display_name(callback.from_user))} отказался от вызова.",
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
            await edit_challenge(
                challenge,
                bot,
                await challenge_text(database, challenge),
                reply_markup=challenge_keyboard(challenge_id),
            )
            return
        if not await database.finish_challenge(challenge_id):
            return
        await publish_played_result(challenge, bot)

    @router.callback_query(F.data.startswith("bj:"))
    async def blackjack_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data:
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
            or challenge["status"] not in {"pending", "active"}
            or challenge["game_type"] != "blackjack"
        ):
            await callback.answer("Этот вызов уже завершён.", show_alert=True)
            return
        if await target_is_immune(
            database, int(challenge["chat_id"]), int(challenge["opponent_id"])
        ):
            if await database.finish_challenge(challenge_id, "immune"):
                await edit_challenge(challenge, bot, IMMUNITY_TEXT)
            await callback.answer()
            return
        participant_ids = {
            int(challenge["challenger_id"]),
            int(challenge["opponent_id"]),
        }
        if callback.from_user.id not in participant_ids:
            await callback.answer("Это не ваш поединок.", show_alert=True)
            return
        if challenge["status"] == "pending":
            if action == "accept":
                await accept_pending_challenge(challenge, callback, bot)
            elif action == "refuse":
                await refuse_pending_challenge(challenge, callback, bot)
            elif action == "cancel":
                await cancel_pending_challenge(challenge, callback, bot)
            else:
                await callback.answer("Сначала примите вызов.", show_alert=True)
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
                await edit_challenge(
                    challenge,
                    bot,
                    f"🚫 {html.escape(display_name(callback.from_user))} "
                    "отказался от вызова.",
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
            await edit_challenge(
                updated_challenge,
                bot,
                await blackjack_text(database, updated_challenge, updated_game),
                reply_markup=blackjack_keyboard(challenge_id),
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

    @router.callback_query(F.data.startswith("ck:"))
    async def checkers_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data:
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
            or challenge["status"] not in {"pending", "active"}
            or challenge["game_type"] != "checkers"
        ):
            await callback.answer("Эта партия уже завершена.", show_alert=True)
            return
        if await target_is_immune(
            database, int(challenge["chat_id"]), int(challenge["opponent_id"])
        ):
            if await database.finish_challenge(challenge_id, "immune"):
                await edit_challenge(challenge, bot, IMMUNITY_TEXT)
            await callback.answer()
            return
        participant_ids = {
            int(challenge["challenger_id"]),
            int(challenge["opponent_id"]),
        }
        if callback.from_user.id not in participant_ids:
            await callback.answer("Это не ваша партия.", show_alert=True)
            return
        if challenge["status"] == "pending":
            if action == "accept":
                await accept_pending_challenge(challenge, callback, bot)
            elif action == "refuse":
                await refuse_pending_challenge(challenge, callback, bot)
            elif action == "cancel":
                await cancel_pending_challenge(challenge, callback, bot)
            else:
                await callback.answer("Сначала примите вызов.", show_alert=True)
            return
        if utc_timestamp() >= int(challenge["deadline"]):
            await callback.answer("Время на ход уже истекло.", show_alert=True)
            return
        game = await database.get_checkers_game(challenge_id)
        if not game:
            await callback.answer("Партия не найдена.", show_alert=True)
            return

        if action == "refuse":
            if int(game["move_count"]) > 0:
                await callback.answer(
                    "После первого хода можно только сдаться.", show_alert=True
                )
                return
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
                await edit_challenge(
                    challenge,
                    bot,
                    f"🚫 {html.escape(display_name(callback.from_user))} "
                    "отказался от вызова.",
                )
            await callback.answer()
            return

        if action == "resign":
            if not await database.finish_challenge(challenge_id):
                await callback.answer("Партия уже завершена.", show_alert=True)
                return
            loser_id = callback.from_user.id
            winner_id = next(user_id for user_id in participant_ids if user_id != loser_id)
            await database.record_challenge_result(challenge_id, winner_id)
            await callback.answer("Вы сдались")
            await publish_game_win(
                challenge,
                bot,
                winner_id,
                loser_id,
                f"🏳 {html.escape(display_name(callback.from_user))} сдался в шашках.",
            )
            return

        if action == "noop":
            await callback.answer()
            return

        try:
            square = int(action)
        except ValueError:
            await callback.answer("Неизвестный ход.", show_alert=True)
            return
        result = await database.checkers_click(
            challenge_id, callback.from_user.id, square
        )
        if result["status"] == "not_turn":
            await callback.answer("Сейчас ход соперника.", show_alert=True)
            return
        if result["status"] == "not_participant":
            await callback.answer("Это не ваша партия.", show_alert=True)
            return
        if result["status"] in {"inactive", "invalid"}:
            await callback.answer("Эта клетка сейчас недоступна.", show_alert=True)
            return
        if result["status"] == "finished":
            await callback.answer("Партия завершена")
            await publish_game_win(
                challenge,
                bot,
                int(result["winner_id"]),
                int(result["loser_id"]),
                f"ШАШКИ!!!\nИтог: {html.escape(str(result['reason']))}.",
            )
            return

        if result["status"] == "selected":
            answer = "Шашка выбрана" if result["selected_square"] is not None else "Выбор снят"
        elif result.get("continuation"):
            answer = "Продолжайте взятие"
        else:
            answer = "Ход выполнен"
        await callback.answer(answer)
        await render_checkers(challenge_id, bot)

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

    def joke_available(
        chat_id: int, command: str, cooldown_seconds: int = JOKE_COOLDOWN_SECONDS
    ) -> bool:
        now = time.monotonic()
        key = (chat_id, command)
        previous = joke_cooldowns.get(key, 0.0)
        if now - previous < cooldown_seconds:
            return False
        joke_cooldowns[key] = now
        return True

    @router.message(text_or_caption_regexp(RANDOM_PHRASE_RE))
    async def random_phrase(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not joke_available(
            message.chat.id, "random_phrase", RANDOM_PHRASE_COOLDOWN_SECONDS
        ):
            return
        phrase = await database.take_random_phrase(
            message.chat.id, RANDOM_CHAT_PHRASES
        )
        await message.answer(phrase)

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
        stolen_now = art_theft_count(message_content(message))
        count = await database.increment_counter(
            message.chat.id, "stolen_art", stolen_now
        )
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

    @router.message(text_or_caption_regexp(LIES_RE))
    async def lies(message: Message) -> None:
        if message.chat.type not in GROUP_TYPES or not joke_available(
            message.chat.id, "lies"
        ):
            return
        await message.answer(
            random.choice(
                (
                    "Конечно",
                    "Как дышит",
                    "Не",
                    "Возможно",
                    "Не знаю",
                    "Не скажу",
                    "Пиздит",
                    "Ну вообще это правда",
                )
            )
        )

    @router.message(
        text_or_caption_regexp(GNIDA_REPLY_INSULT_RE)
        | text_or_caption_regexp(GNIDA_DIRECT_INSULT_RE)
    )
    async def gnida_insult_video(message: Message, bot: Bot) -> None:
        content = message_content(message)
        if message.chat.type not in GROUP_TYPES:
            return
        if not (
            GNIDA_DIRECT_INSULT_RE.match(content)
            or (
                is_reply_to_bot(message, bot)
                and GNIDA_REPLY_INSULT_RE.match(content)
            )
        ):
            return
        if not joke_available(message.chat.id, "gnida_insult_video"):
            return
        try:
            await message.answer_video(FSInputFile(GNIDA_VIDEO_PATH))
        except (FileNotFoundError, TelegramBadRequest, TelegramForbiddenError) as error:
            logging.getLogger(__name__).warning("Could not send Gnida video: %s", error)

    @router.message(
        text_or_caption_regexp(GNIDA_REPLY_MEOW_RE)
        | text_or_caption_regexp(GNIDA_DIRECT_MEOW_RE)
    )
    async def gnida_meow_audio(message: Message, bot: Bot) -> None:
        content = message_content(message)
        if message.chat.type not in GROUP_TYPES:
            return
        if not (
            GNIDA_DIRECT_MEOW_RE.match(content)
            or (
                is_reply_to_bot(message, bot)
                and GNIDA_REPLY_MEOW_RE.match(content)
            )
        ):
            return
        if not joke_available(message.chat.id, "gnida_meow_audio"):
            return
        try:
            await message.answer_voice(FSInputFile(MEOW_AUDIO_PATH))
        except (FileNotFoundError, TelegramAPIError) as error:
            logging.getLogger(__name__).warning("Could not send meow audio: %s", error)

    @router.message(text_or_caption_regexp(BASEMENT_RE))
    async def basement(message: Message, bot: Bot) -> None:
        sender = message.from_user
        replied_user = message.reply_to_message.from_user if message.reply_to_message else None
        sender_rank = await basement_actor_rank(database, message.chat.id, sender)
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or sender_rank is None
            or sender_rank < BASEMENT_DEPUTY_RANK
            or not replied_user
        ):
            return
        if replied_user.is_bot and replied_user.id != bot.id:
            return
        if sleepy_attack_is_blocked(sender, replied_user.username):
            await message.answer(SLEEPY_PROTECTION_TEXT)
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
                f"⛏️ {mention(replied_user.id, display_name(replied_user))} забран в Подвалград, "
                "продуктивной работы в шахтах.",
                parse_mode="HTML",
            )

    @router.message(text_or_caption_regexp(SAMOVAR_RE, mode="search"))
    async def samovar(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and joke_available(message.chat.id, "samovar"):
            await message.answer("Зовите Кита")

    @router.message(text_or_caption_regexp(PISYA_RE))
    async def pisya(message: Message) -> None:
        if message.chat.type in GROUP_TYPES:
            await message.answer("попа")

    @router.message(text_or_caption_regexp(POPA_RE))
    async def popa(message: Message) -> None:
        if message.chat.type in GROUP_TYPES and message.from_user and not message.from_user.is_bot:
            await message.answer("пися")

    @router.message()
    async def run_custom_command(message: Message, bot: Bot) -> None:
        """Final catch-all: execute an owner-defined natural-language command."""
        sender = message.from_user
        content = message_content(message)
        if (
            message.chat.type not in GROUP_TYPES
            or not sender
            or sender.is_bot
            or not content
        ):
            return
        trigger_key = normalize_custom_trigger(content)
        if not trigger_key:
            return
        command = await database.get_custom_command(message.chat.id, trigger_key)
        if command is None:
            return
        exclusive_user_id = command["exclusive_user_id"]
        if exclusive_user_id is not None and sender.id != int(exclusive_user_id):
            await message.answer("Эта команда создана эксклюзивно для другого пользователя.")
            return

        success = random.randint(1, 100) <= int(command["success_chance"])
        field = "success_responses" if success else "failure_responses"
        responses = command_responses(command, field)
        if not responses:
            responses = command_responses(command, "success_responses")
        if not responses:
            logging.getLogger(__name__).warning(
                "Custom command %s has no usable responses", command["id"]
            )
            return
        template = random.choice(responses)
        placeholders = template_placeholders(template)
        recent = await database.recent_users(message.chat.id, 50)
        candidates = [row for row in recent if int(row["user_id"]) != sender.id]

        async def choose_present_user(excluded_id: int | None = None):
            shuffled = [
                row for row in candidates if int(row["user_id"]) != excluded_id
            ]
            random.shuffle(shuffled)
            for row in shuffled:
                if await is_chat_participant(bot, message.chat.id, int(row["user_id"])):
                    return row
            return None

        target: object | None = None
        replied = message.reply_to_message
        if replied and not replied.sender_chat and replied.from_user:
            replied_user = replied.from_user
            await database.upsert_user(
                message.chat.id,
                replied_user.id,
                replied_user.username,
                display_name(replied_user),
                touch=False,
            )
            target = {
                "user_id": replied_user.id,
                "display_name": display_name(replied_user),
            }
        elif "target" in placeholders:
            target = await choose_present_user()

        if "target" in placeholders and target is None:
            await message.answer(
                "Не удалось выбрать цель: ответь командой на сообщение или дождись активности участников."
            )
            return

        target_id = int(target["user_id"]) if target is not None else None
        random_target = (
            await choose_present_user(target_id)
            if "random" in placeholders
            else None
        )
        if "random" in placeholders and random_target is None:
            await message.answer(
                "Не удалось выбрать случайного участника: среди последних 50 пока никого нет."
            )
            return

        cost = int(command["cost"])
        if not await database.spend_francs(message.chat.id, sender.id, cost):
            balance = await database.franc_balance(message.chat.id, sender.id)
            await message.answer(
                f"Недостаточно франков: нужно {cost} ₣, на балансе {balance} ₣."
            )
            return

        actor_mention = mention(sender.id, display_name(sender))
        target_mention = (
            mention(int(target["user_id"]), str(target["display_name"]))
            if target is not None
            else None
        )
        random_mention = (
            mention(int(random_target["user_id"]), str(random_target["display_name"]))
            if random_target is not None
            else None
        )
        await message.answer(
            render_custom_template(
                template,
                actor_mention=actor_mention,
                target_mention=target_mention,
                random_mention=random_mention,
            ),
            parse_mode="HTML",
        )

    return router
