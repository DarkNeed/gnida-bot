"""Persistent interactive phases. Only authoritative replays reach the combat engine."""

from copy import deepcopy
import json
import math
import random
import secrets
import time

from arena_qte_rules import replay


def strike_count(skill):
    return (
        6
        if "six_strike" in skill.tags
        else (
            3
            if "three_strike" in skill.tags
            else 2 if "two_strike" in skill.tags else 1
        )
    )


def challenge(kind, attacker, target, skill, actor):
    from arena_engine import (
        effective_stat,
        combat_modifiers,
        class_modifiers,
        epic_modifiers,
        rpg_modifiers,
        mastery_modifiers,
        gift_modifiers,
        pet_modifiers,
    )

    a, b = deepcopy(attacker), deepcopy(target)
    bonuses = sum(
        e.get("value", 0) for e in a["effects"] if e.get("kind") == "accuracy_flat"
    )
    bonuses += combat_modifiers(a, b, skill, random.Random(0))[0]
    bonuses += class_modifiers(a, b, skill)[0] + epic_modifiers(a, b, skill)[0]
    bonuses += rpg_modifiers(a, b, skill)[0] + mastery_modifiers(a, b, skill)[0]
    bonuses += gift_modifiers(a, b)[0] + pet_modifiers(a, skill)[0]
    accuracy = max(0, min(100, skill.accuracy + bonuses))
    evasion = max(0, min(100, effective_stat(b, "evasion")))
    n = strike_count(skill)
    stats = dict(
        accuracy=accuracy, enemyEvasion=evasion, enemyAccuracy=accuracy, evasion=evasion
    )
    descriptor = dict(
        id=f"{skill.skill_id}:{skill.name}:{n}:{skill.damage_type}",
        base_id=skill.skill_id,
        name=skill.name,
        class_id=skill.class_id,
        branch=attacker.get("archclass_id", ""),
        damage_type=skill.damage_type,
        strikes=n,
    )
    # Kit's announced reflection/coins consist of two different native actions.
    # One pattern, two groups: do not apply the same collisions to both actions.
    subskills = {
        "kit_reflection": ["kit_reflection", "kit_ash"],
        "kit_coins": ["kit_coins", "kit_coins_ash"],
    }.get(skill.skill_id)
    if kind == "defense" and subskills:
        n = descriptor["strikes"] = 2
        descriptor["id"] = f"{skill.skill_id}:{skill.name}:2:{skill.damage_type}"
    return dict(
        version=2,
        profile=descriptor,
        subskills=subskills if kind == "defense" else None,
        damage_base=damage_preview(attacker, target, skill),
        target_hp=target["hp"],
        id=secrets.token_hex(16),
        kind=kind,
        actor=actor,
        name=skill.name,
        strikes=n,
        seed=secrets.randbits(32),
        stats=stats,
        pattern=(
            "slashes" if n == 6 else "rain" if skill.damage_type == "magic" else "cross"
        ),
    )


def damage_preview(attacker, target, skill):
    """Read-only estimate for immediate HP feedback; the paid action is resolved later.

    Raid ally effects, defenses and critical rolls can change before the boss acts.
    No guessed HP or result from the client is ever persisted.
    """
    if not skill.damage_type:
        return 0
    from arena_engine import resolve_skill, BUILTIN_SKILLS

    a, b = deepcopy(attacker), deepcopy(target)
    # Give the projection room to expose the full reference damage, not overkill.
    b["hp"] = max(b["hp"], 1000000)
    state = dict(
        sides={"a": a, "b": b},
        turn=1,
        active_side="a",
        log=[],
        finished=False,
        winner=None,
    )
    try:
        event = resolve_skill(
            state,
            "a",
            skill.skill_id,
            {**BUILTIN_SKILLS, skill.skill_id: skill},
            random.Random(0),
            advance_turn=False,
            tick_actor_bleed=False,
            qte=dict(attack=[True] * strike_count(skill)),
        )
        return event["damage"]
    except ValueError:
        return max(1, round(skill.power))


class ArenaQteMixin:
    def _connect_qte(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_combat_settings (
                actor_id INTEGER PRIMARY KEY, minigames INTEGER NOT NULL CHECK(minigames IN (0,1)));
            CREATE TABLE IF NOT EXISTS arena_qte_flows (
                scope TEXT NOT NULL, token TEXT NOT NULL, actor_id INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(scope,token,actor_id));
        """)

    def _qte_enabled_locked(self, actor):
        if not actor:
            return False
        row = self.connection.execute(
            "SELECT minigames FROM arena_combat_settings WHERE actor_id=?", (actor,)
        ).fetchone()
        return bool(row["minigames"]) if row else True

    async def arena_combat_settings(self, actor, enabled=None):
        async with self._lock:
            if enabled is not None:
                if type(enabled) is not bool:
                    raise ValueError("Некорректная настройка мини-игр.")
                self.connection.execute(
                    "INSERT INTO arena_combat_settings VALUES(?,?) ON CONFLICT(actor_id) DO UPDATE SET minigames=excluded.minigames",
                    (actor, int(enabled)),
                )
                self.connection.commit()
            return dict(minigames=self._qte_enabled_locked(actor))

    def _qte_snapshot_locked(self, scope, row, state):
        if "qte_modes" in state:
            return
        actors = (
            [p["actor_id"] for p in state["players"].values()]
            if scope == "raid"
            else [s["controller_id"] for s in state["sides"].values()]
        )
        state["qte_modes"] = {
            str(actor): self._qte_enabled_locked(actor) for actor in actors
        }
        table, column = (
            ("arena_raids", "data_json")
            if scope == "raid"
            else ("arena_battles", "state_json")
        )
        self.connection.execute(
            f"UPDATE {table} SET {column}=? WHERE token=?",
            (json.dumps(state, ensure_ascii=False), row["token"]),
        )

    def _qte_load_locked(self, scope, token, actor=0):
        row = self.connection.execute(
            "SELECT payload FROM arena_qte_flows WHERE scope=? AND token=? AND actor_id=?",
            (scope, token, actor),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def _qte_save_locked(self, flow, new_stage=False):
        now = time.time()
        stage = flow["stages"][0]
        if new_stage:
            if stage.get("version") == 2:
                from arena_qte_patterns import duration as pattern_duration

                duration = pattern_duration(stage)
            else:
                duration = (
                    6
                    if stage["kind"] == "defense"
                    else stage["strikes"] * (0.95 if stage["strikes"] > 1 else 2.8)
                )
            stage.update(started=now, expires=now + duration + 8)
        self.connection.execute(
            "INSERT INTO arena_qte_flows VALUES(?,?,?,?) ON CONFLICT(scope,token,actor_id) DO UPDATE SET payload=excluded.payload",
            (
                flow["scope"],
                flow["token"],
                flow["owner"],
                json.dumps(flow, ensure_ascii=False),
            ),
        )
        table = "arena_raids" if flow["scope"] == "raid" else "arena_battles"
        self.connection.execute(
            f"UPDATE {table} SET revision=revision+1,deadline=MAX(deadline,?) WHERE token=?",
            (math.ceil(stage["expires"]) + 2, flow["token"]),
        )

    def _qte_delete_locked(self, flow):
        self.connection.execute(
            "DELETE FROM arena_qte_flows WHERE scope=? AND token=? AND actor_id=?",
            (flow["scope"], flow["token"], flow["owner"]),
        )

    def _qte_valid_locked(self, flow):
        try:
            row = (
                self._raid_row_locked(flow["token"])
                if flow["scope"] == "raid"
                else self._arena_row_locked(flow["token"])
            )
            if row["status"] != "active":
                return False
            state = json.loads(
                row["data_json"] if flow["scope"] == "raid" else row["state_json"]
            )
            if flow["scope"] == "battle":
                return (
                    state["turn"] == flow["turn"]
                    and state["active_side"] == flow["key"]
                )
            player = state["players"].get(str(flow["owner"]))
            return bool(
                state["round"] == flow["turn"]
                and player
                and not player.get("withdrawn")
                and player["fighter"]["hp"] > 0
                and player["selected"] is None
            )
        except (ValueError, KeyError):
            return False

    def _qte_battle_begin_locked(self, row, skill_id):
        from arena_engine import validate_skill

        state = json.loads(row["state_json"])
        self._qte_snapshot_locked("battle", row, state)
        key = state["active_side"]
        other = "b" if key == "a" else "a"
        a, b = state["sides"][key], state["sides"][other]
        _, skills = self._fighter_catalog_locked()
        skill = validate_skill(state, key, skill_id, skills)
        stages = []
        modes = state["qte_modes"]
        if skill.hostile:
            if modes.get(str(a["controller_id"])):
                stages.append(challenge("attack", a, b, skill, a["controller_id"]))
            if modes.get(str(b["controller_id"])):
                stages.append(challenge("defense", a, b, skill, b["controller_id"]))
        if not stages:
            return False
        flow = dict(
            scope="battle",
            token=row["token"],
            owner=0,
            skill=skill_id,
            key=key,
            actor=a["controller_id"],
            turn=state["turn"],
            stages=stages,
            result={},
            luck_evasion=bool(
                b["controller_id"] and not modes.get(str(b["controller_id"]))
            ),
            luck_accuracy=bool(
                a["controller_id"] and not modes.get(str(a["controller_id"]))
            ),
        )
        self._qte_save_locked(flow, True)
        return True

    def _qte_battle_drive_locked(self, token):
        from arena_engine import validate_skill

        for _ in range(12):
            row = self._arena_row_locked(token)
            if row["status"] != "active" or self._qte_load_locked("battle", token):
                return row
            state = json.loads(row["state_json"])
            if row["mode"] != "wasteland" or state["active_side"] != "b":
                return row
            _, skills = self._fighter_catalog_locked()
            choices = []
            for sid in state["sides"]["b"]["loadout"]:
                try:
                    validate_skill(state, "b", sid, skills)
                    choices.append(sid)
                except ValueError:
                    pass
            sid = random.choice(choices or ["bum_punch"])
            if self._qte_battle_begin_locked(row, sid):
                return self._arena_row_locked(token)
            self._arena_action_locked(token, 0, row["revision"], sid, _interactive=True)
        raise ValueError("Не удалось завершить ход противника.")

    def _qte_complete_locked(self, flow, proof=None, expired=False):
        if not self._qte_valid_locked(flow):
            self._qte_delete_locked(flow)
            return
        stage = flow["stages"][0]
        result = replay(
            stage,
            dict(abort=True) if expired else proof,
            time.time() - stage["started"],
        )
        key = "attack" if stage["kind"] == "attack" else "dodge"
        mask = result["mask"] if isinstance(result, dict) else result
        flow["result"][key] = mask
        if isinstance(result, dict):
            flow["result"]["pattern_" + key] = result
            if stage.get("subskills"):
                flow["result"]["guard_subskills"] = stage["subskills"]
        flow["stages"].pop(0)
        if flow["scope"] == "battle" and stage["kind"] == "attack" and not any(mask):
            flow["stages"] = [s for s in flow["stages"] if s["kind"] != "defense"]
        if flow["scope"] == "battle" and stage["kind"] == "attack":
            for following in flow["stages"]:
                if following.get("version") == 2 and following["kind"] == "defense":
                    following["enabled_strikes"] = mask
        if flow["stages"]:
            self._qte_save_locked(flow, True)
            return
        self._qte_delete_locked(flow)
        if flow["scope"] == "battle":
            row = self._arena_row_locked(flow["token"])
            self.connection.execute(
                "UPDATE arena_battles SET deadline=MAX(deadline,?) WHERE token=?",
                (int(time.time()) + 2, flow["token"]),
            )
            result = dict(
                flow["result"],
                luck_evasion=flow["luck_evasion"],
                luck_accuracy=flow.get("luck_accuracy", True),
            )
            self._arena_action_locked(
                flow["token"],
                flow["actor"],
                row["revision"],
                flow["skill"],
                _qte=result,
                _interactive=True,
            )
            self._qte_battle_drive_locked(flow["token"])
        else:
            row = self._raid_row_locked(flow["token"])
            # A completed attempt at the boundary is resolved before the round timeout.
            self.connection.execute(
                "UPDATE arena_raids SET deadline=MAX(deadline,?) WHERE token=?",
                (int(time.time()) + 2, flow["token"]),
            )
            result = dict(flow["result"], guard_skill=flow.get("guard_skill"))
            self._arena_raid_action_locked(
                flow["token"], flow["owner"], flow["turn"], flow["skill"], _qte=result
            )

    def _qte_expire_locked(self, scope, token=None):
        rows = self.connection.execute(
            "SELECT payload FROM arena_qte_flows WHERE scope=?"
            + (" AND token=?" if token else ""),
            (scope, token) if token else (scope,),
        ).fetchall()
        for raw in rows:
            flow = json.loads(raw["payload"])
            if not self._qte_valid_locked(flow):
                self._qte_delete_locked(flow)
            elif flow["stages"][0]["expires"] <= time.time():
                self._qte_complete_locked(flow, expired=True)

    async def arena_qte_refresh(self, scope, token):
        async with self._lock:
            with self.connection:
                self._qte_expire_locked(scope, token)

    async def arena_qte_view(self, scope, token, actor):
        async with self._lock:
            flow = self._qte_load_locked(scope, token, actor if scope == "raid" else 0)
            if not flow or not self._qte_valid_locked(flow):
                return None
            stage = flow["stages"][0]
            public = deepcopy(stage)
            public["server_now"] = time.time()
            return dict(
                waiting=True,
                kind=stage["kind"],
                actor=stage["actor"],
                challenge=public if stage["actor"] == actor else None,
            )

    async def arena_interactive_action(
        self, token, actor, revision, action, skill="", proof=None, challenge_id=None
    ):
        async with self._lock:
            with self.connection:
                self._qte_expire_locked("battle", token)
                row = self._arena_row_locked(token)
                if row["status"] != "active":
                    raise ValueError("Бой завершён.")
                state = json.loads(row["state_json"])
                if actor not in {s["controller_id"] for s in state["sides"].values()}:
                    raise ValueError("Это не твой бой.")
                flow = self._qte_load_locked("battle", token)
                if action == "qte":
                    if (
                        not flow
                        or flow["stages"][0]["actor"] != actor
                        or flow["stages"][0]["id"] != challenge_id
                    ):
                        raise ValueError("Мини-игра уже изменилась. Обнови бой.")
                    self._qte_complete_locked(flow, proof)
                else:
                    if row["revision"] != revision:
                        raise ValueError("Ход уже изменился. Обнови бой.")
                    if skill == "surrender":
                        if flow:
                            self._qte_delete_locked(flow)
                        self._arena_action_locked(
                            token, actor, revision, skill, _interactive=True
                        )
                    elif flow:
                        raise ValueError("Сначала заверши текущую мини-игру.")
                    elif state["sides"][state["active_side"]]["controller_id"] != actor:
                        raise ValueError("Сейчас ход соперника.")
                    elif skill == "potion":
                        self._arena_action_locked(
                            token, actor, revision, skill, _interactive=True
                        )
                    elif not self._qte_battle_begin_locked(row, skill):
                        self._arena_action_locked(
                            token, actor, revision, skill, _interactive=True
                        )
                    self._qte_battle_drive_locked(token)
            return self._arena_row_locked(token)

    async def arena_interactive_raid(
        self, token, actor, round_number, skill="", proof=None, challenge_id=None
    ):
        from arena_engine import validate_skill
        from arena_raid_engine import pair_state, BOSS_SKILLS

        async with self._lock:
            with self.connection:
                self._qte_expire_locked("raid", token)
                row = self._raid_row_locked(token)
                if row["status"] != "active":
                    raise ValueError("Рейд завершён.")
                data = json.loads(row["data_json"])
                player = data["players"].get(str(actor))
                if (
                    not player
                    or player.get("withdrawn")
                    or player["fighter"]["hp"] <= 0
                ):
                    raise ValueError("Ты не управляешь живым бойцом.")
                flow = self._qte_load_locked("raid", token, actor)
                if challenge_id:
                    if not flow or flow["stages"][0]["id"] != challenge_id:
                        raise ValueError("Мини-игра уже изменилась. Обнови рейд.")
                    self._qte_complete_locked(flow, proof)
                elif skill == "surrender":
                    if flow:
                        self._qte_delete_locked(flow)
                    self._arena_raid_action_locked(token, actor, round_number, skill)
                else:
                    if flow:
                        raise ValueError("Сначала заверши текущую мини-игру.")
                    if (
                        type(round_number) is not int
                        or round_number != data["round"]
                        or player["selected"] is not None
                    ):
                        raise ValueError("Раунд или выбранный навык уже изменился.")
                    if row["deadline"] <= time.time():
                        raise ValueError("Время выбора истекло.")
                    self._qte_snapshot_locked("raid", row, data)
                    stages = []
                    fighter = player["fighter"]
                    boss = data["boss"]
                    _, skills = self._fighter_catalog_locked()
                    used = (
                        None
                        if skill == "defend"
                        else validate_skill(
                            pair_state(fighter, boss), "a", skill, skills
                        )
                    )
                    if data["qte_modes"].get(str(actor)):
                        if used and used.hostile:
                            stages.append(
                                challenge("attack", fighter, boss, used, actor)
                            )
                        intent = data["intent"]
                        incoming = BOSS_SKILLS.get(intent.get("skill"))
                        if (
                            incoming
                            and incoming.hostile
                            and str(actor)
                            in [str(k) for k in intent.get("targets", [])]
                        ):
                            stages.append(
                                challenge("defense", boss, fighter, incoming, actor)
                            )
                    if stages:
                        flow = dict(
                            scope="raid",
                            token=token,
                            owner=actor,
                            actor=actor,
                            turn=data["round"],
                            skill=skill,
                            stages=stages,
                            result={},
                            guard_skill=data["intent"].get("skill"),
                        )
                        self._qte_save_locked(flow, True)
                    else:
                        self._arena_raid_action_locked(
                            token, actor, round_number, skill
                        )
            return self._raid_row_locked(token)
