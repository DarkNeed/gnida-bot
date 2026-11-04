"""Loopback-only queue v3 review. In-memory sessions, no bot/database imports.

Uses real skills, combat effects and QTE replays. Never registers live API routes.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import random
import secrets
import sys
import time
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.preview_arena import app
from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state,
                          effective_skill, effective_stat, resolve_skill, validate_skill,
                          _begin_resource_turn, _tick)
from arena_rp import rp_skills
from arena_guild_rules import SKILLS as GUILD_SKILLS
from arena_progression import choice_avatar
from arena_archclasses import ARCHCLASSES, class_title
from arena_action_queue import cast_time
from arena_skill_timing import base_duration, duration, forecast, schedule, release
from arena_qte_live import challenge
from arena_qte_rules import replay
from arena_qte_combined import combine
from arena_nazarick_dungeon_rules import build_skills as dungeon_skills
from arena_engine import Skill

SKILLS = rp_skills(BUILTIN_SKILLS) | GUILD_SKILLS | dungeon_skills(Skill)
SESSIONS = {}


def pair(actor, target):
    return dict(sides={'a': actor, 'b': target}, active_side='a', turn=1,
                finished=False, winner=None, log=[])


def enemy_plan(data, key):
    fighter = data['fighters'][key]
    living = [k for k in data['heroes'] if data['fighters'][k]['hp'] > 0]
    if fighter['hp'] <= 0 or not living:
        return
    target = living[fighter.get('ai_index', 0) % len(living)]
    options = fighter['loadout']
    for offset in range(len(options)):
        index = (fighter.get('ai_index', 0) + offset) % len(options)
        sid = options[index]
        try:
            skill = validate_skill(pair(fighter, data['fighters'][target]), 'a', sid, SKILLS)
        except ValueError:
            continue
        fighter['ai_index'] = index + 1
        break
    else:
        sid, skill = 'bum_punch', SKILLS['bum_punch']
    schedule(data, key, sid, target, duration(fighter, skill))


def new_session(body):
    cls = body.get('class_id', 'assassin')
    if cls not in FIGHTER_CLASSES:
        raise ValueError('Неизвестный класс.')
    arch = body.get('arch', '')
    if arch and (arch not in ARCHCLASSES or ARCHCLASSES[arch]['class_id'] != cls):
        raise ValueError('Ветка не относится к классу.')
    sources = [dict(slave_id=1, owner_id=1, class_id=cls, level=20, archclass_id=arch),
               dict(slave_id=0, owner_id=0, class_id='mage', level=20)]
    if body.get('native') and cls == 'assassin':
        sources[0]['loadout'] = (['assassin_cut', 'assassin_needle', 'assassin_smoke', 'arch_assassin_shadow']
            if arch == 'assassin_shadow' else ['assassin_cut', 'assassin_expose', 'assassin_execution', 'arch_assassin_blood']
            if arch == 'assassin_blood' else ['assassin_cut', 'assassin_needle', 'assassin_smoke', 'assassin_execution'])
    fighters = create_battle_state(*sources)['sides']
    hero, mage = fighters['a'], fighters['b']
    # All native skills can be tested without four-slot loadout limits here.
    if not body.get('native'):
        hero['loadout'] = [s.skill_id for s in SKILLS.values() if s.class_id == cls
                          and not s.skill_id.startswith('guild_') and not any(t.startswith('archclass:') and t != 'archclass:' + arch for t in s.tags)]
    hero.update(name=class_title(hero, FIGHTER_CLASSES[cls].name), rp_sandbox=not body.get('native'),
                defense_mode=body.get('defense', 'dodge'))
    if hero['defense_mode'] not in ('dodge', 'block'):
        raise ValueError('Неизвестный режим защиты.')
    mage.update(name='Маг', rp_sandbox=True, loadout=['mana_blob', 'mana_shot', 'mana_overload'])
    data = dict(time=0., pending=[], fighters={'h1': hero, 'e1': mage}, heroes=['h1'], enemies=['e1'],
                stages=[], group=[], results={}, log=[], revision=0, finished=False, created=time.time())
    scenario = body.get('scenario', 'mixed')
    if scenario in ('mixed', 'sync', 'party'):
        bum = create_battle_state(dict(slave_id=0, owner_id=0, class_id='ragamuffin', level=20), sources[0])['sides']['a']
        bum.update(name='Бомж', rp_sandbox=True, loadout=['bum_punch', 'dust_in_eyes'])
        data['fighters']['e2'] = bum
        data['enemies'].append('e2')
    if scenario == 'party':
        ally = create_battle_state(dict(slave_id=2, owner_id=2, class_id='warrior', level=20), sources[1])['sides']['a']
        ally.update(name='Воин · союзник', rp_sandbox=True, defense_mode=hero['defense_mode'],
                    loadout=['armor_split', 'steel_charge', 'counter_lunge', 'bum_punch'])
        data['fighters']['h2'] = ally
        data['heroes'].append('h2')
    for key in data['enemies']:
        enemy_plan(data, key)
    if scenario == 'sync':
        for event in data['pending']:
            event.update(end=3., duration=3., target='h1')
    return data


def idle_heroes(data):
    pending = {e['actor'] for e in data['pending']} | {e['actor'] for e in data['group']}
    return [k for k in data['heroes'] if data['fighters'][k]['hp'] > 0 and k not in pending]


def prepare_stage(stage):
    stage.update(started=time.time(), expires=time.time() + 90, server_now=time.time())
    return stage


def complete_group(data):
    # Members whose casts finished together were released before damage: a
    # simultaneous hit is not retroactively cancelled by death in this group.
    for event in data['group']:
        actor, target = data['fighters'][event['actor']], data['fighters'][event['target']]
        if any(e['kind'] == 'stun' for e in actor['effects']):
            _tick(actor)
            data['log'].append(dict(at=data['time'], text=actor['name'] + ': ошеломление сорвало каст.'))
            continue
        if target['hp'] <= 0:
            _tick(actor)
            data['log'].append(dict(at=data['time'], text=actor['name'] + ': цель уже повержена, каст отменён.'))
            continue
        saved_hp = actor['hp']
        if saved_hp <= 0:
            actor['hp'] = 1
        actor['resource'] += event.get('reserved', 0)
        try:
            state = pair(actor, target)
            result = resolve_skill(state, 'a', event['skill'], SKILLS, random.Random(secrets.randbits(32)),
                                   advance_turn=False, qte=data['results'].get(event['actor'], {}))
            data['log'].append(dict(at=data['time'], actor=event['actor'], target=event['target'],
                                    event=result, text=actor['name'] + ' · ' + result['skill_name'] + ': ' + result['text']))
        except ValueError as error:
            data['log'].append(dict(at=data['time'], text=actor['name'] + ': каст отменён — ' + str(error)))
        finally:
            if saved_hp <= 0:
                actor['hp'] = 0
    data['group'] = []
    data['results'] = {}
    # Death cancels unfinished casts. No automatic follow-up for players.
    data['pending'] = [e for e in data['pending'] if data['fighters'][e['actor']]['hp'] > 0]
    data['finished'] = (not any(data['fighters'][k]['hp'] > 0 for k in data['heroes']) or
                        not any(data['fighters'][k]['hp'] > 0 for k in data['enemies']))
    if data['finished']:
        data['pending'] = []
        return
    for key in data['enemies'] + data['heroes']:
        if data['fighters'][key]['hp'] <= 0 or any(e['actor'] == key for e in data['pending']):
            continue
        state = pair(data['fighters'][key], data['fighters'][data['heroes'][0]])
        _begin_resource_turn(state, 'a')
        if key in data['enemies']:
            enemy_plan(data, key)


def drive(data):
    for _ in range(100):
        if data['stages'] or data['finished']:
            return
        if data['group']:
            complete_group(data)
            continue
        if idle_heroes(data):
            return
        data['group'] = release(data)
        if not data['group']:
            return
        incoming = {}
        for event in data['group']:
            actor, target = data['fighters'][event['actor']], data['fighters'][event['target']]
            skill = effective_skill(pair(actor, target), 'a', event['skill'], SKILLS)
            if (not skill.damage_type or actor['hp'] <= 0 or target['hp'] <= 0
                    or any(e['kind'] == 'stun' for e in actor['effects'])):
                continue
            kind = 'attack' if event['actor'] in data['heroes'] else 'defense'
            stage = challenge(kind, actor, target, skill, target['controller_id'] if kind == 'defense' else actor['controller_id'])
            stage['queue_source'] = event['actor']
            if kind == 'attack':
                data['stages'].append(stage)
            else:
                stage['encounter_enemy'] = event['actor']
                incoming.setdefault(event['target'], []).append(stage)
        for target, members in incoming.items():
            stage = combine(members, data['fighters'][target]['controller_id'], data['fighters'][target]['hp']) if len(members) > 1 else members[0]
            stage['queue_target'] = target
            data['stages'].append(stage)
        if data['stages']:
            prepare_stage(data['stages'][0])
    raise ValueError('Очередь превысила предел событий.')


def view(data, token):
    fighters = {}
    idle = idle_heroes(data)
    for key, fighter in data['fighters'].items():
        cls = FIGHTER_CLASSES[fighter['class_id']]
        target_key = next((k for k in data['enemies'] if data['fighters'][k]['hp'] > 0), 'e1')
        target = data['fighters'][target_key]
        details = []
        if key in idle:
            for sid in fighter['loadout']:
                try:
                    skill = effective_skill(pair(fighter, target), 'a', sid, SKILLS)
                    try:
                        validate_skill(pair(fighter, target), 'a', sid, SKILLS)
                        reason = ''
                    except ValueError as error:
                        reason = str(error)
                    enemy_end = min((e['end'] for e in data['pending'] if e['actor'] in data['enemies'] and e['target'] == key), default=None)
                    details.append(dict(id=sid, name=skill.name, cost=skill.cost,
                                        duration=duration(fighter, skill), base=base_duration(skill), reason=reason,
                                        forecast=forecast(data['time'], duration(fighter, skill), enemy_end)))
                except KeyError:
                    continue
        full = deepcopy(fighter)
        from arena_archclasses import archclass_view
        full.update(class_name=class_title(fighter, cls.name), class_rarity=cls.rarity,
                    resource_name=cls.resource_name, sprite=cls.class_id,
                    class_avatar_url=choice_avatar(cls.class_id, fighter.get('archclass_id', ''), 20),
                    archclass=archclass_view(fighter),
                    effective_stats={stat: effective_stat(fighter, stat) for stat in fighter['stats']},
                    skill_details=[])
        if key in data['heroes'] and fighter['resource'] < min((SKILLS[s].cost for s in fighter['loadout']), default=0):
            if 'bum_punch' not in fighter['loadout']:
                full['skill_details'].append(dict(asdict(SKILLS['bum_punch']), cast_time=duration(fighter, SKILLS['bum_punch'])))
        details_by_id = {s['id']: s for s in details}
        for sid in fighter['loadout']:
            skill = effective_skill(pair(fighter, target), 'a', sid, SKILLS)
            full['skill_details'].append(dict(asdict(skill), cast_time=duration(fighter, skill),
                unavailable_reason=details_by_id.get(sid, {}).get('reason', ''),
                queue_forecast=details_by_id.get(sid, {}).get('forecast')))
        fighters[key] = dict(name=fighter['name'], class_id=fighter['class_id'], hp=fighter['hp'],
                             max_hp=fighter['stats']['max_hp'], resource=fighter['resource'],
                             speed=effective_stat(fighter, 'speed'),
                             sprite=choice_avatar(cls.class_id, fighter.get('archclass_id', ''), 20),
                             effects=[e for e in fighter['effects'] if e.get('duration', 0) < 10000],
                             skills=sorted(details, key=lambda s: (s['duration'], s['name'])), arena=full)
    from arena_casino_chance import public as public_casino
    return dict(token=token, time=data['time'], revision=data['revision'], pending=deepcopy(data['pending']),
                group=deepcopy(data['group']), fighters=fighters, heroes=data['heroes'], enemies=data['enemies'], idle=idle,
                finished=data['finished'], log=data['log'][-40:], stage=public_casino(data['stages'][0]) if data['stages'] else None)


async def review(request):
    raise web.HTTPFound('/arena-queue-review' + ('?' + request.query_string if request.query_string else ''))


async def legacy_lab(request):
    return web.FileResponse(ROOT / 'tools/unified_queue_review/index.html', headers={'Cache-Control': 'no-store'})


async def arena_review(request):
    from arena_assets import render_arena_index
    import re
    html = render_arena_index(ROOT / 'webapp')
    # RP navigation and live spectator transport do not exist on this isolated
    # server. All battle renderers/assets are the original production files.
    html = re.sub(r'<script src="/(?:rp/client|static/qte-watch)\.js[^\"]*"></script>', '', html)
    return web.Response(text=html, content_type='text/html',
                        headers={'Cache-Control': 'no-store'})


async def catalog(request):
    return web.json_response(dict(classes=[dict(id=k, name=c.name, branches=[dict(id=a, name=v['name']) for a, v in ARCHCLASSES.items() if v['class_id'] == k]) for k, c in FIGHTER_CLASSES.items()],
        skills=[dict(id=s.skill_id, name=s.name, class_id=s.class_id, base=base_duration(s)) for s in SKILLS.values()]))


async def create(request):
    body = await request.json()
    # Expire abandoned local sessions rather than accumulating review data.
    for token in list(SESSIONS):
        if time.time() - SESSIONS[token]['created'] > 7200:
            del SESSIONS[token]
    if len(SESSIONS) > 50:
        SESSIONS.pop(next(iter(SESSIONS)))
    token = secrets.token_urlsafe(16)
    SESSIONS[token] = new_session(body)
    return web.json_response(view(SESSIONS[token], token))


async def action(request):
    body = await request.json()
    token = request.match_info['token']
    if token not in SESSIONS:
        raise ValueError('Демо истекло. Начни новый бой.')
    data = SESSIONS[token]
    if body.get('revision') != data['revision']:
        raise ValueError('Действие уже обработано. Обнови демо.')
    working = deepcopy(data)
    if body.get('action') == 'qte':
        if not working['stages'] or body.get('challenge_id') != working['stages'][0]['id']:
            raise ValueError('Нет такой мини-игры.')
        stage = working['stages'][0]
        result = replay(stage, body.get('proof'), time.time() - stage['started'])
        if stage.get('version') == 4:
            working['results'].update(result['sources'])
        elif stage['kind'] == 'attack':
            working['results'][stage['queue_source']] = dict(attack=result['mask'], pattern_attack=result)
        else:
            working['results'][stage['queue_source']] = dict(dodge=result['mask'], pattern_dodge=result)
        working['stages'].pop(0)
        if working['stages']:
            prepare_stage(working['stages'][0])
    else:
        actor, sid, target = body.get('actor'), body.get('skill'), body.get('target')
        if working['stages'] or working['finished'] or actor not in idle_heroes(working):
            raise ValueError('Этот персонаж сейчас не выбирает действие.')
        if target not in working['enemies'] or working['fighters'][target]['hp'] <= 0:
            raise ValueError('Выбери живого противника.')
        fighter = working['fighters'][actor]
        skill = validate_skill(pair(fighter, working['fighters'][target]), 'a', sid, SKILLS)
        from arena_pets import pet_cost
        from arena_mirror_effects import gift_cost
        cost = pet_cost(fighter, skill, gift_cost(fighter, skill))
        event = schedule(working, actor, sid, target, duration(fighter, skill))
        event['reserved'] = cost
        fighter['resource'] -= cost
    drive(working)
    working['revision'] += 1
    SESSIONS[token] = working
    return web.json_response(view(working, token))


async def casino(request):
    from arena_casino_chance import commit
    body = await request.json()
    data = SESSIONS.get(request.match_info['token'])
    if not data or not data['stages'] or data['stages'][0]['id'] != body.get('challenge_id'):
        raise ValueError('Нет такой мини-игры.')
    return web.json_response(commit(data['stages'][0], body.get('choice')))


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except (ValueError, KeyError, TypeError) as error:
        return web.json_response(dict(error=str(error)), status=400)


app.middlewares.append(errors)
app.router.add_get('/unified-queue-review', review)
app.router.add_get('/queue-lab', legacy_lab)
app.router.add_get('/arena-queue-review', arena_review)
app.router.add_get('/queue-review/catalog', catalog)
app.router.add_post('/queue-review/session', create)
app.router.add_post('/queue-review/session/{token}', action)
app.router.add_post('/queue-review/session/{token}/casino', casino)
app.router.add_static('/queue-review/ui/', ROOT / 'tools/unified_queue_review')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8154)
    web.run_app(app, host='127.0.0.1', port=parser.parse_args().port)
