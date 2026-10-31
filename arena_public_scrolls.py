"""Non-class-bound forge rewards. No boss-exclusive mechanics or free class unlocks."""

# Their advertised core bonus needs an inherent class resource. Generic attacks,
# heals and combos such as hunter_shot + hunter_visceral remain cross-class loot.
NATIVE_RESOURCE_SCROLLS = frozenset(('mana_overload', 'holy_judgment'))


def build_public_scrolls(Skill, PassiveSkill, effect):
    skills = (
        Skill('sweeping_kick', 'Подсечка', 'universal', 1, 'physical', 6, 90, 10, 1,
              effects=(effect('sweeping_kick_slow', 'speed_pct', -.10, 2),),
              tags=('universal_attack',), rarity='common',
              description='Адаптивный удар: тип определяется большей атакой. Снижает скорость врага на 10% на два его действия.'),
        Skill('catch_breath', 'Перевести дух', 'universal', 1, None, 0, 100, 0, 3,
              effects=(effect('catch_breath_energy', 'resource', 25, target='self'),), rarity='common',
              description='Расходует действие и активно восстанавливает 25 энергии. Перезарядка — 3 хода.'),
        Skill('field_dressing', 'Полевая перевязка', 'universal', 3, None, 0, 100, 15, 3,
              effects=(effect('field_dressing_heal', 'heal_pct', .15, target='self'),), rarity='uncommon',
              description='Лечебный навык: восстанавливает 15% максимального HP, расходуя действие.'),
        Skill('rupturing_strike', 'Разрушительный выпад', 'universal', 5, 'physical', 20, 95, 35, 3,
              pierce=.20, tags=('universal_attack',), rarity='rare',
              description='Адаптивный удар, игнорирующий 20% защиты. Тип определяется большей атакой.'),
        Skill('royal_verdict', 'Королевский приговор', 'universal', 15, 'physical', 42, 95, 65, 5,
              pierce=.50, tags=('universal_attack',), rarity='legendary',
              description='Мощный адаптивный удар, игнорирующий 50% защиты. 65 энергии, перезарядка 5 ходов. Не является атакой босса.'),
    )
    passives = (
        PassiveSkill('unyielding_will', 'Несокрушимая воля', (
            dict(effect('unyielding_physical', 'physical_defense_pct', .25, target='self'), description='+25% физической защиты.'),
            dict(effect('unyielding_magic', 'magic_defense_pct', .25, target='self'), description='+25% магической защиты.'),
        ), 'legendary'),
    )
    return {s.skill_id: s for s in skills}, {p.skill_id: p for p in passives}
