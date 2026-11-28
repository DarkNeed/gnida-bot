"""Cult of the Ancients: native skills and encounter-local pact mechanics."""

CLASS_ID = "cultist"
CAP = 3
WHISPER = "cult_depth_whisper"
YELLOW = "cult_yellow_sign"
SEAL = "cult_blasphemy"
GATE = "cult_gate_open"

# Name, patron passive, description.
PATRONS = {
    "cultist_cthulhu": (
        "Ктулху", "Спящий в Р’льехе",
        "Попадания навыками Ктулху накладывают Шёпот глубин: следующий каст цели на 18% дольше. Уже начатые касты не меняются.",
    ),
    "cultist_yog": (
        "Йог-Сотот", "Ключ и врата",
        "Неподвижный Ключ открывает вход на три собственных действия. Успешные «Сходящиеся сферы» закрывают пару врат и возвращают 8 энергии. Промах не закрывает вход.",
    ),
    "cultist_shub": (
        "Шуб-Нигуррат", "Тысяча молодых",
        "Один отпрыск поглощает часть прямого урона из собственного запаса HP. Попадания родными атаками растят его до III стадии и дают ему по 6 HP. После гибели нужны 4 своих действия до повторного призыва; новый отпрыск начинает рост с нуля.",
    ),
    "cultist_hastur": (
        "Хастур", "Пьеса без конца",
        "Под Жёлтым знаком вторая и последующие физические либо магические атаки подряд наносят на 18% меньше прямого урона. Другой тип атаки, поддержка или защита разрывают повтор.",
    ),
}

# The branch ID stays stable so saved skill loadouts and patron restrictions
# survive ascension. The form ID is distinct and also keys its battle sprite.
FORMS = {
    "cultist_cthulhu": {
        "id": "cultist_cthulhu_final", "name": "Звёздное отродье Р’льеха",
        "appearance": "Крылатое отродье с телом амфибии и венцом щупалец.",
        "passive": "Давление глубин",
        "description": "Шёпот глубин удлиняет следующий каст на 25% вместо 18%. Родные атаки наносят +10% урона цели под твоим Шёпотом.",
    },
    "cultist_yog": {
        "id": "cultist_yog_final", "name": "Дитя Врат",
        "appearance": "Клубок живых сфер и рёбер, зависший в разрыве пространства.",
        "passive": "Плоть порога",
        "description": "Неподвижный Ключ даёт 2 фанатизма вместо 1. Закрытие пары врат возвращает 12 маны вместо 8.",
    },
    "cultist_shub": {
        "id": "cultist_shub_final", "name": "Тёмное дитя Чёрного Козла",
        "appearance": "Копытный клубок чёрных корней с ветвистыми рогами.",
        "passive": "Бессмертные корни",
        "description": "Отпрыск появляется с 30 HP вместо 24. Минимальная задержка призыва после его гибели — 3 своих действия вместо 4; оставшаяся перезарядка не сбрасывается.",
    },
    "cultist_hastur": {
        "id": "cultist_hastur_final", "name": "Живая маска Каркозы",
        "appearance": "Старая фарфоровая маска и жёлтые лохмотья без тела под ними.",
        "passive": "Лицо стало ролью",
        "description": "Жёлтый знак держится 5 действий цели вместо 4. Штраф за повторение школы атаки — 25% вместо 18%.",
    },
}

SKILL_PATTERNS = {
    "cult_sign": "edict", "cult_voice": "void", "cult_rite": "death",
    "cult_depths": "beast", "arch_cultist_cthulhu": "beast",
    "arch_cultist_yog": "portal", "arch_cultist_hastur": "script",
    "cult_yellow": "mirror", "cult_roots": "beast",
}
PORTAL_SKILL = "arch_cultist_yog"


def branch_loadout(branch):
    first = {
        "cultist_cthulhu": "cult_depths", "cultist_yog": "cult_gate",
        "cultist_shub": "cult_brood", "cultist_hastur": "cult_yellow",
    }.get(branch)
    return ["cult_sign", "cult_voice", first, "arch_" + branch] if first else [
        "cult_sign", "cult_voice", "cult_rite",
    ]


def build_catalog(FighterClass, Skill, effect):
    stats = ("max_hp", "physical_attack", "magic_attack", "physical_defense",
             "magic_defense", "speed", "evasion")
    cls = FighterClass(CLASS_ID, "Культист Бездны", "Мана", 5,
        dict(zip(stats, (43, 5, 13, 7, 11, 10, 7))),
        dict(zip(stats, (4.3, .3, 1.45, .65, .9, .65, .30))),
        (
            dict(effect("cult_mind", "magic_defense_pct", .10, target="self"),
                 name="Закалённый разум", description="Магическая защита +10%."),
            dict(effect("cult_litany", "accuracy_flat", 4, target="self"),
                 name="Выученная литания", description="Точность +4."),
        ), "uncommon")

    def s(key, name, level, power, mana, cd, time, desc, *, branch="", tags=(), pierce=None):
        full_tags = ("cultist", *tags, *(("archclass:" + branch,) if branch else ()))
        return Skill(key, name, CLASS_ID, level, "magic" if power else None, power,
                     96 if power else 100, mana, cd, rarity="rare" if branch else "uncommon",
                     description=desc, pierce=pierce, tags=full_tags, cast_base=time)

    skills = (
        s("cult_sign", "Кощунственный знак", 5, 9, 10, 0, 2.1,
          "Попадание даёт 1 фанатизм и оставляет личную печать на 3 действия цели."),
        s("cult_voice", "Голос из-за грани", 6, 12, 18, 1, 2.65,
          "Попадание даёт 1 фанатизм. По цели со своей печатью снимает её и даёт 2 вместо 1."),
        s("cult_rite", "Запретный обряд", 8, 23, 29, 2, 3.85,
          "Требует 2 фанатизма и тратит их только при попадании. Пробивает 28% магической защиты.",
          tags=("cult_spend",), pierce=.28),
        s("cult_depths", "Шёпот затонувшего города", 10, 11, 19, 2, 2.85,
          "Видения наносят магический урон. Попадание даёт 1 фанатизм и накладывает Шёпот глубин.",
          branch="cultist_cthulhu"),
        s("arch_cultist_cthulhu", "Пробуждение Р’льеха", 15, 24, 36, 3, 4.25,
          "Требует 2 фанатизма, тратит их только при попадании. Прилив ранит выбранную цель; Шёпот глубин охватывает её и до двух других живых врагов.",
          branch="cultist_cthulhu", tags=("cult_spend", "three_strike")),
        s("cult_gate", "Неподвижный Ключ", 10, 0, 13, 2, 1.9,
          "Открывает вход на 3 собственных действия и даёт 1 фанатизм (2 в форме «Дитя Врат»).",
          branch="cultist_yog"),
        s("arch_cultist_yog", "Сходящиеся сферы", 15, 24, 34, 2, 3.7,
          "Нужны открытый вход и 2 фанатизма. На попадании закрывает пару врат и тратит заряды. Две волны выходят из разных врат.",
          branch="cultist_yog", tags=("cult_spend", "two_strike"), pierce=.32),
        s("cult_brood", "Чёрный козёл лесов", 10, 0, 26, 5, 3.15,
          "Призывает одного отпрыска с 24 HP (30 на финальной ступени). Его можно атаковать отдельно. Он принимает 30% прямого урона по хозяину, если атака не задела обоих. Пока он жив, повторный призыв недоступен.",
          branch="cultist_shub"),
        s("cult_roots", "Корни Чёрного козла", 12, 15, 18, 2, 2.9,
          "Требует живого отпрыска. Он атакует корнями; попадание даёт 1 фанатизм и продвигает рост как другая родная атака.",
          branch="cultist_shub", tags=("two_strike",)),
        s("arch_cultist_shub", "Голод выводка", 15, 0, 17, 2, 2.4,
          "Требует живого отпрыска и 2 фанатизма. Хищник атакует сам в своей очереди, принимает 15% прямого урона по хозяину и усиливает родные атаки на 6% за стадию роста. Повторное применение возвращает защитника.",
          branch="cultist_shub", tags=("cult_spend",)),
        s("cult_yellow", "Жёлтый знак", 10, 10, 19, 2, 2.65,
          "Попадание даёт 1 фанатизм и отмечает цель на 4 её действия (5 в форме «Живая маска Каркозы»). Новый знак заменяет старый.",
          branch="cultist_hastur"),
        s("arch_cultist_hastur", "Второй акт Каркозы", 15, 21, 33, 3, 3.9,
          "Требует 2 фанатизма, тратит их только при попадании. +30% урона по цели, которая повторилась под твоим Жёлтым знаком.",
          branch="cultist_hastur", tags=("cult_spend", "two_strike"), pierce=.24),
    )
    return {CLASS_ID: cls}, {skill.skill_id: skill for skill in skills}


def is_final(side):
    return final_form(side) is not None


def final_form(side):
    if side.get("level", 0) >= 20 and side.get("archclass_stage", 20) >= 20:
        return FORMS.get(patron(side))
    return None


def patron(side):
    side = side or {}
    if side.get("class_id") == CLASS_ID and side.get("level", 0) >= 10:
        return side.get("archclass_id", "")
    return ""


def _marker(side, key):
    return next((item for item in side.get("effects", ()) if item.get("id") == key), None)


def _owner(side):
    return [side.get("controller_id", 0), side.get("slave_id", 0)]


def _owned(target, key, actor):
    item = _marker(target, key)
    return item if item and item.get("cult_owner") == _owner(actor) else None


def _seal(actor):
    return SEAL + ":" + ":".join(map(str, _owner(actor)))


def _mark(side, key, name, description, turns, *, kind=None, target="enemy", **extra):
    _remove(side, key)
    item = dict(id=key, name=name, description=description, kind=kind or key, value=1,
                duration=turns, target=target, **extra)
    side["effects"].append(item)
    return item


def _brood(side):
    brood = side.get("rpg_state", {}).get("cult_brood")
    return brood if brood and brood["hp"] > 0 else None


def restriction(actor, skill):
    if actor.get("class_id") != CLASS_ID or skill.class_id != CLASS_ID:
        return ""
    memory = actor.get("rpg_state", {})
    if "cult_spend" in skill.tags and memory.get("cult_fanaticism", 0) < 2:
        return "Нужно 2 фанатизма."
    if skill.skill_id == PORTAL_SKILL and not _marker(actor, GATE):
        return "Сначала открой вход Неподвижным Ключом."
    if skill.skill_id == "cult_brood" and _brood(actor):
        return "У тебя уже есть живой отпрыск."
    if skill.skill_id in ("arch_cultist_shub", "cult_roots") and not _brood(actor):
        return "Нужен живой отпрыск."
    return ""


def damage_multiplier(actor, target, skill):
    multiplier = 1
    yellow = _marker(actor, YELLOW)
    if yellow and skill.damage_type and yellow.get("last") == skill.damage_type:
        multiplier *= 1 - yellow["penalty"]
    if actor.get("class_id") != CLASS_ID or skill.class_id != CLASS_ID:
        return multiplier
    form = final_form(actor)
    if form is FORMS["cultist_cthulhu"] and skill.damage_type and _owned(target, WHISPER, actor):
        multiplier *= 1.10
    brood = _brood(actor)
    if brood and brood["predator"] and skill.damage_type:
        multiplier *= 1 + .06 * brood["stage"]
    if skill.skill_id == "arch_cultist_hastur":
        sign = _owned(target, YELLOW, actor)
        if sign and sign.get("repeated"):
            multiplier *= 1.30
    return multiplier


def cover_view(target):
    """Snapshot for the client forecast; never used as proof of damage."""
    brood = _brood(target) if not target.get("_cult_brood_exposed") and patron(target) == "cultist_shub" else None
    if brood:
        return dict(hp=brood["hp"], percent=15 if brood["predator"] else 30)
    from arena_summons import guard
    unit, percent = guard(target)
    if unit:
        return dict(hp=unit["hp"], percent=percent)
    return None


def cover_name(target):
    from arena_summons import TYPES, guard
    unit, _ = guard(target)
    return TYPES[unit["kind"]][0].lower() if unit else "отпрыск"


def remove_brood(owner):
    if owner.get("rpg_state", {}).pop("cult_brood", None) is not None:
        cooldowns = owner["cooldowns"]
        cooldowns["cult_brood"] = max(cooldowns.get("cult_brood", 0), 3 if is_final(owner) else 4)


def incoming(target, damage):
    """Spend the brood's HP on a cast, not on each pellet or overkill."""
    if damage <= 0 or not (cover := cover_view(target)):
        return damage, 0
    from arena_summons import guard
    brood = _brood(target) if patron(target) == "cultist_shub" else None
    companion = brood or guard(target)[0]
    absorbed = min(cover["hp"], (min(damage, target["hp"]) * cover["percent"] + 50) // 100)
    companion["hp"] -= absorbed
    if brood and brood["hp"] <= 0:
        remove_brood(target)
    return damage - absorbed, absorbed


def record_action(actor, damage_type):
    sign = _marker(actor, YELLOW)
    if sign:
        sign["repeated"] = bool(damage_type and sign.get("last") == damage_type)
        sign["last"] = damage_type


def cast_multiplier(side):
    whisper = _marker(side, WHISPER)
    return 1 + whisper["delay"] if whisper else 1


def consume_whisper(side):
    if _marker(side, WHISPER):
        _remove(side, WHISPER)


def _remove(side, key):
    side["effects"][:] = [item for item in side["effects"] if item.get("id") != key]


def _whisper(actor, target, context, area):
    targets = [target]
    if area and context and any(p["fighter"] is actor for p in context.get("players", {}).values()):
        enemies = context.get("enemies") or {"boss": context.get("boss")}
        targets.extend(enemy for enemy in enemies.values()
                       if enemy and enemy is not target and enemy["hp"] > 0)
    delay = .25 if is_final(actor) else .18
    count = 0
    for enemy in [foe for foe in targets if foe["hp"] > 0][:3]:
        old = _marker(enemy, WHISPER)
        applied = max(delay, old["delay"] if old else 0)
        owner = old.get("cult_owner") if old and old["delay"] > delay else _owner(actor)
        _mark(enemy, WHISPER, "Шёпот глубин",
              f"Следующий ещё не начатый каст дольше на {round(applied * 100)}%. Не складывается.", 3,
              delay=applied, cult_owner=owner)
        count += 1
    return count


def after_action(actor, target, skill, hit, context=None):
    if not hit or actor.get("class_id") != CLASS_ID or skill.class_id != CLASS_ID:
        return []
    key, notes = skill.skill_id, []
    memory = actor.setdefault("rpg_state", {})
    before = memory.get("cult_fanaticism", 0)
    change = 0
    if "cult_spend" in skill.tags:
        change = -2
    elif key in ("cult_sign", "cult_voice", "cult_depths", "cult_gate", "cult_yellow", "cult_roots"):
        change = 1
    if key == "cult_gate" and is_final(actor):
        change = 2
    if key == "cult_sign" and target["hp"] > 0:
        _mark(target, _seal(actor), "Кощунственная печать", "Наложивший её культист может прочитать её Голосом из-за грани.", 3,
              kind=SEAL)
    elif key == "cult_voice" and _marker(target, _seal(actor)):
        change = 2
        _remove(target, _seal(actor))
    if change:
        amount = max(0, min(CAP, before + change))
        memory["cult_fanaticism"] = amount
        if before != amount:
            notes.append(f"Фанатизм: {amount}/{CAP}")
    if key in ("cult_depths", "arch_cultist_cthulhu"):
        count = _whisper(actor, target, context, key == "arch_cultist_cthulhu")
        if count:
            notes.append(f"Шёпот глубин: целей {count}")
    elif key == "cult_gate":
        _mark(actor, GATE, "Вход открыт", "Готовит Сходящиеся сферы.", 3, target="self")
    elif key == PORTAL_SKILL:
        _remove(actor, GATE)
        refund = 12 if is_final(actor) else 8
        actual = min(refund, actor["stats"]["resource_max"] - actor["resource"])
        actor["resource"] += actual
        notes.append(f"Врата сомкнулись: +{actual} маны")
    elif key == "cult_yellow" and target["hp"] > 0:
        penalty = .25 if is_final(actor) else .18
        _mark(target, YELLOW, "Жёлтый знак",
              f"Повтор той же школы атаки подряд: прямой урон −{round(penalty * 100)}%.", 5 if is_final(actor) else 4,
              cult_owner=_owner(actor), penalty=penalty)
    elif key == "cult_brood":
        hp = 30 if is_final(actor) else 24
        serial = max(1, memory.get("cult_brood_serial", 1)) + 1
        memory["cult_brood_serial"] = serial
        memory["cult_brood"] = dict(stage=1, hp=hp, max_hp=hp, predator=False, serial=serial)
        notes.append(f"Отпрыск: {hp} HP, защитник")
    elif key == "arch_cultist_shub":
        brood = _brood(actor)
        if brood:
            brood["predator"] = not brood["predator"]
            notes.append("Отпрыск: " + ("хищник" if brood["predator"] else "защитник"))
    brood = _brood(actor)
    if brood and skill.damage_type and brood["stage"] < 3:
        brood["stage"] += 1
        brood["hp"] += 6
        brood["max_hp"] += 6
        notes.append(f"Рост отпрыска: {brood['stage']}/3")
    return notes


def milestones(side):
    branch = side["archclass_id"]
    from arena_engine import BUILTIN_SKILLS
    skills = [s for s in BUILTIN_SKILLS.values() if "archclass:" + branch in s.tags]
    return [dict(level=s.unlock_level, description=f"Новый навык: «{s.name}». {s.description}",
                 skill_id=s.skill_id, unlocked=side["level"] >= s.unlock_level) for s in skills]
