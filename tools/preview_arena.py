"""Local, token-free visual preview. Does not run Telegram polling or touch bot data."""

from pathlib import Path
from dataclasses import asdict
import argparse
import time
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
from arena_raid_engine import (
    create_raid_state,
    pair_state,
    resolve_round,
    BOSS_NAME,
    BOSS_SKILLS,
)
from arena_engine import effective_skill
from arena_archclasses import class_title
from arena_progression import choice_avatar

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


def raid_preview(phase="active"):
    """Detached synthetic raid; no player data or Telegram credentials."""
    participants = [
        dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i) for i in (1, 2, 3)
    ]
    sources = [
        dict(
            slave_id=i,
            owner_id=i,
            class_id=cls,
            level=12,
            archclass_id=branch,
            archclass_stage=10,
            loadout={
                "nerd": ["humiliate", "charging", "mother_joke", "go_to_store"],
                "jock": ["smack", "wallop", "flex_chest", "clench"],
                "cutie": ["uwu", "posing", "air_kiss", "meow"],
            }[cls],
        )
        for i, cls, branch in (
            (1, "nerd", "hacker"),
            (2, "jock", "mge_bro"),
            (3, "cutie", "princess"),
        )
    ]
    data = create_raid_state(participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS)
    names = {"1": "Хакер", "2": "Мге-браток", "3": "Принцесса"}
    for p in participants:
        p.update(name=names[str(p["actor_id"])], fighter_name=names[str(p["actor_id"])])
    for key, f in [("boss", data["boss"])] + [
        (k, p["fighter"]) for k, p in data["players"].items()
    ]:
        cls = FIGHTER_CLASSES[f["class_id"]]
        f.update(
            name=BOSS_NAME if key == "boss" else names[key],
            class_name="Рейдовый босс" if key == "boss" else class_title(f, cls.name),
            sprite=f["class_id"],
            class_avatar_url=choice_avatar(f["class_id"], f.get("archclass_id", "")),
            resource_name=cls.resource_name,
            class_rarity=cls.rarity,
            effective_stats={k: effective_stat(f, k) for k in f["stats"]},
        )
        target = data["players"]["1"]["fighter"] if key == "boss" else data["boss"]
        catalog = BOSS_SKILLS if key == "boss" else BUILTIN_SKILLS
        ids = f["loadout"]
        f["skill_details"] = [
            asdict(effective_skill(pair_state(f, target), "a", sid, catalog))
            for sid in ids
        ]
    for p in data["players"].values():
        p["ready"] = False
    data["players"]["2"].update(ready=True, selected=None)
    data["log"] = [
        dict(
            round=1,
            actor="1",
            target="boss",
            text="Унизить: −18 HP · энергия противника −15",
        ),
        dict(round=1, actor="boss", target="3", text="Размах цепью: −12 HP"),
    ]
    data["boss"]["effects"].append(
        dict(id="dust", kind="accuracy_flat", value=-20, duration=2)
    )
    data["players"]["1"]["fighter"]["effects"].append(
        dict(id="guard", kind="physical_defense_pct", value=0.35, duration=1)
    )
    if phase == "finished":
        data.update(
            finished=True,
            won=True,
            result="Босс повержен!",
            rewards={str(i): dict(xp=58, francs=76, loot="") for i in (1, 2, 3)},
        )
        data["boss"]["hp"] = 0
    if phase == "animation":
        import random

        data["log"] = []
        for key, sid in (("1", "humiliate"), ("2", "smack"), ("3", "meow")):
            data["players"][key]["selected"] = sid
        resolve_round(data, BUILTIN_SKILLS, random.Random(7))
        for player in data["players"].values():
            player["ready"] = False
    now = int(time.time())
    return dict(
        token="preview",
        chat_id=-1,
        creator_id=1,
        actor_id=99 if phase == "spectator" else 1,
        status=(
            "lobby"
            if phase == "lobby"
            else "finished" if phase == "finished" else "active"
        ),
        revision=1 if phase == "animation" else 0,
        deadline=now + 120,
        server_time=now,
        boss_name=BOSS_NAME,
        participants=participants if phase != "lobby" else participants[:2],
        choices=[dict(fighter_id=1, personal=True, name="Мой личный персонаж")],
        data=None if phase == "lobby" else data,
    )


async def demo_raid(request):
    phase = request.match_info["phase"]
    if phase not in {"lobby", "active", "spectator", "finished", "animation"}:
        raise web.HTTPNotFound()
    return web.json_response(raid_preview(phase))


app.router.add_get("/", index)
app.router.add_get("/static/client.js", client)
app.router.add_get("/demo/fighter/{class_id}", demo_fighter)
app.router.add_get("/demo/mirror/{phase}", demo_mirror)
app.router.add_get("/demo/raid/{phase}", demo_raid)
app.router.add_static("/static/", ROOT)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8085)
    web.run_app(app, host="127.0.0.1", port=parser.parse_args().port)
