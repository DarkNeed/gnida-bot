"""Committed casino attacks. No wager, franc balance or client-supplied damage."""

import random
import secrets
import time

RED = frozenset((1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36))
DICE_FACTORS = (.25, .5, .75, 1, 1.5, 2.5)


def mode(profile):
    key = profile.get('base_id', profile.get('skill_id', ''))
    if key == 'casino_all_in': return 'roulette'
    if key == 'mastery_gambler': return 'dice'
    if key == 'casino_deposit' and profile.get('name', '').startswith('777'): return 'slots'
    return None


def draw(kind, choice, rng):
    if kind == 'roulette':
        if choice not in ('red', 'black', 'green'): raise ValueError('Выбери красное, чёрное или зелёное.')
        sector = rng.randrange(37)
        color = 'green' if sector == 0 else 'red' if sector in RED else 'black'
        return dict(mode=kind, choice=choice, sector=sector, color=color,
                    factor=(30 if color == 'green' else 2) if color == choice else 0)
    if choice != 'launch': raise ValueError('Сначала запусти бросок.')
    if kind == 'dice':
        face = rng.randrange(1, 7)
        return dict(mode=kind, face=face, factor=DICE_FACTORS[face-1])
    if kind == 'slots':
        reels = [rng.choice((7, 1, 2, 3)) for _ in range(3)]
        sevens = reels.count(7)
        factor = 8 if sevens == 3 else 3 if len(set(reels)) == 1 else 2 if sevens == 2 else 1 if sevens == 1 else .35
        return dict(mode=kind, reels=reels, factor=factor)
    raise ValueError('У этого навыка нет случайного запуска.')


def commit(stage, choice, now=None):
    """Persist before reveal; same request is idempotent, changing a bet is forbidden."""
    kind = stage.get('casino_mode')
    expected = ('red', 'black', 'green') if kind == 'roulette' else ('launch',)
    if not isinstance(choice, str) or choice not in expected: raise ValueError('Некорректная ставка.')
    if stage.get('casino_result'):
        if stage['casino_choice'] != choice: raise ValueError('Ставка уже принята. Изменить её нельзя.')
        return dict(stage['casino_result'])
    entropy = stage.setdefault('_casino_chance_seed', secrets.token_hex(32))
    outcome = draw(kind, choice, random.Random(entropy))
    stage.update(casino_result=outcome, casino_choice=choice,
                 casino_launched_at=time.time() if now is None else now)
    return dict(outcome)


def replay(stage, proof, elapsed):
    if not isinstance(proof, dict): raise ValueError('Нет записи запуска.')
    n = stage['strikes']
    result = stage.get('casino_result')
    if not result:
        if proof.get('abort') is True: return dict(mask=[False]*n, weights=[0]*n)
        raise ValueError('Сначала запусти случайный бросок.')
    # Once revealed, closing/reloading cannot cancel or alter the committed result.
    return dict(mask=[result['factor'] > 0]*n, weights=[1/n]*n, casino=dict(result))


def public(stage):
    return {k:v for k,v in stage.items() if k != '_casino_chance_seed'}
