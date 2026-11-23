import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from arena_qte_live import ArenaQteMixin
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


class QteSweepTests(unittest.TestCase):
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

        db = Sweep()
        db.connection = sqlite3.connect(":memory:")
        self.addCleanup(db.connection.close)
        db.connection.row_factory = sqlite3.Row
        db._connect_qte()
        db.connection.executemany(
            "INSERT INTO arena_qte_flows VALUES ('raid',?,1,?)",
            [(token,json.dumps(dict(token=token,stages=[dict(expires=0)]))) for token in "abc"],
        )
        db._qte_expire_locked("raid")
        self.assertEqual(completed,["a"])
        self.assertEqual(db._qte_load_locked("raid","c",1)["stages"][0]["expires"],1e10)
