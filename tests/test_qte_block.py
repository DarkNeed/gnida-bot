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


class BlockLabTests(unittest.IsolatedAsyncioTestCase):
    async def test_lab_works_without_database_telegram_or_gameplay_writes(self):
        client = TestClient(
            TestServer(create_arena_app(SimpleNamespace(), SimpleNamespace(), "test"))
        )
        await client.start_server()
        try:
            for path in ("/qte-lab/block", "/qte-lab/block/"):
                response = await client.get(path)
                self.assertEqual(response.status, 200)
                html = await response.text()
                self.assertNotIn("__REV__", html)
                self.assertNotIn("__CATALOG__", html)
                self.assertNotIn("telegram-web-app", html)
            for path in re.findall(r'(?:src|href)="(/[^\"]+)"', html):
                self.assertEqual((await client.get(path)).status, 200, path)
            for name in ("engine", "client"):
                source = await (await client.get(f"/qte-lab/block/{name}.js")).text()
                for forbidden in (
                    "fetch(",
                    "/api/",
                    "localStorage",
                    "sessionStorage",
                    "XMLHttpRequest",
                ):
                    self.assertNotIn(forbidden, source)
            self.assertEqual((await client.post("/qte-lab/block/")).status, 405)
        finally:
            await client.close()

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_block_rules_and_all_catalog_schedules(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_block.cjs"))],
            input=json.dumps(review_catalog()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
