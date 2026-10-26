"""Reward-free RP encounters: a non-playing master and independent enemies."""

import random
import re

from arena_engine import Skill, create_battle_state, stats_for, _tick, restore_turn_resource

MOBS = {
    'goblin': dict(name='Гоблин', aliases=('гоблин', 'goblin'), role='Налётчик',
                   sprite='/static/assets/encounters/goblin.svg', hp=55, growth=9,
                   skill='encounter_stab'),
    'brute': dict(name='Громила', aliases=('громила', 'brute'), role='Щитоносец',
                  sprite='/static/assets/encounters/brute.svg', hp=95, growth=13,
                  skill='encounter_smash'),
    'shaman': dict(name='Шаман', aliases=('шаман', 'shaman'), role='Лекарь',
                   sprite='/static/assets/encounters/shaman.svg', hp=50, growth=8,
                   skill='encounter_hex'),
}
MOB_SKILLS = {
    s.skill_id: s for s in (
        Skill('encounter_stab', 'Ржавый клинок', 'ragamuffin', 1, 'physical', 8, 90, 0, 0),
        Skill('encounter_smash', 'Тяжёлый замах', 'ragamuffin', 1, 'physical', 16, 85, 0, 0),
        Skill('encounter_hex', 'Болотный сгусток', 'ragamuffin', 1, 'magic', 10, 95, 0, 0),
    )
}


def validate_roster(roster):
    if not isinstance(roster, list) or not 1 <= len(roster) <= 3 or any(
        not isinstance(mob, str) or mob not in MOBS for mob in roster
    ):
        raise ValueError('Во встрече должно быть от 1 до 3 мобов: гоблин, громила, шаман.')
    return list(roster)


def parse_roster(text):
    """/встреча гоблин 2, шаман; no arbitrary stats or rewards from chat input."""
    if not text.strip():
        raise ValueError('Пример: /встреча гоблин или /встреча гоблин 2, шаман. До 3 врагов, без наград.')
    roster = []
    for part in text.casefold().split(','):
        match = re.fullmatch(r'\s*([\w-]+)(?:\s+([1-3]))?\s*', part)
        mob = next((key for key, info in MOBS.items() if match and match[1] in info['aliases']), None)
        if not mob:
            raise ValueError('Неизвестный моб. Доступны: гоблин, громила, шаман. Пример: /встреча гоблин 2, шаман')
        roster.extend([mob] * int(match[2] or 1))
    return validate_roster(roster)


def parse_named_roster(text, templates):
    """Resolve only the caller's mob templates; exact names precede count suffixes."""
    normalize = lambda name: ' '.join(name.casefold().split())
    own = {}
    for template in templates:
        if template['kind'] == 'mob':
            own.setdefault(normalize(template['definition']['name']), []).append(template)
    builtin = {normalize(alias): key for key, mob in MOBS.items() for alias in mob['aliases']}

    def resolve(name):
        matches = own.get(normalize(name), [])
        if len(matches) > 1:
            raise ValueError('У тебя несколько мобов с названием «' + name.strip() + '». '
                             'Переименуй их в /рп → Мои мобы или выбери нужного через RP-меню.')
        if matches:
            return dict(kind='mob', id=matches[0]['id'])
        if normalize(name) in builtin:
            return dict(kind='builtin', id=builtin[normalize(name)])
        return None

    if not text.strip():
        raise ValueError('Пример: /встреча гоблин 2, шаман или /встреча название своего моба. '
                         'Сохрани своих мобов в /рп → Мои мобы. До 3 врагов, без наград.')
    # An exact saved name may itself contain a comma or end in a number.
    exact = resolve(text)
    if exact:
        return [exact]
    roster = []
    for part in text.split(','):
        item, count = resolve(part), 1
        if item is None:
            match = re.fullmatch(r'\s*(.+?)\s+([1-3])\s*', part)
            if match:
                item, count = resolve(match[1]), int(match[2])
        if item is None:
            raise ValueError('Неизвестный моб: «' + part.strip() + '». '
                             'Доступны гоблин, громила, шаман и твои сохранённые мобы из /рп. '
                             'Пример: /встреча Лесной разбойник 2, шаман. До 3 врагов.')
        roster.extend(dict(item) for _ in range(count))
        if len(roster) > 3:
            raise ValueError('Во встрече может быть от 1 до 3 противников.')
    return roster


def roster_text(roster):
    return ', '.join(MOBS[mob]['name'] if isinstance(mob, str) else mob.get('name', mob.get('definition', {}).get('name', 'Моб')) for mob in roster)


def alive_enemies(data):
    return {key: fighter for key, fighter in data['enemies'].items() if fighter['hp'] > 0}


def target_enemy(data, target=None):
    living = alive_enemies(data)
    if target is None:
        target = next(iter(living), None)
    if not isinstance(target, str) or target not in living:
        raise ValueError('Выберите живого противника этой встречи.')
    return target, living[target]


def create_encounter(participants, sources, classes, skills, roster, master_id):
    from arena_raid_engine import create_raid_state
    if not isinstance(roster, list) or not 1 <= len(roster) <= 3:
        raise ValueError('Во встрече должно быть от одного до трёх мобов.')
    from arena_rp import template_fighter, rp_skills
    skills = rp_skills(skills)
    data = create_raid_state(participants, sources, classes, skills, 'iron')
    for participant, source in zip(participants, sources):
        if source.get('_rp_template'):
            data['players'][str(participant['actor_id'])]['fighter'] = template_fighter(
                source['_rp_template'], participant['actor_id'], classes, skills)
    # Normal combat sources remain capped; only separately stored RP templates
    # can create a sandbox fighter. Consumables and grants never enter this path.
    data['rp_mode'] = True
    level = max(1, round(sum(s['level'] for s in sources) / len(sources)))
    enemies = {}
    for index, mob in enumerate(roster, 1):
        if isinstance(mob, dict):
            fighter = template_fighter(mob, -index, classes, skills)
            fighter.update(mob_id='custom', enemy_id=f'e{index}', controller_id=0, is_boss=False)
            enemies[f'e{index}'] = fighter
            continue
        if mob not in MOBS:
            raise ValueError('Неизвестный моб.')
        info = MOBS[mob]
        source = dict(slave_id=-index, owner_id=0, class_id='ragamuffin', level=level,
                      passive_details=[], loadout=['bum_punch'])
        fighter = create_battle_state(sources[0], source, classes=classes, skills=skills)['sides']['b']
        fighter['stats'] = stats_for('ragamuffin', level, classes=classes)
        fighter['stats'].update(max_hp=info['hp'] + info['growth'] * level,
                                physical_attack=5 + level * (1.2 if mob == 'brute' else .8),
                                magic_attack=5 + level if mob == 'shaman' else 0,
                                physical_defense=5 + level * .7 if mob == 'brute' else 2 + level * .25,
                                magic_defense=2 + level * .25, evasion=10 if mob == 'goblin' else 3)
        fighter.update(hp=fighter['stats']['max_hp'], name=f'{info["name"]} №{index}',
                       mob_id=mob, enemy_id=f'e{index}', effects=[], mechanics={},
                       loadout=[info['skill']], controller_id=0, is_boss=True)
        enemies[f'e{index}'] = fighter
    data.update(kind='encounter', boss_id='encounter', master_id=master_id,
                enemies=enemies, boss=next(iter(enemies.values())), rewards_enabled=False)
    set_intents(data, skills)
    return data


def set_intents(data, skills=None):
    from arena_raid_engine import alive_players
    players = list(alive_players(data))
    intents = {}
    for index, (key, fighter) in enumerate(alive_enemies(data).items()):
        mob = fighter['mob_id']
        if mob == 'custom':
            from arena_engine import BUILTIN_SKILLS, validate_skill
            from arena_raid_engine import pair_state
            from arena_rp import rp_skills
            catalog = rp_skills(skills or BUILTIN_SKILLS)
            targets = players[(data['round'] + index - 1) % len(players):][:1] if players else []
            opponent = data['players'][targets[0]]['fighter'] if targets else fighter
            ids = fighter['loadout']
            usable = []
            for sid in ids:
                try:
                    validate_skill(pair_state(fighter, opponent), 'a', sid, catalog)
                    usable.append(sid)
                except ValueError:
                    pass
            if fighter['rp_ai'] == 'sequence' and usable:
                start = fighter.get('rp_ai_index', 0) % len(ids)
                position = next((start + j) % len(ids) for j in range(len(ids)) if ids[(start + j) % len(ids)] in usable)
                selected = ids[position]
                fighter['rp_ai_index'] = position + 1
            else:
                selected = (random.SystemRandom().choice(usable) if fighter['rp_ai'] == 'random' else usable[0]) if usable else 'bum_punch'
            kind, text = 'attack', catalog[selected].name
            intents[key] = dict(kind=kind, skill=selected, targets=targets, text=text)
            continue
        if mob == 'shaman' and data['round'] % 3 == 0:
            kind, targets, text = 'heal', [], 'Лечебный настой: восстановит 25% HP раненому союзнику'
        elif mob == 'brute' and data['round'] % 3 == 1:
            kind, targets, text = 'guard', [], 'Прикроет самого раненого союзника: +35% обеих защит'
        else:
            kind, targets = 'attack', players[(data['round'] + index - 1) % len(players):][:1] if players else []
            text = MOB_SKILLS[MOBS[mob]['skill']].name
        intents[key] = dict(kind=kind, skill=MOBS[mob]['skill'] if kind == 'attack' else None,
                            targets=targets, text=text)
    data['enemy_intents'] = intents
    data['intent'] = dict(kind='encounter', targets=[], phase=1,
                          text=' · '.join(f'{data["enemies"][key]["name"]}: {i["text"]}' for key, i in intents.items()))


def finish(data):
    from arena_raid_engine import alive_players
    if data.get('finished'):
        return True
    living, enemies = alive_players(data), alive_enemies(data)
    if not living or not enemies:
        won = bool(living) and not enemies
        data.update(finished=True, won=won,
                    result='Противники повержены! РП-встреча завершена, без наград.' if won
                    else 'Отряд выбыл. РП-встреча завершена, без наград.')
        return True
    return False


def resolve(data, skills, rng=None):
    from arena_raid_engine import (alive_players, native_attack, defend, log_event,
                                   raid_snapshot, RAID_MAX_ROUNDS)
    from arena_engine import effective_stat
    from arena_plague import begin_turn
    if data.get('finished'):
        raise ValueError('Встреча завершена.')
    rng = rng or random.SystemRandom()
    from arena_rp import rp_skills
    skills = rp_skills(skills)
    # JSON does not retain shared object references. Bind the compatibility alias.
    data['boss'] = next(iter(data['enemies'].values()))
    data['round_before'] = raid_snapshot(data)
    guards = {}
    order = sorted(alive_players(data), key=lambda key: (-effective_stat(data['players'][key]['fighter'], 'speed'), int(key)))
    for key in order:
        if finish(data):
            break
        player = data['players'][key]
        actor, selected = player['fighter'], player['selected']
        proof = player.pop('qte_result', {})
        guards[key] = proof.get('encounter_guards', {})
        if selected is None:
            player['missed'] += 1
        else:
            player['manual_turns'] += 1
            player['missed'] = 0
        if any(e['kind'] == 'stun' for e in actor['effects']):
            _tick(actor)
            log_event(data, key, key, 'Ошеломление: действие пропущено.')
            continue
        enemy_key = player.get('selected_target')
        enemy = data['enemies'].get(enemy_key)
        # A self/party support skill does not depend on a dying hostile target.
        if selected in skills and not skills[selected].hostile and (not enemy or enemy['hp'] <= 0):
            enemy_key, enemy = next(iter(alive_enemies(data).items()))
        if selected is None or selected == 'defend' or not enemy or enemy['hp'] <= 0:
            defend(actor, next(iter(alive_enemies(data).values())), data)
            log_event(data, key, key, 'Защита: обе защиты +35%.' if selected in (None, 'defend')
                      else 'Выбранный противник уже повержен: защита вместо атаки, энергия не потрачена.')
            continue
        for field in ('attack', 'pattern_attack'):
            if field in proof:
                actor['_qte_' + field] = proof[field]
        try:
            event = native_attack(actor, enemy, selected, skills, rng,
                                  allies=[p['fighter'] for p in alive_players(data).values()], raid_context=data)
        except ValueError:
            defend(actor, enemy, data)
            log_event(data, key, key, 'Навык стал недоступен: защита без расхода энергии.')
        else:
            log_event(data, key, enemy_key, event['text'], **{field: event[field] for field in
                      ('damage', 'self_damage', 'bleed_damage', 'damage_type', 'hit', 'critical', 'hits', 'hit_results') if field in event}, skill=selected)
        finally:
            actor.pop('_qte_attack', None)
            actor.pop('_qte_pattern_attack', None)
    data['_qte_boss_phase'] = True
    for enemy_key, enemy in data['enemies'].items():
        if finish(data):
            break
        if enemy['hp'] <= 0:
            continue
        poison = begin_turn(enemy)
        if poison:
            log_event(data, enemy_key, enemy_key, f'Чума: −{poison} HP.', damage=poison)
        if finish(data) or enemy['hp'] <= 0:
            continue
        intent = data['enemy_intents'][enemy_key]
        if any(e['kind'] == 'stun' for e in enemy['effects']):
            _tick(enemy)
            log_event(data, enemy_key, enemy_key, 'Ошеломление: намерение сорвано.')
            continue
        if intent['kind'] in ('heal', 'guard'):
            _tick(enemy)
            if enemy['hp'] <= 0:
                log_event(data, enemy_key, enemy_key, 'Противник погиб от горения: намерение сорвано.')
                continue
            target_key, ally = min(alive_enemies(data).items(), key=lambda item: item[1]['hp'] / item[1]['stats']['max_hp'])
            if intent['kind'] == 'heal':
                amount = min(ally['stats']['max_hp'] - ally['hp'], max(1, round(ally['stats']['max_hp'] * .25)))
                ally['hp'] += amount
                from arena_plague import actively_healed
                actively_healed(ally)
                log_event(data, enemy_key, target_key, f'Лечебный настой: +{amount} HP.', healing=amount)
            else:
                ally['effects'] = [e for e in ally['effects'] if not e.get('id', '').startswith('encounter_guard_')]
                for dtype in ('physical', 'magic'):
                    ally['effects'].append(dict(id='encounter_guard_' + dtype, kind=dtype + '_defense_pct', value=.35, duration=2))
                log_event(data, enemy_key, target_key, 'Прикрытие: обе защиты +35% на два действия союзника.')
            continue
        living = alive_players(data)
        # Never redirect an announced attack to someone who had no defense QTE.
        targets = [key for key in intent['targets'] if key in living]
        if not targets:
            _tick(enemy)
            log_event(data, enemy_key, enemy_key, 'Цель выбыла: атака отменена.')
            continue
        for key in targets:
            fighter = living[key]['fighter']
            guard = guards.get(key, {}).get(enemy_key)
            if guard:
                fighter['_qte_guard'] = dict(dodge=guard['dodge'], skill=intent['skill'])
                if 'pattern_dodge' in guard:
                    fighter['_qte_guard']['pattern_dodge'] = guard['pattern_dodge']
            data['intent'] = intent
            try:
                event = native_attack(enemy, fighter, intent['skill'], skills if enemy.get('rp_sandbox') else MOB_SKILLS,
                                      rng, allies=list(alive_enemies(data).values()), raid_context=data)
            except ValueError:
                # An announced resource-dependent ability may become unavailable
                # after a player's drain/stun; never replace it with an unseen hit.
                defend(enemy, fighter, data)
                log_event(data, enemy_key, enemy_key, 'Намерение стало недоступно: защита вместо атаки.')
                break
            fighter.pop('_qte_guard', None)
            log_event(data, enemy_key, key, event['text'], skill=intent['skill'],
                      **{field: event[field] for field in ('damage', 'self_damage', 'bleed_damage', 'damage_type', 'hit', 'critical', 'hits', 'hit_results') if field in event})
    data.pop('_qte_boss_phase', None)
    data['log'] = data['log'][-80:]
    data.pop('round_before', None)
    if not finish(data) and data['round'] >= RAID_MAX_ROUNDS:
        data.update(finished=True, won=False, result='Встреча завершена: предел 100 раундов. Без наград.')
    if not data['finished']:
        data['round'] += 1
        data['round_before'] = raid_snapshot(data)
        for key, player in data['players'].items():
            player.update(selected=None, selected_target=None)
            if not player.get('withdrawn') and player['fighter']['hp'] > 0:
                poison = begin_turn(player['fighter'])
                if poison:
                    log_event(data, key, key, f'Чума: −{poison} HP.', damage=poison)
                restore_turn_resource(player['fighter'])
        data.pop('round_before', None)
        if not finish(data):
            for enemy in alive_enemies(data).values():
                restore_turn_resource(enemy)
            set_intents(data, skills)
    return data
