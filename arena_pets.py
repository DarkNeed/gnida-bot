"""Pet catalog and bounded, action-level companions. No payment or DB code."""
from copy import deepcopy

PET_MAX_LEVEL = 10
PET_MILESTONES = (3, 6, 10)
PET_ODDS = {"common": 20, "rare": 50, "epic": 27, "legendary": 3}
PET_PACKS = {"one": (1, 25), "five": (5, 110), "ten": (10, 200)}
PET_TERMS_VERSION = "pets-2026-10-12-v1"
PETS = {}
for key, name, rarity, effect in (
    ("boykisser", "Бойкиссер", "rare", "После нескольких атак возвращает энергию; ослабления помогают."),
    ("dakimakura", "Мимик-дакимакура", "epic", "Периодически защищает от следующего удара; защитные навыки ускоряют подготовку."),
    ("gachi_duck", "Гачи-уточка", "rare", "Готовит пробитие физической и магической защиты; поддержка ускоряет заряд."),
    ("sandwich", "Живой сэндвич", "common", "Один раз за бой лечит живого хозяина при HP не выше 30%."),
    ("bonzi", "BonziBuddy", "epic", "Попадания готовят кражу энергии; навыки похищения усиливают её."),
    ("bug", "Жук-баг", "rare", "Сокращает другую перезарядку, а если сокращать нечего — возвращает энергию."),
    ("rat", "Крыса-консильери", "epic", "Чередование навыков готовит усиление следующей атаки."),
    ("pigeon", "Голубь-инкассатор", "rare", "Готовит точность следующей атаки; восстановление энергии ускоряет доставку."),
    ("printer", "Говорящий принтер", "rare", "Исполнение выполнимого поручения возвращает немного энергии."),
    ("clippy", "Клиппи", "epic", "После промаха готовит точность; неудавшееся ослабление частично возвращает энергию."),
    ("hamster", "Хомяк-коллектор", "rare", "После промаха следующая атака получает пробитие."),
    ("chao", "Мстительный Чао", "epic", "Входящие атаки заряжают защиту при низком HP. Самоурон не заряжает её."),
    ("smesharik", "Кровавый Смешарик", "rare", "Попадания собирают краску для слабого кровотечения; родное кровотечение помогает."),
    ("taxidermy", "Таксидермический пёс", "epic", "Периодически ослабляет обе защиты; расход ослаблений ускоряет помощь."),
    ("poro", "Звёздный Пору", "epic", "Готовит скидку следующему платному навыку; чередование цен и расход зарядов помогают."),
    ("moon_mimic", "Лунный мимик", "legendary", "Траты энергии постепенно готовят небольшой щит."),
):
    PETS[key] = dict(id=key, name=name, rarity=rarity, description=effect,
                     sprite_url=f"/static/assets/pets/{key}.png", max_level=PET_MAX_LEVEL)


def pet_snapshot(value):
    if not isinstance(value, dict) or value.get("id") not in PETS:
        return None
    level = max(1, min(10, int(value.get("level", 1))))
    points = sum(level >= milestone for milestone in PET_MILESTONES)
    power = max(0, min(points, int(value.get("power", 0))))
    tempo = max(0, min(points - power, int(value.get("tempo", 0))))
    return dict(PETS[value["id"]], level=level, power=power, tempo=tempo)


def _pet(side):
    pet = side.get("pet")
    # Frequency never becomes every-action spam; surplus tempo strengthens the proc.
    return dict(pet, power=pet["power"] + .1 * (pet["level"] - 1) + .3 * max(0, pet["tempo"]-2)) if pet and pet.get("id") in PETS else None


def _memory(side):
    return side.setdefault("pet_state", {})


def _period(pet, base=4):
    return max(2, base - pet["tempo"])


def pet_cost(side, skill, base_cost):
    pet = _pet(side)
    if pet and pet["id"] == "poro" and side.get("pet_state", {}).get("ready") and base_cost > 0:
        return max(1, base_cost - round(4 + 2 * pet["power"]))
    return base_cost


def pet_modifiers(actor, skill):
    pet = _pet(actor)
    if not pet or not skill.damage_type or not actor.get("pet_state", {}).get("ready"):
        return 0, 0, 0
    key, power = pet["id"], pet["power"]
    if key in {"pigeon", "clippy"}:
        return 5 + 2 * power, 0, 0
    if key in {"gachi_duck", "hamster"}:
        return (pet["tempo"] if key == "hamster" else 0), 0, .06 + .02 * power
    if key == "rat":
        return 0, .05 + .015 * power, 0
    return 0, 0, 0


def pet_before_action(actor, target, skill, cost=None):
    context = dict(resource=actor["resource"], negatives=_negatives(target),
                   charges={k: actor.get("mechanics", {}).get(k, 0) for k in ("grudge", "focus", "order")})
    pet = _pet(actor)
    if pet:
        memory = _memory(actor)
        if memory.get("ready") and (
            skill.damage_type and pet["id"] in {"pigeon", "clippy", "gachi_duck", "hamster", "rat"}
            or (skill.cost if cost is None else cost) > 0 and pet["id"] == "poro"
        ):
            memory["ready"] = False
    return context


def _negatives(side):
    return {e.get("kind") for e in side["effects"] if not e.get("pet")
            and (e.get("value", 0) < 0 or e.get("kind") in {"bleed", "stun"})}


def _effect(side, key, kind, value, duration=2, consume=False):
    side["effects"] = [e for e in side["effects"] if e.get("id") != key]
    side["effects"].append(dict(id=key, kind=kind, value=value, duration=duration,
                                pet=True, consume_on_hit=consume))
    if key == "pet_guard":
        side["effects"][-1].update(name="Защита питомца",
            description=f"Получаемый урон −{round(abs(value)*100)}% до следующего попадания (не дольше {duration} действий).")


def _refund(side, amount):
    actual = min(max(0, int(amount)), side["stats"]["resource_max"] - side["resource"])
    side["resource"] += actual
    return actual


def _shield(side, pet):
    _effect(side, "pet_guard", "damage_taken_pct", -(.08 + .02 * pet["power"]), 3, True)


def _sandwich(side):
    pet = _pet(side)
    if not pet or pet["id"] != "sandwich" or _memory(side).get("used"):
        return []
    if not 0 < side["hp"] <= side["stats"]["max_hp"] * (.30 + .05 * pet["tempo"]):
        return []
    healed = min(side["stats"]["max_hp"] - side["hp"],
                 max(1, round(side["stats"]["max_hp"] * (.08 + .02 * pet["power"]))))
    side["hp"] += healed
    _memory(side)["used"] = True
    return [f"{pet['name']}: +{healed} HP"]


def pet_after_action(actor, target, skill, hit, damage, cost, context, applied, skills):
    """One call per paid/native action, never recursive and never per sub-hit."""
    notes = []
    if damage and target["hp"] > 0:
        notes.extend(_sandwich(target))
        defender = _pet(target)
        if defender and defender["id"] == "chao":
            memory = _memory(target)
            memory["incoming"] = min(3, memory.get("incoming", 0) + 1)
            if memory["incoming"] >= _period(defender, 3) and target["hp"] <= target["stats"]["max_hp"] * (.4 + .05 * defender["tempo"]):
                memory["incoming"] = 0
                _shield(target, defender)
                notes.append("Мстительный Чао: защита следующего удара")
    if actor["hp"] <= 0:
        return notes
    notes.extend(_sandwich(actor))
    pet = _pet(actor)
    if not pet:
        return notes
    key, power = pet["id"], pet["power"]
    m = _memory(actor)
    m["steps"] = m.get("steps", 0) + 1
    m["cooldown"] = max(0, m.get("cooldown", 0) - 1)
    charge = m.get("charge", 0)
    negative_added = bool(_negatives(target) - context["negatives"])
    restored = actor["resource"] > context["resource"] - cost
    ready_note = ""
    if key == "boykisser" and skill.damage_type:
        charge += 1
        if charge >= _period(pet):
            charge = 0
            amount = _refund(actor, 3 + power + int(negative_added))
            if amount: notes.append(f"Бойкиссер: +{amount} энергии")
    elif key == "dakimakura":
        charge += 1 + int(not skill.hostile and bool(skill.effects))
        if charge >= _period(pet, 5):
            charge = 0; _shield(actor, pet); notes.append("Мимик-дакимакура: защита следующего удара")
    elif key == "gachi_duck":
        charge += 1 + int(not skill.damage_type)
        if charge >= _period(pet, 5): charge = 0; m["ready"] = True; ready_note = "пробитие готово"
    elif key == "bonzi" and damage:
        charge += 1
        if charge >= _period(pet):
            charge = 0
            extra = int(any(e["kind"] == "resource_leech" for e in skill.effects))
            stolen = min(target["resource"], round(2 + power + extra))
            target["resource"] -= stolen
            returned = _refund(actor, (stolen + 1) // 2)
            if stolen: notes.append(f"BonziBuddy: −{stolen} энергии цели, +{returned} хозяину")
    elif key == "bug" and not m["cooldown"]:
        charge += 1
        if charge >= _period(pet):
            charge = 0; m["cooldown"] = 2
            choices = [k for k, v in actor["cooldowns"].items() if k != skill.skill_id and v > 0]
            if choices:
                chosen = max(choices, key=lambda k: (actor["cooldowns"][k], k))
                actor["cooldowns"][chosen] = max(0, actor["cooldowns"][chosen] - (1 + int(power >= 2)))
                notes.append("Жук-баг: другая перезарядка сокращена")
            else:
                amount = _refund(actor, 2 + power)
                if amount: notes.append(f"Жук-баг: +{amount} энергии")
    elif key == "rat":
        charge = charge + 1 if m.get("last_skill") != skill.skill_id else 0
        if charge >= _period(pet): charge = 0; m["ready"] = True; ready_note = "усиление готово"
    elif key == "pigeon":
        charge += 1 + int(restored)
        if charge >= _period(pet, 5): charge = 0; m["ready"] = True; ready_note = "точность готова"
    elif key == "printer":
        def classify(s):
            return "attack" if s.damage_type else "restore" if any(e["kind"] == "resource" and e["value"] > 0 and e.get("target") == "self" for e in s.effects) else "support"
        available = [skills[k] for k in actor["loadout"] if k in skills
                     and skills[k].cost <= actor["resource"] and not actor["cooldowns"].get(k, 0)
                     and not ("once_per_battle" in skills[k].tags and k in actor.get("used_skills", []))]
        tasks = ["attack"] + [kind for kind in ("restore", "support") if any(classify(s) == kind for s in available)]
        task = m.get("task", "attack")
        if task not in tasks:
            task = m["task"] = "attack"
        kind = classify(skill)
        if task == kind and not m["cooldown"]:
            amount = _refund(actor, 2 + power)
            m["cooldown"] = _period(pet, 3)
            if amount: notes.append(f"Говорящий принтер: поручение исполнено, +{amount} энергии")
            m["task"] = tasks[(tasks.index(kind) + 1) % len(tasks)] if kind in tasks else "attack"
    elif key == "clippy" and not m["cooldown"]:
        if skill.damage_type and not hit:
            m["ready"] = True; m["cooldown"] = _period(pet, 3); ready_note = "помощь с точностью готова"
        elif hit and any(e.get("target") == "enemy" and e.get("chance", 1) < 1 for e in skill.effects) and not applied:
            amount = _refund(actor, 2 + power); m["cooldown"] = _period(pet, 3)
            if amount: notes.append(f"Клиппи: +{amount} энергии за неудавшийся эффект")
    elif key == "hamster" and skill.damage_type and not hit:
        m["ready"] = True; ready_note = "должник отмечен: пробитие готово"
    elif key == "smesharik" and damage and target["hp"] > 0 and not m["cooldown"]:
        charge += 1 + int("bleed" in _negatives(target))
        if charge >= _period(pet, 5):
            charge = 0; m["cooldown"] = 3
            _effect(target, "pet_paint", "bleed", 1 + int(power >= 2), 2 + int(power >= 3))
            notes.append("Кровавый Смешарик: кровотечение")
    elif key == "taxidermy" and target["hp"] > 0 and not m["cooldown"]:
        charge += 1 + int(hit and bool(context["negatives"] - _negatives(target)))
        if charge >= _period(pet, 5):
            charge = 0; m["cooldown"] = 3
            for kind in ("physical_defense_pct", "magic_defense_pct"):
                _effect(target, "pet_dog_" + kind, kind, -(.04 + .01 * power), 2)
            notes.append("Таксидермический пёс: обе защиты цели снижены")
    elif key == "poro" and cost > 0:
        previous = m.get("last_cost", cost)
        spent_charge = any(actor.get("mechanics", {}).get(k, 0) < v for k, v in context["charges"].items())
        charge += 1 + int((previous >= 20) != (cost >= 20) or spent_charge)
        m["last_cost"] = cost
        if charge >= _period(pet, 5): charge = 0; m["ready"] = True; ready_note = "скидка следующему платному навыку"
    elif key == "moon_mimic":
        charge += cost
        if charge >= max(40, 80 - 15 * pet["tempo"]):
            charge = 0; _shield(actor, pet); notes.append("Лунный мимик: защита следующего удара")
    m["last_skill"] = skill.skill_id
    m["charge"] = charge
    if ready_note: notes.append(pet["name"] + ": " + ready_note)
    return notes


def pet_status(side):
    if not _pet(side): return None
    return dict(pet=deepcopy(side["pet"]), pet_state=deepcopy(side.get("pet_state", {})))
