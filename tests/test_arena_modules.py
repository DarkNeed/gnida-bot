"""Per-chat feature switches; class groups are no longer gated."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from arena_web import menu_view


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

    async def toggle(self,key,on,chat=1):
        settings=await self.db.arena_modules(chat)
        return await self.db.arena_set_module(chat,10,key,on,settings['revision'])

    async def test_defaults_chat_isolation_revision_restart(self):
        settings=await self.db.arena_modules(1)
        self.assertEqual({m['id'] for m in settings['modules'] if m['enabled']},{'arena','slavery'})
        await self.toggle('arena',False)
        with self.assertRaisesRegex(ValueError,'изменились'):
            await self.db.arena_set_module(1,20,'slavery',False,0)
        await self.db.close();await self.db.connect()
        self.assertFalse(await self.db.feature_enabled(1,'arena'))
        self.assertTrue(await self.db.feature_enabled(2,'arena'))
        self.assertTrue(await self.db.feature_enabled(1,'slavery'))

    async def test_disabled_arena_cancels_old_fight_and_blocks_new_until_enabled(self):
        battle=await self.db.arena_wasteland(1,10,10,personal=True)
        await self.toggle('arena',False)
        closed=await self.db.arena_get(battle['token'])
        self.assertEqual(closed['status'],'cancelled')
        self.assertEqual(json.loads(closed['state_json'])['rewards'],{})
        with self.assertRaisesRegex(ValueError,'выключен'):
            await self.db.arena_wasteland(1,10,10,personal=True)
        await self.toggle('arena',True)
        self.assertEqual((await self.db.arena_wasteland(1,10,10,personal=True))['status'],'active')

    async def test_all_classes_and_tractates_available_and_old_group_controls_rejected(self):
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute('UPDATE personal_profiles SET xp=72,level=5,progression_level=5 WHERE chat_id=0 AND user_id=10')
        self.db._arena_add_item_locked(1,10,'skill','mana_shot','uncommon',1)
        item=self.db.connection.execute('SELECT id FROM arena_inventory WHERE chat_id=0').fetchone()[0]
        self.db.connection.commit()
        await self.db.arena_use_item(1,10,item,10,True)
        view=await menu_view(self.db,2,10)
        self.assertIn('mage',{c['id'] for c in view['personal']['classes']})
        self.assertIn('mana_shot',{s['skill_id'] for s in view['personal']['skills']})
        self.assertIn(('skill','mana_shot'),self.db._forge_catalog_locked(1))
        for key in ('classic','humor','moon'):
            with self.assertRaises(ValueError):await self.toggle(key,False)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1,10,10,True,'module_class','ragamuffin')

    async def test_toggling_does_not_restore_or_change_profile_and_items(self):
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET class_id='jock',level=18,xp=1500,progression_level=10 WHERE chat_id=0 AND user_id=10")
        self.db._arena_add_item_locked(1,10,'skill','dust_in_eyes','common',3)
        self.db.connection.commit()
        before=dict(self.db._arena_profile_locked(1,10,True))
        await self.toggle('arena',False)
        await self.toggle('arena',True)
        self.assertEqual(dict(self.db._arena_profile_locked(2,10,True)),before)
        self.assertEqual(self.db.connection.execute('SELECT quantity FROM arena_inventory WHERE chat_id=0').fetchone()[0],3)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM arena_class_archives').fetchone()[0],0)

    async def test_hunter_ai_ignores_locked_visceral(self):
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
        self.assertEqual(json.loads(result['state_json'])['log'][-1]['skill_id'],'bum_punch')
