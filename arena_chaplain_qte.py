"""Chaplain phase patterns; mirrored exactly by qte-unique/engine."""
import math


def prepare(s, e, add, beam, circle, bullet):
    p, d, player = s['p'], s['d'], s['player']
    phase = p['chaplain']
    move = int(p['skill']['base_id'].rsplit('_', 1)[1])
    x, y, i = player['x'], player['y'], e['index']
    sign = 1 if i % 2 else -1
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    history = s.get('history', [])
    old = next((v for v in reversed(history) if v['t'] <= s['time'] - .6), dict(x=x, y=y))
    start = e['at'] + d['warning']
    def hand(theta, length, turn, delay=0, duration=.36):
        add(dict(type='line', ax=600, ay=155,
                 bx=600+math.cos(theta)*length, by=155+math.sin(theta)*length,
                 r=8*d['beamScale'], motif='clock_hand', clockTurn=turn), delay, duration)

    if phase == 2 and move == 0:
        angle = math.atan2(y-155, x-600)
        hand(angle-sign*.10, 650, sign*.45)
        hand(angle+sign*.20, 420, -sign*.40, .48)
    elif (phase == 2 and move == 1) or (phase >= 3 and move == 2):
        width, height = (100, 72) if phase == 2 else (125, 86)
        add(dict(type='rect', x=clamp(x-width/2, 0, 720-width), y=clamp(y-height/2, 0, 320-height),
                 w=width, h=height, label='ДОСТУП ЗАПРЕЩЁН'), 0, .22)
        if phase >= 3:
            beam(0, old['y'], 720, old['y'], 7, .32, .16)
        if phase == 4:
            beam(old['x'], 0, old['x'], 320, 7, .58, .16)
    elif phase == 2 and move == 2:
        circle(old['x'], old['y'], 28, .12, .2)
        beam(x, 0, x, 320, 7, .42, .16)
    elif move == 0:
        bx, by = (30 if sign > 0 else 690), 45 + e['jitter'] * 230
        angle = math.atan2(y-by, x-bx)
        for j in range(-2, 3):
            a = angle + j * .15
            bullet(bx, by, math.cos(a) * d['speed'] * .8, math.sin(a) * d['speed'] * .8,
                   7 if j == 0 else 5, 0, motif='clock', tier='normal' if j == 0 else 'minor',
                   freezeAt=.20, freezeFor=.35)
        if phase == 4:
            hand(math.atan2(old['y']-155, old['x']-600), 650, sign*.32, .65, .30)
    elif phase == 3 and move == 1:
        # Visible pre-announced teleport; no swept collision along the jump.
        if i in (1, 3):
            s.setdefault('relocations', []).append(dict(at=start+.20, x=old['x'], y=old['y'],
                                                        warning=e['at'], done=False))
        circle(old['x'], old['y'], 26, .72, .18)
        beam(0, y, 720, y, 7, .4, .16)
    elif phase == 4 and move == 1:
        half = 68 - 8*d['intensity']
        gap = clamp(y + sign * 42, half+12, 320-half-12)
        add(dict(type='rect', x=0, y=0, w=720, h=max(0, gap-half), label='СВЕТ'), 0, .14)
        add(dict(type='rect', x=0, y=gap+half, w=720, h=max(0, 320-gap-half), label='СВЕТ'), 0, .14)
        if i % 2:
            beam(x, 0, x, 320, 6, .58, .14)
