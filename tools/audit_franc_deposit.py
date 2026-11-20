"""Offline fictional-franc audit: exact finite-bank cycles and seeded simulations.

No real wallets, DBs or production rules are changed. A cycle stops at its first
winning roll, insufficient funds, stake cap or attempt cap. A winning roll is NOT
necessarily a profitable cycle. The Monte Carlo RNG is reproducible test data,
not the production SystemRandom generator and not a prediction of future bets.
"""
import argparse
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction
import json
from math import sqrt
from pathlib import Path
import random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from franc_deposit import DEPOSIT_COOLDOWN, DEPOSIT_COOLDOWN_TIERS, deposit_cooldown, deposit_multiplier


@dataclass(frozen=True)
class Rules:
    wins: int
    outcomes: int
    multiplier: int
    stake_cap: int | None = None
    attempts: int = 200
    tiered_cooldown: bool = False
    additional_payouts: tuple[tuple[int, int], ...] = ()

    def winning_payouts(self):
        """Pairs of outcome count and multiplier, largest tier first."""
        top = self.wins - sum(count for count, _ in self.additional_payouts)
        return ((top, self.multiplier), *self.additional_payouts)

    def return_per_stake(self):
        return Fraction(sum(count*mult for count,mult in self.winning_payouts()),self.outcomes)


def live_rules():
    """Enumerate the production payout tiers, without touching a wallet."""
    outcomes=100
    counts=Counter(deposit_multiplier(roll) for roll in range(outcomes))
    wins=outcomes-counts.pop(0,0)
    tiers=tuple((counts[mult],mult) for mult in sorted(counts,reverse=True))
    return Rules(wins,outcomes,tiers[0][1],tiered_cooldown=True,additional_payouts=tiers[1:])


STRATEGIES=('flat_100','half','all','doubling_1','recovery_1','recovery_100')


def stake_for(strategy,bank,losses,loss_streak,multiplier):
    if strategy=='flat_100':return 100
    if strategy=='half':return bank//2
    if strategy=='all':return bank
    if strategy=='doubling_1':return 1<<loss_streak
    target=1 if strategy=='recovery_1' else 100
    # Smallest integer bet that covers previous cycle losses + desired profit
    # if the NEXT roll wins. This does not make that next win guaranteed.
    return max(1,(losses+target+multiplier-2)//(multiplier-1))


def cooldown(stake,tiered):
    if not tiered:return DEPOSIT_COOLDOWN
    return deposit_cooldown(stake)


def loss_path(start,strategy,rules):
    bank=start;losses=0;path=[];reason='attempt_limit'
    for streak in range(rules.attempts):
        stake=stake_for(strategy,bank,losses,streak,rules.multiplier)
        if stake<1:reason='zero_stake';break
        if rules.stake_cap is not None and stake>rules.stake_cap:reason='stake_cap';break
        if stake>bank:reason='insufficient_funds';break
        path.append(stake);bank-=stake;losses+=stake
    return path,bank,reason


def exact_cycle(start,strategy,rules):
    p=Fraction(rules.wins,rules.outcomes);q=1-p;reach=Fraction(1)
    tiers=[(Fraction(count,rules.outcomes),mult) for count,mult in rules.winning_payouts()]
    gain=turnover=blocked_seconds=profit_probability=win_probability=Fraction(0)
    path,residual,reason=loss_path(start,strategy,rules)
    losses=0
    for stake in path:
        for chance,mult in tiers:
            net=stake*(mult-1)-losses
            probability=reach*chance
            gain+=probability*net
            if net>0:profit_probability+=probability
        win_probability+=reach*p
        turnover+=reach*stake
        blocked_seconds+=reach*cooldown(stake,rules.tiered_cooldown)
        losses+=stake;reach*=q
    gain+=reach*(residual-start)
    assert gain==(rules.return_per_stake()-1)*turnover
    return dict(bank=start,strategy=strategy,profit_probability_pct=float(100*profit_probability),
                any_win_probability_pct=float(100*win_probability),failure_probability_pct=float(100*reach),
                loss_if_entire_loss_path=start-residual,residual_bank=residual,loss_path_length=len(path),
                stop_reason=reason,mean_profit=float(gain),mean_turnover=float(turnover),
                expected_cooldown_minutes=float(blocked_seconds/60))


def simulate(start,strategy,rules,trials,seed):
    rng=random.Random(seed);positive=failed=wins=0;total=total2=bets=0
    payouts=[mult for count,mult in rules.winning_payouts() for _ in range(count)] + [0]*(rules.outcomes-rules.wins)
    for _ in range(trials):
        bank=start;losses=0;won=False
        for streak in range(rules.attempts):
            stake=stake_for(strategy,bank,losses,streak,rules.multiplier)
            if stake<1 or stake>bank or rules.stake_cap is not None and stake>rules.stake_cap:break
            bank-=stake;bets+=1
            multiplier=payouts[rng.randrange(rules.outcomes)]
            if multiplier:
                bank+=stake*multiplier;won=True;break
            losses+=stake
        gain=bank-start;positive+=gain>0;wins+=won;failed+=not won
        total+=gain;total2+=gain*gain
    mean=total/trials
    variance=max(0,(total2-trials*mean*mean)/max(1,trials-1))
    return dict(trials=trials,seed=seed,profit_probability_pct=positive/trials*100,
                any_win_probability_pct=wins/trials*100,failed_cycles=failed,mean_profit=mean,
                mean_profit_95pct_interval=[mean-1.96*sqrt(variance/trials),mean+1.96*sqrt(variance/trials)],
                bets=bets)


def run(trials=100000,seed=20261025):
    live=live_rules()
    configurations={
        'current':live,
        'previous_20pct':Rules(20,100,5),
        'previous_20pct_with_cooldowns':Rules(20,100,5,tiered_cooldown=True),
        'current_with_constant_cooldown':replace(live,tiered_cooldown=False),
    }
    cases=[]
    for bank in (1000,10000):
        for name,rules in configurations.items():
            for strategy in STRATEGIES:
                exact=exact_cycle(bank,strategy,rules)
                # Cooldown affects time, not outcomes; avoid duplicating identical simulations.
                simulation=simulate(bank,strategy,rules,trials,seed) if name in ('current','previous_20pct') else None
                cases.append(dict(configuration=name,exact=exact,simulation=simulation))
    return dict(live_rules=dict(wins=live.wins,outcomes=live.outcomes,multiplier=live.multiplier,
                               winning_payouts=live.winning_payouts(),return_per_stake=float(live.return_per_stake()),
                               minimum_cooldown=DEPOSIT_COOLDOWN,cooldown_tiers=DEPOSIT_COOLDOWN_TIERS,
                               tiered_cooldown=live.tiered_cooldown),
                assumptions=['Independent rolls; no enterprise income, gifts or other external credits.',
                             'Cycle ends on first winning roll, insufficient funds or a published cap.',
                             'Recovery bets are sized for the largest payout; a smaller win may still end the cycle in loss.',
                             '200 attempts is the model horizon, not a production daily limit; no gameplay stake cap is enabled.',
                             'No real player exploit sequence was supplied; recovery is a tested hypothesis.'],
                cases=cases,total_simulated_cycles=2*2*len(STRATEGIES)*trials)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials',type=int,default=100000)
    parser.add_argument('--seed',type=int,default=20261025)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.trials<1:parser.error('--trials must be positive')
    report=run(args.trials,args.seed)
    content=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(content+'\n',encoding='utf-8')
        print(f'{report["total_simulated_cycles"]:,} simulated cycles; report: {args.output}')
    else:print(content)
