import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

import test_challenge_recovery as challenge_helpers
import test_arena_progression as profile_helpers
import test_arena_market_client as client_helpers
from arena_engine import BUILTIN_SKILLS, xp_for_next_level
from arena_evolution import evolution_info
from arena_rpg import RPG_BRANCHES, rpg_variant
from arena_rpg_descriptions import BRANCH_SKILLS
from arena_web import menu_view


class TimeoutConsequenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=challenge_helpers.ChallengeRecoveryTests.asyncSetUp
    asyncTearDown=challenge_helpers.ChallengeRecoveryTests.asyncTearDown

    async def challenge(self,game='rps',stake=0,friendly=False):
        cid=await self.db.create_challenge(-100,1,2,game_type=game,awaiting_acceptance=True,
            opponent_newcomer=True,friendly=friendly,player_stake=stake)
        await self.db.accept_challenge(cid,2)
        return cid

    async def expire(self,cid):
        row=await self.db.get_challenge(cid)
        with patch('database.utc_timestamp',return_value=row['deadline']):
            return await self.db.claim_expired_challenge(cid)

    async def test_rps_newcomer_cannot_accept_and_hide_after_opponent_choice(self):
        cid=await self.challenge();await self.db.choose(cid,1,'rock')
        result=await self.expire(cid)
        self.assertEqual((result['winner_id'],result['slavery_outcome']),(1,'enslaved'))
        self.assertEqual((await self.db.get_owner(-100,2))['owner_id'],1)
        await self.db.close();await self.db.connect()
        await self.db.finish_challenge_deadline(cid)
        self.assertEqual((await self.db.get_challenge(cid))['status'],'finished')
        self.assertEqual(await self.db.transfer_after_loss(-100,2,1,challenge_id=cid),('enslaved',2))
        self.assertEqual(len(await self.db.list_business_slaves(-100,1)),1)

    async def test_blackjack_and_checkers_turn_owner_loses(self):
        for game in ('blackjack','checkers'):
            cid=await self.challenge(game)
            self.db.connection.execute(f'UPDATE {game}_games SET turn_user_id=2 WHERE challenge_id=?',(cid,));self.db.connection.commit()
            result=await self.expire(cid)
            self.assertEqual(result['winner_id'],1)
            self.assertEqual((await self.db.get_owner(-100,2))['owner_id'],1)
            await self.db.finish_challenge_deadline(cid)
            await self.db.release_slave(-100,1,2)

    async def test_stake_goes_to_winner_but_friendly_never_changes_ownership(self):
        cid=await self.challenge(stake=80,friendly=True);await self.db.choose(cid,1,'rock')
        self.assertEqual((await self.expire(cid))['winner_id'],1)
        self.assertEqual((await self.db.franc_balance(-100,1),await self.db.franc_balance(-100,2)),(1080,920))
        self.assertIsNone(await self.db.get_owner(-100,2))

    async def test_both_rps_players_absent_have_no_arbitrary_winner(self):
        cid=await self.challenge(stake=80,friendly=True)
        self.assertIsNone((await self.expire(cid))['winner_id'])
        self.assertEqual((await self.db.franc_balance(-100,1),await self.db.franc_balance(-100,2)),(1000,1000))

    async def test_timeout_result_and_consequences_roll_back_together(self):
        cid=await self.challenge();await self.db.choose(cid,1,'rock')
        with patch.object(self.db,'_transfer_after_loss_locked',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):await self.expire(cid)
        self.assertEqual((await self.db.get_challenge(cid))['status'],'active')
        self.assertIsNone(await self.db.get_owner(-100,2))
        await self.expire(cid)
        self.assertEqual((await self.db.get_owner(-100,2))['owner_id'],1)


class SkillOfferTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=profile_helpers.ProgressionTests.asyncSetUp
    asyncTearDown=profile_helpers.ProgressionTests.asyncTearDown

    async def prepare(self,full=False):
        await self.db.arena_characters(10)
        known=['bum_punch','mana_shot','mana_blob','mana_focus']
        if full:known+=['mana_barrier','mana_overload']
        xp=sum(xp_for_next_level(n) for n in range(1,14))
        self.db.connection.execute("""UPDATE personal_profiles SET class_id='mage',archclass_id='mage_necromancer',
            level=14,xp=?,progression_level=10,skill_memory=?,skill_seen=?,skill_offers='[]',loadout=? WHERE chat_id=0 AND user_id=10""",
            (xp,json.dumps(known),json.dumps(known+['mana_barrier','mana_overload']),json.dumps(known[:4])))
        self.db.connection.commit()
        await menu_view(self.db,1,10)
        self.db.connection.execute("UPDATE personal_profiles SET skill_offers='[]' WHERE chat_id=0 AND user_id=10")
        self.db._grant_profile_xp_locked('personal_profiles',0,10,xp_for_next_level(14))
        self.db.connection.commit()
        return (await menu_view(self.db,1,10))['personal']

    async def resolve(self,p,decision='learn',replace=None,equip=None,actor=10,slot=1):
        return await self.db.arena_edit_profile(1,actor,10,True,'skill_offer',dict(skill=p['skill_offers'][0]['skill_id'],
            decision=decision,known=p['known_skills'],selected=p['loadout'],replace_memory=replace,equip_replace=equip),expected_slot=slot)

    async def test_new_branch_skill_prompts_and_replaces_battle_slot_without_forgetting(self):
        p=await self.prepare()
        self.assertEqual([s['skill_id'] for s in p['skill_offers']],['arch_mage_necromancer'])
        self.assertEqual(p['loadout'],['bum_punch','mana_shot','mana_blob','mana_focus'])
        await self.resolve(p,equip='mana_shot')
        p=(await menu_view(self.db,2,10))['personal']
        self.assertEqual(p['skill_offers'],[])
        self.assertIn('arch_mage_necromancer',p['loadout'])
        self.assertIn('mana_shot',p['known_skills'])
        self.assertNotIn('mana_shot',p['loadout'])

    async def test_full_memory_requires_explicit_replacement_and_never_forgets_bum_punch(self):
        p=await self.prepare(True)
        with self.assertRaises(ValueError):await self.resolve(p)
        with self.assertRaises(ValueError):await self.resolve(p,replace='bum_punch')
        await self.resolve(p,replace='mana_blob',equip='mana_blob')
        p=(await menu_view(self.db,1,10))['personal']
        self.assertEqual(len(p['known_skills']),6)
        self.assertNotIn('mana_blob',p['known_skills'])
        self.assertIn('arch_mage_necromancer',p['loadout'])

    async def test_skip_remains_available_but_does_not_prompt_again_after_restart(self):
        p=await self.prepare();await self.resolve(p,decision='skip')
        await self.db.close();await self.db.connect()
        p=(await menu_view(self.db,1,10))['personal']
        self.assertEqual(p['skill_offers'],[])
        self.assertNotIn('arch_mage_necromancer',p['known_skills'])
        self.assertIn('arch_mage_necromancer',[s['skill_id'] for s in p['available_skills']])

    async def test_stale_choice_wrong_actor_and_wrong_character_do_not_mutate(self):
        p=await self.prepare()
        with self.assertRaises(ValueError):await self.resolve(p,actor=20)
        with self.assertRaises(ValueError):await self.resolve(p,slot=2)
        await self.resolve(p,equip='mana_focus')
        with self.assertRaises(ValueError):await self.resolve(p,equip='mana_focus')

    async def test_owner_gets_five_slots_without_payment_and_others_do_not(self):
        view=await self.db.arena_characters(1980056841)
        self.assertEqual(view['capacity'],5)
        self.assertFalse(any(s['locked'] for s in view['slots']))
        await self.db.arena_select_character(1,1980056841,5,view['revision'])
        await self.db.close();await self.db.connect()
        self.assertEqual((await self.db.arena_characters(1980056841))['active_slot'],5)
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM pet_orders WHERE user_id=1980056841').fetchone()[0],0)


class RPGDescriptionTests(unittest.TestCase):
    def test_necromancer_has_distinct_specific_descriptions_and_focus_is_not_a_summon(self):
        source=dict(class_id='mage',archclass_id='mage_necromancer',level=15,archclass_stage=10,effects=[],rpg_state={})
        descriptions=[]
        for sid in ('mana_shot','mana_blob','mana_barrier'):
            info=evolution_info(BUILTIN_SKILLS[sid],'mage',source)
            descriptions.append(info['description'])
            self.assertNotEqual(info['name'],'Некромант')
        self.assertEqual(len(set(descriptions)),3)
        self.assertIsNone(evolution_info(BUILTIN_SKILLS['mana_focus'],'mage',source))
        self.assertNotIn('Автоматический призыв',descriptions[0])

    def test_all_branch_skill_descriptions_are_specific_not_full_branch_overview(self):
        for key,entries in BRANCH_SKILLS.items():
            cls=RPG_BRANCHES[key][0]
            source=dict(class_id=cls,archclass_id=key,level=18,archclass_stage=10,effects=[],rpg_state={})
            for sid in entries:
                info=evolution_info(BUILTIN_SKILLS[sid],cls,source)
                self.assertTrue(info['description'],(key,sid))
                self.assertNotIn('условия финальной атаки указаны',info['condition'])


class SkillChoiceClientTests(unittest.TestCase):
    run_client=client_helpers.ArenaMarketClientTests.run_client

    def test_comparison_ui_has_new_card_four_moves_and_explicit_decline(self):
        data=client_helpers.ArenaMarketClientTests().menu_data()
        data['personal'].update(skills=[asdict(BUILTIN_SKILLS[k]) for k in ('bum_punch','mana_shot','mana_blob','mana_focus')],
            loadout=['bum_punch','mana_shot','mana_blob','mana_focus'],skill_offers=[asdict(BUILTIN_SKILLS['arch_mage_necromancer'])])
        body=self.run_client("page='personal';menuScreen(input);",data)
        self.assertIn('Жатва душ',body)
        self.assertEqual(body.count('class="move-old"'),4)
        self.assertIn('Не брать — оставить прежние',body)
        self.assertIn('Изучить в резерв',body)
