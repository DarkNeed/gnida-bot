"""The experimental server must remain separate from production battle APIs."""
import importlib.util
from pathlib import Path
import unittest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('queue_preview', ROOT / 'tools/preview_action_queue.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class QueuePreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(preview.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_assets_and_no_cache(self):
        for path in ['/action-queue-review', '/party-battle-review', '/lab/battle.js', '/lab/battle-client.js', '/lab/battle.css', '/lab/client.js', '/lab/engine.js', '/lab/existing.js', '/lab/existing-view.js', '/lab/style.css', '/shared/qte-input.js', '/shared/qte-input.css', '/existing/patterns.js', '/existing/block.js', '/existing/art.js', '/existing/view.js', '/existing/block-view.js', '/assets/rpg/mage.png']:
            response = await self.client.get(path)
            self.assertEqual(response.status, 200, path)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_original_catalog_embedded(self):
        import json
        import re
        text = await (await self.client.get('/action-queue-review')).text()
        catalog = json.loads(re.search(r'<script id="catalog" type="application/json">(.*?)</script>', text, re.S).group(1))
        self.assertGreater(len(catalog), 400)
        self.assertTrue(any(s['base_id'] == 'warning_shot' for s in catalog))
        self.assertTrue(all('cost' in s for s in catalog))
        self.assertNotIn('__CATALOG__', text)

    async def test_no_production_endpoints_or_writes(self):
        self.assertEqual((await self.client.get('/api/rp')).status, 404)
        self.assertEqual((await self.client.get('/api/battle')).status, 404)
        self.assertEqual((await self.client.post('/action-queue-review', json={})).status, 405)
        self.assertEqual(await (await self.client.get('/health')).json(), {'ok': True, 'lab': True, 'accounts': False})


if __name__ == '__main__':
    unittest.main()
