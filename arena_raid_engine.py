"""One-to-three-player PvE rounds. Native skills share the combat resolver."""

from copy import deepcopy
import random
import math

from arena_engine import (
    Skill,
    create_battle_state,
    effective_stat,
    effective_skill,
    resolve_skill,
    restore_turn_resource,
    _tick,
    bleeding_damage,
    stats_for,
    MAX_FIGHTER_LEVEL,
)
from arena_doof import DOOF_SKILLS, set_doof_intent, resolve_doof_action
from arena_kit import (KIT_LEVEL, KIT_STATS, KIT_SKILLS, set_kit_intent,
                       resolve_kit_action, kit_prepare_action, kit_finish_action,
                       kit_react, kit_defend)
from arena_whaler import WHALER_SKILLS, WHALER_LEVEL
from arena_chaplain import CHAPLAIN_LEVEL, CHAPLAIN_SKILLS

RAID_SIZE = 3
RAID_ROUND_SECONDS = 120
RAID_MAX_ROUNDS = 100
BOSS_NAME = "Железный сборщик"
BOSSES = {
    'chaplain': dict(name='Капеллан — Хранитель последней редакции',
                      sprite='/static/assets/chaplain.png', skills=tuple(CHAPLAIN_SKILLS),
                      recommended_level=20, min_level=1, fixed_level=CHAPLAIN_LEVEL,
                      phase_count=4, phase_sprites={'1': '/static/assets/chaplain.png',
                          '2': '/static/assets/chaplain.png', '3': '/static/assets/chaplain_phase_three.png',
                          '4': '/static/assets/chaplain_phase_four.png'},
                      difficulty='Разрыв регламента', loot_skill='last_amendment'),
    'whaler': dict(name='Китобой — Чумной ловчий', sprite='/static/assets/whaler.png',
                   skills=tuple(WHALER_SKILLS), recommended_level=20, min_level=20,
                   fixed_level=WHALER_LEVEL, difficulty='Чумной рейд', loot_skill='swamp_miasma'),
    'kit': dict(name='Кит — Ангел чёрного солнца', sprite='/static/assets/kit.png',
                phase_sprites={'1': '/static/assets/kit.png',
                               '2': '/static/assets/kit_phase_two.png',
                               '3': '/static/assets/kit_phase_three.png'},
                skills=tuple(KIT_SKILLS), recommended_level=20, fixed_level=KIT_LEVEL,
                phase_count=3, difficulty='Кошмар', loot_skill='solar_eclipse'),
    "doofenshmirtz": dict(
        name="Фуфелшмерц — Злоба-инкорпорейтед",
        sprite="/static/assets/doofenshmirtz.png",
        ally_sprite="/static/assets/perry.png",
        skills=tuple(DOOF_SKILLS),
        recommended_level=18,
        loot_skill="deportator_inator",
    ),
    "iron": dict(name=BOSS_NAME, skills=("raid_sweep", "raid_crush", "raid_rampage")),
    "lei_heng": dict(
        name="Лей Хенг — Охотник на тигров",
        sprite="/static/assets/lei_heng.png",
        skills=("lei_double_slash", "lei_explosive_slash", "lei_perfected_flurry"),
        recommended_level=18,
        loot_skill="tigerslayer_flurry",
    ),
}
BOSS_SKILLS = {
    s.skill_id: s
    for s in (
        Skill("raid_sweep", "Размах цепью", "middle", 1, "physical", 8, 95, 0, 0),
        Skill("raid_crush", "Дробящий удар", "middle", 1, "physical", 17, 95, 0, 0),
        Skill("raid_rampage", "Яростный размах", "middle", 1, "physical", 10, 95, 0, 0),
        Skill(
            "lei_double_slash", "Двойной разрез", "middle", 1, "physical", 17, 95, 0, 0
        ),
        Skill(
            "lei_explosive_slash",
            "Взрывной разрез",
            "middle",
            1,
            "physical",
            8,
            95,
            0,
            0,
        ),
        Skill(
            "lei_perfected_flurry",
            "Совершенная поступь тигробоя",
            "middle",
            1,
            "physical",
            32,
            95,
            0,
            0,
            tags=("six_strike",),
        ),
    )
}
BOSS_SKILLS.update(DOOF_SKILLS)
BOSS_SKILLS.update(KIT_SKILLS)
BOSS_SKILLS.update(WHALER_SKILLS)
BOSS_SKILLS.update(CHAPLAIN_SKILLS)


def raid_boss_sprite(boss_id, phase=1):
    """Presentation only; legacy saved raids receive phase art on the next read."""
    boss = BOSSES.get(boss_id, BOSSES['iron'])
    return boss.get('phase_sprites', {}).get(str(phase), boss.get('sprite', ''))


def alive_players(data):
    return {
        k: p
        for k, p in data["players"].items()
        if not p.get("withdrawn") and p["fighter"]["hp"] > 0
    }


def pair_state(actor, target):
    return dict(
        sides={"a": actor, "b": target},
        active_side="a",
        turn=1,
        log=[],
        finished=False,
        winner=None,
    )


def native_attack(actor, target, skill_id, skills, rng, *, tick_actor_bleed=True, allies=None, raid_context=None):
    qte={}
    attack=actor.pop('_qte_attack',None)
    if attack is not None:qte['attack']=attack
    pattern_attack=actor.pop('_qte_pattern_attack',None)
    if pattern_attack is not None:qte['pattern_attack']=pattern_attack
    guard=target.get('_qte_guard')
    if guard and raid_context and raid_context.get('_qte_boss_phase') and guard.get('skill')==raid_context.get('intent',{}).get('skill'):
        qte['dodge']=guard['dodge']
        if 'pattern_dodge' in guard:
            result=deepcopy(guard['pattern_dodge'])
            subskills=guard.get('subskills')
            if subskills:
                if skill_id in subskills:
                    group=subskills.index(skill_id)
                    result['contacts']=[dict(c,strike=0) for c in result['contacts'] if c['strike']==group]
                    qte['dodge']=[guard['dodge'][group]]
                else:
                    result=None
                    qte.pop('dodge',None)
            if result is not None:qte['pattern_dodge']=result
    return resolve_skill(
        pair_state(actor, target),
        "a",
        skill_id,
        skills,
        rng,
        advance_turn=False,
        tick_actor_bleed=tick_actor_bleed,
        allies=allies,
        raid_context=raid_context,
        qte=qte or None,
    )


def set_intent(data):
    living = alive_players(data)
    if not living:
        return
    boss = data["boss"]
    boss["is_boss"] = True
    if data.get('boss_id') == 'chaplain':
        from arena_chaplain import set_intent as chaplain_intent
        chaplain_intent(data)
        return
    if data.get('boss_id') == 'whaler':
        from arena_whaler import set_intent as whaler_intent
        whaler_intent(data)
        return
    if data.get('boss_id') == 'kit':
        set_kit_intent(data)
        return
    phase = 2 if boss["hp"] <= boss["stats"]["max_hp"] // 2 else 1
    data["phase"] = phase
    if data.get("boss_id") == "doofenshmirtz":
        set_doof_intent(data)
        return
    pattern = (data["round"] - 1) % 3
    for player in data["players"].values():
        fighter = player["fighter"]
        fighter["effects"] = [
            e for e in fighter["effects"] if e.get("id") != "lei_prey"
        ]
    if data.get("boss_id", "iron") == "lei_heng":
        keys = list(living)
        target = keys[((data["round"] - 1) // 3) % len(keys)]
        if pattern == 2:
            living[target]["fighter"]["effects"].append(
                dict(
                    id="lei_prey",
                    kind="raid_prey",
                    value=1,
                    duration=1,
                    name="Добыча",
                    description="Цель поступи тигробоя. Защита снижает урон этой атаки на 60%.",
                )
            )
        data["intent"] = dict(
            kind="attack",
            phase=phase,
            skill=("lei_explosive_slash", "lei_double_slash", "lei_perfected_flurry")[
                pattern
            ],
            targets=keys if pattern == 0 else [target],
            text=(
                "Готовит взрывной разрез по всему отряду.",
                "Готовит двойной разрез по отмеченному бойцу.",
                "Добыча отмечена: готовит поступь тигробоя. Защищайтесь: −60% урона атаки!",
            )[pattern],
        )
        return
    if pattern == 0:
        intent = dict(
            kind="attack",
            skill="raid_rampage" if phase == 2 else "raid_sweep",
            targets=list(living),
            text="Готовит удар цепью по всему отряду.",
        )
    elif pattern == 1:
        keys = list(living)
        target = keys[(data["round"] // 3) % len(keys)]
        intent = dict(
            kind="attack",
            skill="raid_crush",
            targets=[target],
            text="Готовит дробящий удар по отмеченному бойцу.",
        )
    else:
        intent = dict(
            kind="shield",
            targets=[],
            text="Поднимет щит: обе защиты +30% на два раунда.",
        )
    # Phase is announced before choices; crossing 50% during this round cannot
    # silently strengthen the already announced attack.
    intent["phase"] = phase
    data["intent"] = intent


AVAILABLE_BOSSES = ("lei_heng", "doofenshmirtz", "kit", "whaler", "chaplain")


def raid_boss_level(levels):
    levels = [max(1, min(MAX_FIGHTER_LEVEL, int(level))) for level in levels]
    if not levels:
        raise ValueError("Для рейда нужен хотя бы один боец.")
    return max(math.ceil(sum(levels) / len(levels)) + 2, max(levels) + 1)


def create_raid_state(participants, sources, classes, skills, boss_id="iron"):
    if boss_id not in BOSSES:
        raise ValueError("Неизвестный босс.")
    if not 1 <= len(participants) <= RAID_SIZE or len(sources) != len(participants):
        raise ValueError("Для старта нужны от одного до трёх участников и их бойцы.")
    level = (raid_boss_level([s["level"] for s in sources])
             if boss_id in AVAILABLE_BOSSES
             else min(20, round(sum(s["level"] for s in sources) / len(sources))))
    if boss_id == 'kit':
        level = KIT_LEVEL
    if boss_id == 'whaler':
        if any(s['level'] < 20 for s in sources):
            raise ValueError('Китобой доступен каждому участнику с 20 уровня.')
        level = WHALER_LEVEL
    if boss_id == 'chaplain':
        level = CHAPLAIN_LEVEL
    enemy = dict(
        slave_id=0,
        owner_id=0,
        class_id="nerd" if boss_id == "doofenshmirtz" else "middle",
        level=level,
        passive_details=[],
    )
    players = {}
    for p, source in zip(participants, sources):
        state = create_battle_state(source, enemy, classes=classes, skills=skills)
        players[str(p["actor_id"])] = dict(
            actor_id=p["actor_id"],
            fighter_id=p["fighter_id"],
            personal=bool(p["personal"]),
            slave_owner=p["slave_owner"],
            fighter=state["sides"]["a"],
            selected=None,
            manual_turns=0,
            missed=0,
            reward_blocked=False,
            withdrawn=False,
        )
    boss = state["sides"]["b"]
    boss["level"] = level
    boss["stats"] = stats_for(enemy["class_id"], level, classes=classes, boss=True)
    boss["stats"]["max_hp"] = max(
        1, round(sum(p["fighter"]["stats"]["max_hp"] for p in players.values()) * 1.4)
    )
    if boss_id == "doofenshmirtz":
        boss["stats"]["max_hp"] = round(boss["stats"]["max_hp"] * 1.05)
        boss["stats"]["magic_attack"] = round(boss["stats"]["magic_attack"] * 1.05, 2)
    if boss_id in AVAILABLE_BOSSES:
        boss["stats"]["max_hp"] = round(boss["stats"]["max_hp"] * 1.25)
        boss["raid_damage_multiplier"] = 1.15
    boss["hp"] = boss["stats"]["max_hp"]
    # Keep the boss's native evasion for the post-QTE server roll.
    for stat in ("physical_defense", "magic_defense"):
        boss["stats"][stat] *= 0.7
    boss["stats"]["physical_attack"] *= 0.85
    if boss_id == 'kit':
        # Fixed encounter: no player level, HP, party size or class enters these numbers.
        boss['stats'] = dict(KIT_STATS)
        boss['hp'] = KIT_STATS['max_hp']
        boss['resource'] = KIT_STATS['resource_max']
        boss['raid_damage_multiplier'] = 1.0
        boss['passive_details'] = [dict(name='Эхо-щиты', rarity='legendary', effects=[
            dict(kind='kit_echo_shields', value=.25, description='Первое успешное прямое атакующее действие отряда за раунд ослаблено на 25%. Эхо-взор также ослабляет предсказанную атаку; эти защиты не складываются. Питомцы, призывы и периодический урон не расходуют щит.')])]
    boss["loadout"] = list(BOSSES[boss_id]["skills"])
    if boss_id == 'whaler':
        boss['stats'] = dict(max_hp=600 + 300 * (len(players)-1), resource_max=100,
                             physical_attack=0, magic_attack=0, physical_defense=0,
                             magic_defense=0, evasion=5, speed=15, resource_regen=0)
        boss['hp'] = boss['stats']['max_hp']
        boss['raid_damage_multiplier'] = 1
    boss["name"] = BOSSES[boss_id]["name"]
    if boss_id == 'chaplain':
        boss['stats'].update(max_hp=720 + 360 * (len(participants) - 1),
                             physical_attack=14, magic_attack=18,
                             physical_defense=12, magic_defense=12, evasion=8, speed=12)
        boss.update(hp=boss['stats']['max_hp'], effects=[], raid_damage_multiplier=1.0)
    boss["mechanics"] = {}
    boss["is_boss"] = True
    data = dict(
        players=players,
        boss_id=boss_id,
        boss=boss,
        round=1,
        phase=1,
        log=[],
        result="",
        finished=False,
        won=False,
        rewards={},
        control_resistance=0,
        control_lock=0,
    )
    if boss_id == 'chaplain':
        from arena_chaplain import initialize
        initialize(data)
    set_intent(data)
    return data


def raid_snapshot(data):
    """Small detached visual state; never expose hidden action selections."""
    fighters = {"boss": data["boss"]} | {
        k: p["fighter"] for k, p in data["players"].items()
    }
    return {
        k: deepcopy(
            {
                field: f.get(field, {})
                for field in ("hp", "resource", "effects", "mechanics", "cooldowns", "epic_state", "rpg_state", "final_state", "mastery_state", "own_turns")
            }
        )
        for k, f in fighters.items()
    }


def log_event(data, actor, target, text, **extra):
    data["event_seq"] = data.get("event_seq", 0) + 1
    first = not data["log"] or data["log"][-1]["round"] != data["round"]
    data["log"].append(
        dict(
            round=data["round"],
            actor=actor,
            target=target,
            text=text,
            seq=data["event_seq"],
            after=raid_snapshot(data),
            **({"before": data.get("round_before") or raid_snapshot(data)} if first else {}),
            **extra,
        )
    )


def defend(fighter,opponent=None,raid_context=None):
    if opponent is not None:
        from arena_archclasses import obey_enemy_prescript
        from arena_finals import break_grip
        obey_enemy_prescript(fighter,None,opponent,raid_context)
        break_grip(fighter,opponent)
    _tick(fighter)
    fighter["effects"] = [
        e for e in fighter["effects"] if not e.get("id", "").startswith("raid_guard_")
    ]
    for dtype in ("physical", "magic"):
        fighter["effects"].append(
            dict(
                id="raid_guard_" + dtype,
                kind=dtype + "_defense_pct",
                value=0.35,
                duration=1,
                target="self",
            )
        )


def finish_if_needed(data):
    if data.get('boss_id') == 'chaplain' and not data.get('finished'):
        from arena_chaplain import intercept_end
        intercept_end(data)
    living = alive_players(data)
    if data["boss"]["hp"] <= 0 or not living:
        data["finished"] = True
        data["won"] = data["boss"]["hp"] <= 0 and bool(living)
        data["result"] = (
            "Босс повержен!" if data["won"] else "Отряд потерпел поражение."
        )
        if data["boss"]["hp"] <= 0 and not living:
            data["result"] = "Босс и отряд погибли. Ничья, без наград."
        return True
    return False


def resolve_round(data, skills, rng=None):
    if data["finished"]:
        raise ValueError("Рейд завершён.")
    rng = rng or random.SystemRandom()
    if data.get('whaler_reaction'):
        from arena_whaler import resume_reaction
        return resume_reaction(data, skills, rng)
    data["round_before"] = raid_snapshot(data)
    boss = data["boss"]
    boss["is_boss"] = True
    stunned = False
    living = alive_players(data)
    for player in living.values():
        result=player.pop('qte_result',{})
        if 'attack' in result:player['fighter']['_qte_attack']=result['attack']
        if 'dodge' in result:player['fighter']['_qte_guard']=dict(dodge=result['dodge'],skill=result.get('guard_skill'))
        if 'pattern_attack' in result:player['fighter']['_qte_pattern_attack']=result['pattern_attack']
        if 'pattern_dodge' in result:
            player['fighter']['_qte_guard'].update(pattern_dodge=result['pattern_dodge'],subskills=result.get('guard_subskills'))
    order = sorted(
        living, key=lambda k: (-effective_stat(living[k]["fighter"], "speed"), int(k))
    )
    for key in order:
        if finish_if_needed(data) or data.get('_chaplain_rewound'):
            break
        player = living[key]
        actor = player["fighter"]
        selected = player["selected"]
        if player.get("deported_round") == data["round"]:
            _tick(actor)
            log_event(data, key, key, "Депортация: боец вернётся в следующем раунде.")
            continue
        if selected is None:
            player["missed"] += 1
            player["reward_blocked"] |= player["missed"] >= 3
        else:
            player["manual_turns"] += 1
            player["missed"] = 0
        if any(e["kind"] == "stun" for e in actor["effects"]):
            _tick(actor)
            log_event(data, key, key, "Ошеломление: действие пропущено.")
            continue
        if data.get('boss_id') == 'chaplain' and isinstance(selected, str) and selected.startswith('chaplain_anchor:'):
            from arena_chaplain import anchor
            anchor(data, key, selected)
            continue
        if selected is None or selected == "defend":
            player["previous_skill"] = None
            if data.get('boss_id') == 'kit':
                kit_defend(data, key)
            defend(actor,boss,data)
            log_event(
                data,
                key,
                key,
                "Защита: обе защиты +35%."
                + (" Время выбора истекло." if selected is None else ""),
            )
            continue
        # Resource/cooldowns were validated at submission. Enemy disruption can
        # change the applicable variant before this fighter acts: do not charge
        # or execute an unaffordable ability, and never abort the whole round.
        prepared = None
        chaplain_before = None
        if data.get('boss_id') == 'chaplain':
            from arena_chaplain import action_before
            chaplain_before = action_before(data)
        try:
            if data.get('boss_id') == 'kit':
                prepared = kit_prepare_action(data, key, effective_skill(pair_state(actor, boss), 'a', selected, skills))
            event = native_attack(actor, boss, selected, skills, rng,
                                  allies=[p['fighter'] for p in data['players'].values()
                                          if not p.get('withdrawn') and not p.get('reward_blocked')],
                                  raid_context=data)
        except ValueError:
            if prepared:
                boss['effects'] = [e for e in boss['effects'] if e.get('id') != 'kit_action_shield']
                kit_defend(data, key)
            defend(actor,boss,data)
            log_event(data, key, key, "Навык недоступен после изменений в бою: защита.")
            continue
        if prepared:
            kit_finish_action(data, key, event, prepared)
        if data.get('boss_id') == 'chaplain':
            from arena_chaplain import marked_cost, record_action
            record_action(data, chaplain_before)
            marked_cost(data, key, selected)
        if data.get('boss_id') == 'whaler':
            data.setdefault('whaler_restored', {})[key] = event.get('deliberate_resource_restored', 0)
        log_event(
            data,
            key,
            "boss",
            event["text"],
            damage=event["damage"],
            self_damage=event["self_damage"],
            bleed_damage=event["bleed_damage"],
            skill=selected,
            damage_type=event["damage_type"],
            hit=event["hit"],
            critical=event["critical"],
            **({"hits": event["hits"]} if "hits" in event else {}),
            **({"hit_results": event["hit_results"]} if "hit_results" in event else {}),
        )
        if data.get("boss_id") == "doofenshmirtz":
            if (
                player.get("previous_skill") == selected
                and skills[selected].damage_type
            ):
                memory = boss.setdefault("mechanics", {})
                memory["two_coins"] = min(2, memory.get("two_coins", 0) + 1)
                log_event(
                    data,
                    "boss",
                    "boss",
                    "У меня было бы две монетки: следующий удар усилен на "
                    + str(10 * memory["two_coins"])
                    + "%.",
                )
            player["previous_skill"] = selected
        control = any(e["kind"] == "stun" for e in boss["effects"])
        boss["effects"] = [e for e in boss["effects"] if e["kind"] != "stun"]
        if control:
            chance = max(0.1, 1 - 0.25 * data["control_resistance"])
            accepted = (
                not data["control_lock"] and not stunned and rng.random() < chance
            )
            data["control_resistance"] = min(4, data["control_resistance"] + 1)
            if accepted:
                stunned = True
            else:
                log_event(data, "boss", "boss", "Босс сопротивляется ошеломлению.")
        if prepared and not stunned:
            kit_react(data, key, event, prepared, rng)
    if data.get('boss_id') == 'whaler' and not finish_if_needed(data):
        from arena_whaler import prepare_reaction
        if prepare_reaction(data, rng, stunned):
            if data.get('qte_modes', {}).get(data['whaler_reaction']['target']):
                return data
            from arena_whaler import resume_reaction
            return resume_reaction(data, skills, rng)
    return _finish_boss_round(data, skills, rng, stunned)


def _finish_boss_round(data, skills, rng, stunned, tick_whaler=True):
    boss, living = data['boss'], alive_players(data)
    if tick_whaler:
        from arena_plague import begin_turn
        poison = begin_turn(boss)
        if poison:
            log_event(data, 'boss', 'boss', f'Чума: −{poison} HP.', damage=poison)
    if data.get('boss_id') == 'chaplain':
        from arena_chaplain import transition
        transition(data)
    data['_qte_boss_phase']=True
    if not finish_if_needed(data) and not data.get('_chaplain_rewound') and not data.get('_chaplain_transitioned'):
        if stunned:
            from arena_archclasses import obey_enemy_prescript
            obey_enemy_prescript(boss,None,next(iter(living.values()))['fighter'],data)
            _tick(boss)
            data["control_lock"] = 2
            log_event(data, "boss", "boss", "Босс ошеломлён: намерение сорвано.")
        elif data.get("boss_id") == "doofenshmirtz":
            resolve_doof_action(data, rng)
            data["control_lock"] = max(0, data["control_lock"] - 1)
        elif data.get('boss_id') == 'kit':
            resolve_kit_action(data, rng)
            data['control_lock'] = max(0, data['control_lock'] - 1)
        elif data.get('boss_id') == 'whaler':
            from arena_whaler import resolve_action
            resolve_action(data, rng)
            data['control_lock'] = max(0, data['control_lock'] - 1)
        elif data.get('boss_id') == 'chaplain' and data['intent']['kind'] == 'chaplain_rewind':
            from arena_chaplain import rewind
            rewind(data)
        else:
            intent = data["intent"]
            if intent["kind"] == "shield":
                from arena_archclasses import obey_enemy_prescript
                from arena_finals import break_grip
                obey_enemy_prescript(boss,None,next(iter(living.values()))['fighter'],data)
                for p in living.values():break_grip(boss,p['fighter'])
                _tick(boss)
                boss["effects"] = [
                    e
                    for e in boss["effects"]
                    if not e.get("id", "").startswith("raid_shield_")
                ]
                for dtype in ("physical", "magic"):
                    boss["effects"].append(
                        dict(
                            id="raid_shield_" + dtype,
                            kind=dtype + "_defense_pct",
                            value=0.3,
                            duration=2,
                            target="self",
                        )
                    )
                log_event(
                    data,
                    "boss",
                    "boss",
                    "Босс поднял щит: обе защиты +30% на два раунда.",
                )
            else:
                targets = [k for k in intent["targets"] if k in alive_players(data)]
                if not targets:
                    targets = list(alive_players(data))[:1]
                # An area attack is one boss action, not three ticks of its buffs.
                original = deepcopy(boss)
                pending_bleed = bleeding_damage(original) + sum(max(0,int(e['value'])) for e in original['effects'] if e['kind']=='burn')
                boss_after = None
                for key in targets:
                    if boss['hp']<=0:
                        break
                    attacker = deepcopy(original)
                    attacker['hp']=boss['hp']
                    if intent["skill"] == "lei_perfected_flurry" and any(
                        e.get("id") == "raid_guard_physical"
                        for e in data["players"][key]["fighter"]["effects"]
                    ):
                        attacker["effects"].append(
                            dict(
                                id="lei_guard_reduction",
                                kind="final_damage_multiplier",
                                value=0.4,
                                duration=1,
                            )
                        )
                    if intent["phase"] == 2 and data.get('boss_id') != 'chaplain':
                        attacker["effects"].append(
                            dict(
                                id="raid_fury",
                                kind="damage_pct",
                                value=0.25,
                                duration=1,
                            )
                        )
                    event = native_attack(
                        attacker,
                        data["players"][key]["fighter"],
                        intent["skill"],
                        BOSS_SKILLS,
                        rng,
                        tick_actor_bleed=False,
                        raid_context=data,
                    )
                    if boss_after is None:
                        boss_after = attacker
                    boss['hp']=max(0,boss['hp']-event.get('reaction_damage',0))
                    boss_after['hp']=boss['hp']
                    log_event(
                        data,
                        "boss",
                        key,
                        event["text"],
                        damage=event["damage"],
                        skill=intent["skill"],
                        damage_type=event["damage_type"],
                        hit=event["hit"],
                        critical=event["critical"],
                        **({"hits": event["hits"]} if "hits" in event else {}),
                        **({"hit_results": event["hit_results"]} if "hit_results" in event else {}),
                    )
                if boss_after is not None:
                    boss.clear()
                    boss.update(boss_after)
                else:
                    _tick(boss)
                if boss_after is not None and pending_bleed:
                    dot = min(boss["hp"], pending_bleed)
                    boss["hp"] -= dot
                    log_event(
                        data, "boss", "boss", f"Кровотечение / горение: −{dot} HP.", damage=dot
                    )
                if intent["skill"] == "lei_perfected_flurry" and targets:
                    boss["effects"].append(
                        dict(
                            id="lei_overheat",
                            kind="damage_taken_pct",
                            value=0.25,
                            duration=1,
                            name="Перегрев",
                            description="Получает на 25% больше урона до следующего действия босса.",
                        )
                    )
                    log_event(
                        data,
                        "boss",
                        "boss",
                        "Перегрев: босс получает на 25% больше урона в следующем раунде.",
                    )
            data["control_lock"] = max(0, data["control_lock"] - 1)
    if not data['finished'] and boss.get('mechanics',{}).get('enemy_prescript'):
        # Dialogues, phase utilities and other non-native boss actions also
        # consume an order. Native attacks already popped it, including AoE.
        from arena_archclasses import obey_enemy_prescript
        note=obey_enemy_prescript(boss,None,next(iter(data['players'].values()))['fighter'],data)
        if note:log_event(data,'boss','boss',note)
    if not finish_if_needed(data) and data["round"] >= RAID_MAX_ROUNDS:
        data.update(
            finished=True,
            won=False,
            result=f"Босс ушёл: достигнут предел {RAID_MAX_ROUNDS} раундов. Без наград.",
        )
    data.pop('_qte_boss_phase',None)
    for player in data['players'].values():
        player['fighter'].pop('_qte_attack',None)
        player['fighter'].pop('_qte_pattern_attack',None)
        player['fighter'].pop('_qte_guard',None)
    data["log"] = data["log"][-80:]
    data.pop("round_before", None)
    if not data["finished"]:
        data["round"] += 1
        # Start-of-turn plague can be the first event of the new round, before
        # resolve_round has captured its action snapshot. Keep its own pre-tick
        # snapshot so logging and saving cannot roll back the completed round.
        data['round_before'] = raid_snapshot(data)
        for player in data["players"].values():
            player["selected"] = None
            if not player.get("withdrawn"):
                from arena_plague import begin_turn
                poison = begin_turn(player['fighter'])
                if poison:
                    log_event(data, str(player['actor_id']), str(player['actor_id']), f'Чума: −{poison} HP.', damage=poison)
                gain = restore_turn_resource(player["fighter"])
                if gain and data["log"]:
                    event = data["log"][-1]
                    key = str(player["actor_id"])
                    event.setdefault("resource_regen", {})[key] = gain
                    event["after"][key]["resource"] = player["fighter"]["resource"]
        data.pop('round_before', None)
        if not finish_if_needed(data):
            set_intent(data)
    data.pop('_chaplain_rewound', None)
    data.pop('_chaplain_transitioned', None)
    if data.get('boss_id') == 'whaler' and data.get('won'):
        data['dialogue'] = dict(speaker='КИТОБОЙ', text='Агх… Вы сильнее Кита. Хотя я не один там был… Встретимся во время чумы.', warning='', persistent=True)
    return data
