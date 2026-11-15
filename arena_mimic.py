"""Battle-local, JSON-persistent mimic memory. Never grants a whole class.

Compiled copies keep a native pattern descriptor and their paid-action rules;
the declared snapshot is immutable even if the live memory is overwritten.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import combinations

ECHO_IDS = tuple(f'mimic_echo_{i}' for i in range(3))
STAT_EFFECTS = {'accuracy_flat','damage_pct','speed_pct','physical_defense_pct',
                'magic_defense_pct','evasion_flat','physical_attack_pct','magic_attack_pct'}
PORTABLE_EFFECTS = STAT_EFFECTS | {'bleed','burn','stun','heal_pct','resource',
    'resource_leech','cleanse_one','dispel_buffs','incoming_damage_multiplier',
    'damage_taken_pct','next_magic_damage','next_physical_damage',
    'physical_defense_flat','magic_defense_flat','speed_flat','skill_cost_flat',
    'plague_infect','rpg_armor_break','rpg_heal','rpg_cleanse','rpg_parry'}
PORTABLE_TAGS = {'two_strike','three_strike','six_strike','five_strike','triple_strike',
    'hybrid_attack','final_train','final_execution','no_boss_control','no_critical','quick'}
EXCLUDED = {'plagiarism','last_amendment','defend','potion','receive_prescript'}
PHASE_NAMES = ('Неудачная подделка','Получается лучше тебя','Оригинал больше не нужен')


def build_skills(Skill):
    result = {s.skill_id:s for s in (
        Skill('mimic_claw','Чужая рука','raid',1,'physical',17,95,0,0,
              tags=('two_strike',),cast_base=2.6,description='Два рассечения длинными когтями.'),
        Skill('mimic_shards','Осколки личности','raid',1,'magic',16,96,15,1,
              cast_base=3.1,description='Зеркальные осколки перекрывают траектории отхода.'),
        Skill('mimic_gaze','Узнать себя','raid',1,'magic',21,96,20,2,
              cast_base=3.5,description='Отражённые лучи с предупреждением перед ударом.'),
        Skill('mimic_feed','Вдох пустоты','raid',1,None,0,100,0,1,
              effects=(dict(id='mimic_feed',kind='resource',value=45,target='self'),),
              description='Восстанавливает 45 энергии, расходуя действие.'),
        Skill('mimic_stitch','Сшитый приём','raid',1,'magic',1,96,0,0,
              cast_base=3.4,description='Две объявленные атаки на одном поле защиты, каждая с 95% силы. Недостающий отпечаток заменяется собственным приёмом.'),
    )}
    for sid in ECHO_IDS:
        result[sid]=Skill(sid,'Пустой отпечаток','raid',1,'physical',1,95,0,0)
    return result


def initialize(data):
    data['unified_version']=3
    boss=data['boss']
    boss.update(is_mimic=True, class_id='ragamuffin', passive_details=[], effects=[],
        _mimic_skills={}, raid_damage_multiplier=1)
    boss['stats'].update(max_hp=1800+1000*(len(data['players'])-1),resource_max=220,
        physical_attack=32,magic_attack=32,physical_defense=24,magic_defense=24,evasion=8,speed=18)
    boss.update(hp=boss['stats']['max_hp'],resource=220)
    data['mimic']=dict(version=2,phase=1,attacks=[],passives=[],locked='',serial=0,last=[],
        last_stitch=-100,stitched_count=0,notice='Первый отпечаток позволит сшить твою атаку с моей.')
    apply_passives(data)


def phase(data):
    m,b=data['mimic'],data['boss']
    if b['hp']<=0:return m['phase']
    value=3 if b['hp']<=b['stats']['max_hp']*.35 else 2 if b['hp']<=b['stats']['max_hp']*.70 else 1
    if value>m['phase']:
        m['phase']=data['phase']=value
        m['last_stitch']=-100
        if value==3 and m['attacks']:
            record=max(m['attacks'],key=lambda r:r['threat'])
            m['locked']=record['uid']
            m['notice']='Закреплён приём «'+record['skill']['name']+'». Его больше не вытеснить.'
        else:m['notice']='Вторая фаза: сшитые атаки чаще, сопротивление отражения возросло.'
        from arena_raid_engine import log_event
        log_event(data,'boss','boss',m['notice'],mimic_phase=value)
    return m['phase']


def _descriptor(skill,actor):
    from arena_qte_live import strike_count
    from arena_casino_chance import mode
    return dict(id=f'{skill.skill_id}:{skill.name}:{strike_count(skill)}:{skill.damage_type}',
        base_id=skill.skill_id,name=skill.name,class_id=skill.class_id,strikes=strike_count(skill),
        branch=actor.get('archclass_id',''),damage_type=skill.damage_type,tags=list(skill.tags),
        description=skill.description,mimic=True,npc_tier=0,
        mimic_outcome=bool(mode(dict(base_id=skill.skill_id,name=skill.name))))


def compile_copy(skill,actor,target):
    """Flatten prepared class charges, not the class's ongoing mechanics."""
    if skill.skill_id in EXCLUDED or skill.skill_id.startswith('mimic_'):
        return None
    effects=[]
    for effect in skill.effects:
        if effect['kind'] not in PORTABLE_EFFECTS:continue
        effect=deepcopy(effect)
        if effect['kind']=='rpg_heal':effect.update(kind='heal_pct',value=effect['value'])
        if effect['kind']=='rpg_cleanse':effect.update(kind='cleanse_one',value=1)
        if effect['kind']=='heal_pct':effect['value']*=actor['stats']['max_hp']/max(1,target['stats']['max_hp'])
        effects.append(effect)
    if not skill.damage_type and not effects:return None
    from arena_engine import class_modifiers, rpg_modifiers, final_modifiers, mastery_modifiers, effective_stat
    a,b=deepcopy(actor),deepcopy(target)
    boost=class_modifiers(a,b,skill)[1]+final_modifiers(a,skill)
    multiplier=rpg_modifiers(a,b,skill)[1]*mastery_modifiers(a,b,skill)[1]
    prepared=bool(skill.class_id=='gambler' and skill.damage_type or multiplier>1.01 or boost>0 or any(t not in PORTABLE_TAGS for t in skill.tags
        if t.startswith(('rpg_','final_','mastery_')))
        or set(skill.tags)&{'once_per_battle','once_on_hit','twice_per_battle'})
    tags=tuple(t for t in skill.tags if t in PORTABLE_TAGS)
    portable=replace(skill,unlock_level=1,power=round(skill.power*max(.1,1+boost)*multiplier,3),
        effects=tuple(effects),tags=tags)
    return dict(skill=asdict(portable),descriptor=_descriptor(skill,actor),prepared=prepared,
                source_hp=actor['stats']['max_hp'],
                source_attack={k:effective_stat(actor,k) for k in ('physical_attack','magic_attack')})


def variant(skill,actor):
    record=actor.get('_mimic_skills',{}).get(skill.skill_id)
    if skill.skill_id=='plagiarism':record=actor.get('plagiarism_memory')
    if not record:return skill
    value=record['skill'];fields=deepcopy(value)
    fields['effects']=tuple(fields.get('effects',[]));fields['tags']=tuple(fields.get('tags',[]))
    # The equipped wrapper ID owns validation, cooldowns and buttons. The source
    # descriptor separately preserves the native visual pattern.
    fields['skill_id']=skill.skill_id
    if skill.skill_id=='plagiarism':
        fields.update(cost=max(45,value['cost']),cooldown=max(4,value['cooldown']),
            name='Плагиат · '+value['name'],unlock_level=20)
        if record['descriptor'].get('mimic_outcome'):
            fields['description']='Повторяет уже увиденный результат броска противника, без новой ставки. '+fields['description']
    else:
        fields['name']='Отражение · '+value['name']
        fields['power']*=record.get('strength',1)
    return replace(skill,**fields)


def restriction(actor,skill_id):
    if skill_id=='plagiarism' and not actor.get('plagiarism_memory'):
        return 'Сначала дождись совместимого действия противника. После применения нужен новый отпечаток.'
    return ''


def pattern(actor,wrapper):
    record=(actor.get('plagiarism_memory') if wrapper=='plagiarism' else actor.get('_mimic_skills',{}).get(wrapper))
    return deepcopy(record['descriptor']) if record else None


def snapshot(actor,target,context):
    return (deepcopy(actor),deepcopy(target)) if context and context.get('boss_id')=='mimic' else None


def _activated(kind,before,after,other_before,other_after,skill,event,acting):
    damage=event.get('damage',0);hit=event.get('hit',False)
    m,n=before.get('mechanics',{}),after.get('mechanics',{})
    r,s=before.get('rpg_state',{}),after.get('rpg_state',{})
    changed=lambda key:m.get(key)!=n.get(key)
    if kind in {'speed_pct','evasion_flat'}:return acting or event.get('dodged',False)
    if kind in {'physical_defense_pct','magic_defense_pct','uniform','tattoos'}:
        return not acting and damage>0 and (kind!='uniform' or before['hp']>before['stats']['max_hp']*.5) and (kind!='tattoos' or before['hp']<=before['stats']['max_hp']*.4)
    if kind in STAT_EFFECTS:return acting and bool(skill.damage_type and hit)
    if kind=='epic_desperation':return acting and damage>0 and before['hp']<=before['stats']['max_hp']*.35
    if kind.startswith('epic_'):return before.get('epic_state',{}).get({'epic_second_wind':'second_wind_used','epic_fine_print':'fine_print_used','epic_plan_b':'plan_b_ready'}[kind])!=after.get('epic_state',{}).get({'epic_second_wind':'second_wind_used','epic_fine_print':'fine_print_used','epic_plan_b':'plan_b_ready'}[kind])
    if kind in {'rpg_mana','rpg_barrier_charge'}:return r.get('mana')!=s.get('mana')
    if kind=='rpg_faith':return r.get('faith')!=s.get('faith')
    if kind=='subordination':return changed('order')
    if kind=='revenge':return changed('grudge')
    if kind=='constellation':return changed('focus') or acting and event.get('critical',False) and m.get('focus',0)>0
    if kind in {'prescript','obedience'}:return acting and m.get('prescript')==skill.skill_id
    if kind=='analysis':return acting and skill.damage_type=='magic' and m.get('last_magic') not in (None,skill.skill_id)
    if kind=='economy':return acting and skill.damage_type=='magic' and skill.cost>0 and m.get('paid_magic')==2
    if kind in {'right_version','fucking_stamina'}:return acting and hit and skill.skill_id in {'flex_chest','clench'}
    if kind=='evasive_love':return not acting and event.get('dodged',False)
    if kind=='blade_loyalty':return acting and bool(skill.damage_type) and m.get('last_attack') not in (None,skill.skill_id)
    if kind=='exhibit':
        from arena_fingers import negative_kinds
        return acting and damage>0 and len(negative_kinds(other_before))>=2
    if kind=='muse':
        from arena_fingers import negative_kinds
        return acting and hit and bool(negative_kinds(other_after)-negative_kinds(other_before))
    if kind=='charming':return acting and after['resource']>max(0,before['resource']-skill.cost) and any(e.get('id')=='adoration' for e in other_after['effects'])
    if kind=='rpg_rally':return r.get('rally')!=s.get('rally')
    if kind=='rpg_hunter_precision':return acting and hit and any(e['kind']=='bleed' for e in other_before['effects'])
    if kind=='rpg_executioner':return acting and damage>0 and skill.damage_type=='physical' and other_before['hp']<=other_before['stats']['max_hp']*.3
    if kind=='rpg_weapon_master':return acting and hit and any(e.get('id')=='armor_split' for e in other_before['effects'])
    if kind=='rpg_merciful':return acting and not skill.damage_type and before['hp']<=before['stats']['max_hp']*.4 and after['hp']>before['hp']
    if kind=='nz_pandora_mask':return acting and damage>0 and before.get('relic_state',{}).get('last_attack') not in (None,skill.skill_id)
    if kind=='nz_demon_glasses':return acting and bool(skill.damage_type)
    if kind=='nz_cocytus_oath':return acting and damage>0 and before['resource']>=before['stats']['resource_max']*.5
    if kind=='nz_sebas_etiquette':return damage>0 and ((acting and before['hp']<=before['stats']['max_hp']*.5) or (not acting and before['hp']>before['stats']['max_hp']*.5))
    if kind=='nz_hermes_armor':return not acting and damage>0
    if kind=='nz_valkyrie_helm':return acting and damage>0 and (before['hp']<=before['stats']['max_hp']*.5 or after['hp']>before['hp'])
    if kind=='nz_twins_bond':return acting and after.get('relic_state',{}).get('twins_actions',0)%3==0 and (after['hp']>before['hp'] or after['resource']>max(0,before['resource']-skill.cost))
    if kind=='nz_victim_seal':return acting and any(e['kind'] in {'burn','bleed'} and e.get('value',0)>0 for e in before['effects'])
    if kind=='casino_comeback':return acting and before.get('casino_state',{})!=after.get('casino_state',{})
    return False


def apply_passives(data):
    boss,m=data['boss'],data['mimic'];turn=boss.get('own_turns',0)
    m['passives']=[p for p in m['passives'] if p['until']>turn]
    boss['passive_details']=[deepcopy(p['definition']) for p in m['passives']]
    boss['effects']=[e for e in boss['effects'] if not e.get('id','').startswith('mimic_passive:') and e.get('id')!='mimic_resistance']
    boss['effects'].append(dict(id='mimic_resistance',kind='incoming_damage_multiplier',
        value=(.90,.80,.70)[m['phase']-1],duration=1000000,target='self',name='Зеркальная плоть'))
    for p in m['passives']:
        for i,e in enumerate(p['definition']['effects']):
            if e['kind'] in STAT_EFFECTS:boss['effects'].append(dict(e,id=f'mimic_passive:{p["key"]}:{i}',duration=1000000))


def observe(context,before,actor,target,skill,event,wrapper):
    # A learned scroll observes ordinary opponents too, but cannot recursively
    # copy itself or a boss's compound phase/interface script.
    if 'plagiarism' in target.get('loadout',[]) and actor is not target:
        copied=compile_copy(skill,actor,target)
        if copied and wrapper!='plagiarism':target['plagiarism_memory']=copied
    if wrapper=='plagiarism':actor.pop('plagiarism_memory',None)
    if not before or not context or context.get('boss_id')!='mimic':return
    data=context;m=data['mimic']
    if not actor.get('is_mimic'):
        copied=compile_copy(skill,before[0],data['boss'])
        if copied:
            existing=next((r for r in m['attacks'] if r['skill']['skill_id']==skill.skill_id),None)
            if existing:
                existing.update(copied);existing['seen']=min(3,existing['seen']+1);existing['charges']=1
                existing['threat']=copied['skill']['power']*(1+(copied['skill'].get('pierce') or 0))+copied['skill']['cost']*.2
            else:
                slots={r['slot'] for r in m['attacks']}
                if len(m['attacks'])==3:
                    old=next(r for r in m['attacks'] if r['uid']!=m['locked']);m['attacks'].remove(old)
                    slot=old['slot']
                else:slot=next(i for i in range(3) if i not in slots)
                m['serial']+=1
                copied.update(uid=str(m['serial']),slot=slot,seen=1,charges=1,source=actor.get('name','Боец'),
                    threat=copied['skill']['power']*(1+(copied['skill'].get('pierce') or 0))+copied['skill']['cost']*.2)
                m['attacks'].append(copied)
            m['notice']='Я запомнил: '+skill.name
    phase(data)
    for acting,old,new,other_old,other_new in ((True,before[0],actor,before[1],target),(False,before[1],target,before[0],actor)):
        if new.get('is_mimic'):continue
        for p in old.get('passive_details',[]):
            effects=p.get('effects',[])
            if not effects or not any(_activated(e['kind'],old,new,other_old,other_new,skill,event,acting) for e in effects):continue
            key='|'.join(sorted(e['kind'] for e in effects))
            stolen=next((v for v in m['passives'] if v['key']==key),None)
            if stolen:stolen['until']=data['boss'].get('own_turns',0)+3
            else:
                if len(m['passives'])>=m['phase']+1:m['passives'].pop(0)
                m['passives'].append(dict(key=key,definition=deepcopy(p),source=new.get('name','Боец'),
                    until=data['boss'].get('own_turns',0)+3))
                from arena_raid_engine import log_event
                log_event(data,'boss','boss','Твоё тоже моё: '+p.get('name',key)+' · '+new.get('name','Боец'))
    apply_passives(data)


def _record(data,record,stitched=False):
    record=deepcopy(record)
    record['strength']=(1.15,1.35,1.55)[data['mimic']['phase']-1]*(1+.20*(record['seen']-1))*(.95 if stitched else 1)
    if record['seen']>=3:
        record['skill']['cast_base']=max(.75,(record['skill'].get('cast_base') or 3)*.85)
    return record


def set_intent(data):
    from arena_raid_engine import alive_players
    phase(data);apply_passives(data)
    boss,m=data['boss'],data['mimic'];keys=list(alive_players(data))
    if not keys:return
    turn=boss.get('own_turns',0)
    available=[r for r in m['attacks'] if (not r['prepared'] or r['charges']>0)
        and not boss['cooldowns'].get(ECHO_IDS[r['slot']],0) and r['skill']['cost']<=boss['resource']]
    hostile=[r for r in available if r['skill']['damage_type']]
    # A real cadence, not turn%3: exhausted charges/cooldowns used to make
    # the only eligible turn disappear. An affordable native partner prevents
    # one-skill builds from disabling the boss's defining mechanic altogether.
    pairs=[list(pair) for pair in combinations(hostile,2) if sum(r['skill']['cost'] for r in pair)<=boss['resource']]
    pair=max(pairs,key=lambda pair:sum(r['threat'] for r in pair)) if pairs else []
    if not pair and hostile:
        from arena_raid_engine import BOSS_SKILLS
        first=max(hostile,key=lambda r:r['threat'])
        for sid in ('mimic_shards','mimic_gaze','mimic_claw'):
            native=BOSS_SKILLS[sid]
            if boss['cooldowns'].get(sid,0) or native.cost+first['skill']['cost']>boss['resource']:continue
            partner=dict(skill=asdict(native),descriptor=_descriptor(native,boss),native_skill=sid,
                uid='native:'+sid,seen=1,slot=-1,prepared=False,charges=1,threat=native.power)
            pair=[first,partner];break
    interval=(3,2,1)[m['phase']-1]
    stitched=bool(pair and turn>=1 and turn-m.get('last_stitch',-100)>=interval)
    selected=[]
    if stitched:sid='mimic_stitch';selected=[_record(data,r,True) for r in pair]
    elif available:
        r=next((r for r in available if r['skill']['skill_id'] not in m['last'][-1:]),available[0])
        sid=ECHO_IDS[r['slot']];selected=[_record(data,r)]
    elif boss['resource']<45 and m['attacks']:sid='mimic_feed'
    else:sid=('mimic_claw','mimic_shards','mimic_gaze')[turn%3]
    boss['_mimic_skills']={(r.get('native_skill') or ECHO_IDS[r['slot']]):r for r in selected}
    targets=[keys[turn%len(keys)]]
    names=' + '.join(r['skill']['name'] for r in selected)
    text=('Сшитый приём: '+names if stitched else 'Отражение: '+names if selected else
        {'mimic_claw':'Чужая рука: два удара когтями','mimic_shards':'Осколки личности','mimic_gaze':'Узнать себя: зеркальные лучи','mimic_feed':'Вдох пустоты: +45 энергии'}[sid])
    data['intent']=dict(kind='mimic',skill=sid,targets=targets,text=text,phase=m['phase'],copies=selected)
    data['dialogue']=dict(speaker='ГОЛОДНОЕ ОТРАЖЕНИЕ',text=('Оригинал больше не нужен.' if m['phase']==3 else
        'Красивый приём. Уже наш.' if selected else 'Покажи, на что ты способен.'),warning=text,
        id=f'mimic:{turn}:{sid}',persistent=True)


def release(data,intent,skills):
    from arena_engine import validate_skill
    from arena_raid_engine import pair_state,alive_players
    boss=data['boss'];copies=intent.get('copies',[])
    if any(e['kind']=='stun' for e in boss['effects']):return []
    result=[];remaining=boss['resource']
    for i,record in enumerate(copies or [None]):
        fighter=deepcopy(boss);sid=(record.get('native_skill') or ECHO_IDS[record['slot']]) if record else intent['skill']
        if record:
            fighter['_mimic_skills']={sid:deepcopy(record)}
            # Match the observed offensive investment without cloning the whole
            # player build. These stats belong to the declared cast snapshot.
            for key,value in record.get('source_attack',{}).items():
                fighter['stats'][key]=max(fighter['stats'][key],min(90,value*.95))
        fighter['resource']=remaining
        target=next((k for k in intent['targets'] if k in alive_players(data)),None)
        if target is None:return []
        try:skill=validate_skill(pair_state(fighter,data['players'][target]['fighter']),'a',sid,skills)
        except ValueError:return []
        remaining-=skill.cost
        result.append(dict(source='boss' if len(copies)<=1 else f'mimic:{i}',fighter=fighter,
            intent=dict(intent,skill=sid,copies=deepcopy([record] if record else []))))
    return result


def resolve_group(data,released,guards,skills,rng):
    from arena_engine import _tick,bleeding_damage
    from arena_raid_engine import native_attack,log_event,alive_players
    boss=data['boss'];original=deepcopy(boss);after=[]
    if not released:
        _tick(boss);return
    remaining=boss['resource']
    for cast in released:
        if boss['hp'] <= 0:break
        intent=cast['intent'];sid=intent['skill'];first=None
        for key in intent['targets']:
            if key not in alive_players(data):continue
            target=data['players'][key]['fighter'];attacker=deepcopy(cast['fighter'])
            attacker.update(hp=boss['hp'],resource=remaining)
            guard=guards.get(key,{}).get(cast['source'])
            if guard:target['_qte_guard']=dict(guard,skill=sid)
            data.update(intent=intent,_qte_boss_phase=True)
            try:
                event=native_attack(attacker,target,sid,skills,rng,tick_actor_bleed=False,raid_context=data)
            except ValueError:
                log_event(data,'boss',key,'Отпечаток недоступен после изменений в бою: каст сорван.',skill=sid,damage=0)
                continue
            finally:target.pop('_qte_guard',None)
            if first is None:
                # Native resolution already includes healing, recoil and the
                # defender's counter. Do not subtract counter damage twice.
                first=attacker;remaining=attacker['resource'];boss['hp']=attacker['hp']
            log_event(data,'boss',key,event['text'],damage=event['damage'],skill=sid,
                damage_type=event['damage_type'],hit=event['hit'],critical=event['critical'],
                **{k:event[k] for k in ('hits','hit_results') if k in event})
        if first:after.append(first)
        for record in intent.get('copies',[]):
            if record:
                data['mimic']['last']=(data['mimic']['last']+[record['skill']['skill_id']])[-2:]
                live=next((r for r in data['mimic']['attacks'] if r['uid']==record['uid']),None)
                if live and live['prepared']:live['charges']=max(0,live['charges']-1)
    if after:
        final=after[-1];hp=max(0,min(boss['stats']['max_hp'],boss['hp']))
        final['cooldowns']={k:max(a['cooldowns'].get(k,0) for a in after) for a in after for k in a['cooldowns']}
        stats=deepcopy(boss['stats'])
        boss.update(final,hp=hp,resource=remaining,stats=stats)
        if len(released)>1:
            data['mimic'].update(last_stitch=original.get('own_turns',0),
                stitched_count=data['mimic'].get('stitched_count',0)+1)
    else:_tick(boss)
    dot=min(boss['hp'],bleeding_damage(original)+sum(max(0,int(e['value'])) for e in original['effects'] if e['kind']=='burn'))
    if dot:boss['hp']-=dot;log_event(data,'boss','boss',f'Кровотечение / горение: −{dot} HP.',damage=dot)
    data.pop('_qte_boss_phase',None)
    phase(data);apply_passives(data)


def presentation(data):
    m=data['mimic'];turn=data['boss'].get('own_turns',0)
    return dict(phase=m['phase'],title=PHASE_NAMES[m['phase']-1],notice=m['notice'],
        resistance=(10,20,30)[m['phase']-1],stitched_count=m.get('stitched_count',0),
        stitch_rule='Сшивание после первого отпечатка: каждые '+str((3,2,1)[m['phase']-1])+' действия. Если второй копии нет — добавит собственный приём.',
        warning='Ниже 35% HP самый опасный текущий отпечаток закрепится навсегда.',
        attacks=[dict(name=r['skill']['name'],seen=r['seen'],source=r['source'],slot=r['slot'],
            locked=r['uid']==m['locked'],prepared=r['prepared'],charges=r['charges'],
            cost=r['skill']['cost'],cooldown=r['skill']['cooldown']) for r in m['attacks']],
        passives=[dict(name=p['definition'].get('name',p['key']),source=p['source'],
            remaining=max(0,p['until']-turn)) for p in m['passives']])
