"""Account RPG migration, feature isolation, reservations and authorization."""
import asyncio
import json
import random
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from database import Database
from arena_engine import xp_for_next_level, FIGHTER_CLASSES, BUILTIN_SKILLS
from arena_web import menu_view, create_arena_app
from arena_raid_engine import raid_boss_level
from handlers.admin_menu import create_admin_menu_router
from handlers.routes import create_router
import test_arena


def xp_at(level):
    return sum(xp_for_next_level(i) for i in range(1,level))


class Hit(random.Random):
    def random(self): return 0
    def uniform(self,a,b): return 1


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'account.sqlite3')
        await self.db.connect()
        for chat in (1,2):
            await self.db.upsert_chat(chat,'QA '+str(chat))
            for user in (10,20,30):
                await self.db.upsert_user(chat,user,str(user),'User '+str(user))
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))

    async def asyncTearDown(self):
        await self.db.close(); self.tmp.cleanup()

    def profile(self,chat=1,user=10):
        return dict(self.db._arena_profile_locked(chat,user,True))

    def level(self,level,cls='ragamuffin',user=10):
        self.profile(user=user)
        self.db.connection.execute('UPDATE personal_profiles SET xp=?,level=?,class_id=?,progression_level=? WHERE chat_id=0 AND user_id=?',
            (xp_at(level),level,cls,level,user))
        self.db.connection.commit()

    def item(self,kind='skill',content='dust_in_eyes',quantity=1):
        self.db._arena_add_item_locked(1,10,kind,content,'common',quantity)
        self.db.connection.commit()
        return self.db._arena_item_locked(2,10,self.db.connection.execute('SELECT id FROM arena_inventory WHERE chat_id=0 AND owner_id=10 AND content_id=?',(content,)).fetchone()[0])['id']

    async def toggle(self,feature,on,chat=1):
        settings=await self.db.arena_modules(chat)
        return await self.db.arena_set_module(chat,10,feature,on,settings['revision'])

    async def test_same_profile_progression_class_and_loadout_in_every_chat(self):
        self.db._grant_profile_xp_locked('personal_profiles',1,10,100)
        self.db.connection.commit()
        await self.db.arena_edit_profile(2,10,10,True,'progression','jock')
        a,b=await menu_view(self.db,1,10),await menu_view(self.db,2,10)
        for field in ('level','xp','class_id','known_skills','loadout','passive_loadout'):
            self.assertEqual(a['personal'][field],b['personal'][field])
        self.assertEqual(a['personal']['class_id'],'jock')
        self.assertFalse(a['slaves']); self.assertFalse(a['self_slave'])
        self.assertTrue(a['global_progression'])
        self.assertTrue({'warrior','mage','priest','hunter'}.issubset({c['id'] for c in a['personal']['classes']}))
        await self.db.close(); await self.db.connect()
        self.assertEqual(self.profile(2)['class_id'],'jock')

    async def test_reset_and_catchup_apply_globally_without_stacking(self):
        self.level(18,'jock')
        await self.db.arena_edit_profile(2,10,10,True,'reset_class',True)
        self.assertEqual(self.profile()['level'],5)
        self.assertEqual(self.profile()['catchup_target_xp'],xp_at(18))
        await self.db.arena_edit_profile(1,10,10,True,'progression','nerd')
        self.db._grant_profile_xp_locked('personal_profiles',2,10,30,battle=True)
        self.assertEqual(self.profile()['xp'],xp_at(5)+60)
        await self.db.arena_edit_profile(2,10,10,True,'reset_class',True)
        self.db._grant_profile_xp_locked('personal_profiles',1,10,30,battle=True)
        self.assertEqual(self.profile()['xp'],xp_at(5)+60)

    async def test_shared_inventory_learning_and_transfer(self):
        self.level(5)
        item=self.item('passive','stone_skin',2)
        await self.db.arena_use_item(2,10,item,10)
        a,b=await menu_view(self.db,1,10),await menu_view(self.db,2,10)
        self.assertEqual(a['inventory'],b['inventory'])
        self.assertIn('stone_skin',a['personal']['known_passives']) if 'known_passives' in a['personal'] else self.assertIn('stone_skin',[p['skill_id'] for p in a['personal']['passives']])
        await self.db.arena_transfer_item(2,10,item,20)
        self.assertEqual(self.db._arena_inventory_locked(1,20)[0]['quantity'],1)
        self.assertFalse(self.db._arena_inventory_locked(1,10))

    async def test_global_sprite_set_and_reset(self):
        await self.db.arena_set_sprite(1,10,b'png-test',True)
        self.assertEqual(await self.db.arena_sprite_info(1,10),await self.db.arena_sprite_info(2,10))
        await self.db.arena_reset_sprite(2,10)
        self.assertIsNone((await self.db.arena_sprite_info(1,10))['sprite_url'])

    async def test_owner_cannot_change_or_apply_items_to_another_account(self):
        await self.db.force_enslave(1,30,10)
        item=self.item('candy','experience')
        for personal in (False,True):
            with self.assertRaises(ValueError): await self.db.arena_edit_profile(1,10,30,personal,'reset_class',True)
            with self.assertRaises(ValueError): await self.db.arena_use_item(1,10,item,30,personal)
        self.assertEqual(self.db._arena_item_locked(1,10,item)['quantity'],1)

    async def test_no_slave_fighters_or_exclusive_grants(self):
        for operation in (self.db.arena_offer(1,10,20,'slaves'),self.db.arena_equip_slave(1,10,30,True),
                          self.db.arena_wasteland(1,10,30,personal=False),self.db.arena_mirror_start(1,10,30,False),
                          self.db.arena_admin_grant(1,10,'skill','x',1980056841,True)):
            with self.assertRaises(ValueError): await operation
        await self.db.create_custom_fighter_content('skill','secret',dict(name='Secret',class_id='ragamuffin',power=10),1980056841)
        await self.db.create_custom_fighter_content('skill','public',dict(name='Public',class_id='ragamuffin',power=10,merchant_available=True),1980056841)
        _,skills=await self.db.get_fighter_catalog()
        self.assertNotIn('secret',skills);self.assertIn('public',skills)
        self.assertFalse(self.db._granted_content_locked(1,10,'skill'))

    async def test_global_reservation_pvp_cancel_and_local_franc_refund(self):
        await self.db.credit_francs(1,10,100);await self.db.credit_francs(1,20,100)
        row=await self.db.arena_offer(1,10,20,'personal',50)
        with self.assertRaises(ValueError):await self.db.arena_offer(2,10,30,'personal')
        with self.assertRaises(ValueError):await self.db.arena_wasteland(2,20)
        await self.db.arena_setup(row['token'],10,'cancel')
        self.assertEqual(await self.db.franc_balance(1,10),100)
        self.assertEqual(await self.db.franc_balance(2,10),0)
        self.assertFalse(self.db._arena_busy_locked(2,10))

    async def test_global_reservation_wasteland_and_no_surrender_xp(self):
        row=await self.db.arena_wasteland(1,10)
        with self.assertRaises(ValueError):await self.db.arena_wasteland(2,10)
        with self.assertRaises(ValueError):await self.db.arena_edit_profile(2,10,10,True,'loadout',['bum_punch'])
        await self.db.arena_action(row['token'],10,row['revision'],'surrender')
        self.assertEqual(self.profile(2)['xp'],0)

    async def test_pvp_pair_reward_limit_is_global_and_survives_restart(self):
        for index,chat in enumerate((1,2,1,2)):
            row=await self.db.arena_offer(chat,10,20,'personal')
            row=await self.db.arena_setup(row['token'],20,'accept')
            state=json.loads(row['state_json'])
            state.update(finished=True,winner='a',finish_reason='knockout',had_player_action=True)
            self.db._arena_finish_locked(row,state)
            self.db.connection.commit()
            self.assertEqual(state['rewards']['a'],10 if index<3 else 1)
            if index==2:
                await self.db.close();await self.db.connect()
        self.assertEqual(self.profile(2)['xp'],31)
        self.assertEqual(self.db.connection.execute('SELECT count FROM arena_pair_rewards WHERE chat_id=0').fetchone()[0],4)

    async def test_global_mirror_and_raid_reservations(self):
        run=await self.db.arena_mirror_start(1,10)
        with self.assertRaises(ValueError):await self.db.arena_raid_create(2,10)
        self.assertEqual((await self.db.arena_mirror_list(2,10))[0]['token'],run['token'])
        await self.toggle('arena',False)
        row=await self.db.arena_raid_create(2,10)
        with self.assertRaises(ValueError):await self.db.arena_wasteland(2,10)
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(row['token'],20,'join',30,False)
        self.assertEqual((await self.db.arena_raid_list(1,10))[0]['token'],row['token'])

    async def test_leave_from_other_chat_cannot_finish_another_players_battle(self):
        row=await self.db.arena_wasteland(1,10)
        with self.assertRaises(ValueError):await self.db.arena_leave_battle(2,20,row['token'])
        await self.db.arena_leave_battle(2,10,row['token'])
        saved=await self.db.arena_get(row['token'])
        self.assertEqual(saved['status'],'finished')
        self.assertEqual(json.loads(saved['state_json'])['finish_reason'],'surrender')
        self.assertFalse(self.db._arena_busy_locked(2,10))
        self.assertEqual(self.profile()['xp'],0)

    async def test_active_duel_disable_refunds_both_and_no_repeated_refunds(self):
        for user in (10,20):await self.db.credit_francs(1,user,100)
        row=await self.db.arena_offer(1,10,20,'personal',50)
        row=await self.db.arena_setup(row['token'],20,'accept')
        self.assertEqual(row['status'],'active')
        with self.assertRaises(ValueError):await self.db.arena_setup(row['token'],20,'accept')
        await self.toggle('arena',False)
        await self.toggle('arena',False)
        for user in (10,20):self.assertEqual(await self.db.franc_balance(1,user),100)

    async def test_leaving_mirror_from_another_chat_frees_account_and_rejects_outsider(self):
        row=await self.db.arena_mirror_start(1,10)
        with self.assertRaises(ValueError):await self.db.arena_leave_mirror(2,20,row['token'])
        await self.db.arena_leave_mirror(2,10,row['token'])
        self.assertFalse(self.db._arena_busy_locked(2,10))
        self.assertEqual(self.profile()['xp'],0)

    async def test_leaving_team_raid_frees_only_withdrawn_account_across_chats(self):
        row=await self.db.arena_raid_create(1,10)
        await self.db.arena_raid_setup(row['token'],20,'join')
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        with self.assertRaises(ValueError):await self.db.arena_leave_raid(2,30,row['token'])
        await self.db.arena_leave_raid(2,10,row['token'])
        self.assertFalse(self.db._arena_busy_locked(2,10))
        self.assertTrue(self.db._arena_busy_locked(2,20))
        self.assertEqual((await self.db.arena_raid_get(row['token']))['status'],'active')
        self.assertEqual(self.profile()['xp'],0)

    async def test_feature_switches_isolated_and_class_groups_removed(self):
        self.assertEqual({m['id'] for m in (await self.db.arena_modules(1))['modules']},{'arena','slavery'})
        await self.toggle('arena',False)
        with self.assertRaises(ValueError):await menu_view(self.db,1,10)
        with self.assertRaises(ValueError):await self.db.arena_raid_create(1,10)
        with self.assertRaises(ValueError):await self.db.arena_set_sprite(1,10,b'x',False)
        self.assertTrue(await self.db.feature_enabled(2,'arena'))
        self.assertTrue(await self.db.feature_enabled(1,'slavery'))
        with self.assertRaises(ValueError):await self.db.arena_set_module(1,10,'classic',True,1)
        self.assertEqual(raid_boss_level([20,20,20]),22)

    async def test_disabling_arena_cancels_and_refunds_without_reset(self):
        self.level(18,'jock')
        await self.db.credit_francs(1,10,100);await self.db.credit_francs(1,20,100)
        row=await self.db.arena_offer(1,10,20,'personal',50)
        await self.toggle('arena',False)
        self.assertEqual((await self.db.arena_get(row['token']))['status'],'cancelled')
        self.assertEqual(await self.db.franc_balance(1,10),100)
        self.assertEqual(self.profile(2)['level'],18)
        await self.toggle('arena',True)
        self.assertEqual(self.profile()['class_id'],'jock')

    async def test_slavery_off_games_friendly_and_ownership_frozen(self):
        await self.db.force_enslave(1,30,10)
        invitation=await self.db.create_challenge(1,20,30,game_type='rps')
        await self.toggle('slavery',False)
        row=await self.db.get_challenge(invitation)
        self.assertTrue(row['friendly']);self.assertFalse(row['forced'])
        for operation in (self.db.transfer_slave(1,10,30,20),self.db.release_slave(1,10,30),self.db.force_enslave(1,20,10),
                          self.db.release_all_slaves(1,10),self.db.set_slave_priority(1,10,30,True)):
            with self.assertRaises(ValueError):await operation
        self.assertEqual((await self.db.get_owner(1,30))['owner_id'],10)
        self.assertTrue(await self.db.feature_enabled(2,'slavery'))
        self.assertEqual(await self.db.transfer_after_loss(1,30,20),('module_disabled',30))

    async def test_old_combat_slots_do_not_block_business_work(self):
        await self.db.force_enslave(1,30,10)
        self.db.connection.execute('INSERT INTO arena_combat_slots VALUES(1,10,30,1)');self.db.connection.commit()
        await self.db.create_business(1,10,'field')
        self.assertEqual(await self.db.set_business_worker_role(1,10,30,'collector'),'updated')
        self.assertIsNone(self.db._arena_combat_slot_locked(1,10,30))

    async def test_disabled_business_does_not_accrue_or_pay_after_resume(self):
        await self.db.force_enslave(1,30,10)
        await self.db.create_business(1,10,'field')
        await self.db.set_business_worker_role(1,10,30,'collector')
        await self.toggle('slavery',False)
        with self.assertRaises(ValueError):await self.db.work_at_business(1,10,20)
        self.db.connection.execute('UPDATE businesses SET last_accrued=? WHERE chat_id=1',(int(time.time())-86400,));self.db.connection.commit()
        await self.db.settle_business(1,10)
        self.assertEqual(await self.db.franc_balance(1,10),0)
        await self.toggle('slavery',True)
        await self.db.settle_business(1,10)
        self.assertEqual(await self.db.franc_balance(1,10),0)

    async def test_forge_shared_wallet_replay_and_alias_double_spend_rejected(self):
        item=self.item(quantity=3)
        self.db.connection.execute('INSERT INTO arena_global_item_aliases VALUES(10001,?,10)',(item,));self.db.connection.execute('INSERT INTO arena_global_item_aliases VALUES(10002,?,10)',(item,));self.db.connection.commit()
        view=await self.db.arena_forge_view(1,10)
        data=dict(operation='dismantle',nonce='a'*32,revision=view['revision'],catalog_revision=view['catalog_revision'],confirm=True,
                  items=[dict(id=10001,quantity=1),dict(id=10002,quantity=1)])
        with self.assertRaisesRegex(ValueError,'повторно'):await self.db.arena_forge_action(1,10,data)
        self.assertEqual(self.db._arena_item_locked(1,10,item)['quantity'],3)
        data['items']=[dict(id=item,quantity=3)]
        await self.db.arena_forge_action(1,10,data)
        self.assertEqual((await self.db.arena_forge_view(2,10))['pages']['common'],6)
        with self.assertRaises(ValueError):await self.db.arena_forge_action(2,10,data)
        self.assertEqual((await self.db.arena_forge_view(1,10))['pages']['common'],6)

    async def test_http_membership_global_read_and_foreign_mutation_denied(self):
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,test_arena.TOKEN)))
        await client.start_server()
        try:
            headers={'X-Telegram-Init-Data':test_arena.signed(10,int(time.time()))}
            response=await client.get('/api/menu/2',headers=headers)
            self.assertEqual(response.status,200)
            self.assertTrue((await response.json())['global_progression'])
            for body in (dict(action='reset_class',user=20,personal=True,value=True),dict(action='equipment',user=30,equipped=True),dict(action='module_class',value='jock')):
                self.assertEqual((await client.post('/api/menu/1',headers=headers,json=body)).status,400)
            await self.toggle('arena',False,2)
            self.assertEqual((await client.get('/api/menu/2',headers=headers)).status,400)
            self.assertEqual((await client.post('/api/menu/2',headers=headers,json=dict(action='wasteland'))).status,400)
        finally:await client.close()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'old.sqlite3')
        with patch.object(Database,'_connect_global_arena',return_value=None):await self.db.connect()
        for chat in (1,2):await self.db.upsert_chat(chat,'Old')
        for chat,level,cls in ((1,10,'jock'),(2,18,'nerd')):
            self.db.connection.execute("INSERT INTO personal_profiles(chat_id,user_id,xp,level,class_id,loadout,updated_at) VALUES(?,10,?,?,?,'[\"bum_punch\"]',?)",(chat,xp_at(level),level,cls,int(time.time())))
            self.db.connection.execute("INSERT INTO arena_inventory(chat_id,owner_id,kind,content_id,rarity,quantity) VALUES(?,10,'skill','dust_in_eyes','common',?)",(chat,chat))
            self.db.connection.execute("INSERT INTO arena_forge_wallets(chat_id,owner_id,pages_json) VALUES(?,10,?)",(chat,json.dumps(dict(common=chat*2))))
            self.db.connection.execute("INSERT INTO arena_pair_rewards VALUES(?,10,20,'2026-10-14',?)",(chat,chat))
        self.db.connection.execute("INSERT INTO arena_learned VALUES(1,10,1,'passive','stone_skin')")
        self.db.connection.execute("INSERT INTO arena_learned VALUES(2,10,1,'passive','light_step')")
        self.db.connection.execute("INSERT INTO arena_sprites VALUES(2,10,'key',?,0)",(b'old-png',))
        self.db._add_francs_locked(1,10,50)
        self.db.connection.execute("INSERT INTO arena_battles(token,chat_id,mode,a_owner,b_owner,status,stake,escrow_a,created_at,deadline) VALUES('old',1,'personal',10,20,'pending',50,50,?,?)",(int(time.time()),int(time.time())+3600))
        self.db.connection.commit()

    async def asyncTearDown(self):await self.db.close();self.tmp.cleanup()

    async def test_merge_max_xp_items_materials_known_passives_and_refund_once(self):
        old_ids=[r[0] for r in self.db.connection.execute('SELECT id FROM arena_inventory')]
        await self.db.close();await self.db.connect()
        profile=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((profile['xp'],profile['level'],profile['class_id']),(xp_at(18),18,'nerd'))
        self.assertEqual(self.db._arena_inventory_locked(2,10)[0]['quantity'],3)
        self.assertEqual(self.db._forge_wallet_locked(1,10)['pages']['common'],6)
        self.assertEqual(self.db._arena_learned_locked(2,10,True,'passive'),{'stone_skin','light_step'})
        self.assertTrue((await self.db.arena_sprite_info(1,10))['sprite_url'])
        self.assertEqual(await self.db.franc_balance(1,10),100)
        self.assertEqual(self.db.connection.execute('SELECT count FROM arena_pair_rewards WHERE chat_id=0').fetchone()[0],3)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM arena_global_legacy_profiles').fetchone()[0],2)
        for item in old_ids:self.assertEqual(self.db._arena_item_locked(2,10,item)['quantity'],3)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM personal_profiles WHERE chat_id<>0').fetchone()[0],2)
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._arena_inventory_locked(1,10)[0]['quantity'],3)
        self.assertEqual(await self.db.franc_balance(1,10),100)

    async def test_failure_rolls_back_payout_and_migration_can_retry(self):
        with patch.object(self.db,'_arena_content_enabled_locked',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.db._connect_global_arena()
        self.assertEqual(await self.db.franc_balance(1,10),50)
        self.assertEqual(self.db.connection.execute("SELECT status FROM arena_battles WHERE token='old'").fetchone()[0],'pending')
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM arena_global_migrations').fetchone())
        self.db._connect_global_arena()
        self.assertEqual(await self.db.franc_balance(1,10),100)

    async def test_highest_slave_profile_becomes_own_account_character(self):
        self.db._ensure_slave_profile_locked(1,10)
        self.db.connection.execute("UPDATE slave_profiles SET xp=?,level=19,class_id='thumb' WHERE chat_id=1 AND user_id=10",(xp_at(19),))
        self.db.connection.commit()
        await self.db.close();await self.db.connect()
        profile=dict(self.db._arena_profile_locked(2,10,True))
        self.assertEqual((profile['class_id'],profile['level'],profile['xp']),('thumb',19,xp_at(19)))

    async def test_existing_global_profile_is_not_overwritten_by_lower_legacy_xp(self):
        self.db._arena_profile_locked(0,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET xp=?,level=19,class_id='jock' WHERE chat_id=0 AND user_id=10",(xp_at(19),))
        self.db.connection.commit()
        await self.db.close();await self.db.connect()
        profile=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((profile['class_id'],profile['level'],profile['xp']),('jock',19,xp_at(19)))

    async def test_removed_class_is_replaced_but_xp_and_original_snapshot_survive(self):
        self.db.connection.execute("UPDATE personal_profiles SET class_id='old_exclusive',loadout='[\"removed_skill\"]' WHERE chat_id=2 AND user_id=10")
        self.db.connection.commit()
        await self.db.close();await self.db.connect()
        profile=dict(self.db._arena_profile_locked(1,10,True))
        self.assertEqual((profile['class_id'],profile['xp']),('ragamuffin',xp_at(18)))
        self.assertNotIn('removed_skill',json.loads(profile['loadout']))
        saved=json.loads(self.db.connection.execute('SELECT profile_json FROM arena_global_legacy_profiles WHERE chat_id=2 AND user_id=10 AND personal=1').fetchone()[0])
        self.assertEqual(saved['class_id'],'old_exclusive')

    async def test_pre_migration_backup_is_consistent_and_not_overwritten_on_restart(self):
        await self.db.close();await self.db.connect()
        copies=list((Path(self.tmp.name)/'backups').glob('before-account-rpg-*.sqlite3'))
        self.assertEqual(len(copies),1)
        with closing(sqlite3.connect(copies[0])) as saved:
            self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(saved.execute("SELECT status FROM arena_battles WHERE token='old'").fetchone()[0],'pending')
            self.assertEqual(saved.execute('SELECT balance FROM franc_balances WHERE chat_id=1 AND user_id=10').fetchone()[0],50)
            self.assertEqual(saved.execute('SELECT count(*) FROM personal_profiles WHERE chat_id<>0').fetchone()[0],2)
        await self.db.close();await self.db.connect()
        self.assertEqual(len(list((Path(self.tmp.name)/'backups').glob('before-account-rpg-*.sqlite3'))),1)

    async def test_backup_error_prevents_migration_and_payout(self):
        with patch('arena_global.sqlite3.connect',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.db._connect_global_arena()
        self.assertEqual(await self.db.franc_balance(1,10),50)
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM arena_global_migrations').fetchone())
