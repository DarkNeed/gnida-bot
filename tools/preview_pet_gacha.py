"""Approval-only local preview: no bot imports, payments, database or inventory."""
import argparse
import json
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1] / "art" / "pets-v1"
REVIEW = ROOT / "review"


def create_app():
    app = web.Application()
    catalog = json.loads((ROOT / "PROMPTS.json").read_text(encoding="utf-8"))["pets"]
    allowed = {pet["id"] for pet in catalog}

    async def page(request):
        return web.FileResponse(REVIEW / "index.html", headers={"Cache-Control": "no-store"})

    async def style(request):
        return web.FileResponse(REVIEW / "review.css", headers={"Cache-Control": "no-store"})

    async def script(request):
        return web.FileResponse(REVIEW / "review-client", headers={"Content-Type": "application/javascript", "Cache-Control": "no-store"})

    async def pets(request):
        return web.json_response([
            {key: pet[key] for key in ("id", "name", "affinity", "rarity", "effect", "quote")}
            for pet in catalog
        ])

    async def image(request):
        pet_id = request.match_info["pet_id"]
        if pet_id not in allowed:
            raise web.HTTPNotFound()
        clean = ROOT / "clean" / (pet_id + ".png")
        path = clean if clean.is_file() else ROOT / (pet_id + ".png")
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    app.router.add_get("/", page)
    app.router.add_get("/review.css", style)
    app.router.add_get("/review.js", script)
    app.router.add_get("/pets.json", pets)
    app.router.add_get("/pets/{pet_id}.png", image)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8100)
    web.run_app(create_app(), host="127.0.0.1", port=parser.parse_args().port)
