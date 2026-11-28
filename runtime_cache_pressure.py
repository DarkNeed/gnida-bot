"""Best-effort Linux page-cache hints for the bot's own files."""

import asyncio
from collections import OrderedDict
import logging
import os
from pathlib import Path, PurePosixPath
import stat
import time

LOG = logging.getLogger("runtime.cache")
MIB = 1024 * 1024
STATIC_PREFIX = "/static/assets/"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".ogg", ".wav", ".flac", ".m4a"}


def supported(probe):
    return probe.version in (1, 2) and all(hasattr(os, name) for name in (
        "posix_fadvise", "POSIX_FADV_DONTNEED", "O_NOFOLLOW", "O_NONBLOCK"))


def _advise_files(database, asset_root, assets):
    hinted = 0
    # Never target SQLite's WAL/SHM files or run a global drop_caches.
    for path, root in [(database, None), *((asset_root.joinpath(*p.parts), asset_root) for p in assets)]:
        if path is None:
            continue
        try:
            path = path.resolve(strict=True)
            if root is not None and not path.is_relative_to(root):
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if stat.S_ISREG(info.st_mode) and info.st_size >= 128 * 1024:
                    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                    hinted += 1
            finally:
                os.close(fd)
        except (OSError, RuntimeError, ValueError):
            # Missing, replaced or unsupported files are safe to skip.
            continue
    return hinted


class FileCachePressure:
    def __init__(self, probe, database, asset_root, *, clock=time.monotonic):
        self.probe = probe
        self.database = Path(database)
        self.asset_root = Path(asset_root).resolve()
        self.clock = clock
        self.recent_assets = OrderedDict()
        self.last_db_hint = float("-inf")

    def record_asset(self, url_path):
        if not url_path.startswith(STATIC_PREFIX) or "\\" in url_path:
            return
        path = PurePosixPath(url_path[len(STATIC_PREFIX):])
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in MEDIA_SUFFIXES:
            return
        self.recent_assets[path] = self.clock()
        self.recent_assets.move_to_end(path)
        if len(self.recent_assets) > 128:
            self.recent_assets.popitem(last=False)

    async def check(self):
        meters = self.probe.sample()
        total, limit = meters.get("cg_current"), meters.get("cg_limit")
        cache = (meters.get("cg_file") or 0) - (meters.get("cg_shmem") or 0)
        if not total or not limit or total < .80 * limit or cache < 128 * MIB:
            return 0
        current = self.clock()
        paths = []
        for asset, touched in self.recent_assets.items():
            if current - touched < 15 or len(paths) >= 32:
                break
            paths.append(asset)
        for asset in paths:
            self.recent_assets.pop(asset, None)
        database = self.database if current - self.last_db_hint >= 120 else None
        if database is not None:
            self.last_db_hint = current
        if not paths and database is None:
            return 0
        hinted = await asyncio.to_thread(_advise_files, database, self.asset_root, paths)
        if hinted:
            LOG.info("CACHE_PRESSURE before_mib=%.1f file_minus_shmem_mib=%.1f files_hinted=%d",
                     total / MIB, cache / MIB, hinted)
        return hinted

    async def run(self):
        while True:
            await asyncio.sleep(15)
            await self.check()
