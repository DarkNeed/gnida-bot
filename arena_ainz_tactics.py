"""Combat-local strengths and exploitable openings for the six Ainz styles."""
STRATEGIES = (
    ('Призывы прикрывают Аинза и усиливают его магию.',
     'После уничтожения обоих призывов связь обрывается: Аинз получает на 25% больше прямого урона до нового призыва.',
     'Сначала убей заклинателя, затем рыцаря. Сильные атаки придержи до обрыва связи.'),
    ('Короткие касты, парные заходы и кровотечение за атакующие действия.',
     'Полностью избежав его атаки, открой Аинза для одного удара с бонусом 30%.',
     'Не убегай всё время в одну сторону. Переживи пару клинков и отвечай быстрым навыком; при кровотечении полезна поддержка.'),
    ('Солнечные стрелы загибаются и оставляют на цели уязвимость.',
     'Чистая защита вынуждает перенатянуть тетиву: следующие два удара по Аинзу сильнее на 20%.',
     'Уводи прицел, затем меняй направление. Не стой вдоль световой дорожки и используй окно перезарядки.'),
    ('Очень тяжёлые удары и возвращающиеся кристаллические осколки.',
     'После казни и сокрушительного разворота два удара по Аинзу получают бонус 40%.',
     'Не начинай долгий каст перед замахом. Сначала переживи удар и обратный ход осколков, затем трать накопленные ресурсы.'),
    ('Белые доспехи адаптируются: два одинаковых типа урона подряд повышают соответствующую защиту на 25%.',
     'Смена типа урона после адаптации или действие поддержки сбрасывает её и открывает один усиленный на 20% удар.',
     'Чередуйте физические и магические атаки. В соло вставляй защиту или восстановление, а не повторяй один навык.'),
    ('Остановка времени, автономный посох, печати и подготовка ритуала смерти.',
     'Урон за подготовку ослабляет ритуал; после ослабленного ритуала или разреза реальности открываются два удара с бонусом 20%.',
     'Сохрани ресурсы на подготовку ритуала. В мини-игре читай надписи и выходи между траекториями вращающихся камней.'),
)


def opening(data,hits,value,label):
    m,boss=data['nazarick'],data['boss']
    m['ainz_opening_hits']=max(hits,m.get('ainz_opening_hits',0))
    boss['effects']=[e for e in boss['effects'] if e.get('id')!='ainz_form_opening']
    boss['effects'].append(dict(id='ainz_form_opening',kind='damage_taken_pct',value=value,duration=1000000,
        name=label,description=f'Следующие {m["ainz_opening_hits"]} попадания по Аинзу: входящий урон +{round(value*100)}%.'))


def clear_adaptation(data):
    m,boss=data['nazarick'],data['boss']
    adapted=m.get('ainz_damage_streak',0)>=2
    m['ainz_damage_streak']=0;m.pop('ainz_last_damage_type',None)
    boss['effects']=[e for e in boss['effects'] if e.get('id')!='ainz_form_adaptation']
    return adapted


def before_player(data,skill_id,skills):
    if data['nazarick']['phase']!=5:return
    skill=skills.get(skill_id)
    if skill_id=='defend' or skill and not skill.hostile:
        if clear_adaptation(data):opening(data,1,.20,'Сброшенная адаптация')


def after_player(data,skill,event):
    if not event.get('damage',0):return
    m,boss=data['nazarick'],data['boss']
    if m.get('ainz_opening_hits',0):
        m['ainz_opening_hits']-=1
        if not m['ainz_opening_hits']:
            boss['effects']=[e for e in boss['effects'] if e.get('id')!='ainz_form_opening']
    if m['phase']!=5 or not skill.damage_type:return
    last=m.get('ainz_last_damage_type');adapted=m.get('ainz_damage_streak',0)>=2
    if last and last!=skill.damage_type:
        clear_adaptation(data)
        if adapted:opening(data,1,.20,'Сломанная адаптация')
    m['ainz_damage_streak']=m.get('ainz_damage_streak',0)+1
    m['ainz_last_damage_type']=skill.damage_type
    if m['ainz_damage_streak']>=2:
        boss['effects']=[e for e in boss['effects'] if e.get('id')!='ainz_form_adaptation']
        kind='physical_defense_pct' if skill.damage_type=='physical' else 'magic_defense_pct'
        boss['effects'].append(dict(id='ainz_form_adaptation',kind=kind,value=.25,duration=1000000,
            name='Адаптация белых доспехов',description='Защита от повторяемого типа урона +25%.'))


def clean_guard(guard,skill_id):
    if not guard or 'pattern_dodge' not in guard:return False
    contacts=guard['pattern_dodge'].get('contacts',[])
    if guard.get('subskills'):
        if skill_id not in guard['subskills']:return False
        group=guard['subskills'].index(skill_id)
        contacts=[c for c in contacts if c.get('strike')==group]
    return not any(c.get('weight',0)>0 and c.get('reduction',0)<1 for c in contacts)


def after_boss(data,intent,clean=False,ritual_weakened=False):
    phase=data['nazarick']['phase']
    if phase==2 and clean:opening(data,1,.30,'Потерянный темп')
    elif phase==3 and clean:opening(data,2,.20,'Перенатяжение тетивы')
    elif phase==4 and intent.get('skill','').endswith(('_0','_3')):opening(data,2,.40,'Инерция тяжёлой секиры')
    elif phase==6 and (ritual_weakened or intent.get('skill','').endswith('_3')):opening(data,2,.20,'Разрыв магического контура')
