from urllib.parse import quote


def arena_link(username: str, start: str) -> str:
    return f"https://t.me/{username.lstrip('@')}?startapp={quote(start)}"
