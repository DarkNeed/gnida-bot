import json
from pathlib import Path
import re
import subprocess
import unittest
from aiohttp.test_utils import TestClient, TestServer
from arena_qte_unique import review_catalog

ROOT = Path(__file__).resolve().parents[1]


class ArtRenderTests(unittest.TestCase):
    def test_all_profiles_render_read_only(self):
        result = json.loads(subprocess.check_output(
            ['node', 'tests/qte_art_render.cjs'], cwd=ROOT,
            input=json.dumps(review_catalog()).encode(),
        ))
        self.assertGreater(result['profiles'], 250)
        self.assertGreater(result['draws'], 15000)
        self.assertGreaterEqual(result['motifs'], 25)
        self.assertEqual(result['classes'] + result['existingCasino'], 14)

    def test_live_loads_art_before_views_and_versions_it(self):
        from arena_assets import render_arena_index
        page = render_arena_index(ROOT / 'webapp')
        art = re.search(r'/static/qte-art.js\?v=([a-f0-9]+)', page)
        view = re.search(r'/static/qte-view.js\?v=([a-f0-9]+)', page)
        self.assertIsNotNone(art)
        self.assertEqual(art.group(1), view.group(1))
        self.assertLess(art.start(), view.start())

    def test_labs_use_live_renderers_for_every_class(self):
        client = (ROOT / 'webapp/qte-unique/client').read_text(encoding='utf8')
        self.assertEqual(client.count('if(window.QTEView){window.QTEView.draw(ctx,canvas,s);return;}'), 2)
        block = (ROOT / 'webapp/qte-block/client').read_text(encoding='utf8')
        self.assertIn('if(window.QTEBlockView){window.QTEBlockView.draw(ctx,canvas,s);return;}', block)


class ArtRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_preview_assets_and_lab_cache_revision(self):
        from tools.preview_qte_art import application
        async with TestClient(TestServer(application())) as client:
            for path in ['/qte-lab/art/', '/qte-lab/unique/', '/qte-lab/block/']:
                res = await client.get(path)
                self.assertEqual(res.status, 200)
                page = await res.text()
                self.assertNotIn('__REV__', page)
                self.assertNotIn('__CATALOG__', page)
                self.assertIn('/static/qte-art.js?v=', page)
                for src in re.findall(r'<script[^>]*src="([^"]+)"', page):
                    asset = await client.get(src)
                    self.assertEqual(asset.status, 200, src)
                    self.assertIn('javascript', asset.headers.get('Content-Type', ''))
            res = await client.post('/api/arena')
            self.assertEqual(res.status, 404)


if __name__ == '__main__':
    unittest.main()
