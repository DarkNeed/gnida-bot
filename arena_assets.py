"""Keep the Mini App stylesheet and client on the same content revision."""

import hashlib
from pathlib import Path


def render_arena_index(root: Path) -> str:
    revision = hashlib.sha256()
    for name in ("style.css", "battle-client"):
        revision.update((root / name).read_bytes())
    version = revision.hexdigest()[:16]
    return (
        (root / "index.html")
        .read_text(encoding="utf-8")
        .replace('href="/static/style.css"', f'href="/static/style.css?v={version}"')
        .replace('src="/static/client.js"', f'src="/static/client.js?v={version}"')
    )
