"""Small in-memory Telegram photo cache; never expose bot file URLs/tokens."""
import asyncio
import io
import time
from collections import OrderedDict
from aiogram.exceptions import TelegramAPIError

MAX_AVATAR_BYTES=384*1024


class GuildAvatarCache:
    def __init__(self,bot):
        self.bot=bot;self.cache=OrderedDict();self.lock=asyncio.Lock()

    async def get(self,user):
        # One in-flight download at a time also deduplicates simultaneous loads
        # from several viewers. It never holds the database/combat lock.
        async with self.lock:
            entry=self.cache.get(user)
            if entry and entry[0]>time.monotonic():
                self.cache.move_to_end(user);return entry[1]
            try:value=await asyncio.wait_for(self.download(user),6)
            except (TelegramAPIError,OSError,asyncio.TimeoutError):value=None
            self.cache[user]=(time.monotonic()+(3600 if value else 300),value)
            self.cache.move_to_end(user)
            while len(self.cache)>256:self.cache.popitem(last=False)
            return value

    async def download(self,user):
        photos=await self.bot.get_user_profile_photos(user_id=user,limit=1)
        if not photos.photos or not photos.photos[0]:return None
        photo=min(photos.photos[0],key=lambda p:p.width*p.height)
        if (photo.file_size or 0)>MAX_AVATAR_BYTES:return None
        file=await self.bot.get_file(photo.file_id)
        if not file.file_path or (file.file_size or 0)>MAX_AVATAR_BYTES:return None
        buffer=io.BytesIO()
        await self.bot.download_file(file.file_path,destination=buffer)
        data=buffer.getvalue()
        if len(data)>MAX_AVATAR_BYTES:return None
        mime=('image/jpeg' if data.startswith(b'\xff\xd8\xff') else
              'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
              'image/webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None)
        return (data,mime) if mime else None
