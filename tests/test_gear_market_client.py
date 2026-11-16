import unittest
from arena_equipment import public_item
import test_arena_market_client as client_tests


class GearMerchantClientTests(unittest.TestCase):
    run_client=client_tests.ArenaMarketClientTests.run_client
    menu_data=client_tests.ArenaMarketClientTests.menu_data

    def data(self):
        d=self.menu_data();i=public_item(dict(id='gear1',key='fang',rank='C',rarity='epic',upgrade=0,affixes=['speed','max_hp']))
        i.update(price=i['base_price'],used_by=[],favorite=False,purchase_warning='',comparison=dict(physical_attack=10))
        d['merchant']['gear']=dict(offers=[i],items=[i],stats=dict(physical_attack=5),stat_names=dict(physical_attack='Физ. атака'),
            character_slot=1,hunter_rank='C',busy=False,revision=0,sell_percent=5)
        return d

    def test_tabs_and_gear_filters(self):
        html=self.run_client("page='merchant';merchantTab='gear';menuScreen(input);",self.data())
        for key in ('supplies','study','sell'):self.assertIn('merchanttab:'+key,html)
        self.assertNotIn('merchanttab:gear',html)
        self.assertIn('guildgear',html)
        self.assertIn('Снаряжение — в гильдии',html)
        self.assertNotIn('buy:7',html)

    def test_sale_detail_replaces_list_and_requires_confirmation(self):
        d=self.data();d['balance']=100000
        html=self.run_client("page='merchant';merchantTab='sell';merchantSelected='gear1';menuScreen(input);",d)
        self.assertIn(str(d['merchant']['gear']['items'][0]['sell_price'])+' ₣',html);self.assertNotIn('merchant-gear-grid',html)
        self.assertIn('merchantask:gear1',html)
        html=self.run_client("page='merchant';merchantTab='sell';merchantSelected='gear1';merchantPending={item:'gear1'};menuScreen(input);",d)
        self.assertIn('merchantconfirm',html);self.assertIn('Предмет исчезнет',html)

    def test_sale_shows_5_percent_and_protects_equipped(self):
        d=self.data();d['merchant']['gear']['items'][0]['used_by']=[1]
        html=self.run_client("page='merchant';merchantTab='sell';merchantSelected='gear1';menuScreen(input);",d)
        self.assertIn(str(d['merchant']['gear']['items'][0]['sell_price'])+' ₣',html);self.assertIn('merchantask:gear1" disabled',html)
        self.assertIn('сними вещь',html)
        self.assertIn('Снаряжение — 5% оценочной стоимости +0',html)
        self.assertNotIn('Снаряжение — 20%',html)

    def test_list_and_header_use_server_sale_percent_and_regular_items_unchanged(self):
        d=self.data()
        html=self.run_client("page='merchant';merchantTab='sell';menuScreen(input);",d)
        self.assertIn('Скупка — 5% оценочной стоимости +0',html)
        self.assertIn('50% базовой цены',html)
        d['merchant']['gear']['sell_percent']=3
        html=self.run_client("page='merchant';merchantTab='sell';menuScreen(input);",d)
        self.assertIn('Скупка — 3% оценочной стоимости +0',html)


if __name__=='__main__':unittest.main()
