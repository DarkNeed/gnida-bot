"""RPG milestones. All counters/once flags live in the saved fighter JSON."""

from dataclasses import replace

from arena_rpg_paths import is_final, PATHS


def buff(side, key, kind, value, duration):
    side['effects'] = [e for e in side['effects'] if e.get('id') != key]
    side['effects'].append(dict(id=key, kind=kind, value=value, duration=duration))


def armor_break(side, amount=.15):
    old = next((e['value'] for e in side['effects'] if e.get('id') == 'armor_split'), 0)
    buff(side, 'armor_split', 'physical_defense_pct', max(-.45, old - amount), 3)


def has_effect(side, key):
    return any(e.get('id') == key for e in side['effects'])


def variant(skill, actor, target, key):
    m = actor.get('rpg_state', {})
    sid, level, final = skill.skill_id, actor['level'], is_final(actor)
    if not key or skill.class_id != actor['class_id']:
        return skill
    change = {}
    if key == 'warrior_berserker' and sid == 'arch_warrior_berserker':
        charge = m.get('heat' if final else 'onslaught', 0)
        if charge >= 3:
            change.update(name='Пылающий натиск' if final else 'Кровавый вихрь',
                          power=32, tags=skill.tags + ('three_strike', 'rpg_onslaught_spend'))
            if final:
                change.update(cost=50, cooldown=4,
                              effects=skill.effects + (dict(id='phoenix_burn', kind='burn', value=5, turns=3, target='enemy', chance=1),))
                if charge >= 5:
                    change.update(name='Всё обратить в пепел', power=42, pierce=.40)
    elif key == 'warrior_knight' and sid == 'arch_warrior_knight':
        change['effects'] = skill.effects + (dict(id='knight_guard', kind='incoming_damage_multiplier', value=.75, turns=1, target='self', chance=1),)
        if final and m.get('steadfast', 0) >= 3:
            change.update(name='Бастион отвечает', power=34, cost=50, cooldown=4, pierce=.50,
                          tags=skill.tags + ('rpg_bastion',))
    elif key == 'mage_necromancer' and final and sid == 'mana_barrier' and m.get('souls', 0) >= 3:
        change.update(name='Мёртвые не знают усталости', cost=50, cooldown=4,
                      effects=(dict(id='death_servants', kind='rpg_death_servants', value=9, target='self', chance=1),))
    elif key == 'mage_elementalist':
        if sid == 'mana_overload':
            change['effects'] = skill.effects + (dict(id='rpg_conductivity', kind='magic_defense_pct', value=-.15, turns=4, target='enemy', chance=1),)
        if final and sid == 'arch_mage_elementalist' and all(has_effect(target, e) for e in ('rpg_burn', 'rpg_frost', 'rpg_conductivity')):
            change.update(name='Катаклизм', power=42, cost=50, cooldown=4,
                          tags=skill.tags + ('three_strike', 'rpg_cataclysm'))
    elif key == 'mage_archmage':
        if m.get('echo_ready') and skill.damage_type and skill.cost > 0:
            change['cost'] = max(1, skill.cost - 10) if level >= 12 else skill.cost
        if final and sid == 'arch_mage_archmage' and m.get('echo_ready') and actor.get('own_turns', 0) >= 4 and not m.get('void_used'):
            change.update(name='Точка небытия', power=48, cost=70, pierce=.60,
                          tags=skill.tags + ('rpg_void',))
    elif key == 'priest_bishop':
        if sid == 'priest_heal' and level >= 18 and m.get('prayer_ready'):
            change['effects'] = tuple(dict(e, value=.40) if e['kind'] == 'rpg_heal' else e for e in skill.effects)
        if final and sid == 'priest_heal' and m.get('faith', 0) >= 3 and not m.get('dawn_used'):
            change.update(name='Пока горит свет', cost=60, cooldown=4,
                          effects=(dict(id='dawn_prayer', kind='rpg_dawn', value=.25, target='self', chance=1),),
                          tags=skill.tags + ('rpg_dawn',))
        if sid == 'arch_priest_bishop' and level >= 18 and any(e.get('value', 0) < 0 or e['kind'] in ('bleed', 'burn', 'stun') for e in target['effects']):
            change['pierce'] = .35
    elif key == 'priest_paladin' and final and sid == 'arch_priest_paladin' and m.get('faith', 0) >= 3 and m.get('retribution', 0) >= 3:
        change.update(name='Последний приговор', power=36, cost=60, cooldown=4, pierce=.50,
                      tags=skill.tags + ('two_strike', 'rpg_last_judgment'))
    elif key == 'hunter_beast' and final:
        if skill.damage_type and m.get('beast_fury_until', 0) > actor.get('own_turns', 0):
            change['pierce'] = max(skill.pierce or 0, .35)
        if sid == 'arch_hunter_beast':
            if m.get('beast_fury_until', 0) > actor.get('own_turns', 0):
                change.update(name='Первобытный разрыв', power=34, tags=skill.tags + ('three_strike',))
            elif m.get('beast', 0) >= 3 and not m.get('beast_fury_used'):
                change.update(name='Ярость первородного', power=30, cost=50,
                              tags=skill.tags + ('three_strike', 'rpg_beast_fury'))
    elif key == 'hunter_moon' and final:
        if sid == 'hunter_shot':
            change['name'] = 'Лунный осколок'
        if sid == 'arch_hunter_moon' and m.get('moon_mark') and m.get('visceral_ready') and actor.get('own_turns', 0) < m.get('visceral_until', 0) and not m.get('moon_used'):
            change.update(name='Луна не прощает', power=44, cost=60, pierce=.60,
                          tags=skill.tags + ('two_strike', 'rpg_white_moon'))
    return replace(skill, **change) if change else skill


def context(actor, target):
    m = actor.get('rpg_state', {})
    return dict(m, armor=has_effect(target, 'armor_split'),
                frost=has_effect(target, 'rpg_frost'),
                bleed=any(e['kind'] == 'bleed' for e in target['effects']))


def incoming(target, damage, key):
    if damage <= 0:
        return damage
    m = target.setdefault('rpg_state', {})
    if key == 'mage_necromancer' and target['level'] >= 12 and m.get('summon', 0) > 0:
        damage = max(1, round(damage * .75))
    return damage


def revive(side, key):
    m = side.setdefault('rpg_state', {})
    if side['hp'] <= 0 and key == 'warrior_berserker' and is_final(side) and m.get('heat', 0) >= 3 and not m.get('phoenix_revived'):
        m.update(heat=m['heat'] - 3, phoenix_revived=True)
        side['hp'] = max(1, round(side['stats']['max_hp'] * .30))
        side['effects'] = [e for e in side['effects'] if e['kind'] not in ('burn', 'bleed')]
        buff(side, 'phoenix_reborn', 'damage_pct', .25, 2)
        return True
    return False


def received(target, damage, key, fresh=True):
    m = target.setdefault('rpg_state', {})
    if damage > 0 and fresh:
        guarded = any(e['kind'] in ('incoming_damage_multiplier', 'rpg_counter') for e in target['effects'])
        if key == 'warrior_berserker' and is_final(target):
            m['heat'] = min(5, m.get('heat', 0) + 1)
        if key == 'warrior_knight' and guarded:
            m['steadfast'] = min(3, m.get('steadfast', 0) + 1)
    return revive(target, key)


def modifiers(actor, target, skill, key):
    m, multiplier = actor.get('rpg_state', {}), 1
    if skill.damage_type and skill.class_id == actor['class_id']:
        if key == 'warrior_berserker':
            multiplier *= 1 + .10 * m.get('heat' if is_final(actor) else 'onslaught', 0)
            if actor['hp'] <= actor['stats']['max_hp'] * .35:
                multiplier *= 1.20
        if key == 'hunter_moon' and 'rpg_visceral' in skill.tags and m.get('moon_mark'):
            multiplier *= 1.25
    return multiplier


def incoming_multiplier(target, key):
    m = target.get('rpg_state', {})
    if key == 'warrior_berserker':
        return 1 + .05 * m.get('heat' if is_final(target) else 'onslaught', 0)
    if key == 'hunter_beast':
        return 1 + .10 * m.get('beast', 0) + (.20 if m.get('beast_fury_until', 0) > target.get('own_turns', 0) else 0)
    return 1


def paid_action(actor, target, actual_cost, raid_context=None):
    """The marked opponent transfers only resource actually spent, not extra cost."""
    horizon = next((e for e in actor['effects'] if e.get('id') == 'event_horizon'), None)
    if horizon and actual_cost > 0:
        source=horizon.get('source_controller')
        recipient=target if target.get('controller_id')==source else None
        if raid_context is not None:
            recipient=next((p['fighter'] for p in raid_context['players'].values()
                            if p['fighter'].get('controller_id')==source and not p.get('withdrawn')),None)
        if recipient is None or recipient['hp']<=0:
            return ''
        claim=[actor.get('controller_id'),actor.get('own_turns',0)]
        memory=recipient.setdefault('rpg_state',{})
        if memory.get('horizon_claim')==claim:
            return ''
        memory['horizon_claim']=claim
        gain = min(10, actual_cost, recipient['stats']['resource_max'] - recipient['resource'])
        recipient['resource'] += gain
        return f'Горизонт событий: +{gain} маны' if gain else ''
    return ''


def post_action(actor, target, skill, hit, damage, key, before, allies=None):
    m, notes = actor.setdefault('rpg_state', {}), []
    native = skill.class_id == actor['class_id']
    if key == 'warrior_berserker' and native and skill.damage_type:
        charge = 'heat' if is_final(actor) else 'onslaught'
        if hit:
            if 'rpg_onslaught_spend' in skill.tags:
                m[charge] = max(0, before.get(charge, 0) - 3) if is_final(actor) else (1 if actor['level'] >= 18 else 0)
            else:
                m[charge] = min(5 if is_final(actor) else 3, before.get(charge, 0) + 1 + int(not is_final(actor) and actor['level'] >= 12 and before['armor']))
        if is_final(actor) and before.get('heat', 0) >= 3 and actor['hp'] > 0:
            loss = min(actor['hp'] - 1, max(1, round(actor['stats']['max_hp'] * .05)))
            actor['hp'] -= loss
            if loss:
                notes.append(f'Цена пламени: −{loss} HP')
    if hit and 'rpg_bastion' in skill.tags:
        m['steadfast'] = 0
        buff(actor, 'bastion_guard', 'incoming_damage_multiplier', .55, 1)
        live = [s for s in (allies or []) if s is not actor and s['hp'] > 0]
        if live:
            buff(min(live, key=lambda s: s['hp']/s['stats']['max_hp']), 'bastion_guard', 'incoming_damage_multiplier', .55, 1)
    if key == 'mage_necromancer' and hit and 'rpg_soul_spend' in skill.tags and actor['level'] >= 18 and m.get('summon', 0) > 0:
        m['summon'] = min(3, m['summon'] + 1)
    if key == 'mage_elementalist' and native and hit:
        element = {'mana_shot': 'fire', 'mana_blob': 'ice', 'mana_overload': 'lightning'}.get(skill.skill_id)
        if element:
            if actor['level'] >= 12 and element == 'fire' and before['frost'] and target['hp'] > 0:
                for dtype in ('physical', 'magic'):
                    buff(target, 'thermal_' + dtype, dtype + '_defense_pct', -.20, 2)
            if actor['level'] >= 18:
                seen = set(m.get('elements', [])) | {element}
                if len(seen) == 3:
                    gain = min(20, actor['stats']['resource_max'] - actor['resource'])
                    actor['resource'] += gain
                    notes.append(f'Стихийный цикл: +{gain} маны')
                    seen.clear()
                m['elements'] = sorted(seen)
        if 'rpg_cataclysm' in skill.tags:
            target['effects'] = [e for e in target['effects'] if e.get('id') not in ('rpg_burn', 'rpg_frost', 'rpg_conductivity')]
    if key == 'mage_archmage' and native:
        if hit and skill.damage_type and skill.cost > 0 and before.get('echo_ready'):
            m['echo_ready'] = False
            m['echo_steps'] = [skill.skill_id] if actor['level'] >= 18 and skill.skill_id == 'arch_mage_archmage' else []
        elif not m.get('echo_ready'):
            # A cast counts even when it misses. Repeating a spell neither
            # advances nor destroys the chain; support alone cannot ready it.
            steps = list(dict.fromkeys(m.get('echo_steps', [])))
            if skill.skill_id not in steps:
                steps = steps + [skill.skill_id]
            m['echo_steps'] = steps[-3:]
            attacks = sum(k != 'mana_focus' and k != 'mana_barrier' for k in m['echo_steps'])
            if len(m['echo_steps']) >= 2 and attacks >= 1:
                m['echo_ready'] = True
                notes.append('Мановое эхо подготовлено')
        if hit and 'rpg_void' in skill.tags:
            m['void_used'] = True
            buff(target, 'event_horizon', 'magic_defense_pct', -.25, 2)
            target['effects'][-1]['source_controller']=actor.get('controller_id')
    if key == 'priest_bishop' and actor['level'] >= 18 and hit:
        if skill.skill_id == 'priest_heal':
            m['prayer_ready'] = False
        elif m.get('support_useful'):
            m['prayer_ready'] = True
    if key == 'priest_paladin' and hit and 'rpg_faith_spend' in skill.tags:
        m['retribution'] = max(0, before.get('retribution', 0) - 2) if actor['level'] >= 18 else 0
        if 'rpg_last_judgment' in skill.tags:
            live = [s for s in (allies or [actor]) if s['hp'] > 0]
            if live:
                buff(min(live, key=lambda s: s['hp']/s['stats']['max_hp']), 'judgment_seal', 'incoming_damage_multiplier', .70, 1)
    if key == 'hunter_beast' and hit and native and skill.damage_type:
        spending = 'rpg_beast_spend' in skill.tags
        if actor['level'] >= 12 and before['bleed'] and not spending:
            m['beast'] = min(3, m.get('beast', 0) + 1)
        if actor['level'] >= 18 and (before['bleed'] or target['hp'] <= 0):
            m['beast'] = min(3, m.get('beast', 0) + 1)
        if 'rpg_beast_fury' in skill.tags:
            m.update(beast_fury_used=True, beast_fury_until=actor.get('own_turns', 0) + 3)
    if key == 'hunter_moon' and 'rpg_visceral' in skill.tags:
        if hit:
            m['moon_mark'] = False
            if 'rpg_white_moon' in skill.tags:
                m['moon_used'] = True
        elif actor['level'] >= 18 and actor.get('own_turns', 0) < before.get('visceral_until', 0):
            m['visceral_ready'] = before.get('visceral_ready', False)
    m.pop('support_useful', None)
    return notes
