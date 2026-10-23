from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping


CUSTOM_COMMAND_OWNER_ID = 1980056841
MAX_TRIGGER_LENGTH = 80
MAX_TRIGGER_VARIANTS = 20
MAX_RESPONSE_LENGTH = 1000
MAX_RESPONSES_PER_OUTCOME = 20
MAX_COMMAND_COOLDOWN = 7 * 86400


def parse_command_cooldown(value: str) -> int | None:
    text = value.strip().casefold()
    if text in {'нет','выкл','выключен','-'}:return 0
    if re.fullmatch(r'[0-9]{1,7}',text):
        seconds=int(text)
    else:
        parts=list(re.finditer(r'([0-9]{1,7})\s*(секунд[аыу]?|сек|с|минут[ауы]?|мин|м|час(?:а|ов)?|ч|дней|день|дня|д)',text))
        if not parts or re.sub(r'\s+','',text) != ''.join(re.sub(r'\s+','',p.group()) for p in parts):return None
        seconds=sum(int(p[1]) * (86400 if p[2].startswith('д') else 3600 if p[2].startswith('ч') else 60 if p[2].startswith('м') else 1) for p in parts)
    return seconds if 0<=seconds<=MAX_COMMAND_COOLDOWN else None


def command_cooldown_text(seconds: int) -> str:
    if not seconds:return 'выключен'
    parts=[]
    for size,label in ((86400,'д'),(3600,'ч'),(60,'мин'),(1,'с')):
        count,seconds=divmod(seconds,size)
        if count:parts.append(f'{count} {label}')
    return ' '.join(parts)

_TRAILING_PUNCTUATION_RE = re.compile(r"[!?.…]+$")
_PLACEHOLDER_RE = re.compile(
    r"\{(actor|target|random)\}|"
    r"\((тег1|тег2|тег|рандом(?:ный)?\s+тег)\)",
    re.IGNORECASE,
)


def normalize_custom_trigger(value: str) -> str:
    """Normalize a natural-language command while keeping internal punctuation."""
    normalized = " ".join(value.strip().split())
    normalized = _TRAILING_PUNCTUATION_RE.sub("", normalized).strip()
    return normalized.casefold()


def parse_response_lines(value: str, *, allow_empty: bool = False) -> list[str] | None:
    stripped = value.strip()
    if allow_empty and stripped.casefold() in {"-", "нет", "none"}:
        return []
    # Explicit separators preserve paragraphs; legacy one-line variants still work.
    blocks = bool(re.search(r'(?m)^\s*---\s*$', stripped))
    chunks = re.split(r'(?m)^\s*---\s*$', stripped) if blocks else stripped.splitlines()
    responses = [line.strip() if blocks else line.strip().removeprefix("-").strip() for line in chunks]
    responses = [line for line in responses if line]
    if not responses or len(responses) > MAX_RESPONSES_PER_OUTCOME:
        return None
    if any(len(line) > MAX_RESPONSE_LENGTH for line in responses):
        return None
    return responses


def custom_command_allowed(row: Mapping[str, object], user_id: int) -> bool:
    rules = json.loads(row['access_rules']) if 'access_rules' in row.keys() else {}
    key = str(user_id)
    if key in rules:return rules[key] is True
    if any(rules.values()):return False
    return row['exclusive_user_id'] is None or int(row['exclusive_user_id']) == user_id


async def resolve_command_access(value, resolve_user):
    if value.strip().casefold() in {'нет','-','все','всем'}:return {}
    tokens = re.split(r'[\s,;]+',value.strip())
    if not tokens or len(tokens)>50:raise ValueError('Укажи до 50 пользователей через пробел или запятую.')
    rules = {}
    for token in tokens:
        allowed = not token.startswith('-')
        name = token[1:] if token[:1] in ('-','+') else token
        if not re.fullmatch(r'@[A-Za-z0-9_]{1,32}|[0-9]{1,19}',name):
            raise ValueError('Формат: @user, -@user, Telegram ID или -ID.')
        user = await resolve_user(name) if name.startswith('@') else None
        uid = int(user['user_id']) if user else int(name) if name.isdigit() else 0
        if not 0<uid<2**63:raise ValueError('Не знаю '+name+'. Пришли положительный Telegram ID или дождись сообщения пользователя в чате.')
        rules[str(uid)] = rules.get(str(uid),True) and allowed
    return rules


def valid_command_access(rules):
    return isinstance(rules,dict) and len(rules)<=50 and all(
        isinstance(k,str) and re.fullmatch(r'[1-9][0-9]{0,18}',k) and int(k)<2**63 and type(v) is bool
        for k,v in rules.items())


def command_responses(row: Mapping[str, object], field: str) -> list[str]:
    raw = row[field]
    if not isinstance(raw, str):
        return []
    parsed = json.loads(raw)
    return [str(item) for item in parsed if isinstance(item, str) and item]


def template_placeholders(template: str) -> set[str]:
    placeholders: set[str] = set()
    for match in _PLACEHOLDER_RE.finditer(template):
        token = (match.group(1) or match.group(2) or "").casefold()
        if token in {"actor", "тег1"}:
            placeholders.add("actor")
        elif token in {"target", "тег2", "тег"}:
            placeholders.add("target")
        else:
            placeholders.add("random")
    return placeholders


def render_custom_template(
    template: str,
    *,
    actor_mention: str,
    target_mention: str | None,
    random_mention: str | None,
) -> str:
    """Escape author text and inject only trusted HTML mention fragments."""
    escaped = html.escape(template)

    def replace(match: re.Match[str]) -> str:
        token = (match.group(1) or match.group(2) or "").casefold()
        if token in {"actor", "тег1"}:
            return actor_mention
        if token in {"target", "тег2", "тег"}:
            return target_mention or "неизвестная цель"
        return random_mention or "случайный участник"

    return _PLACEHOLDER_RE.sub(replace, escaped)
