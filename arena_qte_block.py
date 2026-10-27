"""Authoritative blocking replay; accepts input, never client damage/results."""

import math
from arena_qte_patterns import profile, random_values, impact, clamp

HZ = 120
DURATION = 9.5


def parameters(p, stats):
    armor = max(
        0,
        stats.get(
            (
                "magicDefense"
                if p["skill"].get("damage_type") == "magic"
                else "physicalDefense"
            ),
            0,
        ),
    )
    attack = max(0, stats.get("enemyAttack", 0))
    accuracy = clamp(stats.get("enemyAccuracy", 0), 0, 100)
    strength = armor / (armor + attack + 20)
    return dict(
        armor=armor,
        strength=strength,
        armorMultiplier=100 / (100 + 4 * armor),
        maxStamina=70 + strength * 90,
        arc=(90 + strength * 100) * math.pi / 180,
        perfectWindow=clamp(0.16 + strength * 0.18 - accuracy * 0.0004, 0.12, 0.28),
        recovery=32 + strength * 22,
        rotation=math.pi * 4 * clamp(stats.get('controlScale', 1), .5, 1),
        warning=max(.36, (0.95 - accuracy * 0.003) * (1 - .05 * max(0, p.get('chaplain', 0)-1))) + stats.get('extraWarning', 0),
        pressure=clamp((attack + 20) / (armor + 30), 0.65, 1.5),
        blockReduction=0.75,
    )


def threats(p, seed, params):
    copy=p['skill'].get('copy_skill')
    if p['skill'].get('base_id')=='nz_pandora_p2_1' and copy and copy.get('base_id')!='mana_shot' and not copy.get('base_id','').startswith('nz_'):
        return threats(profile(copy),seed,dict(params,warning=params['warning']+.20))
    from arena_nazarick_patterns import block_threats as nazarick_threats
    nazarick = nazarick_threats(p, seed, params)
    if nazarick is not None:
        return nazarick
    from arena_casino_qte import block_threats
    casino=block_threats(p,seed,params)
    if casino is not None:return casino
    from arena_chaplain_block import threats as chaplain_threats
    special = chaplain_threats(p, seed, params)
    if special is not None:
        return special
    random = random_values((seed ^ p["seed"]) & 0xFFFFFFFF)
    shot = p["kind"] in (
        "gun",
        "mana",
        "charm",
        "stars",
        "paint",
        "death",
        "ice",
        "coins",
        "script",
        "hack",
    )
    area = p["kind"] in (
        "fire",
        "void",
        "eclipse",
        "holy",
        "portal",
        "dust",
        "lightning",
        "mirror",
    )
    count = int(
        clamp((12 if shot else 8) + p["strikes"] + (2 if p["kit"] else 0) + 2 * max(0,p.get('chaplain',0)-1), 8, 24)
    )
    offset = math.floor(next(random) * 8)
    result = []
    for i in range(count):
        wave = area and (i % 3 == 2 or p["kind"] == "void" and i % 3 == 1)
        strike = min(p["strikes"] - 1, math.floor(i * p["strikes"] / count))
        force = impact(p, strike)
        minor = shot and i % 3 != 2
        tier = (
            "heavy"
            if wave
            else "minor" if minor else "critical" if i == count - 1 else force["tier"]
        )
        weight = (
            0.6 if wave else 0.1 if minor else 1 if i == count - 1 else force["weight"]
        )
        at = 2 + i * (8.5 - 1.4) / (count - 1) + (next(random) - 0.5) * 0.10
        # JS remainder keeps its sign; don't normalize negative angles here.
        direction = (
            offset
            + p["polarity"] * (math.floor(i / 2) if shot else i)
            + (2 if i % 4 == 3 else 0)
        )
        direction = (direction - math.trunc(direction / 8) * 8) * math.pi / 4
        result.append(
            dict(
                id=f"block:{i}",
                at=at,
                warning=params["warning"] + (0.18 if wave else 0),
                angle=direction,
                kind="wave" if wave else "bolt" if shot else "slash",
                tier=tier,
                weight=weight,
                strike=strike,
                resolved=False,
            )
        )
    return result


def create(challenge):
    p = profile(challenge["profile"])
    params = parameters(p, challenge["stats"])
    from arena_nazarick_patterns import block_duration
    return dict(
        p=p,
        params=params,
        time=0,
        preparation=1,
        duration=block_duration(p),
        stamina=params["maxStamina"],
        angle=0,
        active=False,
        requested=False,
        raisedAt=-100,
        lastRaise=-100,
        loweredAt=-100,
        perfectUntil=-100,
        brokenUntil=-100,
        events=threats(p, challenge["seed"], params),
        contacts=[],
        enabled=challenge.get("enabled_strikes"),
    )


def angle_diff(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def step(s, command):
    dt = 1 / HZ
    s["time"] += dt
    if s["time"] <= 1 + 1e-8:
        return
    p = s["params"]
    from arena_nazarick_patterns import time_stopped
    frozen=time_stopped(s)
    if "angle" in command and not frozen:
        s["angle"] += clamp(
            angle_diff(command["angle"], s["angle"]),
            -p["rotation"] * dt,
            p["rotation"] * dt,
        )
    requested = bool(command.get("active")) and not frozen
    can_raise = requested and s["time"] >= s["brokenUntil"]
    if can_raise and not s["active"]:
        s["raisedAt"] = s["time"]
        if (
            not s["requested"]
            and s["time"] - s["loweredAt"] >= 0.10 - 1e-8
            and s["time"] - s["lastRaise"] >= 0.32 - 1e-8
        ):
            s["perfectUntil"] = s["time"] + p["perfectWindow"]
            s["lastRaise"] = s["time"]
        else:
            s["perfectUntil"] = -100
    if not can_raise and s["active"]:
        s["loweredAt"] = s["time"]
        s["perfectUntil"] = -100
    s["active"], s["requested"] = can_raise, requested
    s["stamina"] = clamp(
        s["stamina"] + (-2 if s["active"] else p["recovery"]) * dt, 0, p["maxStamina"]
    )
    for event in s["events"]:
        if event["resolved"] or s["time"] < event["at"] - 1e-8:
            continue
        event["resolved"] = True
        if s["enabled"] is not None and not s["enabled"][event["strike"]]:
            continue
        if event['kind'] == 'feint':
            if s['active']:
                s['stamina'] = max(0, s['stamina']-12*p['pressure'])
            s['contacts'].append(dict(id=event['id'], strike=event['strike'], tier=event['tier'],
                weight=0, reduction=0, blocked=False, outcome='feint', tick=round(s['time']*HZ)))
            continue
        cost = (30 if event["kind"] == "wave" else 42 * event["weight"]) * p["pressure"]
        facing = (
            event["kind"] == "wave"
            or abs(angle_diff(s["angle"], event["angle"])) <= p["arc"] / 2
        )
        recent = event["kind"] != "wave" or s["time"] - s["raisedAt"] <= 0.55
        can_block = s["active"] and s["time"] >= s["brokenUntil"] and facing and recent
        perfect = can_block and s["time"] <= s["perfectUntil"] + 1e-8
        reduction, outcome = 0, "miss"
        if perfect:
            reduction, outcome = 1, "perfect"
            s["stamina"] = min(p["maxStamina"], s["stamina"] + 4)
        elif can_block:
            share = min(1, s["stamina"] / cost)
            reduction = p["blockReduction"] * share
            s["stamina"] = max(0, s["stamina"] - cost)
            outcome = "block" if share >= 1 else "break"
            if share < 1:
                s.update(
                    brokenUntil=s["time"] + 0.65,
                    loweredAt=s["time"],
                    active=False,
                    perfectUntil=-100,
                )
        s["contacts"].append(
            dict(
                id=event["id"],
                strike=event["strike"],
                tier=event["tier"],
                weight=event["weight"] * (1 - reduction),
                reduction=reduction,
                blocked=reduction > 0,
                outcome=outcome,
                tick=round(s["time"] * HZ),
                **({'status':event['status']} if event.get('status') and reduction<1 else {}),
            )
        )


def replay(challenge, proof, elapsed):
    from arena_qte_rules import number

    if challenge.get("kind") != "defense" or challenge.get("defense_mode") != "block":
        raise ValueError("Некорректный этап блокирования.")
    if not isinstance(proof, dict):
        raise ValueError("Нет записи блокирования.")
    s = create(challenge)
    n = s["p"]["strikes"]
    abort = proof.get("abort") is True
    if abort:
        contacts = [
            dict(
                id=e["id"],
                strike=e["strike"],
                weight=e["weight"],
                tier=e["tier"],
                reduction=0,
                blocked=False,
                outcome="miss",
                tick=round(e["at"] * HZ),
                **({'status':e['status']} if e.get('status') else {}),
            )
            for e in s["events"]
            if s["enabled"] is None or s["enabled"][e["strike"]]
        ]
    else:
        ticks, events = proof.get("ticks"), proof.get("inputs")
        total=round(s['duration']*HZ)
        if type(ticks) is not int or ticks != total or elapsed + 0.15 < ticks / HZ:
            raise ValueError("Блокирование нужно пройти полностью.")
        if not isinstance(events, list) or len(events) > total:
            raise ValueError("Некорректная запись управления.")
        previous = -1
        for event in events:
            if (
                not isinstance(event, dict)
                or type(event.get("t")) is not int
                or not previous < event["t"] < total
            ):
                raise ValueError("Нарушен порядок управления.")
            if type(event.get("active")) is not bool:
                raise ValueError("Некорректное поднятие щита.")
            number(event.get("angle"), -math.pi, math.pi)
            previous = event["t"]
        index, command = 0, {}
        for tick in range(total):
            if index < len(events) and events[index]["t"] == tick:
                command = events[index]
                index += 1
            step(s, command)
        contacts = s["contacts"]
    return dict(
        mode="block",
        mask=[
            not any(c["strike"] == i and c["weight"] > 0 for c in contacts)
            for i in range(n)
        ],
        contacts=contacts,
    )
