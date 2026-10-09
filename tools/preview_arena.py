"""Local, token-free visual preview. Does not run Telegram polling or touch bot data."""

from pathlib import Path
from dataclasses import asdict
import argparse
import sys
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1] / "webapp"
sys.path.insert(0, str(ROOT.parent))
from arena_assets import render_arena_index
from arena_engine import (
    FIGHTER_CLASSES,
    BUILTIN_SKILLS,
    create_battle_state,
    unlocked_skill_ids,
    effective_stat,
)
from arena_mirror_effects import GIFTS, NORMAL_GIFTS

app = web.Application()


async def index(request):
    return web.Response(
        text=render_arena_index(ROOT),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def client(request):
    return web.FileResponse(
        ROOT / "battle-client", headers={"Content-Type": "application/javascript"}
    )


async def demo_fighter(request):
    """Real catalogs in a synthetic battle: no token, DB or Telegram requests."""
    cls = request.match_info["class_id"]
    if cls not in FIGHTER_CLASSES:
        raise web.HTTPNotFound()
    owned = [
        k for k in unlocked_skill_ids(cls, 20) if BUILTIN_SKILLS[k].class_id == cls
    ]
    source = dict(slave_id=1, owner_id=1, class_id=cls, level=20, loadout=owned)
    state = create_battle_state(
        source,
        dict(source, slave_id=2, owner_id=2, class_id="ragamuffin", loadout=None),
    )
    for key, side in state["sides"].items():
        c = FIGHTER_CLASSES[side["class_id"]]
        side.update(
            name=c.name,
            class_name=c.name,
            sprite=c.class_id,
            class_rarity=c.rarity,
            resource_name=c.resource_name,
            skill_details=[asdict(BUILTIN_SKILLS[k]) for k in side["loadout"]],
            effective_stats={k: effective_stat(side, k) for k in side["stats"]},
        )
    return web.json_response(
        dict(
            token="demo",
            chat_id=-1,
            mode="personal",
            status="active",
            revision=0,
            stake=0,
            actor_id=1,
            own_side="a",
            state=state,
        )
    )


async def demo_mirror(request):
    phase = request.match_info["phase"]
    if phase not in {"gift", "route", "event", "merchant", "ready", "ended", "combat"}:
        raise web.HTTPNotFound()
    details = lambda k: dict(id=k, name=GIFTS[k][0], description=GIFTS[k][1])
    return web.json_response(
        dict(
            token="preview",
            chat_id=-1,
            actor_id=1,
            fighter_id=1,
            personal=True,
            status="finished" if phase == "ended" else "active",
            revision=0,
            phase=phase,
            floor=5 if phase == "ended" else 2,
            total_floors=5,
            hp=34,
            max_hp=60,
            resource=45,
            resource_max=100,
            shards=35,
            xp=25,
            francs=85 if phase == "ended" else 0,
            loot="Твёрдая рука" if phase == "ended" else "",
            result=(
                "Зеркало пройдено!" if phase == "ended" else "Можно продолжить путь."
            ),
            event="altar",
            battle_token="demo",
            gifts=[details("edge")],
            choices=[details(k) for k in NORMAL_GIFTS[:3]],
        )
    )


app.router.add_get("/", index)
app.router.add_get("/static/client.js", client)
app.router.add_get("/demo/fighter/{class_id}", demo_fighter)
app.router.add_get("/demo/mirror/{phase}", demo_mirror)
app.router.add_static("/static/", ROOT)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8085)
    web.run_app(app, host="127.0.0.1", port=parser.parse_args().port)
