"""Public epic scrolls and battle-local combo mechanics (also used by raids)."""

from dataclasses import replace
from arena_fingers import has_trait, negative_effect


def build_epic_catalog(Skill, PassiveSkill, effect):
    skills = (
        Skill("last_argument", "Последний аргумент", "universal", 10, "physical", 32, 95, 50, 4,
              rarity="epic", pierce=.50, tags=("universal_attack", "fourth_action"),
              description="Сокрушительный удар с четвёртого собственного действия. Игнорирует 50% защиты. Тип урона определяется большей атакой бойца."),
        Skill("unsubscribe", "Отмена подписки", "universal", 10, None, 0, 95, 20, 4,
              effects=(effect("unsubscribe", "dispel_buffs", 1),), rarity="epic",
              description="При попадании снимает все временные усиления врага. Не снимает врождённые пассивки и особые механики босса."),
        Skill("safe_house", "Я в домике", "universal", 10, None, 0, 100, 25, 4,
              effects=(effect("safe_house", "incoming_damage_multiplier", .65, 1, target="self"),), rarity="epic",
              description="До следующего собственного действия получает на 35% меньше прямого урона. Снижения урона перемножаются; кровотечение и самоурон не блокируются."),
        Skill("stress_test", "Проверка на прочность", "universal", 10, "physical", 16, 95, 30, 3,
              rarity="epic", tags=("universal_attack", "negative_combo"),
              description="+20% урона за каждый различный отрицательный эффект врага, максимум +100%. Не расходует эффекты. Тип урона определяется большей атакой бойца."),
        Skill("not_today", "Не сегодня", "universal", 10, None, 0, 100, 35, 5,
              effects=(effect("not_today_heal", "heal_pct", .20, target="self"),
                       effect("not_today_cleanse", "cleanse_one", 1, target="self")),
              rarity="epic", tags=("twice_per_battle",),
              description="Лечит 20% максимального HP и снимает один случайный временный дебафф. Два применения за бой, энергия не возвращается."),
        Skill("hands_off", "Руки прочь от клавиатуры", "universal", 10, None, 0, 95, 25, 4,
              effects=(effect("hands_off_accuracy", "accuracy_flat", -15, 2),
                       effect("hands_off_evasion", "evasion_flat", -10, 2)), rarity="epic",
              description="На два действия врага снижает точность на 15 и уклонение на 10 процентных пунктов. Повтор обновляет эффекты, но не складывает их."),
    )
    passives = (
        PassiveSkill("second_wind", "Второе дыхание", (dict(effect("second_wind", "epic_second_wind", 40, target="self"),
            description="После действия при HP ≤30% возвращает 40 энергии один раз за бой. Не спасает от смертельного урона."),), "epic"),
        PassiveSkill("plan_b", "План Б", (dict(effect("plan_b", "epic_plan_b", 1, target="self"),
            description="После промаха или уклонения врага следующая атака получает +25 точности и +30% урона. Не складывается; расходуется при попытке атаки."),), "epic"),
        PassiveSkill("fine_print", "Мелкий шрифт", (dict(effect("fine_print", "epic_fine_print", 1, target="self"),
            description="После четвёртого собственного действия снимает один случайный временный дебафф. Один раз за бой; если дебаффов нет, ждёт их появления."),), "epic"),
        PassiveSkill("nothing_to_lose", "Мне уже нечего терять", (dict(effect("nothing_to_lose", "epic_desperation", .50, target="self"),
            description="При HP ≤35% наносит на 50% больше урона, без штрафа к защите. После лечения выше порога бонус отключается."),), "epic"),
    )
    return {s.skill_id: s for s in skills}, {p.skill_id: p for p in passives}


def adaptive_skill(skill, actor, effective_stat):
    if "universal_attack" not in skill.tags:
        return skill
    kind = "magic" if effective_stat(actor, "magic_attack") > effective_stat(actor, "physical_attack") else "physical"
    return replace(skill, damage_type=kind) if skill.damage_type != kind else skill


def epic_modifiers(actor, target, skill):
    memory = actor.get("epic_state", {})
    accuracy, multiplier = 0, 1.0
    if skill.damage_type:
        if has_trait(actor, "epic_desperation") and 0 < actor["hp"] <= actor["stats"]["max_hp"] * .35:
            multiplier *= 1.50
        if has_trait(actor, "epic_plan_b") and memory.get("plan_b_ready"):
            accuracy += 25
            multiplier *= 1.30
        if "negative_combo" in skill.tags:
            multiplier *= 1 + .20 * min(5, len({e["kind"] for e in target["effects"] if temporary_debuff(e)}))
    return accuracy, multiplier


def temporary_buff(e):
    if not 0 < e.get("duration", 0) < 10000:
        return False
    kind, value = e.get("kind"), e.get("value", 0)
    if kind in {"prepared_attack", "rpg_counter", "rpg_parry", "family_cover"}:
        return True
    if kind == "incoming_damage_multiplier":
        return 0 < value < 1
    if kind == "final_damage_multiplier":
        return value > 1
    if kind == "damage_taken_pct":
        return value < 0
    return value > 0 and kind in {
        "accuracy_flat", "evasion_flat", "damage_pct", "speed_pct", "speed_flat",
        "physical_attack_pct", "magic_attack_pct", "physical_attack_flat", "magic_attack_flat",
        "physical_defense_pct", "magic_defense_pct", "physical_defense_flat", "magic_defense_flat",
        "next_magic_damage", "next_physical_damage",
    }


def temporary_debuff(e):
    if not 0 < e.get("duration", 0) < 10000:
        return False
    if e['kind']=='burn':
        return e.get('value',0)>0
    if e["kind"] == "damage_taken_pct":
        return e.get("value", 0) > 0
    if e["kind"] == "incoming_damage_multiplier":
        return e.get("value", 1) > 1
    if e["kind"] == "final_damage_multiplier":
        return 0 < e.get("value", 1) < 1
    return negative_effect(e)


def cleanse_one(side, rng):
    choices = [e for e in side["effects"] if temporary_debuff(e)]
    if not choices:
        return False
    chosen = rng.choice(choices)
    side["effects"] = [e for e in side["effects"] if e is not chosen]
    return True


def epic_after_action(actor, target, skill, hit, rng):
    memory = actor.setdefault("epic_state", {})
    memory["actions"] = memory.get("actions", 0) + 1
    if "twice_per_battle" in skill.tags:
        uses = memory.setdefault("skill_uses", {})
        uses[skill.skill_id] = uses.get(skill.skill_id, 0) + 1
    if skill.damage_type:
        memory["plan_b_ready"] = bool(has_trait(actor, "epic_plan_b") and not hit)
    notes = []
    for side in (actor, target):
        saved = side.setdefault("epic_state", {})
        if side["hp"] <= 0:
            continue
        if has_trait(side, "epic_second_wind") and not saved.get("second_wind_used") and side["hp"] <= side["stats"]["max_hp"] * .30:
            gain = min(40, max(0, side["stats"]["resource_max"] - side["resource"]))
            side["resource"] += gain
            saved["second_wind_used"] = True
            notes.append(("Второе дыхание" if side is actor else "Второе дыхание врага") + f": +{gain} энергии")
        if has_trait(side, "epic_fine_print") and not saved.get("fine_print_used") and saved.get("actions", 0) >= 4 and cleanse_one(side, rng):
            saved["fine_print_used"] = True
            notes.append("Мелкий шрифт: дебафф снят" if side is actor else "Мелкий шрифт врага: дебафф снят")
    return notes
