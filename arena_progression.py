"""Explicit progression decisions, including choosing to keep the current class."""

from arena_archclasses import branch_options
from arena_rpg import RPG_BRANCHES


def pending_choice(profile):
    level = int(profile["level"])
    resolved = int(profile.get("progression_level", 0))
    if level >= 5 and profile["class_id"] == "ragamuffin" and resolved < 5:
        return 5
    if branch_options(profile["class_id"]):
        if level >= 10 and resolved < 10 and not profile.get("archclass_id"):
            return 10
        if level >= 20 and resolved < 20 and profile['class_id'] not in {v[0] for v in RPG_BRANCHES.values()}:
            return 20
    return 0


def choice_avatar(class_id, archclass_id=""):
    from arena_rpg import RPG_BRANCHES
    if class_id in {'warrior','mage','priest','hunter'} or archclass_id in RPG_BRANCHES:
        # Art is not deployed before the owner's review. Custom sprites take precedence.
        return '/static/assets/ragamuffin.png'
    if archclass_id:
        return "/static/assets/archclasses/" + archclass_id + ".png"
    native = {
        "ragamuffin",
        "cutie",
        "jock",
        "nerd",
        "thumb",
        "index",
        "middle",
        "ring",
        "pinky",
    }
    return (
        "/static/assets/" + (class_id if class_id in native else "ragamuffin") + ".png"
    )
