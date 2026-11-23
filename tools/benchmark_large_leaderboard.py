"""Compare PvP ranking pages on a disposable SQLite season."""

import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import tracemalloc
from unittest.mock import patch

from benchmark_performance import head_function, measure_async
from database import Database
import leaderboards


async def main(args):
    with tempfile.TemporaryDirectory(prefix='gnida-ranking-') as directory:
        db = Database(Path(directory) / 'benchmark.sqlite3')
        await db.connect()
        try:
            season = '2025-10'
            with db.connection:
                db.connection.executemany(
                    'INSERT INTO arena_ratings(season,actor_id,rating,games,wins) VALUES(?,?,?,?,?)',
                    ((season, i, 1100 + i % 123, 4 if i % 10 == 0 else 8, i % 8)
                     for i in range(1, args.players + 1)))
            actor = args.players if args.players % 10 else args.players - 1
            actor = max(1, actor)

            async def load():
                return await db.arena_leaderboard(actor, season=season, mine=True)

            async def measure_page():
                result = await measure_async(load, args.repeats)
                tracemalloc.start()
                try:
                    await load()
                    result['peak_python_kib'] = round(tracemalloc.get_traced_memory()[1] / 1024, 1)
                finally:
                    tracemalloc.stop()
                return result

            current = await measure_page()
            page = await load()
            previous = head_function('leaderboards.py', 'LeaderboardsMixin', 'arena_leaderboard',
                                     vars(leaderboards), args.baseline_ref)
            # Remove the added index only on this throwaway database so the
            # baseline also uses its original query plan.
            db.connection.execute(f'DROP INDEX idx_arena_placed_rating_{leaderboards.RATING_PLACEMENT_GAMES}')
            with patch.object(leaderboards.LeaderboardsMixin, 'arena_leaderboard', previous):
                baseline = await measure_page()
                assert page == await load()
            print(json.dumps({'players': args.players, 'baseline': baseline, 'current': current}, indent=2))
        finally:
            await db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--players', type=int, default=20000)
    parser.add_argument('--repeats', type=int, default=25)
    parser.add_argument('--baseline-ref', default='a07baf1')
    args = parser.parse_args()
    if min(args.players, args.repeats) < 1:
        parser.error('--players and --repeats must be positive')
    asyncio.run(main(args))
