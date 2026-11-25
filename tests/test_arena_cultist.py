from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import arena_cultist as cult
from arena_cultist_qte import RHYTHM
from arena_archclasses import branch_options
from arena_engine import BUILTIN_SKILLS, create_battle_state, resolve_skill, unlocked_skill_ids
from arena_qte_patterns import defense, defense_step, geometry, prepare, profile, touches
from arena_qte_live import challenge
from arena_qte_rules import replay
from arena_qte_unique import review_catalog
from arena_raid_engine import defend, native_attack
from arena_skill_timing import duration
from arena_unified_queue import choice, clock, submit
import test_arena_progression as progression


class Hits:
    def random(self):
        return 0

    def uniform(self, low, high):
        return 1


class CultistTests(unittest.TestCase):
    def battle(self, branch, stage=20, *, enemy_npc=False):
        state = create_battle_state(
            dict(slave_id=1, owner_id=1, class_id="cultist", level=20,
                 archclass_id=branch, archclass_stage=stage, loadout=cult.branch_loadout(branch)),
            dict(slave_id=0 if enemy_npc else 2, owner_id=0 if enemy_npc else 2,
                 class_id="warrior", level=20, loadout=["bum_punch", "steel_charge"]),
            action_queue_version=True,
        )
        for fighter in state["sides"].values():
            fighter["hp"] = fighter["stats"]["max_hp"] = 1000
        return state

    def cast(self, state, key, sid, proof=None):
        state["active_side"] = key
        side = state["sides"][key]
        side["resource"] = side["stats"]["resource_max"]
        return resolve_skill(state, key, sid, rng=Hits(), advance_turn=False, qte=proof)

    def test_fanaticism_and_spending_only_on_hit(self):
        state = self.battle("")
        a, b = state["sides"].values()
        with self.assertRaisesRegex(ValueError, "фанатизма"):
            self.cast(state, "a", "cult_rite")
        self.cast(state, "a", "cult_sign")
        self.assertTrue(cult._marker(b, cult._seal(a)))
        self.cast(state, "a", "cult_voice")
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 3)
        self.assertIsNone(cult._marker(b, cult._seal(a)))
        self.cast(state, "a", "cult_rite", {"attack": [False]})
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 3)
        a["cooldowns"].clear()
        self.cast(state, "a", "cult_rite")
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 1)

    def test_cultists_do_not_overwrite_each_others_personal_seals(self):
        state = self.battle("")
        a, b = state["sides"].values()
        second = dict(deepcopy(a), controller_id=3, slave_id=3)
        for caster in (a, second):
            native_attack(caster, b, "cult_sign", BUILTIN_SKILLS, Hits())
        self.assertEqual(sum(e["kind"] == cult.SEAL for e in b["effects"]), 2)
        native_attack(a, b, "cult_voice", BUILTIN_SKILLS, Hits())
        self.assertIsNone(cult._marker(b, cult._seal(a)))
        self.assertIsNotNone(cult._marker(b, cult._seal(second)))
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 3)

    def test_cthulhu_does_not_delay_committed_cast_and_consumes_next_once(self):
        state = self.battle("cultist_cthulhu")
        _, b = state["sides"].values()
        punch = BUILTIN_SKILLS["bum_punch"]
        base = duration(b, punch)
        committed = submit(state, "b", punch.skill_id, "a", BUILTIN_SKILLS, ident=choice(state, "b"))
        self.cast(state, "a", "cult_depths")
        self.assertEqual(committed["duration"], base)
        self.assertGreater(duration(b, punch), base)
        clock(state)["pending"].clear()
        next_cast = submit(state, "b", punch.skill_id, "a", BUILTIN_SKILLS, ident=choice(state, "b"))
        self.assertGreater(next_cast["duration"], base)
        self.assertEqual(duration(b, punch), base)

    def test_cthulhu_encounter_spreads_mark_not_damage_and_respects_three_target_cap(self):
        state = self.battle("cultist_cthulhu")
        a, b = state["sides"].values()
        a["rpg_state"] = {"cult_fanaticism": 3}
        others = [deepcopy(b) for _ in range(4)]
        context = {"players": {"1": {"fighter": a}}, "enemies": dict(enumerate([b, *others]))}
        event = native_attack(a, b, "arch_cultist_cthulhu", BUILTIN_SKILLS, Hits(), raid_context=context)
        self.assertGreater(event["damage"], 0)
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 1)
        self.assertEqual([bool(cult._marker(f, cult.WHISPER)) for f in [b, *others]],
                         [True, True, True, False, False])
        self.assertTrue(all(f["hp"] == 1000 for f in others))

    def test_yog_requires_gate_releases_on_hit_and_refunds_mana(self):
        state = self.battle("cultist_yog")
        a, _ = state["sides"].values()
        a["rpg_state"] = {"cult_fanaticism": 2}
        with self.assertRaisesRegex(ValueError, "открой вход"):
            self.cast(state, "a", cult.PORTAL_SKILL)
        self.cast(state, "a", "cult_gate")
        self.cast(state, "a", cult.PORTAL_SKILL, {"attack": [False, False]})
        self.assertTrue(cult._marker(a, "cult_gate_open"))
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 3)
        # Reopen via the real active so the alternative retry is within its window.
        a["cooldowns"].clear()
        self.cast(state, "a", "cult_gate")
        self.cast(state, "a", cult.PORTAL_SKILL)
        self.assertIsNone(cult._marker(a, "cult_gate_open"))
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 1)
        self.assertEqual(a["resource"], 100 - BUILTIN_SKILLS[cult.PORTAL_SKILL].cost + 12)

    def test_shub_growth_mitigation_roles_and_death(self):
        state = self.battle("cultist_shub")
        a, b = state["sides"].values()
        self.cast(state, "a", "cult_brood")
        with self.assertRaisesRegex(ValueError, "живой отпрыск"):
            self.cast(state, "a", "cult_brood")
        fresh_hp = a["rpg_state"]["cult_brood"]["hp"]
        self.cast(state, "a", "cult_sign")
        self.cast(state, "a", "cult_voice")
        brood = a["rpg_state"]["cult_brood"]
        self.assertEqual((brood["stage"], brood["hp"]), (3, fresh_hp + 12))
        unprotected = deepcopy(state)
        unprotected["sides"]["a"]["rpg_state"].pop("cult_brood")
        normal = self.cast(unprotected, "b", "steel_charge")["damage"]
        event = self.cast(state, "b", "steel_charge")
        received = event["damage"]
        self.assertIn("отпрыск принял", event["text"])
        self.assertGreater(normal, received)
        self.assertEqual(brood["hp"], fresh_hp + 12 - (normal - received))
        self.cast(state, "a", "arch_cultist_shub")
        self.assertAlmostEqual(cult.damage_multiplier(a, b, BUILTIN_SKILLS["cult_sign"]), 1.18)
        brood["hp"] = 1
        self.cast(state, "b", "bum_punch")
        self.assertNotIn("cult_brood", a["rpg_state"])
        self.assertGreaterEqual(a["cooldowns"]["cult_brood"], 3)

    def test_qte_knows_the_brood_pool_but_does_not_touch_it(self):
        from arena_qte_combined import combine
        state = self.battle("cultist_shub")
        a, b = state["sides"].values()
        self.cast(state, "a", "cult_brood")
        before = deepcopy(a)
        stage = challenge("defense", b, a, BUILTIN_SKILLS["bum_punch"], a["controller_id"])
        self.assertEqual(a, before)
        self.assertEqual(stage["cult_cover"], {"hp": 30, "percent": 30})
        joint = combine([dict(stage, encounter_enemy="b")], a["controller_id"], a["hp"])
        self.assertEqual(joint["cult_cover"], stage["cult_cover"])

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_partial_qte_contacts_round_once_and_use_one_cover_pool(self):
        # Fractional threshold + a depleting pool across consecutive casts.
        script = """
const E=require('./webapp/qte-unique/engine');
const s={initialHp:1000,cover:E.coverState({hp:5,percent:30})};
console.log(JSON.stringify([E.coveredDamage(s,0,2),E.coveredDamage(s,2,9),E.coveredDamage(s,0,30),s.cover.hp]));
"""
        amounts = json.loads(subprocess.check_output(["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1]))
        state = self.battle("cultist_shub")
        a = state["sides"]["a"]
        self.cast(state, "a", "cult_brood")
        a["rpg_state"]["cult_brood"]["hp"] = 5
        first, _ = cult.incoming(a, 9)
        second, _ = cult.incoming(a, 30)
        self.assertEqual([sum(amounts[:2]), *amounts[2:]], [first, second, 0])
        self.assertIsNone(cult.cover_view(a))

    def test_hastur_marks_repetition_and_defend_breaks_it(self):
        state = self.battle("cultist_hastur", 10)
        a, b = state["sides"].values()
        self.cast(state, "a", "cult_yellow")
        first = self.cast(state, "b", "bum_punch")["damage"]
        second = self.cast(state, "b", "bum_punch")["damage"]
        self.assertGreater(first, second)
        self.assertAlmostEqual(cult.damage_multiplier(a, b, BUILTIN_SKILLS["arch_cultist_hastur"]), 1.30)
        defend(b)
        self.assertEqual(cult.damage_multiplier(b, a, BUILTIN_SKILLS["bum_punch"]), 1)

    def test_patron_requires_class_and_level_and_has_two_native_skills(self):
        self.assertEqual({b["id"] for b in branch_options("cultist")}, set(cult.PATRONS))
        for branch in cult.PATRONS:
            first, second = cult.branch_loadout(branch)[2:]
            self.assertNotIn(first, unlocked_skill_ids("cultist", 9, archclass_id=branch))
            self.assertIn(first, unlocked_skill_ids("cultist", 10, archclass_id=branch))
            self.assertNotIn(second, unlocked_skill_ids("cultist", 14, archclass_id=branch))
            self.assertIn(second, unlocked_skill_ids("cultist", 15, archclass_id=branch))
            self.assertNotIn(second, unlocked_skill_ids("mage", 20, archclass_id=branch))
            self.assertNotIn(second, unlocked_skill_ids("cultist", 20))

    def test_final_passives_require_the_form_not_just_character_level(self):
        for stage in (10,20):
            for branch in cult.FORMS:
                with self.subTest(stage=stage, branch=branch):
                    state = self.battle(branch, stage)
                    a, b = state["sides"].values()
                    self.assertEqual(cult.final_form(a), cult.FORMS[branch] if stage == 20 else None)
                    if branch == "cultist_cthulhu":
                        self.cast(state, "a", "cult_depths")
                        self.assertEqual(cult.cast_multiplier(b), 1.25 if stage == 20 else 1.18)
                        other = dict(a, controller_id=3, slave_id=3)
                        attack = BUILTIN_SKILLS["cult_sign"]
                        self.assertEqual(cult.damage_multiplier(a, b, attack), 1.10 if stage == 20 else 1)
                        self.assertEqual(cult.damage_multiplier(other, b, attack), 1)
                    elif branch == "cultist_yog":
                        self.cast(state, "a", "cult_gate")
                        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 2 if stage == 20 else 1)
                    elif branch == "cultist_shub":
                        self.cast(state, "a", "cult_brood")
                        self.assertEqual(cult.cover_view(a)["hp"], 30 if stage == 20 else 24)
                        a["cooldowns"].clear()
                        a["rpg_state"]["cult_brood"]["hp"] = 1
                        cult.incoming(a, 30)
                        self.assertEqual(a["cooldowns"]["cult_brood"], 3 if stage == 20 else 4)
                    else:
                        self.cast(state, "a", "cult_yellow")
                        mark = cult._marker(b, cult.YELLOW)
                        self.assertEqual((mark["duration"],mark["penalty"]), (5,.25) if stage == 20 else (4,.18))
        self.assertIsNone(cult.final_form(dict(class_id="cultist", level=19, archclass_id="cultist_cthulhu")))
        self.assertIsNone(cult.final_form(dict(class_id="mage", level=20, archclass_id="cultist_cthulhu")))

    def test_roots_require_and_grow_a_living_offspring(self):
        state = self.battle("cultist_shub")
        a = state["sides"]["a"]
        a["loadout"][1] = "cult_roots"
        self.assertNotIn("cult_roots", unlocked_skill_ids("cultist", 11, archclass_id="cultist_shub"))
        self.assertIn("cult_roots", unlocked_skill_ids("cultist", 12, archclass_id="cultist_shub"))
        with self.assertRaisesRegex(ValueError, "живой отпрыск"):
            self.cast(state, "a", "cult_roots")
        self.cast(state, "a", "cult_brood")
        event = self.cast(state, "a", "cult_roots")
        self.assertGreater(event["damage"], 0)
        self.assertEqual(a["rpg_state"]["cult_fanaticism"], 1)
        self.assertEqual(a["rpg_state"]["cult_brood"]["stage"], 2)

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_live_dodge_replays_in_browser_and_server(self):
        cases = []
        for sid in RHYTHM:
            skill = next(s for s in review_catalog() if s["base_id"] == sid)
            stats = dict(accuracy=96, enemyEvasion=10, evasion=10, enemyAccuracy=96)
            st = defense(profile(skill), stats, 19)
            prepare(st, st["events"][0])
            self.assertTrue(st["hazards"])
            self.assertEqual(len(st["events"]), RHYTHM[sid][0])
            if sid == "cult_voice":
                left, right = st["hazards"]
                self.assertTrue(all(h["type"] == "polyline" for h in (left, right)))
                self.assertLess(left["fold"][1], right["fold"][0])
                self.assertLess(left["fold"][3] * right["fold"][3], 0)
                self.assertNotEqual(geometry(left, left["start"]+.40)["points"], geometry(left,left["start"])["points"])
            if sid == "cult_yellow":
                self.assertEqual(sum(h["disabled"] for h in st["hazards"]), 2)
                self.assertEqual(st["projectileCount"], 2)
                self.assertTrue(all(h["type"] == "bullet" for h in st["hazards"]))
            if sid == "cult_depths":
                self.assertEqual(len(st["hazards"]), 7)
                self.assertEqual(st["projectileCount"], 5)
                self.assertTrue(all(h["motif"] == "cult_wraith" and h["waveA"] for h in st["hazards"]))
            if sid == "arch_cultist_cthulhu":
                tides = [h for h in st["hazards"] if h["motif"] == "cult_tide"]
                self.assertEqual(len(tides), 4)
                self.assertLess(tides[0]["cultSlide"] * tides[2]["cultSlide"], 0)
                self.assertNotEqual(geometry(tides[0], tides[0]["start"]+.3)["routeY"], tides[0]["routeY"])
                self.assertEqual(sum(h["type"]=="well" for h in st["hazards"]), 2)
            if sid == cult.PORTAL_SKILL:
                self.assertEqual(sum(h.get("gate_show", False) for h in st["hazards"]), 2)
                self.assertEqual(sum(h["motif"] == "cult_sphere" for h in st["hazards"]), 10)
                self.assertEqual({h["motif"] for h in st["hazards"]}, {"cult_comet", "cult_sphere"})
            if sid == "cult_roots":
                self.assertEqual(sum(bool(h.get("homing")) for h in st["hazards"]), 3)
                self.assertEqual({h["y"] for h in st["hazards"] if h["x"] not in (0, 720)}, {0, 320})
                self.assertEqual(sum(h["x"] in (0, 720) for h in st["hazards"]), 1)
            if sid == "cult_rite":
                candles = [h for h in st["hazards"] if h.get("orbit")]
                returns = {h["candle"]:h for h in st["hazards"] if h.get("riteOut")}
                self.assertEqual(len(candles), 17)
                self.assertEqual(len(returns), len(candles))
                self.assertEqual(len({h["orbitSpeed"] > 0 for h in candles}), 2)
                self.assertGreater(max(h["x"] for h in candles)-min(h["x"] for h in candles), 520)
                self.assertNotEqual(geometry(candles[0], candles[0]["start"]+.6)["x"], candles[0]["x"])
                for candle in candles:
                    returned = returns[candle["candle"]]
                    paused = geometry(candle, candle["end"])
                    self.assertAlmostEqual(paused["x"], returned["x"])
                    self.assertAlmostEqual(paused["y"], returned["y"])
                    self.assertAlmostEqual(candle["end"], returned["start"])
            if sid == "cult_sign":
                self.assertEqual(sum(bool(h.get("clockTurn")) for h in st["hazards"]), 5)
                self.assertEqual(st["projectileCount"], 2)  # one blade sweep plus the eye
            if sid == "arch_cultist_hastur":
                self.assertTrue(any(h["motif"] == "cult_stage" and not h["disabled"] for h in st["hazards"]))
                previous = st["cultCue"]
                st["player"]["x"] += 150
                prepare(st, st["events"][1])
                reprise = next(h for h in st["hazards"] if h.get("reprise"))
                self.assertEqual((reprise["replay_x"], reprise["replay_y"]), previous)
                prepare(st, st["events"][2])
                left, right = [h for h in st["hazards"] if h["motif"]=="cult_curtain"]
                self.assertEqual(geometry(left,left["start"])["w"],0)
                self.assertGreater(geometry(right,right["end"])["x"]-geometry(left,left["end"])["w"],110)
            cases.append(dict(version=2, kind="defense", seed=19, stats=stats, profile=skill,
                              strikes=skill["strikes"], defense_preparation=1))
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_patterns_trace.cjs"))],
            input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
        for case, trace in zip(cases, json.loads(result.stdout)):
            with self.subTest(move=case["profile"]["base_id"]):
                self.assertEqual(replay(case, trace["proof"], 30), trace["result"])

    def test_standing_still_is_not_safe_against_sign_or_carcosa(self):
        stats = dict(accuracy=75, enemyEvasion=25, evasion=75, enemyAccuracy=25)
        for sid in ("cult_sign", "arch_cultist_hastur"):
            skill = next(s for s in review_catalog() if s["base_id"] == sid)
            for point in ((12, 12), (708, 308), (360, 160), (230.4, 160)):
                with self.subTest(skill=sid, point=point):
                    st = defense(profile(skill), stats, 19)
                    st["player"].update(x=point[0], y=point[1])
                    while st["time"] < st["preparation"] + 1.55 and not st["contacts"]:
                        defense_step(st, {})
                    self.assertTrue(st["contacts"], "first wave forces movement even at the boundary")

    def test_fanning_candles_reach_players_who_camp_the_rim(self):
        skill = next(s for s in review_catalog() if s["base_id"] == "cult_rite")
        stats = dict(accuracy=75, enemyEvasion=25, evasion=75, enemyAccuracy=25)
        for x,y in ((12,12),(12,160),(708,308),(708,70),(358,308),(440,12)):
            with self.subTest(x=x,y=y):
                st = defense(profile(skill),stats,17)
                st["player"].update(x=x,y=y)
                while st["time"] < st["preparation"]+6.8:
                    defense_step(st,{})
                self.assertTrue(any(":scatter:" in c["id"] for c in st["contacts"]))

    def test_vine_trunk_and_branches_collide_after_the_head_passes(self):
        skill = next(s for s in review_catalog() if s["base_id"] == "cult_roots")
        st = defense(profile(skill),dict(accuracy=75, enemyEvasion=25, evasion=75, enemyAccuracy=25),17)
        while not st["hazards"]:
            defense_step(st,{})
        h = next(h for h in st["hazards"] if h["index"]==0)
        while st["time"] < h["start"]+h["vineStop"]+.11:
            defense_step(st,{})
        self.assertGreater(st["time"],h["start"]+h["vineStop"])
        mid = h["vineTrail"][1]
        tip = geometry(h,st["time"])
        self.assertGreater((tip["x"]-mid[0])**2+(tip["y"]-mid[1])**2, 60**2)
        for x,y in (mid[:2],h["vineBranches"][0][2:]):
            point = dict(x=x,y=y,r=6)
            self.assertTrue(touches(h,point,point,st["time"],1/120))

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_every_cultist_attack_has_a_damage_free_route_at_high_pressure(self):
        from arena_qte_unique import review_catalog
        cases = [
            dict(version=2, kind="defense", seed=17, profile=skill,
                 stats=dict(accuracy=90, enemyEvasion=0, evasion=0, enemyAccuracy=100),
                 strikes=skill["strikes"], defense_preparation=1, perfect=True)
            for skill in review_catalog()
            if skill["base_id"] in RHYTHM and skill["class_id"] == "cultist"
        ]
        self.assertEqual(len(cases), len(RHYTHM))
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_patterns_trace.cjs"))],
            input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        for case, trace in zip(cases, json.loads(result.stdout)):
            self.assertEqual(replay(case, trace["proof"], 30)["contacts"], [], case["profile"]["name"])

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_every_cultist_block_replays_against_the_same_choreography(self):
        from arena_qte_block import replay as replay_block
        cases = [
            dict(version=3, kind="defense", defense_mode="block", seed=23, profile=s,
                 stats=dict(magicDefense=14, enemyAttack=24, enemyAccuracy=90),
                 strikes=s["strikes"], policy="careful")
            for s in review_catalog() if s["base_id"] in RHYTHM
        ]
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_block_trace.cjs"))],
            input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8", timeout=35)
        self.assertEqual(result.returncode, 0, result.stderr)
        for case, trace in zip(cases, json.loads(result.stdout)):
            self.assertEqual(replay_block(case, trace["proof"], 30), trace["result"], case["profile"]["name"])


class CultistMenuTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = progression.ProgressionTests.asyncSetUp
    asyncTearDown = progression.ProgressionTests.asyncTearDown
    level = progression.ProgressionTests.level
    profile = progression.ProgressionTests.profile
    choose = progression.ProgressionTests.choose

    async def test_select_real_classes_and_advance_each_patron(self):
        for branch in cult.PATRONS:
            self.level(5)
            await self.choose("cultist")
            self.level(10, "cultist")
            menu = await self.profile()
            self.assertEqual({row["id"] for row in menu["progression_choice"]["options"]} - {"stay"},
                             set(cult.PATRONS))
            await self.choose(branch)
            menu = await self.profile()
            self.assertIn(cult.PATRONS[branch][1], menu["archclass"]["description"])
            self.assertEqual(menu["archclass"]["stage"], 10)
            self.assertNotIn("form", menu["archclass"])
            self.assertIn(cult.branch_loadout(branch)[2], {s["skill_id"] for s in menu["skills"]})
            self.level(20, "cultist")
            pending = await self.profile()
            opt = next(o for o in pending["progression_choice"]["options"] if o["id"]=="advance")
            form = cult.FORMS[branch]
            self.assertEqual(opt["name"], form["name"])
            self.assertTrue(opt["avatar_url"].endswith("/"+form["id"]+".png"))
            self.assertNotIn("form", pending["archclass"])
            await self.choose("advance")
            menu = await self.profile()
            self.assertEqual(menu["archclass"]["stage"], 20)
            self.assertEqual(menu["archclass"]["id"], branch)
            self.assertEqual(menu["archclass"]["form"], form)
            self.assertEqual(menu["class_avatar_url"],opt["avatar_url"])
            await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
