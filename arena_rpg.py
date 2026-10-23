"""Classic RPG class mechanics. State is saved in battle JSON, never global."""

from dataclasses import replace
from arena_fingers import has_trait
from arena_rpg_combat import (
    variant as path_variant, modifiers as path_modifiers, context as action_context,
    received as path_received, buff, armor_break, incoming, post_action,
)

RPG_BRANCHES = {
    'warrior_berserker': ('warrior','Берсерк','Натиск и усиленные атаки ценой уязвимости.'),
    'warrior_knight': ('warrior','Рыцарь','Защита, контратаки и добивание расколотой брони.'),
    'mage_necromancer': ('mage','Некромант','Скелет, похищение жизни и жатва накопленных душ.'),
    'mage_elementalist': ('mage','Элементалист','Огонь, холод, молнии и реакции между ними.'),
    'mage_archmage': ('mage','Архимаг','Мановое эхо и разрушительные конструкции чистой маны.'),
    'priest_bishop': ('priest','Епископ','Сильное лечение, обереги и магическая кара.'),
    'priest_paladin': ('priest','Паладин','Броня, физическая кара и Воздаяние за защищённого бойца.'),
    'hunter_beast': ('hunter','Охотник звериной крови','Зверство усиливает удары и возврат крови, но повышает входящий урон.'),
    'hunter_moon': ('hunter','Охотник бледной луны','Пистолет, прерывания и мистические висцеральные атаки.'),
}


def build_rpg_catalog(FighterClass, Skill, effect):
    stats = ('max_hp','physical_attack','magic_attack','physical_defense','magic_defense','speed','evasion')
    specifications = (
        ('warrior','Воин','Выносливость',(52,14,5,12,9,8,5),(5,1.5,.3,1.1,.8,.6,.2),
         (('rpg_weapon_master','Мастер оружия','Удары по расколотой броне получают +10 точности.'),
          ('rpg_executioner','Довести до конца','Против цели с HP ≤30% физические атаки получают +20% урона.'))),
        ('mage','Маг','Мана',(41,4,16,6,12,9,5),(4,.3,1.8,.6,1.0,.7,.2),
         (('rpg_mana','Перенасыщение','Попавшие родные магические атаки дают заряд маны, до 3. Перегрузка расходует их ради +35% урона за заряд.'),
          ('rpg_barrier_charge','Упругая мана','Попавшая атака врага при действующем Мановом барьере или активном призыве Некроманта даёт один заряд Перенасыщения, до 3. Не больше одного заряда за вражеское действие.'))),
        ('priest','Жрец','Мана',(48,8,13,9,12,7,5),(4.5,1.0,1.4,.9,1.0,.5,.2),
         (('rpg_faith','Вера','Успешные родные атаки и полезная поддержка дают Веру, до 3. Кара расходует её: +20% урона за заряд. Лечение полного HP не даёт Веру.'),
          ('rpg_merciful','Милосердие','При HP ≤40% родное лечение сильнее на 25%.'))),
        ('hunter','Охотник','Выносливость',(46,14,8,8,8,15,12),(4.5,1.4,.7,.8,.8,1.0,.3),
         (('rpg_rally','Кровавый ответ','Следующая успешная атака возвращает до 75% нанесённого прямого урона в сложенной форме или висцеральной атакой, до 50% — тяжёлым оружием. Не больше недавно потерянного от врага HP; запас исчезает после своего действия, самоурон его не создаёт.'),
          ('rpg_hunter_precision','Опыт охоты','Атаки по кровоточащей цели получают +10 точности.'))),
    )
    classes = {cid:FighterClass(cid,name,resource,5,dict(zip(stats,base)),dict(zip(stats,growth)),
               tuple(dict(effect(k,k,1,target='self'),name=n,description=d) for k,n,d in passives),'uncommon')
               for cid,name,resource,base,growth,passives in specifications}
    def s(cid,key,name,level,dtype,power,cost,cooldown=0,effects=(),tags=(),description='',pierce=None):
        return Skill(key,name,cid,level,dtype,power,95 if dtype or any(e.get('target')=='enemy' for e in effects) else 100,
                     cost,cooldown,effects,'rare' if level>=8 else 'uncommon',description,pierce,tags)
    skills = (
        s('warrior','armor_split','Раскол брони',5,'physical',9,15,1,(effect('armor_split','rpg_armor_break',.15,3),),description='Снижает физическую защиту на 15%, повтор усиливает раскол до 45%. Три действия цели.'),
        s('warrior','steel_charge','Стальной натиск',5,'physical',14,25,1,description='Против расколотой брони становится двумя ударами с суммарной силой 22 и отдельной проверкой каждого попадания.'),
        s('warrior','counter_lunge','Ответный выпад',6,None,0,20,3,(effect('counter_lunge','rpg_counter',8,1,target='self'),),description='Готовит один контрудар на следующую прямую атаку врага до своего следующего действия. Не срабатывает после смерти.'),
        s('warrior','warrior_execute','Казнь',8,'physical',18,40,3,description='При HP цели ≤30% сила повышается до 30; при расколотой броне дополнительно игнорирует 35% защиты.'),
        s('mage','mana_shot','Мановый выстрел',5,'magic',10,10,description='Недорогая магическая атака. При попадании с пассивкой Перенасыщение даёт заряд маны.'),
        s('mage','mana_blob','Сгусток маны',5,'magic',16,25,1,description='Усиленная магическая атака. При попадании с пассивкой Перенасыщение даёт заряд маны.'),
        s('mage','mana_barrier','Мановый барьер',6,None,0,25,3,(effect('mana_barrier','incoming_damage_multiplier',.70,2,target='self'),),description='Прямой урон −30% на два собственных действия; попадания врага подготавливают Перенасыщение.'),
        s('mage','mana_focus','Сосредоточиться',5,None,0,0,0,(effect('mana_focus','resource',35,target='self'),),description='Возвращает 35 маны, расходуя действие.'),
        s('mage','mana_overload','Перегрузка',8,'magic',18,40,3,tags=('rpg_mana_spend',),description='Расходует до 3 зарядов Перенасыщения: +35% урона за заряд. При промахе заряды сохраняются.'),
        s('priest','light_word','Слово света',5,'magic',10,10),
        s('priest','priest_heal','Исцеление',5,None,0,25,3,(effect('priest_heal','rpg_heal',.25,target='self'),),description='Лечит 25% максимального HP. В рейде автоматически выбирает живого союзника с наименьшим процентом HP.'),
        s('priest','priest_ward','Оберег',6,None,0,20,3,(effect('priest_ward','incoming_damage_multiplier',.75,1,target='self'),),description='Прямой урон −25% до следующего собственного действия.'),
        s('priest','priest_cleanse','Очищение',6,None,0,15,2,(effect('priest_cleanse','cleanse_one',1,target='self'),)),
        s('priest','holy_judgment','Кара',8,'magic',18,40,3,tags=('rpg_faith_spend',),description='Расходует Веру ради +20% урона за заряд. Паладин наносит физический урон и использует Воздаяние.'),
        s('hunter','hunter_cut','Рваный разрез',5,'physical',10,15,0,(effect('hunter_bleed','bleed',3,3,chance=.75),),description='75% шанса кровотечения. В раскрытой форме сила 16, цена 25, пробитие 25%; в сложенной — усиленный возврат крови.'),
        s('hunter','hunter_transform','Раскрыть охоту',5,'physical',9,15,1,tags=('rpg_transform',),description='Атакует и переключает оружие: раскрытая форма — тяжёлый удар, сложенная — лёгкий. Без отдельного подтверждения.'),
        s('hunter','hunter_shot','Прерывающий выстрел',6,'physical',4,20,2,(effect('hunter_parry','rpg_parry',1,1,target='self'),),description='При попадании готовит прерывание следующей атаки противника. Если враг атакует — открывается висцеральная атака. Босс не теряет действие; его урон по охотнику снижается на 35%.'),
        s('hunter','hunter_visceral','Висцеральная атака',8,'physical',28,40,3,tags=('rpg_visceral',),description='Требует успешного прерывания, игнорирует 50% защиты, возвращает больше недавно потерянного HP. Окно — два собственных действия.',pierce=.50),
        s('hunter','blood_bullets','Кровавые пули',6,None,0,0,2,(effect('blood_bullets','rpg_blood_bullets',.10,target='self'),),description='Жертвует 10% максимального HP ради 30 энергии. Не может убить; самоурон нельзя вернуть Кровавым ответом.'),
    )
    unique = (
        s('warrior','arch_warrior_berserker','Кровавый натиск',15,'physical',24,45,3,tags=('archclass:warrior_berserker',),description='Мощный удар; против расколотой брони игнорирует 40% защиты.'),
        s('warrior','arch_warrior_knight','Сокрушительный контрудар',15,'physical',18,35,3,(effect('knight_counter','rpg_counter',12,1,target='self'),),('archclass:warrior_knight',)),
        s('mage','arch_mage_necromancer','Жатва душ',15,'magic',20,40,3,tags=('archclass:mage_necromancer','rpg_soul_spend','rpg_leech'),description='+30% урона за душу, до 3. Возвращает 30% снятого HP; души расходуются только при попадании.'),
        s('mage','arch_mage_elementalist','Метеор',15,'magic',26,50,4,tags=('archclass:mage_elementalist','rpg_meteor'),description='По горящей цели урон +50%; при попадании горение расходуется.'),
        s('mage','arch_mage_archmage','Великое стирание',15,'magic',30,60,4,tags=('archclass:mage_archmage',),description='Игнорирует 40% магической защиты. Может использовать подготовленное Мановое эхо.',pierce=.40),
        s('priest','arch_priest_bishop','Страшный суд',15,'magic',24,45,3,tags=('archclass:priest_bishop','rpg_faith_spend'),description='Расходует Веру с удвоенным бонусом, +40% урона за заряд.'),
        s('priest','arch_priest_paladin','Карающий приговор',15,'physical',25,45,3,tags=('archclass:priest_paladin','rpg_faith_spend'),description='Расходует Веру и накопленное Воздаяние.',pierce=.35),
        s('hunter','arch_hunter_beast','Разорвать добычу',15,'physical',22,40,3,tags=('archclass:hunter_beast','rpg_beast_spend'),description='+25% урона за Зверство, до 3. Расходует Зверство только при попадании.'),
        s('hunter','arch_hunter_moon','Приговор бледной луны',15,'magic',36,45,3,tags=('archclass:hunter_moon','rpg_visceral','hybrid_attack'),description='Требует прерывания; использует большую атаку бойца и магическую защиту врага. Попадание сокращает перезарядку Прерывающего выстрела на 1 действие.',pierce=.50),
    )
    return classes, {s.skill_id:s for s in (*skills,*unique)}


def branch(side):
    key=side.get('archclass_id','')
    return key if side.get('level',0)>=10 and key in RPG_BRANCHES and RPG_BRANCHES[key][0]==side.get('class_id') else ''


def rpg_variant(skill, actor, target):
    sid, key, memory = skill.skill_id, branch(actor), actor.get('rpg_state',{})
    changes = {}
    if sid=='steel_charge' and any(e.get('id')=='armor_split' for e in target['effects']):
        changes.update(name='Стальной прорыв',power=22,tags=skill.tags+('two_strike',))
    elif sid=='warrior_execute' and target['hp']<=target['stats']['max_hp']*.30:
        changes.update(name='Без права на пощаду',power=30,pierce=.35 if any(e.get('id')=='armor_split' for e in target['effects']) else None)
    elif sid=='arch_warrior_berserker' and any(e.get('id')=='armor_split' for e in target['effects']):
        changes.update(pierce=.40)
    elif sid=='hunter_cut' and memory.get('weapon_open'):
        changes.update(name='Тяжёлый рваный разрез',power=16,cost=25,pierce=.25)
    elif sid=='hunter_transform':
        changes.update(name='Сложить охоту' if memory.get('weapon_open') else 'Раскрыть охоту',
                       power=9 if memory.get('weapon_open') else 17,cost=15 if memory.get('weapon_open') else 20)
    if skill.class_id == actor['class_id'] and key:
        if key=='warrior_berserker' and sid=='counter_lunge':
            changes.update(name='Неистовый натиск',effects=(dict(id='berserk_damage',kind='damage_pct',value=.35,turns=2,target='self',chance=1),dict(id='berserk_risk',kind='damage_taken_pct',value=.20,turns=2,target='self',chance=1)))
        elif key=='warrior_knight' and sid=='counter_lunge':
            changes.update(name='Страж клинка',effects=skill.effects+(dict(id='knight_guard',kind='incoming_damage_multiplier',value=.75,turns=1,target='self',chance=1),))
        elif key=='mage_necromancer':
            if sid=='mana_shot': changes.update(name='Костяной выстрел',power=12)
            if sid=='mana_blob': changes.update(name='Похищение жизни',tags=skill.tags+('rpg_leech',))
            if sid=='mana_barrier': changes.update(name='Поднять мертвеца',effects=(dict(id='skeleton',kind='rpg_summon',value=6,turns=3,target='self',chance=1),))
        elif key=='mage_elementalist':
            if sid=='mana_shot': changes.update(name='Огненный шар',effects=(dict(id='rpg_burn',kind='burn',value=3,turns=3,target='enemy',chance=.85),))
            if sid=='mana_blob': changes.update(name='Ледяное копьё',effects=(dict(id='rpg_frost',kind='speed_pct',value=-.25,turns=2,target='enemy',chance=1),))
            if sid=='mana_overload':
                changes.update(name='Цепная молния',power=24 if any(e.get('id')=='rpg_frost' for e in target['effects']) else 18)
        elif key=='priest_bishop' and sid=='priest_heal':
            changes.update(name='Высшая молитва',effects=tuple(dict(e,value=.30 if actor['level']>=12 else .28) for e in skill.effects))
        elif key=='priest_paladin':
            if sid=='holy_judgment': changes.update(name='Карающий удар',damage_type='physical',power=22)
            if sid=='priest_ward': changes.update(name='Святой заслон',effects=tuple(dict(e,value=.55) for e in skill.effects))
        elif key=='hunter_moon' and sid=='hunter_visceral':
            changes.update(name='Лунная висцеральная атака',damage_type='magic',tags=skill.tags+('hybrid_attack',))
        if skill.damage_type and actor['level']>=12 and not sid.startswith('arch_'):
            changes['power']=changes.get('power',skill.power)+1
    result = replace(skill,**changes) if changes else skill
    return path_variant(result, actor, target, key)


def rpg_restriction(actor, skill):
    m = actor.get('rpg_state',{})
    if 'rpg_visceral' in skill.tags and (not m.get('visceral_ready') or actor.get('own_turns',0)>=m.get('visceral_until',0)):
        return 'Сначала успешно прерви атаку противника выстрелом.'
    if skill.skill_id=='blood_bullets' and actor['hp']<=max(1,round(actor['stats']['max_hp']*.10)):
        return 'Недостаточно HP для Кровавых пуль; навык не может убить.'
    return ''


def rpg_modifiers(actor,target,skill):
    m,key=actor.get('rpg_state',{}),branch(actor)
    accuracy, multiplier = 0,1.0
    if skill.damage_type:
        if has_trait(actor,'rpg_weapon_master') and any(e.get('id')=='armor_split' for e in target['effects']): accuracy+=10
        if has_trait(actor,'rpg_executioner') and skill.damage_type=='physical' and target['hp']<=target['stats']['max_hp']*.30: multiplier*=1.20
        if has_trait(actor,'rpg_hunter_precision') and any(e['kind']=='bleed' for e in target['effects']): accuracy+=10
        if 'rpg_mana_spend' in skill.tags:
            flow=.25*actor.get('mastery_state',{}).get('flow',0) if 'mastery_flow' in skill.tags else 0
            multiplier*=1+.35*m.get('mana',0)+flow
        if 'rpg_faith_spend' in skill.tags: multiplier*=1+(.40 if skill.skill_id=='arch_priest_bishop' else .20)*m.get('faith',0)
        if 'rpg_soul_spend' in skill.tags: multiplier*=1+.30*m.get('souls',0)
        if 'rpg_beast_spend' in skill.tags: multiplier*=1+.25*m.get('beast',0)
        if 'rpg_meteor' in skill.tags and any(e['kind']=='burn' for e in target['effects']): multiplier*=1.50
        if key=='mage_archmage' and skill.class_id=='mage' and skill.cost>0 and m.get('echo_ready'): multiplier*=1.60
        if key=='hunter_beast': multiplier*=1+.10*m.get('beast',0)
        if key=='priest_paladin' and 'rpg_faith_spend' in skill.tags: multiplier*=1+.15*m.get('retribution',0)
    return accuracy,multiplier*path_modifiers(actor,target,skill,key)


def rpg_parry(actor,target,skill):
    if not skill.damage_type or not any(e['kind']=='rpg_parry' for e in target['effects']): return False,1.0
    target['effects']=[e for e in target['effects'] if e['kind']!='rpg_parry']
    saved=target.setdefault('rpg_state',{})
    saved.update(visceral_ready=True,visceral_until=target.get('own_turns',0)+2)
    if branch(target)=='hunter_moon' and target['level']>=12:
        saved['moon_mark']=True
    return (False,.65) if actor.get('is_boss') else (True,1.0)


def rpg_received_damage(target, damage, before_hp, action_id=None, raid_context=None, *, blocked=False):
    if damage<=0 and not blocked: return
    m=target.setdefault('rpg_state',{})
    fresh=action_id is None or m.get('received_action')!=action_id
    if action_id is not None: m['received_action']=action_id
    path_received(target,damage,branch(target),fresh,blocked=blocked)
    # A shielded ally credits its living Paladin, once for the whole enemy
    # action (including an AoE or a summon follow-up), not once per victim.
    if raid_context is not None:
        from arena_finals import owner
        for shield in target['effects']:
            source_id=shield.get('source_controller')
            if (shield.get('id')!='paladin_ward' or source_id is None
                    or shield.get('value',1)>=1):continue
            source=owner(raid_context,target,source_id)
            if source is not None and branch(source)=='priest_paladin':
                _grant_retribution(source,action_id)
    if target['hp']<=0: return
    m=target.setdefault('rpg_state',{})
    if damage>0 and has_trait(target,'rpg_rally'):
        m['rally_ceiling']=max(m.get('rally_ceiling',0),before_hp)
        m['rally']=min(target['stats']['max_hp'],m.get('rally',0)+damage)
    mana_guard = (any(e.get('id') == 'mana_barrier' for e in target['effects'])
                  or branch(target) == 'mage_necromancer' and m.get('summon', 0) > 0)
    if fresh and has_trait(target, 'rpg_barrier_charge') and mana_guard:
        m['mana'] = min(3, m.get('mana', 0) + 1)
    if fresh and branch(target)=='priest_paladin' and (blocked or any(e['kind']=='incoming_damage_multiplier' and e.get('value',1)<1 for e in target['effects'])):
        _grant_retribution(target,action_id)


def _grant_retribution(source, action_id):
    memory=source.setdefault('rpg_state',{})
    if action_id is not None and memory.get('retribution_action')==action_id:return
    if action_id is not None:memory['retribution_action']=list(action_id)
    memory['retribution']=min(3,memory.get('retribution',0)+1)


def rpg_effect(actor,target,item,rng,allies=None,raid_context=None):
    """Return None for ordinary engine effects, otherwise a log note."""
    kind=item['kind']; recipient=target if item.get('target')=='enemy' else actor
    if kind=='rpg_armor_break':
        armor_break(target, item['value'])
        return 'броня расколота'
    if kind=='rpg_heal':
        candidates=[s for s in (allies or [actor]) if s['hp']>0]
        recipient=min(candidates,key=lambda s:s['hp']/s['stats']['max_hp']) if candidates else actor
        bonus=1.25 if has_trait(actor,'rpg_merciful') and recipient['hp']<=recipient['stats']['max_hp']*.40 else 1
        healed=min(recipient['stats']['max_hp']-recipient['hp'],round(recipient['stats']['max_hp']*item['value']*bonus))
        recipient['hp']+=healed
        if item['value'] > 0:
            from arena_plague import actively_healed
            actively_healed(recipient)
        if branch(actor)=='priest_bishop' and healed:
            recipient['effects']=[e for e in recipient['effects'] if e.get('id')!='bishop_guard']
            recipient['effects'].append(dict(id='bishop_guard',kind='incoming_damage_multiplier',value=.85,duration=1))
            if actor['level']>=12 and recipient['hp']-healed<=recipient['stats']['max_hp']*.40:
                from arena_epic import cleanse_one
                cleanse_one(recipient,rng)
        actor.setdefault('rpg_state',{})['healed']=healed
        if healed: actor['rpg_state']['support_useful']=True
        return f'исцеление: +{healed} HP'+(' союзнику' if recipient is not actor else '')
    if kind=='rpg_blood_bullets':
        loss=max(1,round(actor['stats']['max_hp']*.10));actor['hp']-=loss
        gained=min(30,actor['stats']['resource_max']-actor['resource']);actor['resource']+=gained
        return f'Кровавые пули: −{loss} HP, +{gained} энергии'
    if kind=='rpg_summon':
        actor.setdefault('rpg_state',{}).update(summon=3,summon_power=item['value'],summon_fresh=True,death_servants=False)
        return 'скелет призван на три действия'
    if kind=='rpg_death_servants':
        actor.setdefault('rpg_state',{}).update(summon=3,summon_power=item['value'],summon_fresh=True,death_servants=True,souls=0)
        return 'Страж и Палач призваны на три действия'
    if kind=='rpg_dawn':
        m=actor.setdefault('rpg_state',{})
        candidates=allies or [actor]
        dead=[s for s in candidates if s['hp']<=0]
        if raid_context is not None and dead and not raid_context.get('rpg_revive_used'):
            restored=dead[0]
            restored['hp']=max(1,round(restored['stats']['max_hp']*.30))
            from arena_plague import actively_healed
            actively_healed(restored)
            restored['effects']=[e for e in restored['effects'] if e['kind'] not in ('bleed','burn','stun')]
            raid_context['rpg_revive_used']=True
            note=f'союзник возвращён с {restored["hp"]} HP'
        else:
            total=0
            for restored in candidates:
                if restored['hp']<=0: continue
                amount=min(restored['stats']['max_hp']-restored['hp'],round(restored['stats']['max_hp']*(.25 if allies else .50)))
                restored['hp']+=amount;total+=amount
                from arena_plague import actively_healed
                actively_healed(restored)
                buff(restored,'dawn_guard','incoming_damage_multiplier',.70,1)
            note=f'рассветное исцеление: +{total} HP'
        m.update(dawn_used=True,faith=0)
        return note
    if kind=='incoming_damage_multiplier' and item.get('id')=='priest_ward' and branch(actor)=='priest_paladin':
        buff(actor,'priest_ward',kind,item['value'],max(1,item.get('turns',1)))
        if actor['level']>=12 and actor.get('rpg_state',{}).get('faith',0)>0:
            live=[s for s in (allies or []) if s is not actor and s['hp']>0]
            if live:
                friend=min(live,key=lambda s:s['hp']/s['stats']['max_hp'])
                buff(friend,'paladin_ward',kind,item['value'],1)
                friend['effects'][-1]['source_controller']=actor.get('controller_id')
        return 'Святой заслон'
    if kind=='cleanse_one' and item.get('id')=='priest_cleanse':
        from arena_epic import cleanse_one
        before=len(actor['effects'])
        cleanse_one(actor,rng)
        if len(actor['effects'])<before:
            actor.setdefault('rpg_state',{})['support_useful']=True
        return 'Очищение'
    return None


def rpg_after_action(actor,target,skill,hit,damage,before_hp,rng,effective_stat,context=None,allies=None,raid_context=None):
    m,key=actor.setdefault('rpg_state',{}),branch(actor)
    context=context or action_context(actor,target)
    m['actions']=actor.get('own_turns',0);notes=[]
    reaction_damage=0
    if hit and skill.damage_type:
        if 'rpg_mana_spend' in skill.tags: m['mana']=0
        elif has_trait(actor,'rpg_mana') and skill.class_id=='mage': m['mana']=min(3,m.get('mana',0)+1)
        if 'rpg_faith_spend' in skill.tags: m.update(faith=0,retribution=0)
        elif has_trait(actor,'rpg_faith') and skill.class_id=='priest': m['faith']=min(3,m.get('faith',0)+1)
        if 'rpg_soul_spend' in skill.tags: m['souls']=0
        if 'rpg_beast_spend' in skill.tags: m['beast']=0
        elif key=='hunter_beast' and skill.class_id=='hunter': m['beast']=min(3,m.get('beast',0)+1)
        if 'rpg_meteor' in skill.tags: target['effects']=[e for e in target['effects'] if e['kind']!='burn']
    if hit and skill.class_id=='priest' and not skill.damage_type and (m.get('healed',0)>0 or m.get('support_useful') or skill.skill_id=='priest_ward') and has_trait(actor,'rpg_faith'): m['faith']=min(3,m.get('faith',0)+1)
    m.pop('healed',None)
    if actor['hp']>0:
        if damage and has_trait(actor,'rpg_rally'):
            share=.75 if not m.get('weapon_open') or 'rpg_visceral' in skill.tags else .50
            gain=max(0,min(m.get('rally',0),m.get('rally_ceiling',actor['hp'])-actor['hp'],round(damage*share)))
            actor['hp']+=gain
            if gain: notes.append(f'Кровавый ответ: +{gain} HP')
        if hit and 'rpg_leech' in skill.tags:
            gain=min(actor['stats']['max_hp']-actor['hp'],round(damage*.30));actor['hp']+=gain
            if gain: notes.append(f'Похищение жизни: +{gain} HP')
        if m.get('summon',0)>0 and not m.pop('summon_fresh',False) and target['hp']>0:
            guard=1
            for shield in target['effects']:
                if shield['kind']=='incoming_damage_multiplier':guard*=max(.1,shield.get('value',1))
            dealt=max(1,round(m.get('summon_power',6)*(1+effective_stat(actor,'magic_attack')/20)*100/(100+effective_stat(target,'magic_defense')*4)*guard))
            dealt=incoming(target,dealt,branch(target))
            dealt=min(target['hp'],dealt)
            old_hp=target['hp'];target['hp']=max(0,target['hp']-dealt);rpg_received_damage(target,dealt,old_hp,context.get('action_id'),raid_context)
            m['summon']-=1;m['souls']=min(3,m.get('souls',0)+1);notes.append(f'{"Палач" if m.get("death_servants") else "Скелет"}: −{dealt} HP, души {m["souls"]}/3')
    m.pop('rally',None);m.pop('rally_ceiling',None)
    if 'rpg_transform' in skill.tags: m['weapon_open']=not m.get('weapon_open',False);notes.append('оружие раскрыто' if m['weapon_open'] else 'оружие сложено')
    if 'rpg_visceral' in skill.tags or actor.get('own_turns',0)>=m.get('visceral_until',0): m['visceral_ready']=False
    notes+=post_action(actor,target,skill,hit,damage,key,context,allies)
    # A prepared counter is one reaction, not another selectable player turn.
    counter=next((e for e in target['effects'] if e['kind']=='rpg_counter'),None)
    if (damage or context.get('blocked_contact')) and target['hp']>0 and actor['hp']>0 and counter:
        target['effects']=[e for e in target['effects'] if e is not counter]
        dealt=min(actor['hp'],max(1,round(counter['value']*(1+effective_stat(target,'physical_attack')/20)*100/(100+effective_stat(actor,'physical_defense')*4))))
        if branch(target)=='warrior_knight' and target['level']>=18 and any(e.get('id')=='armor_split' for e in actor['effects']):
            dealt=round(dealt*1.25)
            target.setdefault('rpg_state',{})['steadfast']=max(1,target.get('rpg_state',{}).get('steadfast',0))
        dealt=incoming(actor,dealt,branch(actor))
        old_hp=actor['hp'];actor['hp']=max(0,actor['hp']-dealt);rpg_received_damage(actor,dealt,old_hp)
        if branch(target)=='warrior_knight' and target['level']>=12:
            armor_break(actor)
        reaction_damage=dealt
        notes.append(f'Контрудар врага: −{dealt} HP')
    return notes,reaction_damage
