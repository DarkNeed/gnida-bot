"""Optimization contracts: fresh state, bounded caches and indexed discovery."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arena_assets import render_arena_index
from arena_content_cache import _parsed_class, _parsed_skill, custom_skill
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_modules import ClassModulesMixin
from database import Database


class IndexCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("index.html", '<link href="/static/style.css"><script src="/static/client.js"></script>')
        for name in ("style.css", "battle-client", "arena-audio"):
            self.write(name, "initial")

    def write(self, name, content):
        (self.root / name).write_text(content, encoding="utf-8")

    def test_warm_request_does_not_read_or_hash_sources(self):
        expected = render_arena_index(self.root)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("source reread")), \
                patch.object(Path, "read_text", side_effect=AssertionError("HTML reread")):
            self.assertEqual(render_arena_index(self.root), expected)

    def test_html_optional_creation_deletion_and_atomic_replace_invalidate(self):
        original = render_arena_index(self.root)
        self.write("guild.js", "new optional asset")
        added = render_arena_index(self.root)
        self.assertNotEqual(added, original)
        (self.root / "guild.js").unlink()
        self.assertEqual(render_arena_index(self.root), original)
        self.write("index.html", '<main>Updated</main><script src="/static/client.js"></script>')
        changed_html = render_arena_index(self.root)
        self.assertIn("Updated", changed_html)
        # Same size/mtime but a different file identity (atomic deployments).
        old_stat = (self.root / "battle-client").stat()
        self.write("replacement", "changed")
        os.utime(self.root / "replacement", ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        (self.root / "replacement").replace(self.root / "battle-client")
        self.assertNotEqual(render_arena_index(self.root), changed_html)

    def test_missing_required_asset_does_not_serve_stale_cache(self):
        render_arena_index(self.root)
        (self.root / "style.css").unlink()
        with self.assertRaises(FileNotFoundError):
            render_arena_index(self.root)

    def test_different_roots_do_not_share_html(self):
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory)
            for name in ("index.html", "style.css", "battle-client", "arena-audio"):
                (other / name).write_text("different", encoding="utf-8")
            self.assertNotEqual(render_arena_index(self.root), render_arena_index(other))


class CatalogCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "catalog.sqlite3")
        await self.db.connect()
        self.class_payload = asdict(FIGHTER_CLASSES["ragamuffin"])
        self.class_payload.update(name="Custom", passives=[dict(kind="damage_pct", value=.1, extra={"nested": 1})])
        self.skill_payload = dict(name="Custom skill", class_id="perf_custom", merchant_available=True,
                                  damage_type="magic", power=10,
                                  effects=[dict(kind="bleed", value=2, turns=3)])
        self.db.connection.execute(
            "INSERT INTO custom_fighter_classes VALUES('perf_custom','Custom',0,?,10,0)",
            (json.dumps(self.class_payload),),
        )
        self.db.connection.execute(
            "INSERT INTO custom_fighter_skills VALUES('perf_skill','Custom skill',?,10,0)",
            (json.dumps(self.skill_payload),),
        )
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def catalog(self):
        return self.db._fighter_catalog_locked()

    def change_skill(self, **changes):
        payload = self.skill_payload | changes
        self.db.connection.execute(
            "UPDATE custom_fighter_skills SET definition_json=? WHERE skill_id='perf_skill'",
            (json.dumps(payload),),
        )

    async def test_cache_hits_but_returned_mutable_fields_are_isolated(self):
        classes, skills = self.catalog()
        before = (_parsed_class.cache_info().hits, _parsed_skill.cache_info().hits)
        classes["perf_custom"].base_stats["max_hp"] = 9999
        classes["perf_custom"].growth["speed"] = 9999
        classes["perf_custom"].passives[0]["extra"]["nested"] = 99
        skills["perf_skill"].effects[0]["value"] = 9999
        skills.pop("bum_punch")
        classes, skills = self.catalog()
        self.assertGreater(_parsed_class.cache_info().hits, before[0])
        self.assertGreater(_parsed_skill.cache_info().hits, before[1])
        self.assertEqual(classes["perf_custom"].base_stats, self.class_payload["base_stats"])
        self.assertEqual(classes["perf_custom"].growth, self.class_payload["growth"])
        self.assertEqual(classes["perf_custom"].passives[0]["extra"]["nested"], 1)
        self.assertEqual(skills["perf_skill"].effects[0]["value"], 2)
        self.assertIn("bum_punch", skills)

    async def test_edits_and_rollback_are_visible_immediately(self):
        self.assertEqual(self.catalog()[1]["perf_skill"].power, 10)
        self.change_skill(power=23)
        self.assertEqual(self.catalog()[1]["perf_skill"].power, 23)
        self.db.connection.rollback()
        self.assertEqual(self.catalog()[1]["perf_skill"].power, 10)
        self.change_skill(power=34)
        self.assertEqual(self.catalog()[1]["perf_skill"].power, 34)
        self.db.connection.commit()
        await self.db.close()
        await self.db.connect()
        self.assertEqual(self.catalog()[1]["perf_skill"].power, 34)

    async def test_class_definition_edits_are_visible_and_can_be_rolled_back(self):
        before = self.catalog()[0]["perf_custom"]
        payload = self.class_payload | {"name": "Changed", "base_stats": before.base_stats | {"max_hp": 777}}
        self.db.connection.execute(
            "UPDATE custom_fighter_classes SET definition_json=? WHERE class_id='perf_custom'",
            (json.dumps(payload),),
        )
        changed = self.catalog()[0]["perf_custom"]
        self.assertEqual(changed.name, "Changed")
        self.assertEqual(changed.base_stats["max_hp"], 777)
        self.db.connection.rollback()
        self.assertEqual(self.catalog()[0]["perf_custom"], before)

    async def test_hide_unhide_delete_and_merchant_flag_invalidate(self):
        self.catalog()
        self.db.connection.execute("UPDATE custom_fighter_classes SET hidden=1")
        classes, skills = self.catalog()
        self.assertNotIn("perf_custom", classes)
        self.assertNotIn("perf_skill", skills)
        self.db.connection.execute("UPDATE custom_fighter_classes SET hidden=0")
        self.assertIn("perf_skill", self.catalog()[1])
        self.change_skill(merchant_available=False)
        self.assertNotIn("perf_skill", self.catalog()[1])
        self.db.connection.rollback()
        self.assertIn("perf_skill", self.catalog()[1])
        self.db.connection.execute("DELETE FROM custom_fighter_skills")
        self.assertNotIn("perf_skill", self.catalog()[1])

    async def test_malformed_definition_can_be_repaired_after_cached_miss(self):
        self.db.connection.execute("UPDATE custom_fighter_skills SET definition_json='{' ")
        self.assertNotIn("perf_skill", self.catalog()[1])
        self.change_skill()
        self.assertIn("perf_skill", self.catalog()[1])

    async def test_single_content_checks_match_full_catalog_and_never_build_it(self):
        for mutation in (None, "hide", "unhide", "bad_skill", "restore", "delete"):
            if mutation == "hide":
                self.db.connection.execute("UPDATE custom_fighter_classes SET hidden=1")
            elif mutation == "unhide":
                self.db.connection.execute("UPDATE custom_fighter_classes SET hidden=0")
            elif mutation == "bad_skill":
                self.db.connection.execute("UPDATE custom_fighter_skills SET definition_json='{' ")
            elif mutation == "restore":
                self.change_skill()
            elif mutation == "delete":
                self.db.connection.execute("DELETE FROM custom_fighter_classes")
            classes, skills = self.catalog()
            with patch.object(self.db, "_fighter_catalog_locked", side_effect=AssertionError("full catalog")):
                for kind, content, source in (("class", "perf_custom", classes), ("skill", "perf_skill", skills),
                                               ("class", "missing", classes), ("skill", "missing", skills)):
                    self.assertEqual(self.db._arena_content_enabled_locked(-100, kind, content), content in source)

    async def test_external_connection_changes_are_not_cached_as_player_state(self):
        self.catalog()
        other = Database(self.db.path)
        await other.connect()
        try:
            other.connection.execute("UPDATE custom_fighter_classes SET hidden=1")
            other.connection.commit()
            self.assertNotIn("perf_custom", self.catalog()[0])
        finally:
            await other.close()

    def test_caches_are_bounded(self):
        for index in range(540):
            custom_skill(f"cache_bound_{index}", json.dumps(self.skill_payload))
        self.assertLessEqual(_parsed_skill.cache_info().currsize, 512)
        self.assertLessEqual(_parsed_class.cache_info().currsize, 128)


class ContentGateTests(unittest.TestCase):
    def test_builtin_and_noncombat_items_do_not_rebuild_catalog(self):
        fake = SimpleNamespace(_fighter_catalog_locked=Mock(side_effect=AssertionError("catalog rebuilt")))
        for class_id in FIGHTER_CLASSES:
            self.assertTrue(ClassModulesMixin._arena_class_enabled_locked(fake, -100, class_id))
            self.assertTrue(ClassModulesMixin._arena_content_enabled_locked(fake, -100, "class", class_id))
        for skill_id in BUILTIN_SKILLS:
            self.assertTrue(ClassModulesMixin._arena_content_enabled_locked(fake, -100, "skill", skill_id))
        for kind in ("passive", "potion", "class_reset", "unknown"):
            self.assertTrue(ClassModulesMixin._arena_content_enabled_locked(fake, -100, kind, "item"))

class EnterpriseLookupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "enterprises.sqlite3")
        await self.db.connect()
        for chat, owner, kind in ((-1, 10, "field"), (-1, 10, "mine"), (-2, 10, "field"), (-1, 20, "field"), (-3, 30, "field")):
            self.db.connection.execute(
                "INSERT INTO businesses(chat_id,owner_id,business_type,created_at,last_accrued) VALUES(?,?,?,0,0)",
                (chat, owner, kind),
            )
        for chat, owner, worker in ((-1, 10, 10), (-1, 10, 40), (-1, 20, 10), (-3, 30, 40), (-4, 50, 40)):
            self.db.connection.execute(
                "INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at) VALUES(?,?,?,'worker',0)",
                (chat, owner, worker),
            )
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def test_same_owners_as_legacy_join_without_duplicates_or_orphans(self):
        for user in (10, 20, 30, 40, 999):
            expected = set(map(tuple, self.db.connection.execute(
                """SELECT DISTINCT b.chat_id,b.owner_id FROM businesses b LEFT JOIN business_workers w
                   ON w.chat_id=b.chat_id AND w.owner_id=b.owner_id WHERE b.owner_id=? OR w.worker_id=?""",
                (user, user),
            )))
            with patch.object(self.db, "_settle_business_locked", return_value=None) as settle:
                await self.db.settle_businesses_for_user(user)
            actual = [(call.args[0], call.args[1]) for call in settle.call_args_list]
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(expected))

    async def test_discovery_uses_global_indexes_and_survives_reconnect(self):
        await self.db.close()
        await self.db.connect()
        statements = []
        self.db.connection.set_trace_callback(statements.append)
        try:
            with patch.object(self.db, "_settle_business_locked", return_value=None):
                await self.db.settle_businesses_for_user(40)
        finally:
            self.db.connection.set_trace_callback(None)
        query = next(sql for sql in statements if "UNION" in sql)
        plan = " ".join(row[3] for row in self.db.connection.execute("EXPLAIN QUERY PLAN " + query))
        self.assertIn("idx_business_owner_global", plan)
        self.assertIn("idx_business_worker_global", plan)
        self.assertNotIn("SCAN b", plan)
        self.assertNotIn("SCAN w", plan)
