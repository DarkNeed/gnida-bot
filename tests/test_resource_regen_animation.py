"""Only passive regeneration is marked for instant, non-attack UI updates."""
import unittest

import arena_unified_queue as queue
from test_unified_live import direct, raid


class ResourceRegenEventTests(unittest.TestCase):
    def test_direct_gain_is_logged_marked_and_not_repeated(self):
        data=direct();fighter=data['sides']['a'];fighter.update(resource=20,own_turns=1)
        queue._begin(data,'a')
        self.assertEqual(fighter['resource'],28)
        event=data['log'][-1]
        self.assertEqual(event['action_kind'],'resource_regen')
        self.assertEqual(event['resource_regen'],{'a':8})
        self.assertEqual(event['text'],'Энергия: +8.')
        count=len(data['log']);queue._begin(data,'a')
        self.assertEqual(fighter['resource'],28)
        self.assertEqual(len(data['log']),count)

    def test_raid_gain_keeps_resource_snapshot(self):
        data=raid();fighter=data['players']['10']['fighter'];fighter.update(resource=30,own_turns=1)
        queue._begin(data,'10')
        event=data['log'][-1]
        self.assertEqual(event['action_kind'],'resource_regen')
        self.assertEqual(event['after']['10']['resource'],38)
        self.assertEqual(event['resource_regen'],{'10':8})

    def test_poison_with_regen_is_not_silent(self):
        data=direct();fighter=data['sides']['a'];fighter.update(resource=20,own_turns=1)
        fighter['effects'].append(dict(id='plague',kind='plague_fever',value=3,duration=2))
        hp=fighter['hp'];queue._begin(data,'a')
        self.assertEqual(fighter['hp'],hp-3)
        self.assertEqual(fighter['resource'],28)
        self.assertNotEqual(data['log'][-1].get('action_kind'),'resource_regen')
        self.assertIn('Чума:',data['log'][-1]['text'])
