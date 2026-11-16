"""Bounded cache of validated custom definitions, never of player state.

Keys include the exact stored JSON, so edits, hides, deletes and rolled-back
transactions are visible immediately. Mutable fields are copied on every read.
"""

import json
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

from arena_engine import fighter_class_from_dict, skill_from_dict


@lru_cache(maxsize=128)
def _parsed_class(content_id, definition):
    try:
        payload = json.loads(definition)
        return fighter_class_from_dict(content_id, payload) if isinstance(payload, dict) else None
    except (TypeError, ValueError, KeyError):
        return None


@lru_cache(maxsize=512)
def _parsed_skill(content_id, definition):
    try:
        payload = json.loads(definition)
        if not isinstance(payload, dict) or not payload.get("merchant_available", False):
            return None
        return skill_from_dict(content_id, payload)
    except (TypeError, ValueError, KeyError):
        return None


def custom_class(content_id, definition):
    value = _parsed_class(content_id, definition)
    if value is None:
        return None
    return replace(value, base_stats=dict(value.base_stats), growth=dict(value.growth),
                   passives=deepcopy(value.passives))


def custom_skill(content_id, definition):
    value = _parsed_skill(content_id, definition)
    if value is None:
        return None
    # The validator normalizes effects to flat, scalar-only dictionaries.
    return replace(value, effects=tuple(dict(effect) for effect in value.effects))
