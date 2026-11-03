"""Keep the Mini App stylesheet and client on the same content revision."""

import hashlib
from pathlib import Path


def render_arena_index(root: Path) -> str:
    revision = hashlib.sha256()
    for name in ("style.css", "battle-client", "arena-audio"):
        revision.update((root / name).read_bytes())
    for name in ("holdings.css", "holdings-client", "npc-workers.js", "npc-workers.css"):
        if (root / name).exists():
            revision.update((root / name).read_bytes())
    for name in (
        "qte-live",
        "qte-combined.js",
        "raid-intents.js",
        "raid-timeline.js",
        "raid-intents.css",
        "nazarick-qte.js",
        "qte-watch",
        "qte-live.css",
        "qte-lab/engine",
        "qte-input",
        "qte-input.css",
        "qte-unique/engine",
        "qte-view",
        "qte-art.js",
        "guild.js",
        "guild.css",
        "kingdom.js",
        "kingdom-map.js",
        "kingdom-army.js",
        "kingdom-diplomacy.js",
        "kingdom-diplomacy.css",
        "kingdom-budget.js",
        "kingdom-budget.css",
        "kingdom.css",
        "equipment.js",
        "equipment.css",
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
        .replace('<script src="/static/holdings.js"', f'<link rel="stylesheet" href="/static/npc-workers.css?v={version}"><script src="/static/npc-workers.js?v={version}"></script><script src="/static/holdings.js"')
        .replace('href="/static/style.css"', f'href="/static/style.css?v={version}"')
        .replace('src="/static/client.js"', f'src="/static/client.js?v={version}"')
        .replace('src="/static/audio.js"', f'src="/static/audio.js?v={version}"')
        .replace('src="/static/nazarick-qte.js"', f'src="/static/nazarick-qte.js?v={version}"')
        .replace('src="/rp/client.js"', f'src="/rp/client.js?v={version}"')
        .replace('href="/static/rp.css"', f'href="/static/rp.css?v={version}"')
        .replace('src="/static/holdings.js"', f'src="/static/holdings.js?v={version}"')
        .replace(
            'href="/static/holdings.css"', f'href="/static/holdings.css?v={version}"'
        )
        .replace('src="/static/qte-live.js"', f'src="/static/qte-live.js?v={version}"')
        .replace('src="/static/qte-combined.js"', f'src="/static/qte-combined.js?v={version}"')
        .replace('src="/static/raid-intents.js"', f'src="/static/raid-intents.js?v={version}"')
        .replace('src="/static/raid-timeline.js"', f'src="/static/raid-timeline.js?v={version}"')
        .replace('href="/static/raid-intents.css"', f'href="/static/raid-intents.css?v={version}"')
        .replace('src="/static/qte-watch.js"', f'src="/static/qte-watch.js?v={version}"')
        .replace(
            'src="/static/qte-engine.js"', f'src="/static/qte-engine.js?v={version}"'
        )
        .replace('src="/static/qte-view.js"', f'src="/static/qte-view.js?v={version}"')
        .replace('src="/static/qte-art.js"', f'src="/static/qte-art.js?v={version}"')
        .replace('src="/static/guild.js"', f'src="/static/guild.js?v={version}"')
        .replace('href="/static/guild.css"', f'href="/static/guild.css?v={version}"')
        .replace('src="/static/kingdom.js"', f'src="/static/kingdom.js?v={version}"')
        .replace('src="/static/kingdom-map.js"', f'src="/static/kingdom-map.js?v={version}"')
        .replace('src="/static/kingdom-army.js"', f'src="/static/kingdom-army.js?v={version}"')
        .replace('src="/static/kingdom-diplomacy.js"', f'src="/static/kingdom-diplomacy.js?v={version}"')
        .replace('href="/static/kingdom-diplomacy.css"', f'href="/static/kingdom-diplomacy.css?v={version}"')
        .replace('src="/static/kingdom-budget.js"', f'src="/static/kingdom-budget.js?v={version}"')
        .replace('href="/static/kingdom-budget.css"', f'href="/static/kingdom-budget.css?v={version}"')
        .replace('href="/static/kingdom.css"', f'href="/static/kingdom.css?v={version}"')
        .replace('src="/static/equipment.js"', f'src="/static/equipment.js?v={version}"')
        .replace('href="/static/equipment.css"', f'href="/static/equipment.css?v={version}"')
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
