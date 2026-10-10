"""Native specializations. They modify existing skills, never add combat slots."""

ARCHCLASS_LEVEL = 10
ARCHCLASS_FINAL_LEVEL = 20


def branch(class_id, name, final_name, description, final_description):
    return dict(
        class_id=class_id,
        name=name,
        final_name=final_name,
        description=description,
        final_description=final_description,
    )


ARCHCLASSES = {
    "femboy": branch(
        "cutie",
        "Фембой",
        "Фембой",
        "«Воздушный поцелуй» по умилённой цели становится «Попался, натурал»: сила 13, цена 25, уклонение цели −10 на 2 хода.",
        "Сила 14; снижение уклонения −15.",
    ),
    "princess": branch(
        "cutie",
        "Принцесса",
        "Принцесса",
        "«Позирование» становится «Мне нельзя делать больно»: прежнее уклонение и +20% обеих защит на один свой ход, цена 25.",
        "Защиты +30%, цена остаётся 25.",
    ),
    "gachi_actor": branch(
        "jock",
        "Гачи-актёр",
        "Гачи-актёр",
        "«Зажим булками» становится «Welcome to the club»: дополнительно снижает физическую атаку цели на 15% на 2 хода, цена 25.",
        "Физическая атака цели −25%.",
    ),
    "mge_bro": branch(
        "jock",
        "Мге-браток",
        "Мге-браток",
        "«Жопный пик» становится «Дуэль на миду»: сила 20, цена 50; собственная физическая защита −20% на один свой ход.",
        "Сила 22, цена 55; уязвимость сохраняется.",
    ),
    "programmer": branch(
        "nerd",
        "Программист",
        "Программист",
        "«Зарядка» становится «Горячий фикс»: сокращает остальные перезарядки на ход. Под зарядкой следующая платная родная магическая атака дешевле на 5, но не бесплатна.",
        "Экономия следующей атаки — 8 энергии.",
    ),
    "hacker": branch(
        "nerd",
        "Хакер",
        "Хакер",
        "«Деанон» становится «Доступ получен»: помимо прежних эффектов похищает до 10 энергии и возвращает половину отнятого; цена 25.",
        "Похищает до 15 энергии, цена 30.",
    ),
    "thumb_discipline": branch(
        "thumb",
        "Капо: Дисциплина",
        "Соттокапо: Дисциплина",
        "«Предупредительный выстрел» становится «Соблюдай субординацию»: физическая атака цели −25% на 2 хода, цена 25.",
        "Физическая атака цели −35%.",
    ),
    "thumb_execution": branch(
        "thumb",
        "Капо: Расстрел",
        "Соттокапо: Расстрел",
        "При трёх зарядах субординации «Приговор старшего» превращается в «Приговор без обжалования»: сила 21, цена 45, пробитие 50%, атака цели −15% на 2 хода. Заменяет обычный бонус зарядов.",
        "Сила 22, пробитие 60%, цена 50.",
    ),
    "index_proxy": branch(
        "index",
        "Прокси",
        "Прокси",
        "«Последняя строка» по предписанию становится «Предписание исполнено»: точность 95%, цена 40, при попадании возвращает ещё 5 Воли.",
        "Возврат увеличивается до 10 Воли.",
    ),
    "index_messenger": branch(
        "index",
        "Посланник",
        "Посланник",
        "«Получить предписание» также назначает врагу доступную атаку для его следующего действия. Нарушение отнимает до 8 энергии; зелье не считается действием.",
        "Штраф за нарушение — до 12 энергии. Пропуск хода тоже нарушает предписание.",
    ),
    "middle_guardian": branch(
        "middle",
        "Старший брат: Опора семьи",
        "Великий брат: Опора семьи",
        "«Стиснуть зубы» становится «За спиной семьи»: +35% физической и +25% магической защиты на один свой ход; прежнее восстановление Ярости.",
        "Физическая защита +45%, магическая +35%.",
    ),
    "middle_revenge": branch(
        "middle",
        "Старший брат: Книга мести",
        "Великий брат: Книга мести",
        "При трёх обидах «За всю семью» становится «Долг крови»: сила 19, цена 45, но обе собственные защиты −20% на один свой ход. Обычное усиление обидами сохраняется; защитный эффект базового превращения заменяется.",
        "Сила 20, цена 50; уязвимость сохраняется.",
    ),
    "ring_pointillist": branch(
        "ring",
        "Доцент-пуантилист",
        "Маэстро-пуантилист",
        "«Красный этюд» становится «Точка за точкой»: сила 9, цена 25, кровотечение 4 на 3 хода вместо 3.",
        "Кровотечение 5, цена 30.",
    ),
    "ring_fauvist": branch(
        "ring",
        "Доцент-фовист",
        "Маэстро-фовист",
        "При трёх разных ослаблениях «Последний штрих» становится «Завершённый шедевр»: сила 18, цена 40; снимает ослабления после попадания, не после промаха.",
        "Сила 20, цена 45.",
    ),
    "pinky_dihui": branch(
        "pinky",
        "Звезда Дихуэй",
        "Звезда Дихуэй",
        "При трёх зарядах сосредоточенности «Лунная дуга» становится «Затмение»: сила 12, точность 95%, цена 25, пробитие 45%. Заряды расходуются даже при промахе; эта атака не критует.",
        "Пробитие 55%, цена 30.",
    ),
    "pinky_tiansha": branch(
        "pinky",
        "Звезда Тяньган",
        "Звезда Тяньган",
        "При трёх зарядах сосредоточенности «Падающая звезда» становится «Рассечь небеса»: сила 19, цена 50. Заряды расходуются даже при промахе; прежний шанс критического удара, максимум 75%.",
        "Сила 21, цена 55.",
    ),
}


def selected_branch(source):
    entry = ARCHCLASSES.get(source.get("archclass_id", ""))
    if (
        entry
        and entry["class_id"] == source["class_id"]
        and source["level"] >= ARCHCLASS_LEVEL
    ):
        return entry
    return None


def archclass_view(source):
    entry = selected_branch(source)
    if not entry:
        return None
    final = final_stage(source)
    from arena_archprogress import milestones

    return dict(
        entry,
        id=source["archclass_id"],
        stage=20 if final else 10,
        title=entry["final_name"] if final else entry["name"],
        progression=milestones(source),
    )


def class_title(source, base_name):
    view = archclass_view(source)
    return view["title"] if view else base_name


def final_stage(source):
    # Old battle snapshots and NPCs retain their level-based behavior.
    return (
        source["level"] >= ARCHCLASS_FINAL_LEVEL
        and source.get("archclass_stage", 20) >= 20
    )


def branch_options(class_id):
    return [
        dict(entry, id=key)
        for key, entry in ARCHCLASSES.items()
        if entry["class_id"] == class_id
    ]


def e(key, kind, value, turns=0, target="enemy"):
    return dict(id=key, kind=kind, value=value, turns=turns, target=target, chance=1)


def arch_rule(skill, source):
    entry = selected_branch(source)
    if not entry or skill.class_id != source["class_id"]:
        return None
    from arena_archprogress import improve_rule, skill_branch, unique_rule

    if skill_branch(skill):
        return unique_rule(skill, source)
    key, final = source["archclass_id"], final_stage(source)
    rule = dict(
        trigger="always",
        condition="Выбрана специализация «" + entry["name"] + "»",
        description=entry["description"]
        + (" " + entry["final_description"] if final else ""),
    )
    changes = None
    if key == "femboy" and skill.skill_id == "air_kiss":
        rule.update(trigger="adoration", condition="Противник под умилением")
        changes = dict(
            name="Попался, натурал",
            power=14 if final else 13,
            cost=25,
            effects=skill.effects
            + (e("femboy_evasion", "evasion_flat", -15 if final else -10, 2),),
        )
    elif key == "princess" and skill.skill_id == "posing":
        changes = dict(
            name="Мне нельзя делать больно",
            cost=25,
            effects=skill.effects
            + tuple(
                e(
                    "princess_" + dtype,
                    dtype + "_defense_pct",
                    0.30 if final else 0.20,
                    1,
                    "self",
                )
                for dtype in ("physical", "magic")
            ),
        )
    elif key == "gachi_actor" and skill.skill_id == "clench":
        changes = dict(
            name="Welcome to the club",
            cost=25,
            effects=skill.effects
            + (e("gachi_attack", "physical_attack_pct", -0.25 if final else -0.15, 2),),
        )
    elif key == "mge_bro" and skill.skill_id == "butt_peak":
        changes = dict(
            name="Дуэль на миду",
            power=22 if final else 20,
            cost=55 if final else 50,
            effects=(e("mge_risk", "physical_defense_pct", -0.20, 1, "self"),),
        )
    elif key == "programmer" and skill.skill_id == "charging":
        changes = dict(name="Горячий фикс", tags=("optimize",))
    elif key == "programmer" and skill.damage_type == "magic" and skill.cost:
        rule.update(
            trigger="charging",
            condition="Действует подготовка от «Зарядки» / «Горячего фикса»",
        )
        changes = dict(
            name=skill.name + " · оптимизировано",
            cost=max(1, skill.cost - (8 if final else 5)),
        )
    elif key == "hacker" and skill.skill_id == "doxxing":
        changes = dict(
            name="Доступ получен",
            cost=30 if final else 25,
            effects=skill.effects
            + (e("hacker_drain", "resource_leech", 15 if final else 10),),
        )
    elif key == "thumb_discipline" and skill.skill_id == "warning_shot":
        changes = dict(
            name="Соблюдай субординацию",
            cost=25,
            effects=(
                e("warning", "physical_attack_pct", -0.35 if final else -0.25, 2),
            ),
        )
    elif key == "thumb_execution" and skill.skill_id == "senior_verdict":
        rule.update(trigger="order", condition="Накоплены три заряда субординации")
        changes = dict(
            name="Приговор без обжалования",
            power=22 if final else 21,
            cost=50 if final else 45,
            pierce=0.60 if final else 0.50,
            tags=("no_order_bonus",),
            effects=(e("verdict_suppression", "physical_attack_pct", -0.15, 2),),
        )
    elif key == "index_proxy" and skill.skill_id == "last_line":
        rule.update(
            trigger="prescript", condition="«Последняя строка» указана в предписании"
        )
        changes = dict(
            name="Предписание исполнено",
            accuracy=95,
            cost=40,
            effects=(e("proxy_refund", "resource", 10 if final else 5, target="self"),),
        )
    elif key == "index_messenger" and skill.skill_id == "receive_prescript":
        changes = dict(name="Доставка предписания", tags=("enemy_prescript",))
    elif key == "middle_guardian" and skill.skill_id == "grit_teeth":
        changes = dict(
            name="За спиной семьи",
            effects=(
                e("grit_restore", "resource", 35, target="self"),
                e(
                    "grit_guard",
                    "physical_defense_pct",
                    0.45 if final else 0.35,
                    1,
                    "self",
                ),
                e(
                    "grit_magic",
                    "magic_defense_pct",
                    0.35 if final else 0.25,
                    1,
                    "self",
                ),
            ),
        )
    elif key == "middle_revenge" and skill.skill_id == "whole_family":
        rule.update(trigger="grudge", condition="Накоплены три обиды")
        changes = dict(
            name="Долг крови",
            power=20 if final else 19,
            cost=50 if final else 45,
            effects=tuple(
                e("revenge_risk_" + dtype, dtype + "_defense_pct", -0.20, 1, "self")
                for dtype in ("physical", "magic")
            ),
        )
    elif key == "ring_pointillist" and skill.skill_id == "red_etude":
        changes = dict(
            name="Точка за точкой",
            power=9,
            cost=30 if final else 25,
            effects=(e("bleed", "bleed", 5 if final else 4, 3),),
        )
    elif key == "ring_fauvist" and skill.skill_id == "last_stroke":
        rule.update(
            trigger="negatives", condition="На цели три разных отрицательных эффекта"
        )
        changes = dict(
            name="Завершённый шедевр",
            power=20 if final else 18,
            cost=45 if final else 40,
            tags=("consume_negatives",),
        )
    elif key == "pinky_dihui" and skill.skill_id == "moon_arc":
        rule.update(trigger="focus", condition="Накоплены три заряда сосредоточенности")
        changes = dict(
            name="Затмение",
            power=12,
            accuracy=95,
            cost=30 if final else 25,
            pierce=0.55 if final else 0.45,
            tags=("consume_focus", "no_critical"),
        )
    elif key == "pinky_tiansha" and skill.skill_id == "falling_star":
        rule.update(trigger="focus", condition="Накоплены три заряда сосредоточенности")
        changes = dict(
            name="Рассечь небеса",
            power=21 if final else 19,
            cost=55 if final else 50,
            tags=("consume_focus",),
        )
    if changes is None:
        return None
    rule["name"] = changes.pop("name")
    rule["changes"] = changes
    return improve_rule(rule, source, skill)


def obey_enemy_prescript(actor, skill_id):
    order = actor.get("mechanics", {}).pop("enemy_prescript", None)
    if not order:
        return ""
    if order["skill_id"] == skill_id:
        return "предписание противника исполнено"
    penalty = min(actor["resource"], order["penalty"])
    actor["resource"] -= penalty
    return f"предписание противника нарушено: −{penalty} энергии"


def arch_after_action(actor, target, skill, hit, skills, rng):
    notes = []
    if "optimize" in skill.tags:
        actor["cooldowns"] = {
            k: v if k == skill.skill_id else v - 1
            for k, v in actor["cooldowns"].items()
            if k == skill.skill_id or v > 1
        }
    if "enemy_prescript" in skill.tags and hit:
        # Evaluate transformed and mirror-discounted prices, not the base
        # catalog: a cheap base attack can currently be a costly finisher.
        from arena_evolution import skill_variant
        from arena_mirror_effects import gift_cost

        choices = [
            k
            for k in target["loadout"]
            if k in skills and skills[k].damage_type and not target["cooldowns"].get(k)
        ]
        # Free fallback guarantees an achievable command even at zero energy.
        if "bum_punch" in skills:
            choices.append("bum_punch")
        choices = list(
            dict.fromkeys(
                k
                for k in choices
                if gift_cost(
                    target,
                    skill_variant(skills[k], target, actor, target.get("own_turns", 0)),
                )
                <= target["resource"]
            )
        )
        if choices:
            from arena_archprogress import prescript_penalty

            chosen = rng.choice(choices)
            target.setdefault("mechanics", {})["enemy_prescript"] = dict(
                skill_id=chosen, penalty=prescript_penalty(actor)
            )
            notes.append("предписание врагу: «" + skills[chosen].name + "»")
    return notes
