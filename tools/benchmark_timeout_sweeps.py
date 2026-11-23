"""Measure background arena sweeps without touching the live database."""

import argparse
import asyncio
from contextlib import ExitStack
from itertools import cycle
import json
from pathlib import Path
import tempfile
import time
import tracemalloc
from unittest.mock import patch

from benchmark_performance import head_function, measure
import arena_qte_live
import arena_raid
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_qte_combined import combine
from arena_raid_engine import BOSS_SKILLS, create_raid_state
from database import Database


def build_fixture(db, count):
    now = int(time.time())
    ids = (1, 2, 3)
    fighters = [dict(slave_id=k, owner_id=k, class_id='assassin', level=20) for k in ids]
    party = [dict(actor_id=k, fighter_id=k, personal=True, slave_owner=k) for k in ids]
    state = create_raid_state(party, fighters, FIGHTER_CLASSES, BUILTIN_SKILLS, 'kit', unified=True)
    state['_queue_wait'] = {'id': 'wave'}
    state['log'] = [dict(round=i, actor='boss', target='1', text='Отражение: −7 HP.',
                         skill='kit_reflection', hit=True, damage=7) for i in range(1, 81)]
    state_json = json.dumps(state, ensure_ascii=False)
    member = arena_qte_live.challenge('defense', state['boss'], state['players']['1']['fighter'],
                                       BOSS_SKILLS['kit_reflection'], 1)
    member.update(encounter_enemy='boss', seed=42)
    stage = combine([member], 1, state['players']['1']['fighter']['hp'])
    # Leave every stage open across all timed sweeps. Due stages continue to
    # need the full combat resolver; this measures the cost of idle polling.
    stage.update(started=now, expires=now + 86400)
    c = db.connection
    with c:
        c.executemany("""INSERT INTO arena_raids
            (token,chat_id,creator_id,status,data_json,created_at,deadline,silent,message_id)
            VALUES (?,1,1,?,?,?,?,?,?)""",
            [(f'raid-{i}', 'active', state_json, now, now + 86400, 0, 1)
             for i in range(count)] +
            [(f'lobby-{i}', 'lobby', None, now, now + 86400, 1, None) for i in range(count)])
        c.executemany("INSERT INTO arena_raid_players VALUES (?,?,?,1,?)",
                      ((f'raid-{i}', k, k, k) for i in range(count) for k in ids))
        c.executemany("INSERT INTO arena_qte_flows VALUES ('raid',?,1,?)",
                      ((f'raid-{i}', json.dumps(dict(scope='raid', token=f'raid-{i}', owner=1,
                                                   unified_group='wave', stages=[stage]), ensure_ascii=False))
                       for i in range(count)))
    return len(state_json.encode()), len(json.dumps(stage, ensure_ascii=False).encode())


def describe(call, repeats):
    timings = measure(call, repeats)
    tracemalloc.start()
    try:
        call()
        timings['peak_python_kib'] = round(tracemalloc.get_traced_memory()[1] / 1024, 1)
    finally:
        tracemalloc.stop()
    return timings


async def run(args, ref):
    with ExitStack() as stack:
        if ref:
            for module, cls, names in (
                (arena_qte_live, 'ArenaQteMixin', ('_connect_qte', '_qte_expire_locked', '_qte_valid_locked')),
                (arena_raid, 'RaidMixin', ('_raid_row_locked', '_raid_expire_locked')),
            ):
                for name in names:
                    original = head_function(module.__name__ + '.py', cls, name, vars(module), ref)
                    stack.enter_context(patch.object(getattr(module, cls), name, original))
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='gnida-timeouts-'))
        db = Database(Path(directory) / 'benchmark.sqlite3')
        await db.connect()
        try:
            state_bytes, stage_bytes = build_fixture(db, args.raids)
            result = {
                'raid_state_bytes': state_bytes,
                'qte_stage_bytes': stage_bytes,
                'future_qte_sweep': describe(lambda: db._qte_expire_locked('raid'), args.repeats),
                'raid_sweep_including_qte': describe(db._raid_expire_locked, args.repeats),
            }
            flow = db._qte_load_locked('raid', 'raid-0', 1)
            before = json.dumps(flow, ensure_ascii=False)
            flow['stages'][0]['expires'] += 1
            payloads = cycle((json.dumps(flow, ensure_ascii=False), before))
            with db.connection:
                result['qte_payload_write_without_commit'] = measure(lambda: db.connection.execute(
                    "UPDATE arena_qte_flows SET payload=? WHERE scope='raid' AND token='raid-0' AND actor_id=1",
                    (next(payloads),)), args.repeats)
            return result
        finally:
            await db.close()


async def main(args):
    before = await run(args, args.baseline_ref)
    after = await run(args, None)
    print(json.dumps({'active_raids': args.raids, 'fresh_lobbies': args.raids,
                      'baseline': before, 'optimized': after}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='a07baf1')
    parser.add_argument('--raids', type=int, default=200)
    parser.add_argument('--repeats', type=int, default=30)
    args = parser.parse_args()
    if min(args.raids, args.repeats) < 1:
        parser.error('--raids and --repeats must be positive')
    asyncio.run(main(args))
