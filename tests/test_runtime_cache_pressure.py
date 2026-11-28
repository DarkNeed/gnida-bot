import os
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer

from arena_web import create_arena_app
from runtime_cache_pressure import FileCachePressure, MIB, _advise_files


class PressureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = 100
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.probe = Mock(sample=Mock(return_value=dict(cg_current=800*MIB, cg_limit=1024*MIB,
                                                       cg_file=560*MIB, cg_shmem=0)))
        self.guard = FileCachePressure(self.probe, self.root / "game.sqlite3", self.assets,
                                       clock=lambda: self.clock)

    async def test_threshold_shared_memory_and_cooldown(self):
        self.guard.record_asset("/static/assets/guild/large.png")
        with patch("runtime_cache_pressure._advise_files", return_value=2) as advise:
            self.clock = 123
            self.assertEqual(await self.guard.check(), 0)
            self.probe.sample.return_value.update(cg_current=900*MIB, cg_shmem=500*MIB)
            self.assertEqual(await self.guard.check(), 0)
            advise.assert_not_called()
            self.probe.sample.return_value.update(cg_shmem=0)
            self.guard.record_asset("/static/assets/just-loaded.png")
            self.assertEqual(await self.guard.check(), 2)
            self.assertEqual(advise.call_args.args[0:2], (self.guard.database, self.assets))
            self.assertEqual(advise.call_args.args[2], [PurePosixPath("guild/large.png")])
            self.assertEqual(await self.guard.check(), 0)
            self.clock += 20
            await self.guard.check()
            self.assertIsNone(advise.call_args.args[0])
            self.assertEqual(advise.call_args.args[2], [PurePosixPath("just-loaded.png")])

    async def test_assets_are_bounded_and_only_trusted_media_paths_are_tracked(self):
        for index in range(300):
            self.guard.record_asset(f"/static/assets/guild/{index}.png")
        for bad in ("/static/assets/../secrets.png", "/static/assets//etc/test.png",
                    "/static/assets/secret\\file.png", "/static/assets/token.txt", "/api/res/asset.png"):
            self.guard.record_asset(bad)
        self.assertEqual(len(self.guard.recent_assets), 128)
        self.assertEqual(next(iter(self.guard.recent_assets)), PurePosixPath("guild/172.png"))

    async def test_real_http_route_records_the_media_path(self):
        app = create_arena_app(Mock(), Mock(), "preview", record_asset=self.guard.record_asset)
        async with TestClient(TestServer(app)) as client:
            self.assertEqual((await client.get("/static/assets/cutie.png")).status, 200)
            self.assertEqual((await client.get("/static/style.css")).status, 200)
        self.assertEqual(tuple(self.guard.recent_assets), (PurePosixPath("cutie.png"),))

    @unittest.skipUnless(hasattr(os, "posix_fadvise"), "requires Linux file-cache advice")
    async def test_only_clean_page_hints_for_own_regular_files_no_content_changes(self):
        media = self.assets / "large.png"
        payload = b"asset" * 30000
        media.write_bytes(payload)
        unrelated = self.root / "private.png"
        unrelated.write_bytes(payload)
        (self.assets / "escape.png").symlink_to(unrelated)
        with patch("runtime_cache_pressure.os.posix_fadvise") as advise:
            hits = _advise_files(None, self.assets, [PurePosixPath("large.png"), PurePosixPath("escape.png")])
        self.assertEqual(hits, 1)
        advise.assert_called_once()
        self.assertEqual(media.read_bytes(), payload)
        self.assertEqual(unrelated.read_bytes(), payload)
