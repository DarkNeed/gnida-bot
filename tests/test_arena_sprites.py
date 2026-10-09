import hashlib
import hmac
import json
import random
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from PIL import Image, PngImagePlugin
from aiohttp.test_utils import TestClient, TestServer
from arena_images import MAX_SPRITE_BYTES, normalize_sprite
from arena_web import create_arena_app, menu_view, battle_view
from database import Database

TOKEN = "123456:test-sprites"


def png(size=(36, 36), color=(255, 255, 255, 255), opaque=False, metadata=False):
    image = Image.new("RGBA", size, color if opaque else (0, 0, 0, 0))
    if not opaque:
        image.paste(color, (3, 3, size[0]-3, size[1]-3))
    output = BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("Comment", "private artist metadata")
    image.save(output, format="PNG", pnginfo=info)
    return output.getvalue()


def headers(user=10, pixels="true"):
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user})}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k,v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(data), "Content-Type": "image/png", "X-Pixel-Art": pixels}


class SpriteValidationTests(unittest.TestCase):
    def test_native_sizes_alpha_and_metadata(self):
        for size in (16, 36, 64, 128, 1024):
            with self.subTest(size=size):
                result = normalize_sprite(png((size, size), metadata=True))
                with Image.open(BytesIO(result)) as image:
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, "RGBA")
                    self.assertEqual(image.getpixel((0, 0)), (0,0,0,0))
                    self.assertEqual(image.info, {})

    def test_non_square_and_partial_alpha_supported(self):
        result = normalize_sprite(png((64, 128), color=(10,20,30,120)))
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size, (64,128))
            self.assertEqual(image.getpixel((4,4)), (10,20,30,120))

    def test_invalid_sizes(self):
        for size in ((15,64), (64,1025), (1025,16)):
            with self.assertRaisesRegex(ValueError, "от 16 до 1024"):
                normalize_sprite(png(size))

    def test_opaque_blank_corrupt_and_non_png(self):
        for data in (png(opaque=True), png(color=(0,0,0,0)), b"<svg></svg>", png()[:50], b""):
            with self.subTest(data=data[:15]):
                with self.assertRaises(ValueError):
                    normalize_sprite(data)
        output=BytesIO()
        Image.new("RGB", (36,36)).save(output,format="JPEG")
        with self.assertRaises(ValueError):
            normalize_sprite(output.getvalue())

    def test_max_bytes(self):
        with self.assertRaisesRegex(ValueError, "2 МБ"):
            normalize_sprite(b"x" * (MAX_SPRITE_BYTES+1))

    def test_animation_rejected(self):
        first=Image.open(BytesIO(png()))
        second=Image.open(BytesIO(png(color=(0,255,0,255))))
        output=BytesIO()
        first.save(output,format="PNG",save_all=True,append_images=[second],duration=200,loop=0)
        first.close()
        second.close()
        with self.assertRaisesRegex(ValueError, "анимированных"):
            normalize_sprite(output.getvalue())

    def test_indexed_png(self):
        image=Image.new("P", (36,36), 0)
        image.putpalette([0,0,0,255,255,255]+[0,0,0]*254)
        image.paste(1,(3,3,30,30))
        output=BytesIO()
        image.save(output,format="PNG",transparency=0)
        self.assertTrue(normalize_sprite(output.getvalue()))


class SpriteHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.temp.name)/"bot.sqlite3")
        await self.db.connect()
        for chat in (1,2):
            await self.db.upsert_chat(chat, "Чат")
            for user in (10,20,30):
                await self.db.upsert_user(chat,user,str(user),"User "+str(user))
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))
        self.client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.db.close()
        self.temp.cleanup()

    async def upload(self, data=None, user=10, chat=1, pixels="true"):
        response=await self.client.post(f"/api/menu/{chat}/sprite", data=png() if data is None else data, headers=headers(user,pixels))
        self.assertEqual(response.status,200,await response.text())
        return await response.json()

    async def test_upload_menu_public_image_and_reset(self):
        result=await self.upload()
        profile=result["menu"]["personal"]
        self.assertTrue(profile["pixel_art"])
        self.assertTrue(profile["can_edit_sprite"])
        response=await self.client.get(profile["sprite_url"])
        self.assertEqual(response.status,200)
        self.assertIn("image/png",response.headers["Content-Type"])
        self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
        self.assertEqual(await response.read(),normalize_sprite(png()))
        response=await self.client.delete("/api/menu/1/sprite",headers=headers())
        self.assertEqual(response.status,200)
        self.assertIsNone((await response.json())["menu"]["personal"]["sprite_url"])
        self.assertIsNone(await self.db.arena_sprite_png(profile["sprite_url"].split("/")[-1][:-4]))

    async def test_replace_one_row_and_chat_separation(self):
        first=await self.upload()
        second=await self.upload(png(color=(0,255,0,255)),pixels="false")
        self.assertNotEqual(first["menu"]["personal"]["sprite_url"],second["menu"]["personal"]["sprite_url"])
        self.assertFalse(second["menu"]["personal"]["pixel_art"])
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_sprites").fetchone()[0],1)
        self.assertIsNone((await menu_view(self.db,2,10))["personal"]["sprite_url"])
        self.assertIsNone((await menu_view(self.db,1,20))["personal"]["sprite_url"])

    async def test_upload_cannot_choose_other_user(self):
        response=await self.client.post("/api/menu/1/sprite?user=20",data=png(),headers=headers())
        self.assertEqual(response.status,200)
        self.assertIsNotNone((await self.db.arena_sprite_info(1,10))["sprite_url"])
        self.assertIsNone((await self.db.arena_sprite_info(1,20))["sprite_url"])

    async def test_auth_and_fresh_membership_for_upload_and_reset(self):
        response=await self.client.post("/api/menu/1/sprite",data=png())
        self.assertEqual(response.status,400)
        await self.upload()
        self.bot.get_chat_member.return_value=SimpleNamespace(status="left")
        for method in (self.client.post,self.client.delete):
            response=await method("/api/menu/1/sprite",headers=headers(),data=png())
            self.assertEqual(response.status,400)
        self.assertIsNotNone((await self.db.arena_sprite_info(1,10))["sprite_url"])

    async def test_bad_upload_keeps_existing(self):
        saved=(await self.upload())["menu"]["personal"]["sprite_url"]
        for data,pixels in ((b"bad","true"),(png(opaque=True),"true"),(png(),"oops")):
            response=await self.client.post("/api/menu/1/sprite",data=data,headers=headers(pixels=pixels))
            self.assertEqual(response.status,400,await response.text())
            self.assertEqual((await self.db.arena_sprite_info(1,10))["sprite_url"],saved)
        response=await self.client.post("/api/menu/1/sprite",data=png(),headers={**headers(),"Content-Type":"image/svg+xml"})
        self.assertEqual(response.status,400)

    async def test_large_upload_returns_json_413(self):
        response=await self.client.post("/api/menu/1/sprite",data=BytesIO(b"x"*(MAX_SPRITE_BYTES+2)),headers=headers())
        self.assertEqual(response.status,413)
        self.assertIn("2 МБ",(await response.json())["error"])

    async def test_valid_upload_over_json_limit_and_json_limit_unchanged(self):
        image=Image.frombytes("RGBA",(256,256),random.Random(1).randbytes(256*256*4))
        image.putpixel((0,0),(0,0,0,0))
        output=BytesIO()
        image.save(output,format="PNG")
        raw=output.getvalue()
        self.assertGreater(len(raw),64*1024)
        await self.upload(raw)
        response=await self.client.post("/api/menu/1",data="x"*(65*1024),headers={**headers(),"Content-Type":"application/json"})
        self.assertEqual(response.status,413)

    async def test_unknown_and_path_like_image_key(self):
        for path in ("/sprites/"+"0"*64+".png","/sprites/not-a-hash.png"):
            response=await self.client.get(path)
            self.assertEqual(response.status,404)

    async def test_own_art_in_slave_and_personal_battle_and_owner_menu(self):
        url=(await self.upload(user=30))["menu"]["personal"]["sprite_url"]
        await self.db.force_enslave(1,30,10)
        await self.db.arena_equip_slave(1,10,30,True)
        owner=await menu_view(self.db,1,10)
        self.assertEqual(owner["slaves"][0]["sprite_url"],url)
        self.assertFalse(owner["slaves"][0]["can_edit_sprite"])
        slave=await menu_view(self.db,1,30)
        self.assertEqual(slave["self_slave"]["sprite_url"],url)
        self.assertTrue(slave["self_slave"]["can_edit_sprite"])
        for actor,fighter,personal in ((10,30,False),(30,30,True)):
            row=await self.db.arena_wasteland(1,actor,fighter,personal=personal)
            view=await battle_view(self.db,row,20)
            self.assertEqual(view["state"]["sides"]["a"]["sprite_url"],url)
            self.assertIsNone(view["state"]["sides"]["b"]["sprite_url"])
            await self.db.arena_action(row["token"],actor,row["revision"],"surrender")
        row=await self.db.arena_offer(1,30,20,"personal")
        await self.db.arena_set_message(row["token"],1)
        row=await self.db.arena_setup(row["token"],20,"accept")
        view=await battle_view(self.db,row,20)
        self.assertEqual(view["state"]["sides"]["a"]["sprite_url"],url)

    async def test_backup_restart_and_ownership_transfer_preserve_image(self):
        url=(await self.upload(user=30))["menu"]["personal"]["sprite_url"]
        await self.db.force_enslave(1,30,10)
        await self.db.force_enslave(1,30,20)
        self.assertEqual((await self.db.arena_sprite_info(1,30))["sprite_url"],url)
        snapshot=Path(self.temp.name)/"backup.sqlite3"
        await self.db.backup_to(snapshot)
        with closing(sqlite3.connect(snapshot)) as connection:
            raw=connection.execute("SELECT png FROM arena_sprites WHERE chat_id=1 AND user_id=30").fetchone()[0]
            self.assertEqual(raw,normalize_sprite(png()))
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.db.arena_sprite_info(1,30))["sprite_url"],url)
