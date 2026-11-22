"""Refresh a chat's archived avatars from Telegram's current profile photo."""
import asyncio
from collections import OrderedDict
import io
import time

from aiogram.exceptions import TelegramAPIError

PHOTO_LIMIT = 96 * 1024  # Telegram's small chat photo is 160×160.


class FamilyAvatarCache:
    def __init__(self, db, bot):
        self.db, self.bot = db, bot
        self.checked = OrderedDict()
        self.locks = [asyncio.Lock() for _ in range(32)]
        self.slots = asyncio.Semaphore(3)

    async def get(self, chat, user, *, refresh=False):
        key = (chat, user)
        async with self.locks[hash(key) % len(self.locks)]:
            saved = await self.db.family_saved_avatar(chat, user)
            checked, retry = self.checked.get(key, (float("-inf"), 0))
            max_age = min(retry, 3) if refresh else retry
            if time.monotonic() - checked < max_age:
                return saved
            try:
                async with self.slots:
                    current = await asyncio.wait_for(self.current(chat, user, saved), timeout=7)
            except (TelegramAPIError, OSError, asyncio.TimeoutError):
                current, retry = saved, 30
            else:
                retry = 300
            if current != saved:
                await self.db.family_save_avatar(chat, user, current)
            self.checked[key] = (time.monotonic(), retry)
            self.checked.move_to_end(key)
            while len(self.checked) > 4096:
                self.checked.popitem(last=False)
            return current

    async def current(self, chat, user, saved):
        member = await self.bot.get_chat_member(chat, user)
        if member.status in ("left", "kicked") or (member.status == "restricted" and not member.is_member):
            return saved
        profile = await self.bot.get_chat(user)
        if profile.type != "private" or profile.id != user:
            return saved
        photo = profile.photo
        if not photo:
            return None
        key = photo.small_file_unique_id
        if saved and saved[0] == key:
            return saved
        file = await self.bot.get_file(photo.small_file_id)
        if not file.file_path or (file.file_size or 0) > PHOTO_LIMIT:
            return saved
        buffer = io.BytesIO()
        await self.bot.download_file(file.file_path, destination=buffer)
        data = buffer.getvalue()
        if len(data) > PHOTO_LIMIT:
            return saved
        mime = ("image/jpeg" if data.startswith(b"\xff\xd8\xff") else
                "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
                "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
        return (key, data, mime) if mime else saved
