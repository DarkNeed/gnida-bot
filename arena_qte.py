"""Isolated, client-only combat experiment. No identity, database or rewards."""

import hashlib
from pathlib import Path

from aiohttp import web


def add_qte_lab_routes(app: web.Application, root: Path) -> None:
    from arena_qte_unique import add_unique_qte_routes

    add_unique_qte_routes(app, root)
    folder = root / "qte-lab"

    async def page(request):
        version = hashlib.sha256(
            b"".join(
                (folder / name).read_bytes()
                for name in ("style.css", "engine", "client")
            )
        ).hexdigest()[:16]
        return web.Response(
            text=(folder / "index.html")
            .read_text(encoding="utf-8")
            .replace("__REV__", version),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def script(request):
        return web.FileResponse(
            folder / request.match_info["name"],
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/qte-lab", page)
    app.router.add_get("/qte-lab/", page)
    app.router.add_get("/qte-lab/{name:engine|client}.js", script)

    async def live(request):
        return web.FileResponse(
            root / "qte-live",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-live.js", live)

    async def patterns(request):
        return web.FileResponse(
            root / "qte-unique" / "engine",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    async def pattern_view(request):
        return web.FileResponse(
            root / "qte-view",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-engine.js", patterns)
    app.router.add_get("/static/qte-view.js", pattern_view)

    async def touch_input(request):
        return web.FileResponse(
            root / "qte-input",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-input.js", touch_input)

    async def touch_style(request):
        return web.FileResponse(
            root / "qte-input.css", headers={"Cache-Control": "no-cache"}
        )

    app.router.add_get("/static/qte-input.css", touch_style)

    async def live_style(request):
        return web.FileResponse(
            root / "qte-live.css", headers={"Cache-Control": "no-cache"}
        )

    app.router.add_get("/static/qte-live.css", live_style)
