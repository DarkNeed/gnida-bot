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
    BOSSES,
    set_intent,
    create_raid_state,
    pair_state,
    resolve_round,
    BOSS_NAME,
    BOSS_SKILLS,
    raid_boss_sprite,
)
from arena_engine import effective_skill
from arena_archclasses import class_title, ARCHCLASSES, archclass_view
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


async def audio(request):
    return web.FileResponse(
        ROOT / "arena-audio", headers={"Content-Type": "application/javascript"}
    )


async def holdings_client(request):
    return web.FileResponse(ROOT/'holdings-client',headers={'Content-Type':'application/javascript; charset=utf-8','Cache-Control':'no-cache'})


async def demo_fighter(request):
    """Real catalogs in a synthetic battle: no token, DB or Telegram requests."""
    cls = request.match_info["class_id"]
    if cls not in FIGHTER_CLASSES:
        raise web.HTTPNotFound()
    arch=request.query.get('arch','')
    if arch and (arch not in ARCHCLASSES or ARCHCLASSES[arch]['class_id']!=cls):
        raise web.HTTPNotFound()
    stage=20 if request.query.get('stage','20')=='20' else 10
    mastery=request.query.get('mastery')=='1'
    resolved=20 if mastery else 0
    if mastery and arch:stage=10
    owned = [
        k for k in unlocked_skill_ids(cls, 20,archclass_id=arch,progression_level=resolved) if BUILTIN_SKILLS[k].class_id == cls
    ]
    if arch:
        primary={'warrior':['armor_split','steel_charge','counter_lunge'],
                 'mage':['mana_shot','mana_blob','mana_focus' if arch=='mage_archmage' else 'mana_overload' if arch=='mage_elementalist' else 'mana_barrier'],
                 'priest':['light_word','priest_heal','priest_ward'],
                 'hunter':['hunter_cut','hunter_shot','blood_bullets']}
        humour_fingers={
            'cutie':['air_kiss','posing','meow'], 'jock':['smack','butt_peak','clench'],
            'nerd':['humiliate','charging','doxxing'], 'thumb':['bayonet','warning_shot','senior_verdict'],
            'index':['receive_prescript','last_line','first_line'],
            'middle':['grit_teeth','whole_family','answer_for_it'],
            'ring':['first_stroke','red_etude','last_stroke'],
            'pinky':['calm_breath','moon_arc','falling_star']}
        owned=primary.get(cls,humour_fingers.get(cls,owned[:3]))+['arch_'+arch]
    source = dict(slave_id=1, owner_id=1, class_id=cls, level=20, loadout=owned,archclass_id=arch,archclass_stage=stage,progression_level=resolved)
    state = create_battle_state(
        source,
        dict(source, slave_id=2, owner_id=2, class_id="ragamuffin", loadout=None,archclass_id='',progression_level=0),
    )
    if arch:
        state['sides']['a']['rpg_state']={
            'warrior_berserker':dict(heat=5) if stage==20 else dict(onslaught=3),
            'warrior_knight':dict(steadfast=3), 'mage_necromancer':dict(souls=3),
            'mage_elementalist':{}, 'mage_archmage':dict(echo_ready=True),
            'priest_bishop':dict(faith=3), 'priest_paladin':dict(faith=3,retribution=3),
            'hunter_beast':dict(beast=3), 'hunter_moon':dict(visceral_ready=True,visceral_until=8,moon_mark=True),
        }.get(arch,{})
        state['sides']['a']['own_turns']=4
        from arena_finals import FINALS
        if arch in FINALS and stage==20:
            state['sides']['a']['final_state']=dict(shame=3,whim=3,grip=3,dominance=3,
                compiled=True,access=3,command=1,zones=['a','b','c'],execution=2,guilt=3,
                steadfast=3,blood_debt=state['sides']['a']['stats']['max_hp'],beast=3,counter_until=6)
            state['sides']['a']['mechanics']=dict(focus=3) if cls=='pinky' else {}
            state['sides']['b']['effects']=[dict(id=k,kind=k,value=-.1,duration=3) for k in ('accuracy_flat','speed_pct','magic_defense_pct')]
            # Only relevant counters should be visible in a single-path demo.
            names=dict(femboy=['shame'],princess=['whim'],gachi_actor=['grip'],mge_bro=['dominance'],
                programmer=['compiled'],hacker=['access'],thumb_discipline=['command'],thumb_execution=['zones'],
                index_proxy=['execution'],index_messenger=['guilt'],middle_guardian=['steadfast'],
                middle_revenge=['blood_debt'],ring_pointillist=[],ring_fauvist=['beast'],
                pinky_dihui=['counter_until'],pinky_tiansha=[])
            state['sides']['a']['final_state']={k:v for k,v in state['sides']['a']['final_state'].items() if k in names[arch]}
    if mastery:
        from arena_mastery import BRANCHES
        a,b=state['sides'].values()
        a['mastery_state']=dict(street_ready=True,combo=['a','b','c'],last_cute='uwu',theory_ready=True,executions=2,flow=3,prayers=3,hunt_ready=True)
        relevant=dict(ragamuffin=['street_ready','combo'],cutie=['last_cute'],nerd=['theory_ready'],index=['executions'],mage=['flow'],priest=['prayers'],hunter=['hunt_ready'],warrior=['combo'])
        a['mastery_state']={k:v for k,v in a['mastery_state'].items() if not arch and k in relevant.get(cls,[])}
        a['mechanics']=dict(order=3,grudge=3,focus=3,last_attack='bum_punch',prescript=BRANCHES[arch][0] if arch else 'last_line')
        a['mechanics']={k:v for k,v in a['mechanics'].items() if k in dict(thumb=['order'],middle=['grudge'],pinky=['focus'],index=['prescript'],jock=['last_attack']).get(cls,[])}
        a['effects']=[dict(id='evolution_prepared',kind='prepared_attack',value=1,duration=2)]
        if cls!='jock':a['effects']=[]
        b['effects']=[dict(id='adoration',kind='damage_pct',value=-.4,duration=3),dict(id='doxxing_magic',kind='magic_defense_pct',value=-.2,duration=3),dict(id='rpg_burn',kind='burn',value=3,duration=3)]
        if cls not in ('cutie','nerd','ring') and arch!='mage_elementalist':b['effects']=[]
        if not arch:
            primary=dict(ragamuffin=['bum_punch','dust_in_eyes','street_breath'],cutie=['uwu','meow','posing'],jock=['smack','clench','butt_peak'],nerd=['humiliate','doxxing','go_to_store'],thumb=['bayonet','warning_shot','senior_verdict'],index=['receive_prescript','first_line','last_line'],middle=['grit_teeth','answer_for_it','whole_family'],ring=['first_stroke','unfinished_portrait','last_stroke'],pinky=['calm_breath','moon_arc','falling_star'],warrior=['armor_split','steel_charge','warrior_execute'],mage=['mana_shot','mana_focus','mana_overload'],priest=['light_word','priest_heal','holy_judgment'],hunter=['hunter_cut','hunter_transform','hunter_visceral'])
            a['loadout']=primary[cls]+['mastery_'+cls]
            if cls=='hunter':a['rpg_state']=dict(visceral_ready=True,visceral_until=8)
    for key, side in state["sides"].items():
        c = FIGHTER_CLASSES[side["class_id"]]
        side.update(
            name=class_title(side,c.name),
            class_name=class_title(side,c.name),
            archclass=archclass_view(side),
            class_avatar_url=choice_avatar(c.class_id,side.get('archclass_id',''),side.get('archclass_stage',10)),
            sprite=c.class_id,
            class_rarity=c.rarity,
            resource_name=c.resource_name,
            skill_details=[asdict(effective_skill(state,key,k)) for k in side["loadout"]],
            effective_stats={k: effective_stat(side, k) for k in side["stats"]},
        )
        from arena_mastery import view as mastery_view
        side['mastery']=mastery_view(side)
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
            level=20 if phase.startswith('kit') else 18 if phase.startswith(("lei_heng", "doof")) else 12,
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
    boss_id = (
        "doofenshmirtz"
        if phase.startswith("doof")
        else 'kit' if phase.startswith('kit') else "lei_heng" if phase.startswith("lei_heng") else "iron"
    )
    boss_info = BOSSES[boss_id]
    data = create_raid_state(
        participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, boss_id
    )
    if boss_id == "lei_heng":
        data["round"] = 3
        set_intent(data)
    if boss_id == 'kit':
        if phase == 'kit_phase2':
            data['boss']['hp'] = round(data['boss']['stats']['max_hp'] * .65)
            data['round'] = 4
        elif phase in ('kit_phase3', 'kit_animation'):
            data['boss']['hp'] = round(data['boss']['stats']['max_hp'] * .34)
            data['round'] = 7
        set_intent(data)
    names = {"1": "Хакер", "2": "Мге-браток", "3": "Принцесса"}
    for p in participants:
        p.update(name=names[str(p["actor_id"])], fighter_name=names[str(p["actor_id"])])
    for key, f in [("boss", data["boss"])] + [
        (k, p["fighter"]) for k, p in data["players"].items()
    ]:
        cls = FIGHTER_CLASSES[f["class_id"]]
        f.update(
            name=boss_info["name"] if key == "boss" else names[key],
            class_name="Рейдовый босс" if key == "boss" else class_title(f, cls.name),
            sprite=f["class_id"],
            class_avatar_url=choice_avatar(f["class_id"], f.get("archclass_id", "")),
            resource_name=cls.resource_name,
            class_rarity=cls.rarity,
            effective_stats={k: effective_stat(f, k) for k in f["stats"]},
        )
        if key == "boss" and boss_info.get("sprite"):
            f["class_avatar_url"] = raid_boss_sprite(boss_id, data.get('phase', 1))
        if key == "boss" and boss_id == "doofenshmirtz":
            f["resource_name"] = "Заряд инатора"
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
    if boss_id in {"lei_heng", "doofenshmirtz", 'kit'}:
        data["log"] = []
        if boss_id == 'kit':
            data['boss']['effects'] = []
            data['players']['1']['fighter']['effects'] = []
        if boss_id == "lei_heng":
            data["boss"]["effects"] = []
            data["players"]["1"]["fighter"]["effects"] = [
                e
                for e in data["players"]["1"]["fighter"]["effects"]
                if e.get("id") == "lei_prey"
            ]
    if phase == "finished":
        data.update(
            finished=True,
            won=True,
            result="Босс повержен!",
            rewards={str(i): dict(xp=58, francs=76, loot="") for i in (1, 2, 3)},
        )
        data["boss"]["hp"] = 0
    if phase in {"animation", "lei_heng_animation", "doof_animation", 'kit_animation'}:
        import random

        data["log"] = []
        for key, sid in (("1", "humiliate"), ("2", "smack"), ("3", "meow")):
            data["players"][key]["selected"] = (
                "defend" if boss_id == 'kit' or boss_id == "lei_heng" and key == "1" else sid
            )
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
        revision=1 if phase.endswith("animation") else 0,
        deadline=now + 120,
        server_time=now,
        boss_name=boss_info["name"],
        boss_id=boss_id,
        recommended_level=boss_info.get("recommended_level", 1),
        fixed_level=boss_info.get('fixed_level'), phase_count=boss_info.get('phase_count', 2),
        difficulty=boss_info.get('difficulty', ''),
        boss_sprites=dict(boss_info.get('phase_sprites', {})),
        ally_sprite=boss_info.get("ally_sprite", ""),
        loot_name=(
            BUILTIN_SKILLS[boss_info["loot_skill"]].name
            if boss_info.get("loot_skill")
            else ""
        ),
        participants=participants if phase != "lobby" else participants[:2],
        choices=[dict(fighter_id=1, personal=True, name="Мой личный персонаж")],
        data=None if phase == "lobby" else data,
    )


async def demo_raid(request):
    phase = request.match_info["phase"]
    if phase not in {
        "lobby",
        "active",
        "spectator",
        "finished",
        "animation",
        "lei_heng",
        "lei_heng_animation",
        "doof",
        "doof_animation",
        'kit', 'kit_phase2', 'kit_phase3', 'kit_animation',
    }:
        raise web.HTTPNotFound()
    return web.json_response(raid_preview(phase))


app.router.add_get("/", index)
app.router.add_get("/static/client.js", client)
app.router.add_get("/static/audio.js", audio)
app.router.add_get('/static/holdings.js',holdings_client)
app.router.add_get("/demo/fighter/{class_id}", demo_fighter)
app.router.add_get("/demo/mirror/{phase}", demo_mirror)
app.router.add_get("/demo/raid/{phase}", demo_raid)
app.router.add_static("/static/", ROOT)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8085)
    web.run_app(app, host="127.0.0.1", port=parser.parse_args().port)
