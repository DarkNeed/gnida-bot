import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
from arena_assets import render_arena_index
from arena_web import create_arena_app


class ArenaAssetRevisionTests(unittest.TestCase):
    def test_css_and_client_version_changes_with_either_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(
                '<link href="/static/style.css"><script src="/static/client.js"></script>',
                encoding="utf-8",
            )
            (root / "style.css").write_text("button{}", encoding="utf-8")
            (root / "battle-client").write_text("const a=1;", encoding="utf-8")
            old = render_arena_index(root)
            self.assertEqual(old, render_arena_index(root))
            self.assertEqual(len(set(re.findall(r"v=([0-9a-f]{16})", old))), 1)
            (root / "style.css").write_text("button{padding:0}", encoding="utf-8")
            css_changed = render_arena_index(root)
            self.assertNotEqual(old, css_changed)
            (root / "battle-client").write_text("const a=2;", encoding="utf-8")
            self.assertNotEqual(css_changed, render_arena_index(root))


class ArenaAssetHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_versioned_assets_load_without_login_and_revalidate(self):
        client = TestClient(
            TestServer(
                create_arena_app(SimpleNamespace(), SimpleNamespace(), "test-token")
            )
        )
        await client.start_server()
        try:
            response = await client.get("/")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            body = await response.text()
            for path in re.findall(r'(?:href|src)="(/static/[^\"]+)"', body):
                self.assertIn("?v=", path)
                asset = await client.get(path)
                self.assertEqual(asset.status, 200)
                self.assertEqual(asset.headers["Cache-Control"], "no-cache")
            css = await client.get("/static/style.css")
            self.assertEqual(css.headers["Cache-Control"], "no-cache")
        finally:
            await client.close()
