import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from database import Database
from arena_web import create_arena_app
from tests.test_arena import signed, TOKEN


class Rolls:
    def __init__(self, values): self.values=iter(values)
    def random(self): return next(self.values)


class HoldingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'holdings.sqlite3'
        self.db=Database(self.path);await self.db.connect()
        self.clock=int(time.time())
        self.mock=patch('database.utc_timestamp',side_effect=lambda:self.clock);self.mock.start()
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Чат '+str(chat))
            for user in (10,20,100,101,102,103,104,105,106,107,108,109,110,111):
                await self.db.upsert_user(chat,user,'user'+str(user),'Участник '+str(user))
            await self.db.credit_francs(chat,10,10000)
            for user in range(100,112):await self.db.force_enslave(chat,user,10)
        # Baseline economy fixtures: no rarity/work bonuses; identity effects have their own suite.
        self.db.connection.execute("UPDATE slave_identities SET luck=0,trait='survivor',rarity='common' WHERE user_id<>1980056841")
        self.db.connection.commit()
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
        self.client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close();self.mock.stop();await self.db.close();self.temp.cleanup()

    async def site(self,kind='mine',chat=-100):
        await self.db.enterprise_create(chat,10,kind)
        return await self.db.get_business(chat,10,business_type=kind)

    async def view(self,chat=-100):return await self.db.holdings_view(chat,10)

    async def start(self,users=None,mission='outskirts',rolls=None,nonce='a'*32):
        users=users or [100,101]
        q=await self.db.expedition_quote(-100,10,mission,users)
        token=await self.db.expedition_start(-100,10,mission,users,q['revision'],nonce,Rolls(rolls or [.0,.99,.99,.99,.99,.99]))
        return token,q

    async def post(self,body,chat=-100,user=10):
        return await self.client.post('/api/holdings/'+str(chat),json=body,headers={'X-Telegram-Init-Data':signed(user,now=int(time.time()))})

    async def test_batch_transfer_capacity_atomic_and_stale(self):
        a=await self.site();b=await self.site('tavern')
        v=await self.view();await self.db.enterprise_batch(-100,10,[100,101],a['id'],'worker',v['revision'])
        self.clock+=3600
        v=await self.view();await self.db.enterprise_batch(-100,10,[100,101],b['id'],'worker',v['revision'])
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,[102],b['id'],'worker',v['revision'])
        v=await self.view()
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,list(range(100,112)),b['id'],'worker',v['revision'])
        self.assertEqual(len((await self.db.enterprise_view(-100,b['id']))['workers']),2)
        self.assertEqual((await self.db.enterprise_view(-100,a['id']))['workers'],[])
        self.assertEqual(sum(r['gross_income'] for r in await self.db.enterprise_statistics(-100,10,a['id'])),6)

    async def test_batch_auth_leaders_and_unassign(self):
        s=await self.site();v=await self.view()
        for users,who,chat in (([20],10,-100),([100],20,-100),([100],10,-200),([100,100],10,-100)):
            with self.assertRaises(ValueError):await self.db.enterprise_batch(chat,who,users,s['id'],'leader',v['revision'])
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,[100,101],s['id'],'leader',v['revision'])
        await self.db.enterprise_batch(-100,10,[100],s['id'],'leader',v['revision'])
        v=await self.view()
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,[101],s['id'],'leader',v['revision'])
        await self.db.enterprise_batch(-100,10,[100],None,'remove',v['revision'])
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.assertEqual(len((await self.db.enterprise_view(-100,s['id']))['workers']),0)

    async def test_close_settles_no_refund_keeps_ownership_ledger_and_reopens(self):
        s=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',s['id'])
        before=await self.db.franc_balance(-100,10);self.clock+=3600
        v=await self.view();await self.db.enterprise_close(-100,10,s['id'],v['revision'])
        self.assertEqual(await self.db.franc_balance(-100,10),before+3)
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM business_workers WHERE chat_id=-100').fetchone()[0],0)
        self.assertEqual(self.db.connection.execute('SELECT SUM(gross_income) FROM enterprise_income_daily WHERE business_id=?',(s['id'],)).fetchone()[0],3)
        with self.assertRaises(ValueError):await self.db.enterprise_close(-100,10,s['id'],v['revision'])
        self.assertEqual(await self.db.enterprise_create(-100,10,'mine'),'created')
        self.assertEqual(await self.db.franc_balance(-100,10),before+3-750)

    async def test_close_does_not_cancel_expedition_or_restore_deleted_job(self):
        s=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',s['id'])
        await self.start([100]);v=await self.view();await self.db.enterprise_close(-100,10,s['id'],v['revision'])
        self.clock+=1801;await self.db.expedition_sweep()
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM business_workers WHERE worker_id=100').fetchone()[0],0)

    async def test_snapshot_strength_current_character_no_new_profile_on_view(self):
        v=await self.view();weak=next(p for p in v['people'] if p['user_id']==100)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM personal_profiles').fetchone()[0],0)
        await self.db.arena_characters(100)
        self.db.connection.execute("UPDATE personal_profiles SET level=18,class_id='mage',loadout='[\"mana_shot\",\"mana_blob\"]' WHERE user_id=100 AND chat_id=0")
        self.db.connection.commit()
        strong=next(p for p in (await self.view())['people'] if p['user_id']==100)
        self.assertGreater(strong['power'],weak['power'])
        q=await self.db.expedition_quote(-100,10,'outskirts',[100])
        self.db.connection.execute('UPDATE personal_profiles SET level=19 WHERE user_id=100 AND chat_id=0');self.db.connection.commit()
        with self.assertRaises(ValueError):await self.db.expedition_start(-100,10,'outskirts',[100],q['revision'],'a'*32)

    async def test_quoted_risks_hidden_rolls_replay_and_restart_exact_rewards(self):
        token,q=await self.start()
        active=(await self.view())['expeditions'][0]
        self.assertIsNone(active['result']);self.assertNotIn('lost',json.dumps(active))
        repeated=await self.db.expedition_start(-100,10,'outskirts',[100,101],q['revision'],'a'*32)
        self.assertEqual(token,repeated)
        self.clock+=1801;await self.db.close();await self.db.connect()
        before=await self.db.franc_balance(-100,10)
        await asyncio.gather(self.db.expedition_sweep(),self.db.expedition_sweep())
        done=(await self.view())['expeditions'][0]
        self.assertEqual(done['status'],'finished');self.assertTrue(done['result']['won'])
        self.assertEqual(done['result']['francs'],100)
        self.assertEqual(await self.db.franc_balance(-100,10),before+100)
        self.assertEqual((await self.db.arena_forge_view(-100,10))['pages']['common'],1)
        self.assertEqual(await self.db.franc_balance(-100,100),10)
        await self.db.expedition_sweep()
        self.assertEqual(await self.db.franc_balance(-100,10),before+100)

    async def test_failure_releases_only_lost_members_in_origin_chat(self):
        await self.start(rolls=[.999,0,.999])
        self.clock+=1801;await self.db.expedition_sweep()
        self.assertIsNone(await self.db.get_owner(-100,100))
        self.assertIsNotNone(await self.db.get_owner(-100,101))
        self.assertIsNotNone(await self.db.get_owner(-200,100))
        result=(await self.view())['expeditions'][0]['result']
        self.assertFalse(result['won']);self.assertEqual(result['francs'],0);self.assertEqual(result['pages'],0)

    async def test_transfer_release_recapture_never_affect_new_ownership(self):
        await self.start(rolls=[0,0,0])
        await self.db.force_enslave(-100,100,20)
        await self.db.force_enslave(-100,101,20)
        self.clock+=1;await self.db.force_enslave(-100,101,10)
        self.clock+=1801;await self.db.expedition_sweep()
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],20)
        self.assertEqual((await self.db.get_owner(-100,101))['owner_id'],10)
        self.assertEqual((await self.view())['expeditions'][0]['result']['francs'],0)

    async def test_one_owner_and_participant_global_cooldown(self):
        await self.start([100])
        with self.assertRaises(ValueError):await self.db.expedition_quote(-200,10,'outskirts',[101])
        with self.assertRaises(ValueError):await self.db.expedition_quote(-200,20,'outskirts',[100])
        self.clock+=1801;await self.db.expedition_sweep()
        with self.assertRaises(ValueError):await self.db.expedition_quote(-200,10,'outskirts',[100])
        self.clock+=6*3600
        self.assertIn('revision',await self.db.expedition_quote(-200,10,'outskirts',[100]))

    async def test_absence_blocks_work_and_assignment_then_scheduled_wages_resume(self):
        s=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',s['id'])
        await self.start([100],mission='quarter')
        self.assertEqual(await self.db.enterprise_assign(-100,10,100,None,s['id']),'away')
        self.assertEqual((await self.db.work_at_business(-100,10,100,s['id']))[0],'away')
        v=await self.view()
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,[100],None,'remove',v['revision'])
        self.clock+=4*3600;await self.db.expedition_sweep()
        rows=await self.db.enterprise_statistics(-100,10,s['id'])
        self.assertEqual(sum(r['gross_income'] for r in rows),6) # Two work hours AFTER scheduled return, not sweep time.
        self.assertIsNotNone(await self.db.business_worker_role(-100,10,100))

    async def test_modules_cancel_without_losses_or_rewards(self):
        for module in ('arena','slavery'):
            await self.start([100],nonce=module*8)
            view=await self.db.arena_modules(-100)
            await self.db.arena_set_module(-100,10,module,False,view['revision'])
            self.clock+=1801;await self.db.expedition_sweep()
            row=self.db.connection.execute('SELECT status FROM slave_expeditions ORDER BY started_at DESC LIMIT 1').fetchone()
            self.assertEqual(row['status'],'cancelled');self.assertIsNotNone(await self.db.get_owner(-100,100))
            view=await self.db.arena_modules(-100)
            await self.db.arena_set_module(-100,10,module,True,view['revision'])
            self.clock+=6*3600

    async def test_api_auth_membership_scope_and_close_confirmation(self):
        s=await self.site()
        self.assertEqual((await self.client.get('/api/holdings/-100')).status,400)
        self.assertEqual((await self.post({'action':'close','site':s['id'],'confirm':False})).status,400)
        v=await self.view()
        self.assertEqual((await self.post({'action':'close','site':s['id'],'confirm':True,'revision':v['revision']},user=20)).status,400)
        self.assertEqual((await self.post({'action':'close','site':s['id'],'confirm':True,'revision':v['revision']},chat=-200)).status,400)
        self.bot.get_chat_member.return_value.status='left'
        self.assertEqual((await self.post({'action':'close','site':s['id'],'confirm':True,'revision':v['revision']})).status,400)
        self.bot.get_chat_member.return_value.status='member'
        self.assertEqual((await self.post({'action':'close','site':s['id'],'confirm':True,'revision':v['revision']})).status,200)

    async def test_chat_picker_verified_and_holdings_work_without_arena(self):
        view=await self.db.arena_modules(-100)
        await self.db.arena_set_module(-100,10,'arena',False,view['revision'])
        headers={'X-Telegram-Init-Data':signed(now=int(time.time()))}
        response=await self.client.get('/api/holdings/-100',headers=headers)
        self.assertEqual(response.status,200);self.assertFalse((await response.json())['arena_enabled'])
        self.bot.get_chat_member.side_effect=lambda c,u:SimpleNamespace(status='left' if c==-200 else 'member')
        response=await self.client.get('/api/holdings/chats',headers=headers)
        self.assertEqual([c['chat_id'] for c in (await response.json())['chats']],[-100])

    async def test_atomic_finish_rolls_back_reward_and_release_on_error(self):
        await self.start(rolls=[0,0,.99]);self.clock+=1801
        with patch.object(self.db,'_forge_save_wallet_locked',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):await self.db.expedition_sweep()
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.assertEqual(self.db.connection.execute('SELECT status FROM slave_expeditions').fetchone()[0],'active')
        await self.db.expedition_sweep();self.assertIsNone(await self.db.get_owner(-100,100))

    async def test_api_no_rolls_or_arbitrary_powers_in_input(self):
        response=await self.post({'action':'expedition_quote','mission':'outskirts','users':[100],'chance':100,'power':100000})
        self.assertEqual(response.status,200);q=(await response.json())['quote']
        self.assertLess(q['chance'],100);self.assertLess(q['members'][0]['power'],1000)
        response=await self.post({'action':'expedition_start','mission':'outskirts','users':[100],'revision':q['revision'],'nonce':'h'*32,'lost':[]})
        self.assertEqual(response.status,200)
        trip=(await response.json())['holdings']['expeditions'][0]
        self.assertIsNone(trip['result'])


if __name__=='__main__':unittest.main()
