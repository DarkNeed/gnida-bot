import re
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
from arena_web import create_arena_app


class QTELabHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_lab_is_isolated_and_assets_load_without_telegram_or_database(self):
        # Empty dependencies deliberately fail if a lab request touches live services.
        client = TestClient(
            TestServer(
                create_arena_app(SimpleNamespace(), SimpleNamespace(), "test-token")
            )
        )
        await client.start_server()
        try:
            for url in ("/qte-lab", "/qte-lab/"):
                response = await client.get(url)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            html = await response.text()
            self.assertNotIn("__REV__", html)
            assets = re.findall(r'(?:src|href)="(/[^\"]+)"', html)
            for path in assets:
                response = await client.get(path)
                self.assertEqual(response.status, 200, path)
            for name in ("engine", "client"):
                response = await client.get(f"/qte-lab/{name}.js")
                self.assertTrue(
                    response.headers["Content-Type"].startswith(
                        "application/javascript"
                    )
                )
                self.assertEqual(response.headers["Cache-Control"], "no-cache")
                code = await response.text()
                for forbidden in (
                    "fetch(",
                    "localStorage",
                    "sessionStorage",
                    "XMLHttpRequest",
                    "/api/",
                ):
                    self.assertNotIn(forbidden, code)
            self.assertEqual((await client.get("/api/menu/-1")).status, 400)
            self.assertEqual((await client.post("/qte-lab/")).status, 405)
        finally:
            await client.close()

    async def test_preview_exposes_the_same_lab(self):
        from tools.preview_arena import app

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for url in (
                "/qte-lab/",
                "/qte-lab/engine.js",
                "/qte-lab/client.js",
                "/static/qte-lab/style.css",
            ):
                self.assertEqual((await client.get(url)).status, 200)
        finally:
            await client.close()


@unittest.skipUnless(shutil.which("node"), "Node is needed for simulation tests")
class QTELabSimulationTests(unittest.TestCase):
    def test_pure_simulation(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_lab.cjs"))],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
