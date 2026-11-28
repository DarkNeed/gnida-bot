import json
import os
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from arena_qte_live import ArenaQteMixin, _QTE_DUE_KEYS
from arena_store import _ARENA_DUE_KEYS
from database import Database
from main import telegram_updates_limit


class TelegramLimitsTests(unittest.TestCase):
    def test_default_and_values(self):
        for value, expected in (("",24),(" 12 ",12),("1",1),("64",64)):
            with self.subTest(value=value), patch.dict(os.environ,TELEGRAM_UPDATES_LIMIT=value):
                self.assertEqual(telegram_updates_limit(),expected)

    def test_rejects_unlimited_or_invalid_setting(self):
        for value in ("0","-2","65","lots"):
            with self.subTest(value=value), patch.dict(os.environ,TELEGRAM_UPDATES_LIMIT=value):
                with self.assertRaisesRegex(RuntimeError,"TELEGRAM_UPDATES_LIMIT"):
                    telegram_updates_limit()


class ArenaSweepMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_keys_use_partial_indexes_without_selecting_history(self):
        with TemporaryDirectory() as temp:
            db = Database(Path(temp) / "history.sqlite3")
            await db.connect()
            try:
                conn = db.connection
                conn.executemany("""INSERT INTO arena_battles(token,chat_id,message_id,mode,a_owner,b_owner,
                    status,created_at,deadline) VALUES(?,1,1,'personal',10,20,'finished',1,20)""",
                                 [(f"old-{i}",) for i in range(2000)])
                conn.executemany("""INSERT INTO arena_battles(token,chat_id,message_id,mode,a_owner,b_owner,
                    status,created_at,deadline) VALUES(?,1,?,'personal',10,20,'pending',?,?)""",
                                 [("due", 1, 95, 99), ("both", None, 1, 98),
                                  ("orphan", None, 1, 150), ("notdue", None, 98, 150)])
                conn.commit()
                plan = [r['detail'] for r in conn.execute("EXPLAIN QUERY PLAN " + _ARENA_DUE_KEYS, (100, 40))]
                self.assertTrue(any('idx_arena_live_deadline' in row for row in plan), plan)
                self.assertTrue(any('idx_arena_unpublished' in row for row in plan), plan)
                with patch("arena_store.utc_timestamp", return_value=100):
                    changed = await db.arena_expire(compact=True)
                    self.assertEqual((await db.arena_get("notdue"))["status"], "pending")
                self.assertEqual(changed, [dict(token="due"), dict(token="both"), dict(token="orphan")])
                self.assertEqual((await db.arena_get("due"))["status"], "expired")
                self.assertEqual((await db.arena_get("orphan"))["status"], "cancelled")
                self.assertEqual(conn.execute('PRAGMA journal_size_limit').fetchone()[0], 8*1024*1024)
            finally:
                await db.close()


class QteSweepTests(unittest.TestCase):
    def make_database(self, cls=ArenaQteMixin):
        db = cls()
        db.connection = sqlite3.connect(":memory:")
        self.addCleanup(db.connection.close)
        db.connection.row_factory = sqlite3.Row
        return db

    def test_reads_current_payloads_without_reviving_flows_removed_during_sweep(self):
        completed = []

        class Sweep(ArenaQteMixin):
            def _qte_valid_locked(self, flow):
                return True

            def _qte_complete_locked(self, flow, *, expired):
                assert expired
                completed.append(flow["token"])
                self.connection.execute("DELETE FROM arena_qte_flows WHERE token IN ('a','b')")
                self.connection.execute(
                    "UPDATE arena_qte_flows SET payload=? WHERE token='c'",
                    (json.dumps(dict(token="c",stages=[dict(expires=1e10)])),),
                )

        db = self.make_database(Sweep)
        db._connect_qte()
        db.connection.executemany(
            "INSERT INTO arena_qte_flows VALUES ('raid',?,1,?)",
            [(token,json.dumps(dict(token=token,stages=[dict(expires=0)]))) for token in "abc"],
        )
        db._qte_expire_locked("raid")
        self.assertEqual(completed,["a"])
        self.assertEqual(db._qte_load_locked("raid","c",1)["stages"][0]["expires"],1e10)

    def test_adds_deadline_index_to_existing_database_and_reads_only_due_flows(self):
        checked = []
        completed = []

        class Sweep(ArenaQteMixin):
            def _qte_valid_locked(self, flow):
                checked.append(flow['token'])
                return flow['token'] != 'stale'

            def _qte_complete_locked(self, flow, *, expired):
                assert expired
                completed.append(flow['token'])
                self._qte_delete_locked(flow)

        db = self.make_database(Sweep)
        db.connection.execute("""CREATE TABLE arena_qte_flows (
            scope TEXT NOT NULL, token TEXT NOT NULL, actor_id INTEGER NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(scope,token,actor_id))""")
        db.connection.executemany("INSERT INTO arena_qte_flows VALUES (?,?,?,?)", [
            (scope, token, 0, json.dumps(dict(scope=scope, token=token, owner=0, stages=[dict(expires=end)])))
            for scope, token, end in [('battle', 'due', 100), ('battle', 'live', 101),
                                      ('battle', 'stale', 101), ('raid', 'other', 99)]
        ])
        db._connect_qte()
        plan = db.connection.execute("EXPLAIN QUERY PLAN " + _QTE_DUE_KEYS, ('battle', 100)).fetchall()
        self.assertTrue(any('idx_qte_due' in row['detail'] and '<expr><?' in row['detail'] for row in plan), plan)
        with patch("arena_qte_live.time.time", return_value=100):
            db._qte_expire_locked('battle')
            self.assertEqual(checked, ['due'])
            self.assertEqual(completed, ['due'])
            self.assertIsNotNone(db._qte_load_locked('battle', 'stale'))
            db._qte_expire_locked('battle', 'stale')
            self.assertEqual(checked, ['due', 'stale'])
            self.assertIsNone(db._qte_load_locked('battle', 'stale'))
            self.assertIsNotNone(db._qte_load_locked('raid', 'other'))
        with patch("arena_qte_live.time.time", return_value=101):
            db._qte_expire_locked('battle')
        self.assertEqual(completed, ['due', 'live'])
