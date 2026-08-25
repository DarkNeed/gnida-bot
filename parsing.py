from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Duration:
    seconds: int
    label: str


_UNITS = {
    "s": 1,
    "sec": 1,
    "сек": 1,
    "секунда": 1,
    "секунды": 1,
    "секунд": 1,
    "m": 60,
    "min": 60,
    "мин": 60,
    "минута": 60,
    "минуты": 60,
    "минут": 60,
    "h": 3600,
    "hr": 3600,
    "ч": 3600,
    "час": 3600,
    "часа": 3600,
    "часов": 3600,
    "d": 86400,
    "day": 86400,
    "д": 86400,
    "день": 86400,
    "дня": 86400,
    "дней": 86400,
    "сутки": 86400,
    "суток": 86400,
    "w": 604800,
    "week": 604800,
    "н": 604800,
    "нед": 604800,
    "неделя": 604800,
    "недели": 604800,
    "недель": 604800,
}

_DURATION_RE = re.compile(r"^(\d+)\s*([a-zа-яё]+)$", re.IGNORECASE)


def parse_duration(value: str) -> Duration | None:
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    multiplier = _UNITS.get(match.group(2).casefold())
    if multiplier is None or amount < 1:
        return None
    seconds = amount * multiplier
    # Telegram treats restrictions shorter than 30 seconds or longer than 366 days as permanent.
    if seconds < 30 or seconds > 366 * 86400:
        return None
    return Duration(seconds=seconds, label=value.strip())


def parse_duration_prefix(value: str) -> tuple[Duration | None, str]:
    """Parse a compact or two-word duration from the beginning of a string."""
    first, remainder = split_first(value)
    if not first:
        return None, ""
    compact = parse_duration(first)
    if compact:
        return compact, remainder
    if first.casefold() == "сутки":
        return parse_duration("1 сутки"), remainder
    if first.isdigit():
        unit, tail = split_first(remainder)
        spaced = parse_duration(f"{first} {unit}") if unit else None
        if spaced:
            return spaced, tail
    return None, value.strip()


def command_payload(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def split_first(value: str) -> tuple[str, str]:
    parts = value.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1].strip() if len(parts) == 2 else ""


def looks_like_user_token(value: str) -> bool:
    return value.startswith("@") or value.lstrip("-").isdigit()


def format_duration(seconds: int) -> str:
    units = ((604800, "нед."), (86400, "дн."), (3600, "ч."), (60, "мин."), (1, "сек."))
    for size, label in units:
        if seconds % size == 0:
            return f"{seconds // size} {label}"
    return f"{seconds} сек."
