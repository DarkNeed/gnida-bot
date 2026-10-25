import unittest

from tools.audit_franc_deposit import Rules, STRATEGIES, exact_cycle, live_rules, simulate
from tools.audit_franc_deposit import loss_path,stake_for
from tests import test_franc_deposit as engine_tests
from franc_deposit import deposit_cooldown


class DepositAuditTests(unittest.TestCase):
    def test_model_reads_current_production_rule(self):
        rules=live_rules()
        self.assertEqual((rules.wins,rules.outcomes,rules.multiplier),(16,100,5))
        self.assertTrue(rules.tiered_cooldown)

    def test_all_bounded_strategies_had_zero_expected_profit_under_legacy_rules(self):
        for bank in (1000,10000):
            for strategy in STRATEGIES:
                for cap in (None,500):
                    with self.subTest(bank=bank,strategy=strategy,cap=cap):
                        self.assertEqual(exact_cycle(bank,strategy,Rules(20,100,5,cap))['mean_profit'],0)

    def test_cooldown_does_not_change_probability_or_profit(self):
        for strategy in STRATEGIES:
            a=exact_cycle(10000,strategy,Rules(20,100,5))
            b=exact_cycle(10000,strategy,Rules(20,100,5,tiered_cooldown=True))
            for key in ('mean_profit','profit_probability_pct','any_win_probability_pct'):
                self.assertEqual(a[key],b[key])
            self.assertGreaterEqual(b['expected_cooldown_minutes'],a['expected_cooldown_minutes'])

    def test_negative_edge_cannot_be_reversed_by_tested_progressions(self):
        for strategy in STRATEGIES:
            r=exact_cycle(1000,strategy,live_rules())
            self.assertLess(r['mean_profit'],0)
            self.assertAlmostEqual(r['mean_profit'],-.2*r['mean_turnover'])

    def test_frequent_small_profit_is_not_a_guarantee(self):
        r=exact_cycle(1000,'recovery_1',Rules(20,100,5))
        self.assertGreater(r['profit_probability_pct'],99)
        self.assertGreater(r['failure_probability_pct'],0)
        self.assertGreater(r['loss_if_entire_loss_path'],500)
        self.assertEqual(r['mean_profit'],0)
        half=exact_cycle(1000,'half',Rules(20,100,5))
        self.assertGreater(half['any_win_probability_pct'],half['profit_probability_pct'])

    def test_simulation_reproducible_with_rare_failed_cycles_included(self):
        a=simulate(1000,'recovery_1',Rules(20,100,5),10000,20261025)
        self.assertEqual(a,simulate(1000,'recovery_1',Rules(20,100,5),10000,20261025))
        self.assertGreater(a['failed_cycles'],0)


class DepositRecoveryEngineTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=engine_tests.DepositTests.asyncSetUp
    asyncTearDown=engine_tests.DepositTests.asyncTearDown
    bet=engine_tests.DepositTests.bet

    async def test_rare_loss_path_reproduces_in_real_wallet_and_cannot_continue(self):
        path,residual,reason=loss_path(1000,'recovery_1',live_rules())
        self.assertEqual((len(path),residual,reason),(26,113,'insufficient_funds'))
        for mid,stake in enumerate(path,1):
            result=await self.bet(roll=99,stake=stake,mid=mid)
            self.assertFalse(result['won']);self.clock+=deposit_cooldown(stake)
        self.assertEqual(await self.db.franc_balance(-100,10),113)
        self.assertEqual(self.db.connection.execute('SELECT SUM(payout-stake) FROM franc_deposits').fetchone()[0],-887)
        next_stake=stake_for('recovery_1',113,887,len(path),5)
        rng=engine_tests.Fixed(0)
        with self.assertRaises(ValueError):await self.bet(stake=next_stake,mid=100,rng=rng)
        self.assertEqual(rng.calls,0)

    async def test_profitable_cycles_also_reproduce_but_require_an_actual_winning_roll(self):
        path,_,_=loss_path(1000,'recovery_1',live_rules());mid=0
        for streak in (0,4,12,25):
            self.db.connection.execute('UPDATE franc_balances SET balance=1000 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
            losses=0
            for stake in path[:streak]:
                mid+=1;await self.bet(roll=99,stake=stake,mid=mid);losses+=stake;self.clock+=deposit_cooldown(stake)
            mid+=1
            won=await self.bet(roll=0,stake=path[streak],mid=mid)
            self.assertGreater(won['balance_after'],1000)
            self.assertEqual(won['balance_after']-1000,4*path[streak]-losses)
            self.clock+=deposit_cooldown(path[streak])


if __name__=='__main__':unittest.main()
