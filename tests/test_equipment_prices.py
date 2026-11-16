from copy import deepcopy
from itertools import combinations
import unittest
from arena_equipment import CATALOG,AFFIXES,RANKS,RARITIES,PRICES,SELL_PERCENT,item_price,item_stats,public_item,item_valuation


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

    def test_every_combination_bounded_and_resale_is_exactly_5_percent(self):
        self.assertEqual(SELL_PERCENT,5)
        for key,definition in CATALOG.items():
            choices=[s for s in AFFIXES if s!=definition['main']]
            for rank in RANKS:
                for rarity in RARITIES:
                    for affixes in combinations(choices,min(2,RARITIES.index(rarity))):
                        i=item(key=key,rank=rank,rarity=rarity,affixes=list(affixes))
                        price=item_price(i)
                        self.assertTrue(0<price<=20000)
                        self.assertEqual(price%10 if price<1000 else price%50,0)
                        public=public_item(i)
                        self.assertEqual(public['sell_price'],price//20)
                        self.assertEqual(public['sell_percent'],5)
                        self.assertTrue(0<public['sell_price']<=1000)
                        self.assertLessEqual(public['sell_price'],(price//5)/4)
                        self.assertLess(public['sell_price'],price)

    def test_resale_ignores_upgrade_and_untrusted_price_fields(self):
        base=item();quote=public_item(base)
        forged=dict(base,upgrade=5,sell_price=999999,sell_percent=100,base_price=999999)
        result=public_item(forged)
        self.assertEqual(result['sell_price'],quote['sell_price'])
        self.assertEqual(result['sell_percent'],5)
        self.assertEqual(result['base_price'],quote['base_price'])

    def test_maximum_payout_is_1000_even_for_nazarick_legendary(self):
        payout=max(public_item(item(key=k,rarity='legendary'))['sell_price'] for k in CATALOG)
        self.assertEqual(payout,1000)

    def test_different_equivalent_base_keys_not_randomly_marked_up(self):
        a=item(key='helmet',rarity='rare');b=dict(a,key='warden')
        self.assertEqual(item_price(a),item_price(b))
        self.assertEqual(item_valuation(a),item_valuation(b))


if __name__=='__main__':unittest.main()
