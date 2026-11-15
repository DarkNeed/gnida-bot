from copy import deepcopy
from itertools import combinations
import unittest
from arena_equipment import CATALOG,AFFIXES,RANKS,RARITIES,PRICES,item_price,item_stats,public_item,item_valuation


def item(**kw):
    return dict(dict(key='fang',rank='S',rarity='epic',upgrade=0,affixes=['speed','evasion']),**kw)


class EquipmentPriceTests(unittest.TestCase):
    def test_affixes_and_synergy_change_price_not_name_or_owner(self):
        strong=item();mixed=item(affixes=['magic_attack','magic_defense'])
        self.assertGreater(item_price(strong),item_price(mixed))
        self.assertEqual(item_price(strong),item_price(dict(strong,id='another',actor=999,class_id='mage')))
        self.assertEqual(item_price(strong),item_price(dict(strong,key='fang',name='Другое название')))

    def test_upgrade_does_not_inflate_price_and_no_input_is_changed(self):
        i=item();before=deepcopy(i)
        self.assertEqual(item_price(i),item_price(dict(i,upgrade=5)))
        self.assertGreater(item_stats(dict(i,upgrade=5))['physical_attack'],item_stats(i)['physical_attack'])
        self.assertEqual(i,before)

    def test_every_combination_bounded_and_resale_is_exactly_20_percent(self):
        for key,definition in CATALOG.items():
            choices=[s for s in AFFIXES if s!=definition['main']]
            for rank in RANKS:
                for rarity in RARITIES:
                    for affixes in combinations(choices,min(2,RARITIES.index(rarity))):
                        i=item(key=key,rank=rank,rarity=rarity,affixes=list(affixes))
                        price=item_price(i)
                        self.assertTrue(0<price<=20000)
                        self.assertEqual(price%10 if price<1000 else price%50,0)
                        self.assertEqual(public_item(i)['sell_price'],price//5)

    def test_different_equivalent_base_keys_not_randomly_marked_up(self):
        a=item(key='helmet',rarity='rare');b=dict(a,key='warden')
        self.assertEqual(item_price(a),item_price(b))
        self.assertEqual(item_valuation(a),item_valuation(b))


if __name__=='__main__':unittest.main()
