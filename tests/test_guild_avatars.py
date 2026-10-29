"""Private Telegram photo proxy, bounded caching and party identity layout."""
import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,patch
from aiohttp.test_utils import TestClient,TestServer
from arena_guild_avatars import GuildAvatarCache,MAX_AVATAR_BYTES
from arena_web import create_arena_app
from test_arena import signed,TOKEN
import test_guild as fixtures
import time

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aSuoAAAAASUVORK5CYII=')


def photo_bot():
    async def download(path,destination):destination.write(PNG)
    return NS(get_user_profile_photos=AsyncMock(return_value=NS(photos=[[NS(file_id='small',width=160,height=160,file_size=90),NS(file_id='large',width=640,height=640,file_size=1000)]])),
        get_file=AsyncMock(return_value=NS(file_path='photos/private-file.jpg',file_size=90)),download_file=AsyncMock(side_effect=download))


class AvatarCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_smallest_thumbnail_and_concurrent_requests_are_cached(self):
        bot=photo_bot();cache=GuildAvatarCache(bot)
        values=await asyncio.gather(*(cache.get(10) for _ in range(5)))
        self.assertTrue(all(v==(PNG,'image/png') for v in values))
        bot.get_file.assert_awaited_once_with('small');bot.get_user_profile_photos.assert_awaited_once_with(user_id=10,limit=1)
        bot.download_file.assert_awaited_once()

    async def test_no_photo_and_unavailable_api_do_not_repeat_requests(self):
        bot=photo_bot();bot.get_user_profile_photos.return_value=NS(photos=[]);cache=GuildAvatarCache(bot)
        self.assertIsNone(await cache.get(10));self.assertIsNone(await cache.get(10))
        bot.get_user_profile_photos.assert_awaited_once();bot.get_file.assert_not_awaited()
        bot.get_user_profile_photos.side_effect=OSError('network unavailable')
        self.assertIsNone(await cache.get(20))

    async def test_oversized_or_non_raster_payload_is_rejected(self):
        bot=photo_bot();bot.get_file.return_value.file_size=MAX_AVATAR_BYTES+1
        self.assertIsNone(await GuildAvatarCache(bot).get(10));bot.download_file.assert_not_awaited()
        bot.get_file.return_value.file_size=90
        async def html(path,destination):destination.write(b'<svg onload="bad()"></svg>')
        bot.download_file.side_effect=html
        self.assertIsNone(await GuildAvatarCache(bot).get(10))

    async def test_cache_is_bounded_and_refreshes_expired_entries(self):
        bot=photo_bot();bot.get_user_profile_photos.return_value=NS(photos=[]);cache=GuildAvatarCache(bot)
        for user in range(260):await cache.get(user)
        self.assertEqual(len(cache.cache),256);self.assertNotIn(0,cache.cache)
        cache.cache[259]=(0,None)
        count=bot.get_user_profile_photos.await_count;await cache.get(259)
        self.assertEqual(bot.get_user_profile_photos.await_count,count+1)

    def test_party_layout_uses_avatar_and_rank_beside_name(self):
        root=Path(__file__).resolve().parents[1]/'webapp'
        js=(root/'guild.js').read_text(encoding='utf-8')
        party=js.split('function party(r){',1)[1].split('async function avatarUrl',1)[0]
        self.assertIn('guild-member-avatar',party);self.assertIn('guild-member-heading',party);self.assertIn('guild-member-rank',party)
        self.assertNotIn('badge(p.rank,true)',party)
        self.assertIn('URL.revokeObjectURL',js)
        self.assertIn("headers:{'X-Telegram-Init-Data':init}",js)


class AvatarRouteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.GuildTests.asyncSetUp
    asyncTearDown=fixtures.GuildTests.asyncTearDown
    create=fixtures.GuildTests.create

    async def test_avatar_requires_signed_chat_membership_and_roster_target(self):
        media=photo_bot()
        for name in ('get_user_profile_photos','get_file','download_file'):setattr(self.bot,name,getattr(media,name))
        run=await self.create()
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)));await client.start_server()
        try:
            url='/api/guild/runs/'+run['id']+'/avatars/10'
            res=await client.get(url);self.assertEqual(res.status,400)
            headers={'X-Telegram-Init-Data':signed(99,int(time.time()))}
            res=await client.get(url,headers=headers);self.assertEqual(res.status,400)
            headers={'X-Telegram-Init-Data':signed(20,int(time.time()))}
            res=await client.get(url,headers=headers)
            self.assertEqual(res.status,200);self.assertEqual(await res.read(),PNG)
            self.assertEqual(res.content_type,'image/png');self.assertEqual(res.headers['Cache-Control'],'no-store')
            res=await client.get(url.rsplit('/',1)[0]+'/30',headers=headers);self.assertEqual(res.status,400)
            media.get_user_profile_photos.assert_awaited_once_with(user_id=10,limit=1)
        finally:await client.close()

    async def test_missing_photo_is_empty_success_for_initials_fallback(self):
        self.bot.get_user_profile_photos=AsyncMock(return_value=NS(photos=[]))
        run=await self.create();client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)));await client.start_server()
        try:
            res=await client.get('/api/guild/runs/'+run['id']+'/avatars/10',headers={'X-Telegram-Init-Data':signed(10,int(time.time()))})
            self.assertEqual(res.status,204);self.assertEqual(await res.read(),b'')
        finally:await client.close()


if __name__=='__main__':unittest.main()
