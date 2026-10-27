"""Review-only skill-pattern catalogue. Never reads accounts or resolves combat."""

from dataclasses import replace
from functools import lru_cache
import hashlib
import json

from aiohttp import web


@lru_cache(maxsize=1)
def review_catalog():
    from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, stats_for
    from arena_raid_engine import BOSS_SKILLS
    from arena_archclasses import ARCHCLASSES, arch_rule
    from arena_evolution import EVOLUTIONS, apply_rule
    from arena_finals import rule as final_rule
    from arena_rpg import rpg_variant
    from arena_mastery import rule as mastery_rule

    result = {}

    def add(skill, origin="Базовый навык", branch=""):
        if not skill.hostile:
            return
        strikes = (
            6
            if "six_strike" in skill.tags
            else (
                3
                if "three_strike" in skill.tags
                else 2 if "two_strike" in skill.tags else 1
            )
        )
        key = f"{skill.skill_id}:{skill.name}:{strikes}:{skill.damage_type}"
        if key in result:
            return
        result[key] = dict(
            id=key,
            base_id=skill.skill_id,
            name=skill.name,
            class_id=skill.class_id,
            class_name=(
                FIGHTER_CLASSES[skill.class_id].name
                if skill.class_id in FIGHTER_CLASSES
                else "Боссы / общие трактаты"
            ),
            origin=origin,
            branch=branch,
            tags=list(skill.tags),
            damage_type=skill.damage_type,
            power=skill.power,
            accuracy=skill.accuracy,
            strikes=strikes,
            description=skill.description,
        )

    for skill in (BUILTIN_SKILLS | BOSS_SKILLS).values():
        add(skill, "Босс" if skill.skill_id in BOSS_SKILLS else "Базовый навык")
        if skill.skill_id in EVOLUTIONS:
            add(apply_rule(skill, EVOLUTIONS[skill.skill_id]), "Условное усиление")

    # Ask the actual pure variant functions for names/tags, including locked
    # finishers. Readiness is irrelevant in a laboratory, not bypassed in-game.
    target = dict(
        hp=20,
        stats=stats_for("warrior", 20),
        effects=[
            dict(id=i, kind=k, value=v, duration=3)
            for i, k, v in (
                ("adoration", "damage_pct", -0.4),
                ("armor_split", "physical_defense_pct", -0.3),
                ("doxxing_magic", "magic_defense_pct", -0.3),
                ("rpg_burn", "burn", 3),
                ("rpg_frost", "speed_pct", -0.25),
                ("rpg_conductivity", "magic_defense_pct", -0.15),
                ("bleed", "bleed", 3),
            )
        ],
    )
    for cls in FIGHTER_CLASSES:
        branches = [("", "Мастерство класса")] + [
            (key, entry["name"])
            for key, entry in ARCHCLASSES.items()
            if entry["class_id"] == cls
        ]
        for branch, title in branches:
            for level, stage in ((10, 10), (20, 10), (20, 20)):
                actor = dict(
                    class_id=cls,
                    level=level,
                    archclass_id=branch,
                    archclass_stage=stage,
                    progression_level=level,
                    hp=30,
                    stats=stats_for(cls, level),
                    own_turns=8,
                    effects=[
                        dict(
                            id="evolution_prepared",
                            kind="prepared_attack",
                            value=0.3,
                            duration=2,
                        )
                    ],
                    mechanics=dict(order=3, grudge=3, focus=3),
                    final_state={},
                    mastery_state={},
                    rpg_state=dict(
                        souls=3,
                        mana=3,
                        faith=3,
                        beast=3,
                        onslaught=3,
                        heat=5,
                        fortitude=3,
                        steadfast=3,
                        retribution=3,
                        elements=["fire", "frost", "lightning"],
                        echo_ready=True,
                        echo_uses=4,
                        visceral_ready=True,
                        visceral_until=99,
                        moon_mark=True,
                    ),
                )
                for skill in BUILTIN_SKILLS.values():
                    if skill.class_id != cls or skill.unlock_level > level:
                        continue
                    if cls=='gambler':
                        from arena_casino import variant as casino_variant
                        from arena_archprogress import branch_skill_allowed
                        if branch_skill_allowed(skill,branch,level):
                            add(casino_variant(skill,actor),title+f' · {level}',branch)
                            if stage==20:
                                add(casino_variant(skill,dict(actor,casino_state=dict(sevens=3,chips=7))),title+' · 777',branch)
                        continue
                    entry = arch_rule(skill, actor)
                    if entry and level >= entry.get("min_level", 10):
                        add(
                            replace(skill, name=entry["name"], **entry["changes"]),
                            title + f" · {level}",
                            branch,
                        )
                    entry = final_rule(skill, actor, target)
                    if entry:
                        add(
                            replace(skill, name=entry["name"], **entry["changes"]),
                            title + " · финал",
                            branch,
                        )
                    add(
                        rpg_variant(skill, actor, target), title + f" · {level}", branch
                    )
                    # Intermediate charged/active forms have their own names:
                    # Phoenix at 3 Heat; Beast after activating its fury.
                    other = dict(
                        actor,
                        rpg_state=dict(actor["rpg_state"], heat=3, beast_fury_until=99),
                    )
                    add(
                        rpg_variant(skill, other, target), title + f" · {level}", branch
                    )
                    entry = mastery_rule(skill, actor, target)
                    if entry:
                        add(
                            replace(skill, **entry["changes"]),
                            title + " · мастерство",
                            branch,
                        )
    return sorted(result.values(), key=lambda row: (row["class_id"], row["name"]))


def add_unique_qte_routes(app, root):
    folder = root / "qte-unique"

    async def page(request):
        version = hashlib.sha256(
            (root / 'nazarick-qte.js').read_bytes() +
            (root / 'qte-block-view').read_bytes() +
            (root / "qte-input").read_bytes()
            + (root / 'qte-casino-view').read_bytes() + (root / 'qte-view').read_bytes()
            + (root / "qte-input.css").read_bytes()
            + b"".join(
                (folder / name).read_bytes()
                for name in ("engine", "client", "style.css")
            )
        ).hexdigest()[:16]
        catalog = json.dumps(review_catalog(), ensure_ascii=False).replace(
            "<", "\\u003c"
        )
        return web.Response(
            text=(folder / "index.html")
            .read_text(encoding="utf-8")
            .replace("__REV__", version)
            .replace("__CATALOG__", catalog),
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

    app.router.add_get("/qte-lab/unique", page)
    app.router.add_get("/qte-lab/unique/", page)
    app.router.add_get("/qte-lab/unique/{name:engine|client}.js", script)
    add_block_qte_routes(app, root)


def add_block_qte_routes(app, root):
    """Read-only prototype; no battle/settings routes or account mutations."""
    folder = root / "qte-block"

    async def page(request):
        version = hashlib.sha256(
            (root / 'nazarick-qte.js').read_bytes() +
            (root / 'qte-block-view').read_bytes() +
            (root / "qte-input").read_bytes()
            + (root / 'qte-casino-view').read_bytes()
            + (root / "qte-input.css").read_bytes()
            + (root / "qte-unique" / "engine").read_bytes()
            + b"".join(
                (folder / name).read_bytes()
                for name in ("engine", "client", "style.css")
            )
        ).hexdigest()[:16]
        catalog = json.dumps(review_catalog(), ensure_ascii=False).replace(
            "<", "\\u003c"
        )
        return web.Response(
            text=(folder / "index.html")
            .read_text(encoding="utf-8")
            .replace("__REV__", version)
            .replace("__CATALOG__", catalog),
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

    app.router.add_get("/qte-lab/block", page)
    app.router.add_get("/qte-lab/block/", page)
    app.router.add_get("/qte-lab/block/{name:engine|client}.js", script)
