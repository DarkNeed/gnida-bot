import asyncio
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

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
        await self.edit("link",3,7)
        await self.edit("link",5,6)
        view = await self.db.family_view(-100,2,False)
        self.assertEqual(view["members"],[1,2,3,4,7])
        self.assertEqual(view["detached"],[[5,6]])
        self.assertIn([3,7],view["parents"])
        self.assertIn([5,6],view["parents"])
        self.assertEqual(view["marriages"],[[2,3]])
        self.assertEqual(view["spouse"],3)
        self.assertEqual((await self.db.family_view(-200,2,False))["members"],[])
        self.assertEqual(await self.db.family_search(-100,"СЕМЕН",False),[dict(id=4,name="Семён",username="person_4")])
        self.assertEqual((await self.db.family_search(-100,"@PERSON_6",False))[0]["id"],6)
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
        self.assertEqual(view["members"],[1,2,3,4,7])
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

    async def test_siblings_connect_components_and_reject_impossible_generations(self):
        await self.edit("origin", 1)
        await self.edit("link", 1, 2)
        await self.edit("link", 3, 4)
        await self.edit("sibling", 3, 2)
        view = await self.db.family_view(-100, 2, True)
        self.assertEqual(view["members"], [1, 2, 3, 4])
        self.assertEqual(view["siblings"], [[2, 3]])
        self.assertEqual(view["parents"], [[1, 2], [3, 4]])
        with self.assertRaisesRegex(FamilyError, "близкими|Близкие"):
            await self.db.family_offer(-100, 2, 3)
        for operation, a, b in [("sibling", 2, 3), ("sibling", 2, 4), ("link", 2, 3), ("sibling", 0, 3)]:
            with self.subTest(operation=operation, a=a, b=b), self.assertRaises(FamilyError):
                await self.db.family_edit(-100, 1, operation, a, b)
        await self.edit("unsibling", 3, 2)
        view = await self.db.family_view(-100, 1, True)
        self.assertEqual(view["members"], [1, 2])
        self.assertEqual(view["detached"], [[3, 4]])
        self.assertEqual(view["siblings"], [])

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

    async def test_empty_origin_preserves_tree_and_keeps_anchors_separate_from_parentage(self):
        await self.edit("origin",1)
        await self.edit("link",1,2)
        changed = await self.edit("origin",0)
        self.assertEqual((changed["added"], changed["removed"]), ([], []))
        await self.edit("link",0,3)
        await self.marry(1,3)  # Sharing a virtual root does not make them siblings.
        view = await self.db.family_view(-100,1,True)
        self.assertEqual(view["origin"],0)
        self.assertEqual(view["branches"],[1,3])
        self.assertEqual(view["members"],[0,1,2,3])
        self.assertEqual(view["parents"],[[1,2]])
        self.assertNotIn(0,[person["id"] for person in view["people"]])
        self.assertFalse(await self.db.family_avatar_allowed(-100,0))
        detached = await self.edit("unlink",0,1)
        self.assertEqual(detached["removed"],[])  # Still reachable via the spouse.
        await self.edit("unlink",0,3)
        state = await self.db.family_view(-100,1,True)
        self.assertEqual(state["members"],[0])
        self.assertEqual(state["detached"],[[1,2,3]])

    async def test_editor_marriage_is_visible_and_uses_court(self):
        await self.edit("origin",1)
        await self.edit("link",1,2)
        for a,b in ((2,2),(1,2),(0,2)):
            with self.assertRaises(FamilyError):
                await self.db.family_edit(-100,1,"marry",a,b)
        old_offer = await self.db.family_offer(-100,3,2)
        preview = await self.db.family_edit(-100,1,"marry",3,2)
        self.assertTrue(preview["marriage_rooted"])
        self.assertIsNone((await self.db.family_view(-100,3,False))["spouse"])
        self.assertEqual(await self.db.family_offer_people(-100,old_offer),(3,2))
        await self.db.family_edit(-100,1,"marry",3,2,expected=preview["revision"])
        self.assertIsNone(await self.db.family_offer_people(-100,old_offer))
        state = await self.db.family_view(-100,2,True)
        self.assertEqual(state["members"],[1,2,3])
        self.assertEqual(state["marriages"],[[2,3]])
        self.assertEqual(state["editor"]["marriages"],[[2,3]])
        self.assertIn("брак внесён через редактор",state["log"][0]["description"])
        with self.assertRaises(FamilyError):
            await self.db.family_edit(-100,1,"marry",2,4)
        await self.edit("origin",0)
        await self.edit("link",0,3)
        self.assertEqual((await self.db.family_view(-100,3,False))["marriages"],[[2,3]])
        case, partner, _ = await self.db.family_filing(-100,3,"")
        self.assertEqual(partner,2)
        await self.db.family_decide(-100,1,True,case,True)
        self.assertEqual((await self.db.family_view(-100,3,False))["marriages"],[])

    async def test_detached_marriage_without_origin_is_present_and_searchable(self):
        preview = await self.edit("marry",2,3)
        self.assertFalse(preview["marriage_rooted"])
        await self.edit("link",3,4)
        view = await self.db.family_view(-100,4,False)
        self.assertEqual(view["members"],[])
        self.assertEqual(view["detached"],[[2,3,4]])
        self.assertEqual(view["marriages"],[[2,3]])
        self.assertEqual(view["parents"],[[3,4]])
        self.assertEqual([p["id"] for p in view["people"]],[2,3,4])
        self.assertTrue(await self.db.family_avatar_allowed(-100,2))
        self.assertFalse(await self.db.family_avatar_allowed(-100,5))

    async def test_avatar_route_uses_current_photo_and_keeps_departed_snapshot(self):
        await self.edit("link",2,3)  # Even an unconnected family gets avatars.
        now = [10]
        self.enterContext(patch("family_avatars.time",SimpleNamespace(monotonic=lambda:now[0])))
        profile = SimpleNamespace(id=2,type="private",photo=SimpleNamespace(small_file_id="current",small_file_unique_id="v1"))
        target = SimpleNamespace(status="member")
        async def member(chat, user):
            return target if user == 2 else SimpleNamespace(status="member")
        async def download(path, *, destination):
            destination.write(b"\xff\xd8\xff" + path.encode())
        bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=member),get_chat=AsyncMock(return_value=profile),
                              get_file=AsyncMock(side_effect=lambda ident:SimpleNamespace(file_path=ident,file_size=12)),
                              download_file=AsyncMock(side_effect=download),get_user_profile_photos=AsyncMock())
        client = TestClient(TestServer(create_arena_app(self.db,bot,TOKEN)))
        self.addAsyncCleanup(client.close)
        await client.start_server()
        auth = {"X-Telegram-Init-Data":signed(3,int(time.time()))}
        path = "/api/family/-100/avatar/2"
        first = await client.get(path,headers=auth)
        self.assertEqual(await first.read(),b"\xff\xd8\xffcurrent")
        self.assertEqual(first.content_type,"image/jpeg")
        profile.photo = SimpleNamespace(small_file_id="new",small_file_unique_id="v2")
        second = await client.get(path,headers=auth)
        self.assertEqual(await second.read(),b"\xff\xd8\xffcurrent")
        now[0] += 4
        refreshed = await client.get(path+"?refresh=1",headers=auth)
        self.assertEqual(await refreshed.read(),b"\xff\xd8\xffnew")
        target.status = "left"
        now[0] += 4
        left = await client.get(path+"?refresh=1",headers=auth)
        self.assertEqual(await left.read(),b"\xff\xd8\xffnew")
        self.assertEqual(bot.get_chat.await_count,2)
        bot.get_user_profile_photos.assert_not_awaited()
        target.status,profile.photo = "member",None
        now[0] += 4
        self.assertEqual((await client.get(path+"?refresh=1",headers=auth)).status,404)
        self.assertIsNone(await self.db.family_saved_avatar(-100,2))

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
        self.assertTrue(FAMILY_RE.match("!древо связь исток @person_2"))
        self.assertTrue(FAMILY_RE.match("/древо исток пустой"))
        self.assertFalse(FAMILY_RE.match("!семья"))
        self.assertFalse(FAMILY_RE.match("!древовидный"))
        await self.edit("origin",0)
        bot.get_chat_member.reset_mock()
        branch = dict(op="preview",edit="link",a=0,b=2)
        preview = await (await client.post(path,json=branch,headers=auth(1))).json()
        self.assertEqual([person["id"] for person in preview["added"]],[2])
        self.assertEqual([call.args for call in bot.get_chat_member.await_args_list],[(-100,1),(-100,2)])
        response = await client.post(path,json=dict(branch,op="apply",revision=preview["revision"],proof=preview["proof"]),headers=auth(1))
        self.assertEqual(response.status,200)
        wedding = dict(op="preview",edit="marry",a=3,b=2)
        self.assertEqual((await client.post(path,json=wedding,headers=auth(2))).status,400)
        self.assertEqual((await client.post(path,json=dict(wedding,a=0),headers=auth(1))).status,400)
        self.assertEqual((await client.post(path,json=dict(wedding,b=6),headers=auth(1))).status,400)
        preview = await (await client.post(path,json=wedding,headers=auth(1))).json()
        self.assertIs(preview["marriage_rooted"],True)
        wedding.update(op="apply",revision=preview["revision"],proof=preview["proof"])
        self.assertEqual((await client.post(path,json=dict(wedding,b=4),headers=auth(1))).status,400)
        self.assertEqual((await client.post(path,json=wedding,headers=auth(1))).status,200)
        view = await (await client.get(path,headers=auth(2))).json()
        self.assertEqual(view["spouse"],3)
        self.assertEqual(view["marriages"],[[2,3]])
        siblings = dict(op="preview", edit="sibling", a=2, b=4)
        self.assertEqual((await client.post(path, json=siblings, headers=auth(2))).status, 400)
        preview = await (await client.post(path, json=siblings, headers=auth(1))).json()
        siblings.update(op="apply", revision=preview["revision"], proof=preview["proof"])
        self.assertEqual((await client.post(path, json=siblings, headers=auth(1))).status, 200)
        view = await (await client.get(path, headers=auth(2))).json()
        self.assertEqual(view["siblings"], [[2, 4]])
