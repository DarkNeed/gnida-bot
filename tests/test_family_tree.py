import asyncio
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from arena_web import create_arena_app
from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from family_tree import FamilyError
from handlers.family import FAMILY_RE
from test_arena import TOKEN, signed


class FamilyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "family.db")
        self.addAsyncCleanup(self.db.close)
        await self.db.connect()
        for user, name in [(1, "Исток"), (2, "Алекс"), (3, "Вера"), (4, "Семён"), (5, "Сова"), (6, "<Гость>")]:
            await self.db.upsert_user(-100, user, "person_" + str(user), name, touch=False)
        await self.db.upsert_chat(-100, "Каргассия")

    async def edit(self, operation, a, b=None):
        result = await self.db.family_edit(-100, 1, operation, a, b)
        await self.db.family_edit(-100, 1, operation, a, b, expected=result["revision"])
        return result

    async def marry(self, a, b):
        token = await self.db.family_offer(-100, a, b)
        await self.db.family_offer_action(-100, token, b, "accept")

    async def test_component_divorce_and_chat_isolation(self):
        await self.edit("origin",1)
        await self.edit("link",1,2)
        await self.marry(2,3)
        await self.edit("link",2,4)
        await self.edit("link",5,6)
        view = await self.db.family_view(-100,2,False)
        self.assertEqual(view["members"],[1,2,4])
        self.assertEqual(view["marriages"],[])
        self.assertEqual(view["spouse"],3)
        self.assertEqual((await self.db.family_view(-200,2,False))["members"],[])
        self.assertEqual(await self.db.family_search(-100,"СЕМЕН",False),[dict(id=4,name="Семён",username="person_4")])
        self.assertFalse((await self.db.family_search(-100,"@PERSON_6",True))[0]["in_tree"])
        await self.edit("link",3,4)
        self.assertEqual((await self.db.family_view(-100,2,False))["marriages"],[[2,3]])
        case, partner, created = await self.db.family_filing(-100,2,"личная причина")
        self.assertEqual((partner,created),(3,True))
        self.assertEqual(await self.db.family_filing(-100,3,"дубль"),(case,2,False))
        self.assertEqual((await self.db.family_view(-100,4,False,case))["cases"],[])
        with self.assertRaises(FamilyError):
            await self.db.family_decide(-100,2,True,case,True)
        with self.assertRaises(FamilyError):
            await self.db.family_decide(-100,5,False,case,True)
        await self.edit("appoint",5)
        await self.db.family_decide(-100,5,False,case,True)
        view = await self.db.family_view(-100,2,False,mine=True)
        self.assertEqual(view["members"],[1,2,3,4])
        self.assertEqual(view["marriages"],[])
        self.assertEqual(view["cases"][0]["status"],"approved")

    async def test_preview_validation_and_revision(self):
        await self.edit("origin",1)
        await self.edit("link",1,2)
        await self.edit("link",2,3)
        for edit,a,b in [("link",3,1),("link",3,2),("link",2,3),("origin",3,None)]:
            with self.assertRaises(FamilyError):
                await self.db.family_edit(-100,1,edit,a,b)
        removal = await self.db.family_edit(-100,1,"unlink",1,2)
        self.assertEqual([p["id"] for p in removal["removed"]],[2,3])
        self.assertEqual((await self.db.family_view(-100,2,False))["members"],[1,2,3])
        await self.edit("link",3,4)
        with self.assertRaises(FamilyError):
            await self.db.family_edit(-100,1,"unlink",1,2,expected=removal["revision"])
        swap = await self.edit("origin",5)
        self.assertEqual([p["id"] for p in swap["removed"]],[1,2,3,4])
        self.assertEqual((await self.db.family_view(-100,2,False))["members"],[5])

    async def test_offer_confirmation_is_single_use_and_recipient_only(self):
        token = await self.db.family_offer(-100,1,3)
        for chat,actor in [(-200,3),(-100,1),(-100,2)]:
            with self.assertRaises(FamilyError):
                await self.db.family_offer_action(chat,token,actor,"accept")
        both = await asyncio.gather(*[self.db.family_offer_action(-100,token,3,"accept") for _ in range(2)],
                                    return_exceptions=True)
        self.assertEqual(sum(result is None for result in both),1)
        self.assertIsInstance(next(result for result in both if result is not None),FamilyError)
        with self.assertRaises(FamilyError):
            await self.db.family_offer(-100,3,4)

    async def test_signed_mini_app_roles_and_preview_before_write(self):
        async def member(chat, user):
            status = "creator" if user == 1 else "left" if user == 6 else "member"
            return SimpleNamespace(status=status, user=SimpleNamespace(
                id=user, is_bot=False, username=f"person_{user}", full_name=f"Участник {user}"))
        bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=member),
                              get_chat=AsyncMock(return_value=SimpleNamespace(type="supergroup")))
        client = TestClient(TestServer(create_arena_app(self.db,bot,TOKEN)))
        self.addAsyncCleanup(client.close)
        await client.start_server()
        path = "/api/family/-100"
        def auth(id):
            return {"X-Telegram-Init-Data": signed(id, int(time.time()))}
        self.assertEqual((await client.get(path)).status,400)
        self.assertEqual((await client.get(path,headers=auth(6))).status,400)
        self.assertEqual((await client.get("/family")).status,200)
        self.assertEqual((await client.get("/static/family.js")).status,200)
        self.assertTrue((await (await client.get(path,headers=auth(CUSTOM_COMMAND_OWNER_ID))).json())["owner"])
        body = dict(op="preview",edit="origin",a=1)
        self.assertEqual((await client.post(path,json=body,headers=auth(2))).status,400)
        self.assertEqual((await client.get(path+"/search?q=сова&directory=1",headers=auth(2))).status,400)
        preview = await (await client.post(path,json=body,headers=auth(1))).json()
        self.assertEqual(preview["added"][0]["id"],1)
        body["op"] = "apply"
        self.assertEqual((await client.post(path,json=body,headers=auth(1))).status,400)
        body["revision"] = preview["revision"]
        self.assertEqual((await client.post(path,json=body,headers=auth(1))).status,400)
        body["proof"] = preview["proof"]
        self.assertEqual((await client.post(path,json={**body, "a": 3},headers=auth(1))).status,400)
        self.assertEqual((await client.post(path,json=body,headers=auth(1))).status,200)
        self.assertEqual((await client.post(path,json=body,headers=auth(1))).status,400)
        view = await (await client.get(path,headers=auth(2))).json()
        self.assertEqual(view["members"],[1])
        self.assertIsNone(view["editor"])
        self.assertTrue(FAMILY_RE.match("!семья связь @person_1 @person_2"))
        self.assertFalse(FAMILY_RE.match("!семьянин"))
