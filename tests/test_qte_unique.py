import json
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace
import unittest

from aiohttp.test_utils import TestClient, TestServer
from arena_qte_unique import review_catalog
from arena_web import create_arena_app


class UniqueReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_only_routes_work_without_database_or_telegram(self):
        client = TestClient(
            TestServer(create_arena_app(SimpleNamespace(), SimpleNamespace(), "test"))
        )
        await client.start_server()
        try:
            for path in ("/qte-lab/unique", "/qte-lab/unique/"):
                response = await client.get(path)
                self.assertEqual(response.status, 200)
                html = await response.text()
                self.assertNotIn("__REV__", html)
                self.assertNotIn("__CATALOG__", html)
                self.assertNotIn("telegram-web-app", html)
            for path in re.findall(r'(?:src|href)="(/[^\"]+)"', html):
                self.assertEqual((await client.get(path)).status, 200, path)
            for name in ("engine", "client"):
                source = await (await client.get(f"/qte-lab/unique/{name}.js")).text()
                for forbidden in (
                    "fetch(",
                    "/api/",
                    "localStorage",
                    "sessionStorage",
                    "XMLHttpRequest",
                ):
                    self.assertNotIn(forbidden, source)
            self.assertEqual((await client.post("/qte-lab/unique/")).status, 405)
        finally:
            await client.close()

    def test_every_native_hostile_skill_and_named_finals_have_profiles(self):
        from arena_engine import BUILTIN_SKILLS
        from arena_raid_engine import BOSS_SKILLS

        catalog = review_catalog()
        ids = {s["base_id"] for s in catalog}
        self.assertTrue(
            {s.skill_id for s in (BUILTIN_SKILLS | BOSS_SKILLS).values() if s.hostile}
            <= ids
        )
        names = {s["name"] for s in catalog}
        for name in (
            "Билет в паровозик",
            "Огненный шар",
            "Ледяное копьё",
            "Цепная молния",
            "Точка небытия",
            "Всё обратить в пепел",
        ):
            self.assertIn(name, names)
        self.assertEqual(len(catalog), len({s["id"] for s in catalog}))

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_review_simulation(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_unique.cjs"))],
            input=json.dumps(review_catalog()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
