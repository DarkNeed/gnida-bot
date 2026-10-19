"""Authoritative replay of the approved mini-games. Client results are never accepted."""

import math

HZ = 120
DURATION = 720


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def parameters(stats, pattern=None):
    a = clamp((stats["accuracy"] - stats["enemyEvasion"]) / 100, -1, 1)
    d = clamp((stats["enemyAccuracy"] - stats["evasion"]) / 100, -1, 1)
    curtains = pattern in ("slashes", "rain")
    p = dict(
        zone=clamp(0.13 + a * 0.16, 0.075, 0.29),
        cursor=clamp(0.85 - a * 0.28, 0.57, 1.13),
        bulletSpeed=(340 + d * 75) * dict(slashes=1.55, rain=1.6).get(pattern, 1),
        radius=5.5 + d * 1.5,
        warning=0.58 - d * 0.24 if curtains else 0.8 - d * 0.2,
        count=4 if d > 0.65 else 2 if d < -0.25 else 3,
        moveSpeed=240,
    )
    if curtains:
        p["gap"] = 152 - d * 52 if pattern == "rain" else 110 - d * 32
    return p


def random_values(seed):
    while True:
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        yield seed / 4294967296


def number(value, low, high):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("Некорректная запись мини-игры.")
    return value


def replay(challenge, proof, elapsed):
    if not isinstance(proof, dict):
        raise ValueError("Нет записи мини-игры.")
    if proof.get("abort") is True:
        return [False] * challenge["strikes"]
    ticks = proof.get("ticks")
    if type(ticks) is not int or not 0 <= ticks <= DURATION:
        raise ValueError("Некорректное время мини-игры.")
    if elapsed + 0.15 < ticks / HZ:
        raise ValueError("Мини-игра ещё не могла завершиться.")
    stats = challenge["stats"]
    if challenge["kind"] == "attack":
        clicks = proof.get("clicks")
        if not isinstance(clicks, list) or len(clicks) > challenge["strikes"]:
            raise ValueError("Некорректные нажатия.")
        n = challenge["strikes"]
        slot = 0.95 if n > 1 else 2.8
        if ticks > math.ceil(n * slot * HZ):
            raise ValueError("Некорректная длительность атаки.")
        p = parameters(stats)
        random = random_values(challenge["seed"])
        zones = [0.3 + next(random) * 0.4 for _ in range(n)]
        result = [False] * n
        seen = set()
        previous = -1
        for tick in clicks:
            if type(tick) is not int or not previous <= tick <= ticks:
                raise ValueError("Нарушен порядок нажатий.")
            previous = tick
            index = min(n - 1, int((tick / HZ) / slot))
            if index in seen or tick / HZ >= n * slot:
                raise ValueError("Повторное нажатие на одну отметку.")
            seen.add(index)
            local = tick / HZ - index * slot
            cursor = 1 - abs((local * p["cursor"] * 2) % 2 - 1)
            result[index] = abs(cursor - zones[index]) <= p["zone"] / 2
        # Early finish is allowed only after committing the last timing window.
        if ticks < math.ceil(n * slot * HZ) and n - 1 not in seen:
            raise ValueError("Атака ещё не завершена.")
        return result
    if ticks != DURATION:
        raise ValueError("Защиту нужно пройти полностью.")
    events = proof.get("inputs")
    if not isinstance(events, list) or len(events) > 760:
        raise ValueError("Слишком длинная запись управления.")
    previous = -1
    for event in events:
        if (
            not isinstance(event, dict)
            or type(event.get("t")) is not int
            or not previous < event["t"] < DURATION
        ):
            raise ValueError("Нарушен порядок управления.")
        previous = event["t"]
        if "target" in event:
            target = event["target"]
            if not isinstance(target, list) or len(target) != 2:
                raise ValueError("Некорректная цель движения.")
            number(target[0], 0, 720)
            number(target[1], 0, 320)
        else:
            number(event.get("x", 0), -1, 1)
            number(event.get("y", 0), -1, 1)
    received = defense_replay(stats, challenge["pattern"], challenge["seed"], events)
    visual_count = dict(slashes=6, rain=3, cross=4)[challenge["pattern"]]
    n = challenge["strikes"]
    # A single hit requires a clean trial. Multi-hits are checked separately.
    return [
        not any(min(n - 1, int(i * n / visual_count)) == j for i in received)
        for j in range(n)
    ]


def distance(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    t = clamp((-x1 * dx - y1 * dy) / (dx * dx + dy * dy or 1), 0, 1)
    return math.hypot(x1 + dx * t, y1 + dy * t)


def defense_replay(stats, pattern, seed, events):
    p = parameters(stats, pattern)
    random = random_values(seed)
    curtain = pattern != "cross"
    pulses = 3 if pattern == "rain" else 2 if pattern == "slashes" else 1
    count = dict(slashes=6, rain=3, cross=4)[pattern]
    axis = 720 if pattern == "rain" else 320
    center = 720 * 0.32 if pattern == "rain" else 160
    direction = 1
    if curtain:
        next(random)
        direction = -1 if next(random) < 0.5 else 1
    advance = (
        55 + (stats["enemyAccuracy"] - stats["evasion"]) * 0.18
        if pattern == "rain"
        else 26 + (stats["enemyAccuracy"] - stats["evasion"]) * 0.08
    )
    waves = []
    for i in range(count * pulses):
        if curtain:
            center += direction * advance * (0.85 + next(random) * 0.3)
            lo = p["gap"] / 2 + 14
            hi = axis - lo
            if center > hi:
                center = hi - (center - hi)
                direction = -1
            if center < lo:
                center = lo + (lo - center)
                direction = 1
        waves.append(
            dict(
                strike=i // pulses,
                at=0.2
                + i
                * (0.28 if pattern == "slashes" else 0.5 if pattern == "rain" else 0.6),
                lane=center / axis if curtain else 0.17 + next(random) * 0.66,
                reverse=curtain and i % 3 == 2,
                warned=False,
                spawned=False,
            )
        )
    bullets = []
    received = set()
    x = 720 * 0.32
    y = 160.0
    time = 0.0
    event_index = 0
    control = {}
    dt = 1 / HZ
    r = p["radius"]
    speed = p["bulletSpeed"]
    for tick in range(DURATION):
        if event_index < len(events) and events[event_index]["t"] == tick:
            control = events[event_index]
            event_index += 1
        oldx = x
        oldy = y
        if "target" in control:
            dx = control["target"][0] - x
            dy = control["target"][1] - y
        else:
            dx = control.get("x", 0)
            dy = control.get("y", 0)
        length = math.hypot(dx, dy)
        travel = (
            min(length, 240 * dt) if "target" in control else 240 * dt * min(length, 1)
        )
        if length:
            x += dx / length * travel
            y += dy / length * travel
        x = clamp(x, 12, 708)
        y = clamp(y, 12, 308)
        time += dt
        for wave in waves:
            if not wave["warned"] and time >= wave["at"]:
                wave["warned"] = True
                if not curtain and wave["strike"] % 2 == 0:
                    wave["lane"] = y / 320
                    wave["crossLane"] = x / 720
            if wave["spawned"] or time < wave["at"] + p["warning"]:
                continue
            wave["spawned"] = True

            def add(bx, by, vx, vy):
                bullets.append([bx, by, vx, vy, wave["strike"]])

            if curtain:
                reverse = wave["reverse"]
                sign = 1 if reverse else -1
                for coordinate in range(0, axis + 1, 16):
                    if abs(coordinate - wave["lane"] * axis) < p["gap"] / 2:
                        continue
                    if pattern == "rain":
                        add(coordinate, 335 if reverse else -15, 0, -sign * speed)
                    else:
                        add(-15 if reverse else 735, coordinate, sign * speed, 0)
            else:
                for j in range(p["count"]):
                    offset = (j - (p["count"] - 1) / 2) * 27
                    add(735, wave["lane"] * 320 + offset, -speed, 0)
                    add(
                        wave.get("crossLane", wave["lane"]) * 720 + offset,
                        -15,
                        0,
                        speed,
                    )
        for b in bullets:
            bx, by = b[:2]
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if distance(bx - oldx, by - oldy, b[0] - x, b[1] - y) <= r + 6:
                received.add(b[4])
        bullets = [b for b in bullets if -40 < b[0] < 760 and -40 < b[1] < 360]
    return received
