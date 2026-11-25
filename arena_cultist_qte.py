"""Cultist defense choreography. Mirror the pure canvas engine functions."""
from math import atan2, cos, pi, sin, tau

W, H = 720, 320
RHYTHM = {
    "cult_sign": (4, 4.05),
    "cult_voice": (4, 3.90),
    "cult_rite": (3, 3.15),
    "cult_depths": (4, 4.10),
    "arch_cultist_cthulhu": (3, 3.80),
    "arch_cultist_yog": (4, 3.90),
    "cult_roots": (4, 4.10),
    "cult_yellow": (4, 4.20),
    "arch_cultist_hastur": (3, 4.18),
}
BLOCK = {
    # (delay, eighth-turn from base angle, kind, weight, art)
    "cult_sign": ((0, 0, "slash", .29, "cult_ink"), (.53, 2, "slash", .36, "cult_eye")),
    "cult_voice": ((0, 0, "slash", .32, "cult_echo"), (.63, 4, "wave", .45, "cult_echo")),
    "cult_rite": ((0, -1, "bolt", .18, "cult_wax"), (.40, 0, "bolt", .18, "cult_wax"),
                  (1.02, 0, "wave", .43, "cult_altar"), (1.55, 4, "bolt", .32, "cult_wax")),
    "cult_depths": ((0, 0, "feint", 0, "cult_wraith"), (.55, 3, "slash", .31, "cult_wraith"),
                    (1.01, -1, "bolt", .42, "cult_wraith")),
    "arch_cultist_cthulhu": ((0, 0, "wave", .58, "cult_tide"),
                             (.92, 4, "slash", .37, "cult_limb")),
    "arch_cultist_yog": ((0, 0, "bolt", .20, "cult_comet"), (.58, 4, "bolt", .34, "cult_sphere"),
                         (.94, 5, "bolt", .21, "cult_sphere")),
    "cult_roots": ((0, 0, "slash", .19, "cult_root"), (.38, -2, "slash", .21, "cult_root"),
                   (.83, 2, "slash", .33, "cult_root")),
    "cult_yellow": ((0, 0, "feint", 0, "cult_mask"), (.65, 2, "slash", .33, "cult_mask"),
                    (1.19, -2, "bolt", .32, "cult_mask")),
    "arch_cultist_hastur": ((0, 0, "slash", .36, "cult_actor"),
                           (.79, 0, "slash", .32, "cult_reprise"), (1.46, 4, "wave", .48, "cult_curtain")),
}


def block_threats(p, seed, params):
    spec = BLOCK.get(p["skill"].get("base_id"))
    if spec is None:
        return None
    from arena_qte_patterns import random_values
    offset = int(next(random_values(seed ^ p["seed"])) * 8)
    result = []
    for cycle in range(3):
        for delay, shift, kind, weight, motif in spec:
            # Three acts, separate shields/angles; duplicate directions are
            # intentional only for Carcosa's delayed reprise.
            angle = (offset + cycle*3 + shift)*pi/4
            result.append(dict(id=f"block:{len(result)}", at=2.02+cycle*2.58+delay,
                               angle=atan2(sin(angle), cos(angle)), kind=kind, motif=motif,
                               tier="heavy" if weight >= .42 else "normal" if weight >= .26 else "minor",
                               warning=max(.59, params["warning"])+(.14 if kind == "wave" else 0),
                               weight=weight, resolved=False))
    for i, threat in enumerate(result):
        threat["strike"] = min(p["strikes"]-1, i*p["strikes"]//len(result))
    return result


def prepare(s, e, add, ident):
    if ident not in RHYTHM:
        return False
    d, at = s["d"], s["player"]
    i, j = e["index"], e["jitter"]
    odd, sign = i % 2, (1 if i % 2 else -1)
    pace = 1 + .20 * d["intensity"]
    clamp = lambda v, a, b: max(a, min(b, v))
    x = clamp(at["x"] + at.get("vx", 0) * min(d["lead"], .12), 24, W - 24)
    y = clamp(at["y"] + at.get("vy", 0) * min(d["lead"], .12), 24, H - 24)

    def line(ax, ay, bx, by, motif, delay=0, duration=.22, width=9, *, weight=.28, **extra):
        add(dict(type="line", ax=ax, ay=ay, bx=bx, by=by, r=width,
                 motif=motif, tier="normal", weight=weight, **extra), delay, duration)

    def disc(cx, cy, radius, motif, delay=0, duration=.26, weight=.48, **extra):
        add(dict(type="circle", x=cx, y=cy, r=radius, motif=motif,
                 tier="heavy", weight=weight, **extra), delay, duration)

    def bolt(bx, by, vx, vy, motif, delay=0, duration=1.8, weight=.16, *, r=8, **extra):
        add(dict(type="bullet", x=bx, y=by, vx=vx, vy=vy, r=r,
                 motif=motif, tier="normal" if weight >= .22 else "minor",
                 weight=weight, **extra), delay, duration)

    def edge(index):
        u = (index % 1)*(2*(W+H-48))
        if u < W-24:
            return 12+u, 12
        u -= W-24
        if u < H-24:
            return W-12, 12+u
        u -= H-24
        return (W-12-u, H-12) if u < W-24 else (12, H-12-(u-(W-24)))

    if ident == "cult_sign":
        # A seal opens underfoot. Its hooked spokes sweep as it opens,
        # leaving one broad sector rather than a stationary dodge circle.
        a = atan2(H/2-y, W/2-x) + sign*(.48+.32*j)
        for n in range(5):
            b = a+1.10+n*.94
            line(x, y, x+cos(b)*162, y+sin(b)*162, "cult_ink", .04*(n%2), .56, 8,
                 cultGrow=.34, clockTurn=sign*.94, damageGroup="seal_blades", weight=.24)
        disc(x, y, 58+7*d["intensity"], "cult_eye", .13, .42)
    elif ident == "cult_voice":
        # The two halves of a spoken fracture slide in opposite directions.
        # Their stuttering speed is rhythmic, not tied to the render rate.
        center = clamp(x+sign*(65+j*42), 115, W-115)
        gap = 110-20*d["intensity"]
        for n, (lo, hi) in enumerate(((-20, center-gap/2), (center+gap/2, W+20))):
            add(dict(type="polyline", motif="cult_echo", r=11+n*2, tier="normal", weight=.37,
                     fold=(lo, hi, -25 if (odd+n)%2 else H+25, 285*pace*(1 if (odd+n)%2 else -1),
                           j*tau+n*1.5, sign*(18+n*5)), tone=n), n*.20, 1.24)
    elif ident == "cult_rite":
        # One continuous procession: each flame settles at the altar, then
        # leaves from that exact seat and sweeps a different part of the rim.
        cx, cy = W/2+(j-.5)*54, H/2+sign*12
        candle = 0
        for layer, (count, radius, stretch) in enumerate(((12, 132, 2.56), (8, 95, 2.3))):
            for n in range(count):
                if (n-i*2-layer*3) % count < (2 if layer == 0 else 1):
                    continue
                a = e["angle"]+n*tau/count
                delay = layer*.17+n%2*.045
                gather = 1.13-delay+n%3*.035
                release = 1.43+layer*.10+n%2*.055
                speed = sign*(1.50 if layer == 0 else -1.25)
                bolt(cx+cos(a)*radius*stretch, cy+sin(a)*radius, 0, 0, "cult_wax",
                     delay, release-delay, .16, r=9, orbit=True, cx=cx, cy=cy,
                     orbitRadius=radius, orbitStretch=stretch, orbitAngle=a,
                     orbitSpeed=speed, spiral=(11-radius)/gather, riteGather=gather,
                     damageGroup=f"gather:{layer}", candle=candle)
                b = a+speed*gather
                bx, by = cx+cos(b)*11*stretch, cy+sin(b)*11
                tx, ty = (clamp(at["x"],12,W-12),clamp(at["y"],12,H-12)) if candle==16 else edge(candle/16+i*.063+j*.05)
                travel = .74+.09*layer
                bolt(bx, by, (tx-bx)/travel, (ty-by)/travel, "cult_wax", release,
                     travel+.08, .22, r=9, waveA=(12+layer*7)*sign if candle!=16 else 0,
                     waveF=tau/travel, riteOut=True, candle=candle, damageGroup=f"scatter:{layer}")
                candle += 1
        disc(cx, cy, 51, "cult_altar", 1.21, .23)
    elif ident == "cult_depths":
        # Obscured imagery drifts through the player; the dark silhouettes
        # tear away from their reflections as they start dealing damage.
        side = 7 if odd else W-7
        anchors = ((side, clamp(y-sign*75, 24, H-24)),
                   (clamp(x-140, 30, W-30), 9 if odd else H-9),
                   (clamp(x+155, 30, W-30), H-9 if odd else 9),
                   (W-side, clamp(y+sign*122, 20, H-20)),
                   (clamp(x+sign*(220+j*52), 24, W-24), H-9 if odd else 9))
        for n, (ax, ay) in enumerate(anchors):
            angle = atan2(y-ay, x-ax)+sign*(n-2)*.12
            speed = (203+n*17)*pace
            bolt(ax, ay, cos(angle)*speed, sin(angle)*speed, "cult_wraith", n*.115, 1.62,
                 .24 if n in (0, 2) else .17, r=15 if n%2 else 19,
                 waveA=sign*(27+n*7)*(1 if n%2 else -1), waveF=5.1+n*.39, vision=n)
        for n in (0, 1):
            bolt(W-side, 47+214*n, -sign*215, sign*(1-2*n)*40, "cult_wraith", .38+n*.08, 1.53,
                 0, r=19, waveA=36*(1-2*n), waveF=4.6, vision=n+5, visualOnly=True)
    elif ident == "arch_cultist_cthulhu":
        # The backwash comes from the opposite shoreline before the first
        # breaker settles; it bends the channel, not the player's controls.
        for n in (0, 1):
            direction = sign*(1-2*n)
            gap = 113-14*d["intensity"]-n*12
            cy = clamp(y+sign*(33+24*j)-sign*n*50, gap/2+29, H-gap/2-29)
            for bank in (0, 1):
                add(dict(type="polyline", x=-42 if direction>0 else W, r=20,
                         cultSlide=direction*(495+n*81)*pace, motif="cult_tide", routeY=cy,
                         routeGap=gap, tideBank=bank, tideBend=19+6*n, tidePhase=sign*n*1.24,
                         tier="heavy", weight=.42, damageGroup=f"tide:{n}"), n*.94, 1.64)
        for n in (0, 1):
            wx = clamp(x+sign*(127 if n else -112), 61, W-61)
            wy = clamp(y+sign*(87 if n else -79), 43, H-43)
            add(dict(type="well", x=wx, y=wy, r=29, pull=34, motif="cult_sink",
                     tier="normal", weight=.22), .28+n*.34, .88)
    elif ident == "arch_cultist_yog":
        for pair in (0, 1):
            facing = sign*(1-2*pair)
            ex = 111+pair*19 if facing>0 else W-111-pair*19
            ey = 47+j*51 if (odd+pair)%2 else H-47-j*51
            gx, gy = W-ex, H-ey+sign*19
            delay = pair*.49
            for n in (-1, 1):
                px, py = gx-facing*87, gy+n*29
                bolt(px, py, (gx-px)/.32, (gy-py)/.32, "cult_comet",
                     delay+.045*(n+1), .32, .11)
            aim = 0 if facing>0 else pi
            tilt = atan2(y-ey, max(90, abs(x-ex)))*facing*.28
            for n in range(-2, 3):
                a = aim+tilt+.31*n
                v = (280+abs(n)*17)*pace
                bolt(ex, ey, cos(a)*v, sin(a)*v, "cult_sphere", delay+.38+.065*abs(n), 1.56,
                     .23 if n == 0 else .13, r=10 if n == 0 else 8,
                     waveA=facing*(18+abs(n)*10)*(1 if n >= 0 else -1), waveF=4.5+abs(n)*.7,
                     gate_x=gx, gate_y=gy, gate_show=n == 0, gate_pair=pair)
    elif ident == "cult_roots":
        # Stagger wall tips so they can follow, but cannot instantly turn.
        side = 0 if x < W/2 else W
        anchors = ((clamp(x-sign*(80+j*42), 28, W-28), 0 if odd else H),
                   (side, clamp(y+sign*(60+j*26), 25, H-25)),
                   (clamp(x+sign*(99+j*45), 28, W-28), H if odd else 0))
        for n, (ax, ay) in enumerate(anchors):
            a = atan2(y-ay, x-ax) + sign*(n-1)*.31
            speed = (177+13*n)*pace
            bolt(ax, ay, cos(a)*speed, sin(a)*speed, "cult_root",
                 n*.24, 1.94, .26, r=10, homing=1.32, turnRate=2.9,
                 vineStop=1.47, vineBody=7.5, vineTwig=3, cultVine=True)
    elif ident == "cult_yellow":
        # Two performers and two literally hollow understudies. They move
        # across the stage, instead of standing on round damage markers.
        near = clamp(x+sign*(142+j*54), 46, W-46)
        far = clamp(x-sign*(116+j*61), 46, W-46)
        for n, (ax, ay) in enumerate(((near, 18 if odd else H-18),
                                     (far, H-18 if odd else 18),
                                     (W-14 if odd else 14, clamp(y-sign*76, 30, H-30)),
                                     (14 if odd else W-14, clamp(y+sign*93, 30, H-30)))):
            decoy = (n%2 == 1)
            a = atan2(y-ay, x-ax)+sign*(.44 if decoy else -.19)
            speed = (194 if n<2 else 258)*pace
            bolt(ax, ay, cos(a)*speed, sin(a)*speed, "cult_mask", .12+n*.24, 1.39,
                 0 if decoy else .36, r=17, waveA=sign*(36+n*3), waveF=5.9-n*.4, visualOnly=decoy)
    else:
        old = s.get("cultCue")
        s["cultCue"] = (x, y)
        if i == 0:
            disc(x, y, 64+8*d["intensity"], "cult_stage", .12, .38, .47)
            for n in (0, 1):
                bx, by = (9, 46) if n else (W-9, H-52)
                py = clamp(y+(1-2*n)*52, 25, H-25)
                travel = .75+.10*n
                bolt(bx, by, (x-bx)/travel, (py-by)/travel, "cult_actor", .17+.20*n,
                     travel+.22, .30, r=15, length=29, waveA=27*(1-2*n), waveF=tau/travel,
                     crossing=travel)
        elif i == 1:
            ox, oy = old or (x, y)
            for n, (tx, ty) in enumerate(((ox, oy),(W-ox, H-oy),(x, y))):
                bx = clamp(tx+sign*(95-95*n), 24, W-24)
                by = H-8 if n%2 else 8
                travel = .65+.08*n
                bolt(bx, by, (tx-bx)/travel, (ty-by)/travel, "cult_actor", .12+.23*n,
                     travel+.25, .28, r=16, length=23, waveA=38*(1-2*(n%2)), waveF=tau/travel,
                     replay_x=tx, replay_y=ty, reprise=True, crossing=travel)
            disc(ox, oy, 55, "cult_reprise", .78, .38, .35)
        else:
            center = clamp(x+(1 if x<W/2 else -1)*(86+j*34), 90, W-90)
            gap = 138-17*d["intensity"]
            for bank in (0, 1):
                add(dict(type="rect", x=0, y=0, w=0, h=H, motif="cult_curtain", tier="heavy",
                         weight=.49, drapeBank=bank, drapeEdge=center+(1 if bank else -1)*gap/2,
                         damageGroup="curtain"), .05+.14*bank, 1.33)
    return True
