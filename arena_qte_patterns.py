"""Version 2 authoritative pattern replay; no JavaScript runtime or client outcomes.

Mirrors webapp/qte-unique/engine at 120 Hz. Only server-created descriptors,
seeds and stats are used. Damage weights remain relative to the native skill.
"""

import math

HZ = 120
TAU = math.tau
W, H = 720, 320
TIERS = dict(minor=0.1, normal=0.3, heavy=0.6, critical=1)


def clamp(v, a, b):
    return max(a, min(b, v))


def jsround(v):
    return math.floor(v + 0.5)


def hash_value(value):
    n = 2166136261
    # JS for-of iterates code points; charCodeAt(0) takes the leading UTF-16 unit.
    for c in str(value):
        code = ord(c)
        if code > 0xFFFF:
            code = 0xD800 + ((code - 0x10000) >> 10)
        n = ((n ^ code) * 16777619) & 0xFFFFFFFF
    return n


def random_values(seed):
    n = seed & 0xFFFFFFFF
    while True:
        n = (n * 1664525 + 1013904223) & 0xFFFFFFFF
        yield n / 4294967296


def family(s):
    ident, n = s.get("base_id", ""), s.get("name", "").lower()
    branch, cls = s.get("branch", ""), s.get("class_id")

    def contains(*words):
        return any(word in n for word in words)

    if ident == 'whaler_harpoon':
        return 'thrust'
    if ident == 'whaler_staff':
        return 'slash'
    if ident in ('whaler_miasma', 'swamp_miasma', 'whaler_rot', 'whaler_rot_magic'):
        return 'death'
    if ident.startswith('whaler_punishment'):
        return 'lightning'

    if contains("паровоз"):
        return "train"
    if "tigerslayer" in ident or "lei_perfected" in ident:
        return "tiger"
    if ident in ("lei_double_slash", "lei_explosive_slash"):
        return "slash"
    if "kit_eclipse" in ident or "solar_eclipse" in ident:
        return "eclipse"
    if ident == "kit_reflection":
        return "mirror"
    if ident.startswith("kit_coins"):
        return "coins"
    if ident == "kit_rift" or contains("небытия", "стирание"):
        return "void"
    if ident == "kit_ash" or contains(
        "пепел", "пылающ", "катаклизм", "метеор", "огненный"
    ):
        return "fire"
    if ident == "kit_light":
        return "holy"
    if ident == "kit_flash" or contains("молни"):
        return "lightning"
    if "deport" in ident:
        return "portal"
    if any(v in ident for v in ("doof_blast", "mge", "butt_peak")) or contains(
        "ракет", "дуэль на миду"
    ):
        return "rocket"
    if ident.startswith("doof_"):
        return "mana"
    if (
        contains("костян", "похищение жизни", "жатва", "мёртв", "душ")
        or "necromancer" in branch + ident
    ):
        return "death"
    if contains("ледян"):
        return "ice"
    if any(v in branch + ident for v in ("beast", "fauvist")) or contains(
        "звер", "хищник", "разорвать", "первобыт"
    ):
        return "beast"
    if "глаз" in ident or "dust_in_eyes" in ident:
        return "dust"
    if cls == "cutie":
        return "charm"
    if "clench" in ident or "gachi" in ident or contains("захват", "club"):
        return "grapple"
    if cls in ("jock", "middle"):
        return "impact"
    if cls == "thumb":
        return "thrust" if ident == "bayonet" else "gun"
    if ident == "hunter_shot" or contains("осколок"):
        return "gun"
    if cls == "index":
        return "edict"
    if cls == "ring":
        return "paint"
    if cls == "pinky":
        return "slash" if contains("тихий", "охраняющ") else "stars"
    if cls == "nerd":
        return (
            "script"
            if "programmer" in branch or contains("патч", "оптимиз", "просчитал")
            else "hack"
        )
    if cls == "mage":
        return "void" if "archmage" in branch + ident else "mana"
    if cls == "priest":
        return (
            "thrust"
            if contains("последний приговор")
            else (
                "impact"
                if "paladin" in branch + ident or contains("карающий")
                else "holy"
            )
        )
    if cls == "warrior":
        return "impact" if contains("контрудар", "бастион", "натиск") else "slash"
    if cls == "hunter":
        return "stars" if contains("лун") else "beast"
    if ident.startswith("raid_") or cls == "ragamuffin":
        return "impact"
    return (
        "mana"
        if s.get("damage_type") == "magic"
        else "thrust" if s.get("damage_type") else "hack"
    )


STYLES = dict(
    slash="arc",
    thrust="bar",
    impact="pulse",
    grapple="gates",
    gun="reticle",
    rocket="pulse",
    train="bar",
    charm="heart",
    hack="scan",
    script="scan",
    edict="scan",
    paint="orbit",
    beast="arc",
    stars="orbit",
    mana="pulse",
    holy="cross",
    void="orbit",
    death="pulse",
    fire="pulse",
    ice="bar",
    lightning="gates",
    portal="gates",
    mirror="gates",
    coins="orbit",
    eclipse="orbit",
    dust="bar",
    tiger="arc",
)


def profile(skill):
    ident = skill["id"]
    seed = hash_value(ident)
    r = random_values(seed)
    kind = family(skill)
    return dict(
        id=ident,
        seed=seed,
        kind=kind,
        style=STYLES[kind],
        skill=skill,
        basic=skill.get("base_id") == "bum_punch" and skill.get("name") == "Удар бомжа",
        strikes=clamp(skill.get("strikes", 1), 1, 6),
        kit=skill.get("base_id", "").startswith("kit_"),
        phase=next(r) * TAU,
        polarity=-1 if next(r) < 0.5 else 1,
        speed=0.94 + next(r) * 0.18,
        spread=0.78 + next(r) * 0.34,
        interval=0.8 + next(r) * 0.4,
        drift=next(r) > 0.6,
    )


def difficulty(stats):
    a = clamp((stats["accuracy"] - stats["enemyEvasion"]) / 100, -1, 1)
    d = clamp((stats["enemyAccuracy"] - stats["evasion"]) / 100, -1, 1)
    intensity = clamp((d + 0.15) / 1.15, 0, 1)
    return dict(
        zone=clamp(0.13 + a * 0.16, 0.075, 0.29),
        cursor=0.85 - a * 0.28,
        warning=0.90 - 0.58 * intensity,
        speed=400 + 350 * intensity**1.4,
        size=44 + 16 * intensity,
        gap=180 - 76 * intensity,
        moveSpeed=240 * clamp(stats.get('controlScale', 1), .5, 1),
        pressure=d,
        intensity=intensity,
        lead=0.28 * intensity * intensity,
        beamScale=1 + 0.2 * intensity * intensity,
    )


def impact(p, i):
    if p["kind"] == "train":
        return dict(
            tier="critical" if i == p["strikes"] - 1 else "heavy",
            weight=(0.35, 0.6, 1)[min(2, i)],
        )
    if p["kind"] == "tiger":
        return dict(
            tier="critical" if i == p["strikes"] - 1 else "heavy",
            weight=1 if i == p["strikes"] - 1 else 0.6,
        )
    if p["kind"] in ("gun", "mana", "charm", "stars", "dust", "paint", "ice", "death"):
        return dict(tier="normal", weight=0.3)
    if p["kind"] in ("void", "eclipse"):
        return dict(tier="critical", weight=1)
    return dict(tier="heavy", weight=0.6)


def attack_weights(p):
    """Native timing marks share the full skill, unlike defensive projectiles."""
    tags = p["skill"].get("tags", ())
    if p["strikes"] == 3 and any(t in tags for t in ("final_train", "final_execution")):
        return [0.2, 0.3, 0.5]
    return [1 / p["strikes"]] * p["strikes"]


def attack(p, stats, seed):
    d, r = difficulty(stats), random_values(seed ^ p["seed"])
    n = p["strikes"]
    active = [
        ((1.8 if n == 1 else 1.18) / d["cursor"]) * (0.96 + next(r) * 0.08)
        for _ in range(n)
    ]
    slots = [v + 0.25 for v in active]
    return dict(
        p=p,
        d=d,
        time=0,
        duration=1 + sum(slots),
        activeSlots=active,
        slots=slots,
        centers=[0.28 + next(r) * 0.44 for _ in slots],
        results=[None] * n,
        attempts=[0] * n,
        lastAttempt=[-1] * n,
    )


def attack_frame(s):
    i, start = 0, 1
    while i < len(s["slots"]) - 1 and s["time"] >= start + s["slots"][i] - 1e-8:
        start += s["slots"][i]
        i += 1
    local = s["time"] - start
    phase = "ready" if s["time"] < 1 else "cue" if local < 0.25 else "active"
    progress = clamp((local - 0.25) / s["activeSlots"][i], 0, 1)
    cursor = 1 - abs(progress * 2 - 1)
    if s["p"]["style"] in ("pulse", "heart"):
        cursor = cursor ** (1.45 if s["p"]["style"] == "heart" else 0.8)
    if i % 2 and s["p"]["polarity"] < 0:
        cursor = 1 - cursor
    center = s["centers"][i] + (
        0.035 * math.sin(local * 3 + s["p"]["phase"]) if s["p"]["drift"] else 0
    )
    return dict(
        index=i,
        cursor=cursor,
        center=center,
        width=s["d"]["zone"],
        phase=phase,
        canHit=phase == "active"
        and s["results"][i] is None
        and s["attempts"][i] < 1,
    )


def duration(challenge):
    return (
        6.8 + challenge.get("defense_preparation", 0)
        if challenge["kind"] == "defense"
        else attack(
            profile(challenge["profile"]), challenge["stats"], challenge["seed"]
        )["duration"]
    )


def defense(p, stats, seed, enabled=None, preparation=1):
    d, r = difficulty(stats), random_values(seed ^ p["seed"])
    if p["kit"]:
        d["warning"] *= 0.92
        d["speed"] *= 1.08
    if p["skill"].get("class_id") == "thumb":
        d["speed"] *= 1.16
        d["warning"] = max(0.30, d["warning"] * 0.94)
        d["beamScale"] *= 1.12
    count = (
        3
        if p["basic"]
        else (
            12
            if p["kind"] == "tiger"
            else (
                6
                if p["kind"] == "train"
                else max(
                    p["strikes"],
                    4
                    + p["seed"] % 3
                    + (
                        1
                        if d["intensity"] > 0.75
                        else -1 if d["intensity"] < 0.25 else 0
                    )
                    + (1 if p["skill"].get("class_id") == "thumb" else 0),
                )
            )
        )
    )
    if p["basic"]:
        d["warning"] = max(0.66, d["warning"])
        d["size"] = 24 + 8 * d["intensity"]
    d['warning'] += stats.get('extraWarning', 0)
    static = p["skill"].get("base_id") != "mother_joke" and p["kind"] in (
        "slash",
        "thrust",
        "grapple",
        "hack",
        "script",
        "edict",
        "holy",
        "lightning",
        "portal",
        "coins",
        "tiger",
    )
    span = (
        (
            4.8
            if p["basic"]
            else (
                5.1
                if static
                else 4.3 if p["kind"] == "fire" else 4 if p["kind"] == "impact" else 3.5
            )
        )
        * (0.94 + (p["interval"] - 0.8) * 0.15)
        * (0.96 if p["kit"] else 1)
        * (1 if p["basic"] else 1 - 0.08 * d["intensity"])
    )
    events = [
        dict(
            at=preparation + 0.18 + i * span / max(1, count - 1),
            strike=min(p["strikes"] - 1, math.floor(i * p["strikes"] / count)),
            index=i,
            jitter=next(r),
            angle=next(r) * TAU,
            ready=False,
        )
        for i in range(count)
    ]
    return dict(
        p=p,
        d=d,
        enabled=enabled,
        time=0,
        preparation=preparation,
        player=dict(x=W * 0.32, y=H * 0.5, r=6),
        hazards=[],
        events=events,
        hitIds=set(),
        contacts=[],
        projectileCount=0,
    )


def prepare(s, e):
    x, y = s["player"]["x"], s["player"]["y"]
    p, d = s["p"], s["d"]
    tx = clamp(x + s["player"].get("vx", 0) * d["lead"], 12, W - 12)
    ty = clamp(y + s["player"].get("vy", 0) * d["lead"], 12, H - 12)
    i = e["index"]
    odd = i % 2
    sign = 1 if odd else -1
    start = e["at"] + d["warning"]
    shapes = []
    n = p["skill"]["name"].lower()
    ident = p["skill"].get("base_id")

    def add(h, delay=0, duration=0.24):
        shapes.append(
            dict(
                h,
                start=start + delay,
                end=start + delay + duration,
                strike=e["strike"],
                at=e["at"],
                index=i,
            )
        )

    def beam(ax, ay, bx, by, width=15, delay=0, duration=0.2):
        add(
            dict(type="line", ax=ax, ay=ay, bx=bx, by=by, r=width * d["beamScale"]),
            delay,
            duration,
        )

    def circle(cx, cy, r, delay=0, duration=0.25):
        add(
            dict(type="circle", x=cx, y=cy, r=r),
            delay + max(0, 0.44 - d["warning"]),
            duration,
        )

    def bullet(bx, by, vx, vy, r=7, delay=0, **extra):
        add(dict(type="bullet", x=bx, y=by, vx=vx, vy=vy, r=r, **extra), delay, 2.9)

    def fan(bx, by, a, n=5, spread=0.5, delay=0, motif=""):
        for j in range(n):
            theta = a + (j - (n - 1) / 2) * spread
            core = j == n // 2
            bullet(
                bx,
                by,
                math.cos(theta) * d["speed"] * p["speed"],
                math.sin(theta) * d["speed"] * p["speed"],
                (6 + d["pressure"]) * (1.1 if core else 0.8),
                delay,
                motif=motif,
                tier="normal" if core else "minor",
            )

    def corridor(vertical=False, offset=0):
        axis, at = (H, y) if vertical else (W, x)
        center = clamp(
            at + (-1 if odd else 1) * (55 + e["jitter"] * 15) + offset,
            d["gap"] / 2 + 8,
            axis - d["gap"] / 2 - 8,
        )
        lo, hi = center - d["gap"] / 2, center + d["gap"] / 2
        if vertical:
            add(dict(type="rect", x=0, y=0, w=W, h=lo), 0, 0.25)
            add(dict(type="rect", x=0, y=hi, w=W, h=H - hi), 0, 0.25)
        else:
            add(dict(type="rect", x=0, y=0, w=lo, h=H), 0, 0.25)
            add(dict(type="rect", x=hi, y=0, w=W - hi, h=H), 0, 0.25)

    def aimed(side=odd, spread=0.1, n=3, delay=0, motif=""):
        bx = (
            (max(W * 0.65, x + 220) if side else min(W * 0.35, x - 220))
            if d["intensity"] > 0.7
            else (W + 15 if side else -15)
        )
        by = 40 + e["jitter"] * (H - 80)
        fan(bx, by, math.atan2(ty - by, tx - bx), n, spread, delay, motif)

    def diagonal(theta, width=18, delay=0):
        dx, dy = math.cos(theta) * 900, math.sin(theta) * 900
        cx, cy = x + (tx - x) * 0.6, y + (ty - y) * 0.6
        beam(cx - dx, cy - dy, cx + dx, cy + dy, width, delay)

    k = p["kind"]
    if k == "slash":
        diagonal((i * 0.61 + p["phase"]) % math.pi, 16 + d["pressure"] * 4)
    elif k == "thrust":
        diagonal(
            (math.pi * 0.18 if odd else -math.pi * 0.12) + math.sin(p["phase"]) * 0.12,
            12 + d["pressure"] * 3,
        )
        if p["skill"].get("class_id") == "thumb":
            diagonal(-0.55 if odd else 0.55, 10, 0.20)
            shapes[-1].update(tier="minor", weight=0.15)
    elif k == "impact":
        circle(x, y, d["size"])
        if not p["basic"]:
            add(
                dict(
                    type="ring",
                    x=x,
                    y=y,
                    r=22,
                    speed=170 + 80 * d["intensity"],
                    gap=e["angle"],
                    gapWidth=1.65 - 0.65 * d["intensity"],
                    thickness=8 + 3 * d["intensity"],
                ),
                0.28,
                1.1,
            )
    elif k == "grapple":
        corridor(bool(odd))
    elif k == "gun":
        if p["skill"].get("class_id") == "thumb":
            bx = x + sign * (210 + 100 * (1 - d["intensity"]))
            by = clamp(y + (e["jitter"] - 0.5) * 180, -15, H + 15)
            fan(
                bx,
                by,
                math.atan2(ty - by, tx - bx),
                7 if d["intensity"] > 0.7 else 5,
                0.12 * p["spread"],
            )
            aimed(not odd, 0.11 * p["spread"], 5 if d["intensity"] > 0.7 else 3, 0.18)
        else:
            aimed(odd, 0.09 * p["spread"], 5 if d["intensity"] > 0.75 else 3)
    elif k == "rocket":
        circle(x, y, d["size"] + 6, 0, 0.3)
        for j in range(8):
            bullet(
                x, y, math.cos(j * TAU / 8) * 230, math.sin(j * TAU / 8) * 230, 5, 0.32
            )
    elif k == "train":
        gap = clamp(y + sign * (70 + p["spread"] * 10), 75, H - 75)
        speed = d["speed"] * 1.35 * (1 + i * 0.035)
        bx = -25 if odd else W + 25
        rows = [yy for yy in range(0, H + 1, 16) if abs(yy - gap) > d["gap"] * 0.32]
        core = min(reversed(rows), key=lambda yy: abs(yy - y))
        for yy in rows:
            main = yy == core
            bullet(
                bx,
                yy,
                speed if odd else -speed,
                0,
                10 if main else 5,
                0,
                motif="train",
                tier=(
                    ("critical" if i == len(s["events"]) - 1 else "heavy")
                    if main
                    else "minor"
                ),
                weight=(0.25, 0.35, 0.45, 0.6, 0.65, 1)[i] if main else 0.1,
            )
    elif k == "charm":
        if "мяу" in n:
            diagonal(0.35 if odd else -0.35, 9)
            diagonal(-0.35 if odd else 0.35, 9, 0.22)
            aimed(odd, 0.22, 3, 0.35, "heart")
        else:
            aimed(odd, 0.19 * p["spread"], 7, 0, "heart")
            circle(x, y, 31, 0.24, 0.2)
    elif k == "hack":
        if ident == "mother_joke":
            circle(x, y, 35, 0, 0.25)
            aimed(odd, 0.12, 5, 0.24, "dust")
        elif odd:
            beam(x, 0, x, H, 18 + d["pressure"] * 4)
        else:
            beam(0, y, W, y, 16 + d["pressure"] * 4)
    elif k == "script":
        corridor(bool(odd))
        circle(clamp(x + sign * 100, 25, W - 25), y, 25, 0.32, 0.35)
    elif k == "edict":
        if "последн" in n or "исполнен" in n:
            diagonal(math.pi * 0.25 + p["polarity"] * 0.16, 13)
        else:
            for j in range(3):
                lane = (tx if odd else ty) + (j - 1) * (68 - 12 * d["intensity"])
                delay = j * (0.21 - 0.07 * d["intensity"])
                if odd:
                    beam(lane, 0, lane, H, 7 + d["pressure"] * 2, delay, 0.15)
                else:
                    beam(0, lane, W, lane, 7 + d["pressure"] * 2, delay, 0.15)
        if d["intensity"] > 0.4:
            diagonal(-0.55 if odd else 0.55, 6, 0.36)
            shapes[-1].update(tier="minor", weight=0.15)
    elif k == "paint":
        circle(x, y, 28 + d["pressure"] * 4, 0, 0.72)
        aimed(odd, 0.16, 4, 0.12, "paint")
    elif k == "beast":
        diagonal(
            (-0.25 if odd else 0.25) + p["polarity"] * 0.15, 22 + d["pressure"] * 4
        )
        diagonal(0.7 if odd else -0.7, 12, 0.3)
    elif k == "stars":
        if "падающ" in n or "небо" in n:
            for j in range(-2, 3):
                bullet(
                    tx + j * (98 - 26 * d["intensity"]),
                    -20,
                    sign * (35 + 30 * d["intensity"]),
                    d["speed"] * 0.95,
                    6 + 2 * d["intensity"],
                    abs(j) * 0.08,
                    motif="star",
                )
            if p["skill"].get("class_id") == "pinky":
                aimed(odd, 0.13, 3, 0.2, "star")
        else:
            bx, by = (80 if odd else W - 80), H * 0.5
            for j in range(9):
                a = j * TAU / 9 + p["phase"] + i * 0.47
                bullet(
                    bx,
                    by,
                    math.cos(a) * d["speed"] * 0.8,
                    math.sin(a) * d["speed"] * 0.8,
                    5,
                    0,
                    turn=sign * 0.7,
                    motif="star",
                )
            if p["skill"].get("class_id") == "pinky":
                aimed(
                    odd,
                    0.12 * p["spread"],
                    5 if d["intensity"] > 0.75 else 3,
                    0.16,
                    "star",
                )
    elif k == "mana":
        aimed(odd, 0.13 * p["spread"], 5, 0, "orb")
        aimed(not odd, 0.1, 3, 0.25, "orb")
    elif k == "holy":
        beam(x, 0, x, H, 14 + d["pressure"] * 3)
        beam(0, y, W, y, 14 + d["pressure"] * 3, 0.12)
    elif k == "void":
        add(dict(type="well", x=x, y=y, r=35 + d["pressure"] * 4, pull=65), 0, 0.9)
        aimed(odd, 0.2, 3, 0.3, "orb")
    elif k == "death":
        if "похищение" in n:
            add(dict(type="well", x=x, y=y, r=30, pull=55), 0, 0.6)
        aimed(odd, 0.17, 5, 0, "bone")
        bx, by = clamp(x + sign * 140, 20, W - 20), (-20 if odd else H + 20)
        fan(bx, by, math.atan2(y - by, x - bx), 3, 0.12, 0.3, "ghost")
    elif k == "fire":
        circle(x, y, d["size"], 0, 0.7)
        circle(
            clamp(x + sign * 95, 20, W - 20),
            clamp(y + sign * 65, 20, H - 20),
            30,
            0.35,
            0.6,
        )
    elif k == "ice":
        for j in range(-2, 3):
            bullet(
                x + j * 78,
                H + 20 if odd else -20,
                0,
                (-1 if odd else 1) * d["speed"],
                8,
                abs(j) * 0.06,
                motif="ice",
            )
    elif k == "lightning":
        xx = clamp(x + sign * 65, 60, W - 60)
        beam(x - 110, 0, xx, y, 10)
        beam(xx, y, x - 20, H, 10, 0.04)
        if odd:
            beam(0, y + 55, W, y - 55, 8, 0.25)
    elif k == "portal":
        corridor(bool(odd))
        diagonal(0.55 if odd else -0.55, 10, 0.4)
    elif k == "mirror":
        aimed(odd, 0.08, 3)
        aimed(not odd, 0.08, 3, 0.32)
    elif k == "coins":
        cx = clamp(x + sign * 55, 80, W - 80)
        beam(cx, 0, cx, H, 25)
        circle(x, y, 36, 0.32, 0.2)
    elif k == "eclipse":
        bx, by = (W - 25 if odd else 25), 30 + (i % 3) * 130
        beam(bx, by, x + (x - bx) * 4, y + (y - by) * 4, 10 + d["pressure"] * 3)
        if i > 1:
            circle(x, y, 32, 0.3, 0.28)
    elif k == "dust":
        aimed(odd, 0.12, 5, 0, "dust")
        aimed(not odd, 0.16, 4, 0.2, "dust")
    elif k == "tiger":
        direction = (0, math.pi / 2, math.pi * 0.24, -math.pi * 0.24, 0, math.pi / 2)[
            e["strike"] % 6
        ]
        diagonal(direction, (7 if odd else 12) + d["pressure"] * 3)
        shapes[0].update(
            tier=(
                "minor"
                if odd
                else "critical" if e["strike"] == p["strikes"] - 1 else "heavy"
            ),
            weight=0.15 if odd else 1 if e["strike"] == p["strikes"] - 1 else 0.6,
        )
    else:
        raise ValueError("Неизвестный узор.")
    for j, h in enumerate(shapes):
        h["id"] = f"wave:{i}:{j}"
        h["damageId"] = f"wave:{i}:bolt" if k == "lightning" and j < 2 else h["id"]
        h["disabled"] = s["enabled"] is not None and not s["enabled"][h["strike"]]
        h.setdefault(
            "tier",
            (
                "heavy"
                if h["type"] in ("line", "circle", "rect")
                else "normal" if h["type"] in ("ring", "well") else "minor"
            ),
        )
        h.setdefault("weight", TIERS[h["tier"]])
        s["hazards"].append(h)
    s["projectileCount"] += len({h["damageId"] for h in shapes if not h["disabled"]})
    e["ready"] = True


def geometry(h, t):
    age = max(0, t - h["start"])
    if h["type"] == "bullet":
        if h.get("turn"):
            a = h["turn"] * age
            cs, sn = math.cos(a), math.sin(a)
            return dict(
                h,
                x=h["x"] + (h["vx"] * sn + h["vy"] * (cs - 1)) / h["turn"],
                y=h["y"] + (h["vx"] * (1 - cs) + h["vy"] * sn) / h["turn"],
            )
        return dict(h, x=h["x"] + h["vx"] * age, y=h["y"] + h["vy"] * age)
    if h["type"] == "ring":
        return dict(h, r=h["r"] + h["speed"] * age)
    return h


def distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    k = clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1), 0, 1)
    return math.hypot(px - ax - k * dx, py - ay - k * dy)


def segment_distance(ax, ay, bx, by, cx, cy, dx, dy):
    det = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
    if abs(det) > 1e-10:
        u = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / det
        v = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / det
        if 0 <= u <= 1 and 0 <= v <= 1:
            return 0
    return min(
        distance(ax, ay, cx, cy, dx, dy),
        distance(bx, by, cx, cy, dx, dy),
        distance(cx, cy, ax, ay, bx, by),
        distance(dx, dy, ax, ay, bx, by),
    )


def touches(h, old, now, t, dt):
    g = geometry(h, t)
    r = now["r"]
    a, b, c, d = old["x"], old["y"], now["x"], now["y"]
    typ = h["type"]
    if typ == "bullet":
        prev = geometry(h, max(h["start"], t - dt))
        return (
            distance(0, 0, prev["x"] - a, prev["y"] - b, g["x"] - c, g["y"] - d)
            <= g["r"] + r
        )
    if typ == "line":
        return (
            segment_distance(a, b, c, d, g["ax"], g["ay"], g["bx"], g["by"])
            <= g["r"] + r
        )
    if typ in ("circle", "well"):
        return distance(g["x"], g["y"], a, b, c, d) <= g["r"] + r
    if typ == "rect":
        x, y, w, ht = g["x"], g["y"], g["w"], g["h"]
        return (
            segment_distance(a, b, c, d, x, y, x + w, y) <= r
            or segment_distance(a, b, c, d, x, y + ht, x + w, y + ht) <= r
            or segment_distance(a, b, c, d, x, y, x, y + ht) <= r
            or segment_distance(a, b, c, d, x + w, y, x + w, y + ht) <= r
            or x <= c <= x + w
            and y <= d <= y + ht
        )
    if typ == "ring":
        angle = math.atan2(d - g["y"], c - g["x"])
        diff = abs(math.atan2(math.sin(angle - g["gap"]), math.cos(angle - g["gap"])))
        if diff < g["gapWidth"] / 2:
            return False
        near = math.hypot(a - g["x"], b - g["y"]) - (g["r"] - g["speed"] * dt)
        far = math.hypot(c - g["x"], d - g["y"]) - g["r"]
        return (
            min(near, far) <= g["thickness"] + r
            and max(near, far) >= -g["thickness"] - r
        )
    return False


def defense_step(s, control):
    dt = 1 / HZ
    previous = s["time"]
    s["time"] += dt
    if s["time"] <= s["preparation"] + 1e-8:
        return
    for e in s["events"]:
        if not e["ready"] and s["time"] >= e["at"]:
            prepare(s, e)
    old = dict(s["player"])
    p = s["player"]
    if "target" in control:
        dx, dy = control["target"][0] - old["x"], control["target"][1] - old["y"]
    else:
        dx, dy = control.get("x", 0), control.get("y", 0)
    length = math.hypot(dx, dy)
    speed = s['d']['moveSpeed']
    travel = min(length, speed * dt) if "target" in control else speed * dt * min(length, 1)
    if length:
        p["x"] += dx / length * travel
        p["y"] += dy / length * travel
    for h in s["hazards"]:
        if h["type"] == "well" and h["start"] <= s["time"] < h["end"]:
            length = math.hypot(h["x"] - p["x"], h["y"] - p["y"])
            if 1 < length < 170:
                p["x"] += (h["x"] - p["x"]) / length * h["pull"] * dt
                p["y"] += (h["y"] - p["y"]) / length * h["pull"] * dt
    p["x"] = clamp(p["x"], 12, W - 12)
    p["y"] = clamp(p["y"], 12, H - 12)
    p["vx"] = (p["x"] - old["x"]) / dt
    p["vy"] = (p["y"] - old["y"]) / dt
    for h in s["hazards"]:
        if (
            h["disabled"]
            or h["end"] < previous
            or h["start"] > s["time"]
            or h["damageId"] in s["hitIds"]
        ):
            continue
        if touches(h, old, p, s["time"], dt):
            s["hitIds"].add(h["damageId"])
            s["contacts"].append(
                dict(
                    id=h["damageId"],
                    strike=h["strike"],
                    weight=h["weight"],
                    tier=h["tier"],
                    tick=jsround(s["time"] * HZ),
                )
            )
    s["hazards"] = [h for h in s["hazards"] if h["end"] >= s["time"]]


def replay(challenge, proof, elapsed):
    from arena_qte_rules import number

    if not isinstance(proof, dict):
        raise ValueError("Нет записи мини-игры.")
    p = profile(challenge["profile"])
    n = p["strikes"]
    is_attack = challenge["kind"] == "attack"
    total = math.ceil(duration(challenge) * HZ - 1e-7)
    if proof.get("abort") is True:
        if is_attack:
            return dict(mask=[False] * n, weights=[0] * n)
        # Skipping must never deal less damage than playing and getting hit.
        s = defense(
            p,
            challenge["stats"],
            challenge["seed"],
            challenge.get("enabled_strikes"),
            challenge.get("defense_preparation", 0),
        )
        all_hazards = {}
        for e in s["events"]:
            prepare(s, e)
            for h in s["hazards"]:
                if not h["disabled"]:
                    all_hazards[h["damageId"]] = dict(
                        id=h["damageId"],
                        strike=h["strike"],
                        weight=h["weight"],
                        tier=h["tier"],
                        tick=jsround(h["start"] * HZ),
                    )
        return dict(
            mask=[False] * n,
            contacts=sorted(all_hazards.values(), key=lambda h: (h["tick"], h["id"])),
            aborted=True,
        )
    ticks = proof.get("ticks")
    if type(ticks) is not int or not 0 <= ticks <= total:
        raise ValueError("Некорректное время мини-игры.")
    if elapsed + 0.15 < ticks / HZ:
        raise ValueError("Мини-игра ещё не могла завершиться.")
    if is_attack:
        clicks = proof.get("clicks")
        if not isinstance(clicks, list) or len(clicks) > n:
            raise ValueError("Слишком много нажатий.")
        s = attack(p, challenge["stats"], challenge["seed"])
        previous = -1
        for tick in clicks:
            if type(tick) is not int or not previous < tick <= ticks:
                raise ValueError("Нарушен порядок нажатий.")
            previous = tick
            s["time"] = min(s["duration"], tick / HZ)
            end = 1
            for i, slot in enumerate(s["slots"]):
                end += slot
                if s["time"] >= end - 1e-8 and s["results"][i] is None:
                    s["results"][i] = False
            f = attack_frame(s)
            i = f["index"]
            if not f["canHit"]:
                raise ValueError(
                    "Нажатие вне окна или попытка этого удара уже использована."
                )
            s["attempts"][i] += 1
            s["lastAttempt"][i] = s["time"]
            if abs(f["cursor"] - f["center"]) <= f["width"] / 2:
                s["results"][i] = True
            else:
                s["results"][i] = False
        # A closed tab is failure, not a way to shorten unplayed marks.
        if ticks < total and s["results"][-1] is None:
            raise ValueError("Атака ещё не завершена.")
        mask = [bool(v) for v in s["results"]]
        return dict(
            mask=mask,
            weights=[attack_weights(p)[i] if v else 0 for i, v in enumerate(mask)],
        )
    if ticks != total:
        raise ValueError("Защиту нужно пройти полностью.")
    events = proof.get("inputs")
    if not isinstance(events, list) or len(events) > total:
        raise ValueError("Слишком длинная запись управления.")
    previous = -1
    for e in events:
        if (
            not isinstance(e, dict)
            or type(e.get("t")) is not int
            or not previous < e["t"] < total
        ):
            raise ValueError("Нарушен порядок управления.")
        previous = e["t"]
        if "target" in e:
            if not isinstance(e["target"], list) or len(e["target"]) != 2:
                raise ValueError("Некорректная цель движения.")
            number(e["target"][0], 0, W)
            number(e["target"][1], 0, H)
        else:
            number(e.get("x", 0), -1, 1)
            number(e.get("y", 0), -1, 1)
    s = defense(
        p,
        challenge["stats"],
        challenge["seed"],
        challenge.get("enabled_strikes"),
        challenge.get("defense_preparation", 0),
    )
    index = 0
    control = {}
    for tick in range(total):
        if index < len(events) and events[index]["t"] == tick:
            control = events[index]
            index += 1
        defense_step(s, control)
    return dict(
        mask=[not any(c["strike"] == i for c in s["contacts"]) for i in range(n)],
        contacts=s["contacts"],
    )
