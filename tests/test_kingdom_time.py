"""Real server clock, deterministic transient POIs and one-time bounded rewards."""
from datetime import datetime
from copy import deepcopy
import unittest
from uuid import uuid4
import test_kingdom as towns
from arena_kingdom_time import MSK,environment,encounters


class TimeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=towns.KingdomTests.asyncSetUp
    asyncTearDown=towns.KingdomTests.asyncTearDown
    view=towns.KingdomTests.view
    action=towns.KingdomTests.action
    found=towns.KingdomTests.found
    town=towns.KingdomTests.town

    def clock_at(self,hour,minute=0,day=1):
        self.now=int(datetime(2026,11,day,hour,minute,tzinfo=MSK).timestamp())

    def test_boundaries_and_night_window_survives_midnight(self):
        for hour,minute,period,phase in [(5,59,'night','night'),(6,0,'day','dawn'),(8,0,'day','day'),(18,0,'day','dusk'),(19,59,'day','dusk'),(20,0,'night','night')]:
            self.clock_at(hour,minute);env=environment(self.now)
            self.assertEqual((env['period'],env['phase']),(period,phase));self.assertGreater(env['ends'],self.now)
        self.clock_at(23);evening=environment(self.now);self.clock_at(2,day=2);night=environment(self.now)
        self.assertEqual(evening['window'],night['window']);self.assertEqual(night['clock'],'02:00')

    async def test_reliable_same_window_coordinates_and_no_occupied_sites(self):
        self.clock_at(12);await self.found();a=await self.view();b=await self.view(actor=20)
        self.assertEqual(a['map_events'],b['map_events']);self.assertEqual(len(a['map_events']),2)
        for event in a['map_events']:
            tile=next(t for t in a['tiles'] if t['q']==event['q'] and t['r']==event['r'])
            self.assertFalse(tile['town']);self.assertFalse(tile['site']);self.assertNotEqual(tile['terrain'],'river')
        self.now+=3600;self.assertEqual(a['map_events'],(await self.view())['map_events'])
        self.clock_at(23);night=await self.view();self.assertEqual({e['period'] for e in night['map_events']},{'night'})
        self.assertTrue(set(e['id'] for e in night['map_events']).isdisjoint(e['id'] for e in a['map_events']))

    async def test_reward_once_per_appearance_nonce_restart_no_francs_or_arena(self):
        self.clock_at(12);await self.found();view=await self.view();event=view['map_events'][0];row=self.town()
        money=await self.db.franc_balance(-100,10);profile=dict(self.db._arena_profile_locked(-100,10,True))
        resources=deepcopy(row['data']['resources']);body=dict(action='explore',event=event['id'],town=row['id'],revision=row['revision'],confirm=True,nonce=uuid4().hex)
        await self.db.kingdom_action(-100,10,body);await self.db.kingdom_action(-100,10,body)
        for key,amount in event['grant'].items():self.assertEqual(self.town()['data']['resources'][key],resources[key]+amount)
        with self.assertRaisesRegex(ValueError,'уже'):await self.action('explore',event=event['id'])
        await self.db.close();await self.db.connect();view=await self.view()
        self.assertTrue(next(e for e in view['map_events'] if e['id']==event['id'])['claimed'])
        self.assertEqual(await self.db.franc_balance(-100,10),money);self.assertEqual(dict(self.db._arena_profile_locked(-100,10,True)),profile)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_inventory').fetchone()[0],0)

    async def test_stale_event_rejected_at_night_and_client_reward_ignored(self):
        self.clock_at(12);await self.found();day=(await self.view())['map_events'][0];self.clock_at(23)
        before=deepcopy(self.town()['data']['resources'])
        with self.assertRaises(ValueError):await self.action('explore',event=day['id'],reward=99999)
        view=await self.view();event=view['map_events'][0];before=deepcopy(self.town()['data']['resources'])
        await self.action('explore',event=event['id'],reward=99999,grant=dict(food=99999),phase='day')
        for key in before:self.assertLessEqual(self.town()['data']['resources'][key]-before[key],event['grant'].get(key,0))
        with self.assertRaises(ValueError):await self.action('explore',actor=20,event=event['id'])

    async def test_night_does_not_reset_on_midnight_next_night_can_be_visited(self):
        self.clock_at(23);await self.found();event=(await self.view())['map_events'][0];await self.action('explore',event=event['id'])
        self.clock_at(2,day=2);await self.view()
        with self.assertRaises(ValueError):await self.action('explore',event=event['id'])
        self.clock_at(23,day=2);new=(await self.view())['map_events'][0]
        self.assertNotEqual(new['id'],event['id']);await self.action('explore',event=new['id'])


if __name__=='__main__':unittest.main()
