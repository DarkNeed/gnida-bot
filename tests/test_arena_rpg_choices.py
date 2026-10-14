import unittest
from io import BytesIO

from PIL import Image
import test_arena_progression as helpers
from arena_progression import choice_avatar
from arena_rpg import RPG_BRANCHES
from arena_rpg_paths import PATHS


class RPGChoicesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=helpers.ProgressionTests.asyncSetUp
    asyncTearDown=helpers.ProgressionTests.asyncTearDown
    level=helpers.ProgressionTests.level
    profile=helpers.ProgressionTests.profile
    choose=helpers.ProgressionTests.choose

    async def test_existing_level_twenty_all_nine_paths_choose_stay_or_advance(self):
        for key,(cls,_,_) in RPG_BRANCHES.items():
            with self.subTest(key=key):
                self.level(20,cls)
                await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
                self.level(20,cls)
                self.db.connection.execute("UPDATE personal_profiles SET archclass_id=?,archclass_stage=10,progression_level=10 WHERE chat_id=0 AND user_id=10",(key,))
                self.db.connection.commit()
                p=await self.profile()
                self.assertEqual(p['progression_choice']['level'],20)
                self.assertEqual([o['id'] for o in p['progression_choice']['options']],['stay','advance'])
                self.assertEqual(p['progression_choice']['options'][1]['avatar_url'],choice_avatar(cls,key,20))
                xp=p['xp']
                await self.choose('advance')
                p=await self.profile()
                self.assertEqual(p['class_name'],PATHS[key][0])
                self.assertEqual(p['class_avatar_url'],choice_avatar(cls,key,20))
                self.assertEqual(p['xp'],xp)
                self.assertIsNone(p['progression_choice'])

    async def test_rpg_final_stay_and_custom_png_survive_restart(self):
        self.level(20,'mage')
        self.db.connection.execute("UPDATE personal_profiles SET archclass_id='mage_archmage',archclass_stage=10,progression_level=10 WHERE chat_id=0 AND user_id=10")
        self.db.connection.commit()
        image=Image.new('RGBA',(36,36));image.paste((255,255,255,255),(3,3,33,33))
        raw=BytesIO();image.save(raw,format='PNG')
        await self.db.arena_set_sprite(1,10,raw.getvalue(),False)
        url=(await self.profile())['sprite_url']
        await self.choose('stay')
        await self.db.close();await self.db.connect()
        p=await self.profile()
        self.assertEqual(p['sprite_url'],url)
        self.assertEqual(p['class_name'],'Архимаг')
        self.assertEqual(p['archclass_stage'],10)
        self.assertIsNone(p['progression_choice'])


if __name__=='__main__':unittest.main()
