import unittest
from dataclasses import asdict

from arena_engine import (
    BUILTIN_PASSIVES,
    BUILTIN_SKILLS,
    create_battle_state,
    resolve_skill,
    skip_turn,
)
from arena_raid_engine import create_raid_state, resolve_round
from arena_engine import FIGHTER_CLASSES
from arena_web import menu_view
from test_arena_fingers import AlwaysHit
import test_arena_market as market_tests


class BleedingTests(unittest.TestCase):
    def state(self):
        a = dict(slave_id=10, owner_id=10, class_id="ring", level=18)
        b = dict(slave_id=20, owner_id=20, class_id="ragamuffin", level=18)
        state = create_battle_state(a, b)
        state["sides"]["a"]["loadout"] = ["first_stroke", "red_etude"]
        return state

    def test_chance_is_75_percent_of_hits(self):
        class Roll(AlwaysHit):
            def __init__(self, chance):
                self.rolls = iter((0, chance))

            def random(self):
                return next(self.rolls, 0)

        for chance in (0, 0.74, 0.75, 0.99):
            state = self.state()
            event = resolve_skill(state, "a", "first_stroke", rng=Roll(chance))
            self.assertTrue(event["hit"])
            self.assertEqual(bool(state["sides"]["b"]["effects"]), chance < 0.75)
            self.assertEqual(event["bleed_damage"], 0)

    def test_bleed_only_on_affected_fighters_attack_even_if_missed(self):
        for hit in (True, False):
            state = self.state()
            target = state["sides"]["b"]
            hp = target["hp"]
            first = resolve_skill(state, "a", "red_etude", rng=AlwaysHit())
            self.assertEqual(target["hp"], hp - first["damage"])
            hp = target["hp"]

            class Roll(AlwaysHit):
                def random(self):
                    return 0 if hit else 0.99

            second = resolve_skill(state, "b", "bum_punch", rng=Roll())
            self.assertEqual(second["hit"], hit)
            self.assertEqual(second["bleed_damage"], 3)
            self.assertEqual(target["hp"], hp - 3)

    def test_utility_timeout_and_stun_do_not_trigger_bleed(self):
        for action in ("utility", "timeout", "stun"):
            state = self.state()
            target = state["sides"]["b"]
            target["effects"] = [dict(id="bleed", kind="bleed", value=3, duration=3)]
            hp = target["hp"]
            if action == "stun":
                target["effects"].append(
                    dict(id="stun", kind="stun", value=1, duration=1)
                )
                state["sides"]["a"]["loadout"] = ["go_to_store"]
                resolve_skill(state, "a", "go_to_store", rng=AlwaysHit())
            else:
                state["active_side"] = "b"
                if action == "timeout":
                    skip_turn(state)
                else:
                    target["loadout"] = ["go_to_store"]
                    resolve_skill(state, "b", "go_to_store", rng=AlwaysHit())
            self.assertEqual(target["hp"], hp)

    def test_lethal_bleed_finishes_after_attack_and_last_duration_ticks(self):
        state = self.state()
        actor = state["sides"]["a"]
        actor["hp"] = 2
        actor["effects"] = [dict(id="bleed", kind="bleed", value=5, duration=1)]
        event = resolve_skill(state, "a", "first_stroke", rng=AlwaysHit())
        self.assertGreater(event["damage"], 0)
        self.assertEqual(event["bleed_damage"], 2)
        self.assertEqual(actor["hp"], 0)
        self.assertTrue(state["finished"])
        self.assertEqual(state["winner"], "b")

    def test_grit_teeth_two_turn_cooldown(self):
        self.assertEqual(BUILTIN_SKILLS["grit_teeth"].cooldown, 2)

    def test_bleed_ticks_for_three_affected_attacks_then_expires(self):
        state = self.state()
        resolve_skill(state, "a", "red_etude", rng=AlwaysHit())
        state["sides"]["a"]["loadout"] = ["go_to_store"]
        for turn in range(4):
            event = resolve_skill(state, "b", "bum_punch", rng=AlwaysHit())
            self.assertEqual(event["bleed_damage"], 3 if turn < 3 else 0)
            resolve_skill(state, "a", "go_to_store", rng=AlwaysHit())

    def test_raid_guards_and_boss_shield_do_not_trigger_bleed(self):
        p = [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)]
        source = dict(slave_id=10, owner_id=10, class_id="ring", level=18)
        raid = create_raid_state(p, [source], FIGHTER_CLASSES, BUILTIN_SKILLS)
        raid["round"] = 3
        raid["intent"] = dict(kind="shield", targets=[], phase=1, text="Щит")
        for f in (raid["boss"], raid["players"]["10"]["fighter"]):
            f["effects"] = [dict(id="bleed", kind="bleed", value=3, duration=3)]
        before = (raid["boss"]["hp"], raid["players"]["10"]["fighter"]["hp"])
        raid["players"]["10"]["selected"] = "defend"
        resolve_round(raid, BUILTIN_SKILLS, AlwaysHit())
        self.assertEqual(
            before, (raid["boss"]["hp"], raid["players"]["10"]["fighter"]["hp"])
        )


class PassiveSlotTests(unittest.TestCase):
    def test_level_gate_and_effects_applied_to_third_passive(self):
        details = [
            asdict(BUILTIN_PASSIVES[k])
            for k in ("stone_skin", "light_step", "battle_rhythm")
        ]
        for level, limit in ((9, 2), (10, 3), (20, 3)):
            source = dict(
                slave_id=10,
                owner_id=10,
                class_id="ragamuffin",
                level=level,
                passive_details=details,
            )
            state = create_battle_state(
                source, dict(source, slave_id=20, passive_details=[])
            )
            actor = state["sides"]["a"]
            self.assertEqual(len(actor["passive_details"]), limit)
            self.assertEqual(
                any(e["kind"] == "damage_pct" for e in actor["effects"]), level >= 10
            )


class PassiveStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = market_tests.ArenaMarketTests.asyncSetUp
    asyncTearDown = market_tests.ArenaMarketTests.asyncTearDown
    add = market_tests.ArenaMarketTests.add
    qty = market_tests.ArenaMarketTests.qty

    async def test_four_learned_and_level_gated_three_equipped_for_both_profiles(self):
        keys = list(BUILTIN_PASSIVES)[:4]
        for user, personal in ((10, True),):
            for key in keys:
                await self.db.arena_use_item(
                    1, 10, self.add("passive", key), user, personal
                )
            view = await menu_view(self.db, 1, 10)
            profile = view["personal"] if personal else view["slaves"][0]
            self.assertEqual(len(profile["passives"]), 4)
            self.assertEqual(len(profile["passive_loadout"]), 2)
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(
                    1, user, user, personal, "passives", keys[:3]
                )
            table = "personal_profiles" if personal else "slave_profiles"
            self.db.connection.execute(
                f"UPDATE {table} SET level=10,progression_level=10,progression_pending_level=0 WHERE chat_id=0 AND user_id=?",
                (user,),
            )
            self.db.connection.commit()
            await self.db.arena_edit_profile(
                1, user, user, personal, "passives", keys[:3]
            )
            self.assertEqual(
                len(self.db._arena_selected_passives_locked(1, user, personal)), 3
            )
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(
                    1, user, user, personal, "passives", keys
                )
            fifth = next(k for k in BUILTIN_PASSIVES if k not in keys)
            item = self.add("passive", fifth)
            quantity = self.qty(item)
            with self.assertRaisesRegex(ValueError, "Максимум 4"):
                await self.db.arena_use_item(1, 10, item, user, personal)
            self.assertEqual(self.qty(item), quantity)
