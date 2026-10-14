import unittest
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from aiohttp.test_utils import TestClient, TestServer

from arena_progression import choice_avatar
from arena_rpg import RPG_BRANCHES
from arena_web import create_arena_app
from tools.prepare_pet_sprites import clean_alpha
import test_arena_market_client as client_tests


class RPGSpriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_transparent_compact_assets_served_with_full_margins(self):
        app=create_arena_app(SimpleNamespace(),SimpleNamespace(),'test-token')
        client=TestClient(TestServer(app));await client.start_server()
        try:
            for cls in ('warrior','mage','priest','hunter'):
                with self.subTest(cls=cls):
                    path=choice_avatar(cls)
                    self.assertEqual(path,'/static/assets/rpg/'+cls+'.png')
                    response=await client.get(path)
                    self.assertEqual(response.status,200)
                    raw=await response.read()
                    self.assertLess(len(raw),700000)
                    with Image.open(BytesIO(raw)) as im:
                        self.assertEqual(im.size,(512,768))
                        self.assertEqual(im.mode,'RGBA')
                        self.assertEqual(im.getchannel('A').getextrema(),(0,255))
                        self.assertEqual(im.getpixel((0,0)),(0,0,0,0))
                        box=im.getchannel('A').getbbox()
                        self.assertGreaterEqual(min(box[0],box[1],512-box[2],768-box[3]),24)
        finally:await client.close()

    def test_branches_use_their_approved_base_skin_not_unknown_files(self):
        for key,(cls,_,_) in RPG_BRANCHES.items():
            self.assertEqual(choice_avatar(cls,key),choice_avatar(cls))
            self.assertEqual(choice_avatar('',key),choice_avatar(cls))
        self.assertEqual(choice_avatar('jock','mge_bro'),'/static/assets/archclasses/mge_bro.png')

    def test_browser_selector_accepts_rpg_paths_and_custom_skin_wins(self):
        runner=client_tests.ArenaMarketClientTests()
        for cls in ('warrior','mage','priest','hunter'):
            profile=dict(sprite=cls,class_avatar_url=choice_avatar(cls))
            self.assertEqual(runner.run_client('out=sprite(input);',profile),choice_avatar(cls))
            self.assertEqual(runner.run_client('out=sprite(input);',cls),choice_avatar(cls))
            custom='/sprites/'+'a'*64+'.png'
            self.assertEqual(runner.run_client('out=sprite(input);',dict(profile,sprite_url=custom)),custom)
            self.assertEqual(runner.run_client('out=sprite(input);',dict(profile,class_avatar_url='/static/assets/rpg/../../bad.png')),choice_avatar(cls))

    def test_alpha_cleanup_preserves_opaque_black_clothing(self):
        im=Image.new('RGBA',(32,32),(40,20,10,100))
        im.paste((0,0,0,254),(10,10,20,20))
        cleaned=clean_alpha(im)
        self.assertEqual(cleaned.getpixel((15,15)),(0,0,0,255))
        self.assertEqual(cleaned.getpixel((0,0)),(0,0,0,0))
        self.assertEqual(im.getpixel((0,0)),(40,20,10,100))
