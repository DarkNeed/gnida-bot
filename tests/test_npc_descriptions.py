"""Descriptions cover every appearance and preserve appraisal boundaries."""
from copy import deepcopy
import unittest
from npc_worker_rules import (PROFESSIONS, RARITIES, TRAIT_DETAILS, WORKPLACES,
                              create, public, efficiency)


class NpcDescriptionTests(unittest.TestCase):
    def row(self,d):
        return dict(id='a'*32,data=d,status='rest',site=None,revision=0,price=100)

    def test_all_professions_genders_and_rarities_have_complete_passports(self):
        for profession in PROFESSIONS:
            for gender in ('male','female'):
                for rarity,quality in RARITIES.items():
                    with self.subTest(profession=profession,gender=gender,rarity=rarity):
                        d=create(profession,gender=gender)
                        d.update(rarity=rarity,appraised=True,profession_level=4,health=64,fatigue=75)
                        before=deepcopy(d);p=public(self.row(d))['passport']
                        self.assertEqual(d,before)
                        for key in ('trait_name','trait_flavor','trait_effect'):self.assertTrue(p[key])
                        self.assertEqual(p['profession_bonus'],6)
                        self.assertEqual(p['preferred_work']['id'],PROFESSIONS[profession]['work'])
                        self.assertEqual(p['rarity_bonus'],dict(income=quality['bonus'],power=quality['bonus']*.25))
                        self.assertEqual({r['id'] for r in p['workplaces']},set(WORKPLACES))
                        for r in p['workplaces']:self.assertEqual(r['multiplier'],round(efficiency(d,r['id']),4))

    def test_unappraised_passports_do_not_disclose_rarity_via_derived_fields(self):
        d=create('miner');before=deepcopy(d)
        hidden=[]
        for rarity in RARITIES:
            d['rarity']=rarity
            shown=public(self.row(d));self.assertNotIn('rarity',shown)
            self.assertIsNone(shown['power']);self.assertIsNone(shown['passport']['rarity_bonus'])
            self.assertTrue(all(r['multiplier'] is None for r in shown['passport']['workplaces']))
            hidden.append(shown['passport'])
        self.assertTrue(all(p==hidden[0] for p in hidden))
        self.assertEqual(d['trait'],before['trait'])

    def test_traits_cover_exactly_the_profession_traits(self):
        self.assertEqual(set(TRAIT_DETAILS),{p['trait'] for p in PROFESSIONS.values()})
        for profession in ('paladin','diplomat'):
            d=create(profession)
            self.assertIn('60',public(self.row(d))['passport']['trait_effect'])


if __name__=='__main__':unittest.main()
