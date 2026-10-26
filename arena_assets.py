"""Keep the Mini App stylesheet and client on the same content revision."""

import hashlib
from pathlib import Path


def render_arena_index(root: Path) -> str:
    revision = hashlib.sha256()
    for name in ("style.css", "battle-client", "arena-audio"):
        revision.update((root / name).read_bytes())
    for name in ("holdings.css", "holdings-client"):
        if (root / name).exists():
            revision.update((root / name).read_bytes())
    for name in (
        "qte-live",
        "qte-watch",
        "qte-live.css",
        "qte-lab/engine",
        "qte-input",
        "qte-input.css",
        "qte-unique/engine",
        "qte-view",
        "qte-casino-view",
        "qte-casino-chance",
        "qte-casino-chance.css",
        "qte-block/engine",
        "qte-block-view",
        "rp-client",
        "rp.css",
    ):
        if (root / name).exists():
            revision.update((root / name).read_bytes())
    version = revision.hexdigest()[:16]
    return (
        (root / "index.html")
        .read_text(encoding="utf-8")
        .replace('href="/static/style.css"', f'href="/static/style.css?v={version}"')
        .replace('src="/static/client.js"', f'src="/static/client.js?v={version}"')
        .replace('src="/static/audio.js"', f'src="/static/audio.js?v={version}"')
        .replace('src="/rp/client.js"', f'src="/rp/client.js?v={version}"')
        .replace('href="/static/rp.css"', f'href="/static/rp.css?v={version}"')
        .replace('src="/static/holdings.js"', f'src="/static/holdings.js?v={version}"')
        .replace(
            'href="/static/holdings.css"', f'href="/static/holdings.css?v={version}"'
        )
        .replace('src="/static/qte-live.js"', f'src="/static/qte-live.js?v={version}"')
        .replace('src="/static/qte-watch.js"', f'src="/static/qte-watch.js?v={version}"')
        .replace(
            'src="/static/qte-engine.js"', f'src="/static/qte-engine.js?v={version}"'
        )
        .replace('src="/static/qte-view.js"', f'src="/static/qte-view.js?v={version}"')
        .replace('src="/static/qte-casino-view.js"', f'src="/static/qte-casino-view.js?v={version}"')
        .replace('src="/static/qte-casino-chance.js"', f'src="/static/qte-casino-chance.js?v={version}"')
        .replace('href="/static/qte-casino-chance.css"', f'href="/static/qte-casino-chance.css?v={version}"')
        .replace('src="/qte-lab/block/engine.js"', f'src="/qte-lab/block/engine.js?v={version}"')
        .replace('src="/static/qte-block-view.js"', f'src="/static/qte-block-view.js?v={version}"')
        .replace('src="/qte-lab/engine.js"', f'src="/qte-lab/engine.js?v={version}"')
        .replace(
            'href="/static/qte-live.css"', f'href="/static/qte-live.css?v={version}"'
        )
        .replace(
            'src="/static/qte-input.js"', f'src="/static/qte-input.js?v={version}"'
        )
        .replace(
            'href="/static/qte-input.css"', f'href="/static/qte-input.css?v={version}"'
        )
    )
