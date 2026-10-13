import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from arena_engine import BUILTIN_SKILLS
from arena_web import menu_view
from arena_wasteland import enemy_source


class ModuleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.temp.name)/'modules.sqlite3')
        await self.db.connect()
        for chat in (1,2):
            await self.db.upsert_chat(chat,'Чат')
            for user in (10,20):await self.db.upsert_user(chat,user,str(user),'Игрок')
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))

    async def asyncTearDown(self):
        await self.db.close();self.temp.cleanup()

    async def toggle(self, key, on, chat=1):
        settings=await self.db.arena_modules(chat)
        return await self.db.arena_set_module(chat,10,key,on,settings['revision'])

    def profile(self,cls='jock',arch='mge_bro'):
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET class_id=?,archclass_id=?,level=18,xp=1500,progression_level=10,loadout='[\"club_hit\"]' WHERE chat_id=1 AND user_id=10",(cls,arch))
        self.db.connection.commit()

    async def test_defaults_chat_isolation_revision_restart(self):
        settings=await self.db.arena_modules(1)
        self.assertEqual({m['id'] for m in settings['modules'] if m['enabled']},{'moon','humor'})
        await self.toggle('classic',True)
        with self.assertRaisesRegex(ValueError,'изменились'):
            await self.db.arena_set_module(1,20,'moon',False,0)
        await self.db.close();await self.db.connect()
        self.assertTrue(next(m['enabled'] for m in (await self.db.arena_modules(1))['modules'] if m['id']=='classic'))
        self.assertFalse(next(m['enabled'] for m in (await self.db.arena_modules(2))['modules'] if m['id']=='classic'))

    async def test_disabled_class_blocks_new_fight_but_preserves_old_battle(self):
        self.profile()
        battle=await self.db.arena_wasteland(1,10,10,personal=True)
        snapshot=battle['state_json']
        await self.toggle('humor',False)
        self.assertEqual((await self.db.arena_get(battle['token']))['state_json'],snapshot)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,10,10,True,'module_class','ragamuffin')
        await self.db.arena_action(battle['token'],10,battle['revision'],'surrender')
        with self.assertRaisesRegex(ValueError,'выключен'):
            await self.db.arena_wasteland(1,10,10,personal=True)

    async def test_archive_roundtrip_preserves_levels_items_skin_and_progress(self):
        self.profile()
        self.db.connection.execute("INSERT INTO arena_learned VALUES(1,10,1,'skill','super_fan')")
        self.db._arena_add_item_locked(1,10,'skill','dust_in_eyes','common',3)
        self.db.connection.commit()
        await self.db.arena_set_sprite(1,10,b'test bytes',False)
        before=dict(self.db._arena_profile_locked(1,10,True))
        await self.toggle('humor',False)
        await self.db.arena_edit_profile(1,10,10,True,'module_class','ragamuffin')
        switched=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((switched['level'],switched['xp']),(18,1500))
        self.assertTrue((await self.db.arena_sprite_info(1,10))['sprite_url'])
        self.assertEqual(self.db.connection.execute('SELECT quantity FROM arena_inventory').fetchone()[0],3)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,20,10,True,'restore_class','jock')
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,10,10,True,'restore_class','jock')
        self.db.connection.execute('UPDATE personal_profiles SET xp=2000,level=19 WHERE chat_id=1 AND user_id=10')
        self.db.connection.commit()
        await self.toggle('humor',True)
        await self.db.arena_edit_profile(1,10,10,True,'restore_class','jock')
        restored=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((restored['class_id'],restored['archclass_id']),('jock','mge_bro'))
        self.assertEqual((restored['level'],restored['xp']),(19,2000))
        self.assertEqual(restored['loadout'],before['loadout'])
        self.assertIsNotNone(self.db.connection.execute("SELECT 1 FROM arena_learned WHERE content_id='super_fan'").fetchone())

    async def test_disabled_tractates_cannot_be_used_or_forged(self):
        self.profile('ragamuffin','')
        self.db._arena_add_item_locked(1,10,'skill','mana_shot','uncommon',1)
        item=self.db.connection.execute('SELECT id FROM arena_inventory').fetchone()[0]
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'выключен'):
            await self.db.arena_use_item(1,10,item,10,True)
        self.assertEqual(self.db.connection.execute('SELECT quantity FROM arena_inventory').fetchone()[0],1)
        self.assertNotIn(('skill','mana_shot'),self.db._forge_catalog_locked(1))
        await self.toggle('classic',True)
        self.assertIn(('skill','mana_shot'),self.db._forge_catalog_locked(1))
        view=await menu_view(self.db,1,10)
        self.assertIn('mage',{c['id'] for c in view['personal']['classes']})

    async def test_npcs_respect_enabled_classes_and_hunter_ai_ignores_locked_visceral(self):
        for _ in range(40):
            self.assertEqual(enemy_source(18,enabled_classes={'ragamuffin'})['class_id'],'ragamuffin')
        await self.toggle('classic',True)
        def hunter(*args,**kwargs):
            return dict(slave_id=0,owner_id=0,controlled=False,class_id='hunter',level=18,
                        archclass_id='hunter_moon',loadout=['hunter_visceral'],known_skills=['hunter_visceral'])
        with patch('arena_store.enemy_source',side_effect=hunter):
            battle=await self.db.arena_wasteland(1,10,10,personal=True)
        state=json.loads(battle['state_json']);state['active_side']='a'
        self.db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(state),battle['token']))
        self.db.connection.commit()
        result=await self.db.arena_action(battle['token'],10,battle['revision'],'bum_punch')
        self.assertEqual(result['revision'],battle['revision']+1)
        log=json.loads(result['state_json'])['log']
        self.assertEqual(log[-1]['skill_id'],'bum_punch')

    async def test_deliberate_reset_cannot_recover_sacrificed_levels_from_archive(self):
        self.profile()
        await self.toggle('humor',False)
        await self.db.arena_edit_profile(1,10,10,True,'module_class','ragamuffin')
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM arena_class_archives').fetchone()[0],1)
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        await self.toggle('humor',True)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,10,10,True,'restore_class','jock')
        profile=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((profile['level'],profile['xp']),(1,0))
