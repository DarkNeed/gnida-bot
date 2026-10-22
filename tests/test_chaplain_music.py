import re
import unittest

from aiohttp.test_utils import TestClient, TestServer
from tools.preview_chaplain import application


class ChaplainMusicReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_music_page_and_assets_work_without_starting_a_raid(self):
        app = await application()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get('/chaplain-music')
            self.assertEqual(response.status, 200)
            html = await response.text()
            self.assertNotIn('__AUDIO_REV__', html)
            for key in ('chaplain_fault', 'chaplain_override', 'chaplain_root'):
                self.assertIn(key, html)
            self.assertNotIn('telegram-web-app', html)
            for url in re.findall(r'(?:src|href)="(/(?:static)/[^\"]+)"', html):
                self.assertEqual((await client.get(url)).status, 200, url)
            self.assertIsNone(app['chaplain_review_db'].connection.execute('SELECT 1 FROM arena_raids LIMIT 1').fetchone())
            index = await client.get('/chaplain-review')
            self.assertIn('/chaplain-music', await index.text())
        finally:
            await client.close()


if __name__ == '__main__':
    unittest.main()
