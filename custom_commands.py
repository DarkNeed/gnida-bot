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
    responses = [line.strip().removeprefix("-").strip() for line in stripped.splitlines()]
    responses = [line for line in responses if line]
    if not responses or len(responses) > MAX_RESPONSES_PER_OUTCOME:
        return None
    if any(len(line) > MAX_RESPONSE_LENGTH for line in responses):
        return None
    return responses


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
