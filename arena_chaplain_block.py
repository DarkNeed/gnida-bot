"""Chaplain interception scores. Keep in sync with qte-block/engine chaplainThreats."""
import math

from arena_qte_patterns import random_values


def identity(p):
    ident = p['skill'].get('base_id', '')
    base = {'chaplain_hand': 0, 'chaplain_chime': 1, 'chaplain_verdict': 2}
    if ident in base:
        return 1, base[ident]
    if ident.startswith('chaplain_p'):
        return int(ident[10]), int(ident.rsplit('_', 1)[1])
    return None


def threats(p, seed, params):
    which = identity(p)
    if which is None:
        return None
    phase, move = which
    random = random_values((seed ^ p['seed']) & 0xFFFFFFFF)
    offset, sign = math.floor(next(random)*12)*math.pi/6, p['polarity']
    events = []

    def add(at, angle, kind='slash', motif='hand', weight=.3, **extra):
        pause = .30 if phase >= 3 and motif == 'hand' else 0
        warning = max(.68, params['warning']) + pause + (.18 if kind == 'wave' else 0)
        angle = math.atan2(math.sin(angle), math.cos(angle))
        tier = 'critical' if weight >= 1 else 'heavy' if weight >= .6 else 'normal' if weight >= .3 else 'minor'
        events.append(dict(at=at, warning=warning, angle=angle, kind=kind,
            motif=motif, tier=tier, weight=weight, pauseFor=pause,
            originAngle=angle-sign*(.85 if phase < 4 else 1.15),
            resolved=False, **extra))

    if move == 0 and phase <= 3:
        count = 8 if phase == 1 else 10
        for i in range(count):
            tick = i if phase == 1 else i//2-(i % 2) if phase == 2 else i
            add(2+i*6.3/(count-1), offset+sign*tick*math.pi/6,
                weight=.6 if i % 4 == 3 else .3)
    elif phase == 1 and move == 1:
        for i in range(4):
            a, at = offset+i*math.pi/2, 2+i*1.8
            add(at, a, motif='bell')
            add(at+.65, a, 'wave', 'bell', .6)
    elif phase == 1 and move == 2:
        for i in range(4):
            a, at = offset+sign*i*math.pi/2, 2+i*1.8
            add(at, a, motif='cut')
            add(at+.65, a+sign*math.pi/2, motif='cut', weight=.6)
    elif phase == 2 and move == 1:
        for i in range(3):
            a, at = offset+sign*i*math.pi/2, 2.4+i*2.4
            add(at-.65, a, 'feint', 'denied', 0)
            add(at, a, motif='window', weight=.6)
            add(at+.65, a+sign*math.pi/2, motif='window')
    elif phase == 2 and move == 2:
        for i in range(3):
            a, at = offset+sign*i*math.pi/2, 2+i*2.3
            add(at, a, motif='stamp')
            add(at+.62, a, motif='echo')
            add(at+1.30, a+math.pi, motif='stamp', weight=.6)
    elif phase == 3 and move == 1:
        for i in range(4):
            a, at = offset+sign*i*math.pi/2, 2+i*1.7
            add(at, a, motif='stamp')
            add(at+.65, a-sign*math.pi/2, motif='echo', weight=.6)
    elif phase == 3 and move == 2:
        for i in range(3):
            a, at = offset+sign*i*math.pi*2/3, 2.4+i*2.4
            add(at-.70, a, 'feint', 'denied', 0)
            add(at, a, motif='delete', weight=.6)
            add(at+.65, a, 'wave', 'delete', .6)
    elif phase == 4 and move == 0:
        for i in range(4):
            a, at = offset+sign*i*math.pi/2, 2+i*1.9
            add(at, a, motif='hand', weight=.1)
            add(at+.48, a-sign*math.pi/2, motif='echo')
            add(at+1.10, a, 'wave', 'clock', .6)
    elif phase == 4 and move == 1:
        for i in range(4):
            a, at = offset+sign*i*math.pi/2, 2.1+i*1.9
            add(at, a, 'wave', 'light', .6)
            add(at+.55, a, motif='light', weight=.1)
    elif phase == 4 and move == 2:
        for i in range(3):
            a, at = offset+sign*i*math.pi*2/3, 2.4+i*2.4
            add(at-.70, a, 'feint', 'denied', 0)
            add(at, a, motif='admin', weight=.6)
            add(at+.62, a-sign*math.pi/2, motif='hand')
            add(at+1.30, a, 'wave', 'admin', .6)
    events.sort(key=lambda e: e['at'])
    # The one-second preparation never eats a warning (including bonus warning time).
    delay = max(0, 1.02-min(e['at']-e['warning'] for e in events))
    for i, event in enumerate(events):
        event['at'] += delay
        event.update(id=f'block:{i}', strike=min(p['strikes']-1, math.floor(i*p['strikes']/len(events))))
    return events
