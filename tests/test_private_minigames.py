import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User
from database import Database
from handlers.routes import PRIVATE_GAMES_SCOPE, create_router


class PrivateGamesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.folder.name)/'games.sqlite3')
        await self.db.connect()
        self.router=create_router(self.db,kargassia_chat_id=None)
        self.users=[User(id=k,is_bot=False,first_name=f'Игрок {k}') for k in (10,20,30)]
        self.bot=SimpleNamespace(token='test-token',get_chat_member=AsyncMock(side_effect=AssertionError('No group membership required')),
            edit_message_text=AsyncMock(),send_message=AsyncMock())
        self.before=set(asyncio.all_tasks())

    async def asyncTearDown(self):
        tasks=[t for t in asyncio.all_tasks() if t not in self.before and t is not asyncio.current_task()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await self.db.close()
        self.folder.cleanup()

    def handler(self,name,kind='callback_query'):
        return next(h.callback for h in getattr(self.router,kind).handlers if h.callback.__name__==name)

    def callback(self,data,user=1):
        return SimpleNamespace(data=data,inline_message_id='private-inline-1',from_user=self.users[user],answer=AsyncMock())

    async def offer(self):
        query=SimpleNamespace(query='play',from_user=self.users[0],answer=AsyncMock())
        await self.handler('inline_challenge_query','inline_query')(query,self.bot)
        return query.answer.await_args.args[0]

    async def start(self,game):
        await self.offer()
        callback=self.callback('ia:10:'+game)
        await self.handler('accept_inline_challenge')(callback,self.bot)
        row=self.db.connection.execute("SELECT * FROM challenges WHERE chat_id=? AND status='active'",(PRIVATE_GAMES_SCOPE,)).fetchone()
        self.assertIsNotNone(row,callback.answer.await_args)
        return row

    async def test_all_games_start_without_any_group_or_configured_home_chat(self):
        for game in ('rps','blackjack','checkers'):
            row=await self.start(game)
            self.assertEqual(row['game_type'],game)
            self.assertTrue(row['friendly'])
            self.assertFalse(row['forced'])
            await self.db.finish_challenge(row['id'],'cancelled')
        self.bot.get_chat_member.assert_not_awaited()
        self.assertIsNone(await self.db.get_user(-1001,10))

    async def test_group_game_and_private_game_do_not_block_each_other(self):
        await self.db.upsert_chat(-1001,'Каргассия')
        for user in self.users[:2]:await self.db.upsert_user(-1001,user.id,user.username,user.full_name)
        group=await self.db.create_challenge(-1001,10,20,game_type='blackjack')
        row=await self.start('rps')
        self.assertNotEqual(row['id'],group)
        self.assertEqual((await self.db.get_challenge(group))['status'],'active')

    async def test_rps_play_is_private_and_does_not_create_slavery(self):
        row=await self.start('rps');ident=row['id']
        outsider=self.callback(f'rps:{ident}:rock',2)
        await self.handler('rps_callback')(outsider,self.bot)
        self.assertIsNone((await self.db.get_challenge(ident))['challenger_choice'])
        for user,choice in ((0,'rock'),(1,'scissors')):
            await self.handler('rps_callback')(self.callback(f'rps:{ident}:{choice}',user),self.bot)
        done=await self.db.get_challenge(ident)
        self.assertEqual(done['status'],'finished')
        self.assertIsNone(await self.db.get_owner(PRIVATE_GAMES_SCOPE,20))
        self.bot.get_chat_member.assert_not_awaited()

    async def test_old_unregistered_offer_requests_a_fresh_invitation(self):
        callback=self.callback('ia:999:rps')
        await self.handler('accept_inline_challenge')(callback,self.bot)
        self.assertIn('новый вызов',callback.answer.await_args.args[0])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM challenges').fetchone()[0],0)


if __name__=='__main__':unittest.main()
