/* Fictional adult workers: production holdings API, never arena identities. */
window.NpcWorkers=(()=>{
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>Number(v||0).toLocaleString('ru-RU');
  const date=v=>new Date(v*1000).toLocaleString('ru-RU');
  const btn=(label,action,id='',primary=false)=>`<button type="button" data-npc-act="${action}" data-npc-id="${esc(id)}"${primary?' class="primary"':''}>${label}</button>`;
  const states={rest:'Отдыхает',work:'На работе',training:'Учится',expedition:'В экспедиции',missing:'Пропал',stock:'У торговца',runaway:'Беглец'};
  let ctx=null,guess=[],eventId=null;
  const bound=new WeakSet();
  function sprite(w,small=true){
    const url=small?w.thumbnail_url:w.sprite_url;
    return /^\/static\/assets\/npc-workers-v1\/(accountant|skeleton|paladin|diplomat|miner|mechanic)-(male|female)(-small)?\.png$/.test(url||'')
      ?`<img src="${esc(url)}" alt="" loading="lazy" decoding="async" width="${small?160:512}" height="${small?240:768}">`
      :`<span>${esc(w.icon)}</span>`;
  }
  function portrait(w,full=false){return `<div class="npc-portrait npc-${esc(w.profession)}" aria-hidden="true">${sprite(w,!full)}<i>NPC · ${w.age} лет</i></div>`}
  function badge(w){return `<span class="npc-quality" style="--quality:${esc(w.quality.color)}">${esc(w.quality.name)}</span>`}
  function metric(label,value,hint=''){return `<div><small>${label}</small><b>${value}</b>${hint?'<small>'+esc(hint)+'</small>':''}</div>`}
  function card(w,market=false){return `<article class="npc-card">${portrait(w)}<div class="npc-card-body"><div class="npc-card-heading">${badge(w)}<small>${esc(states[w.status])}</small></div><h3>${esc(w.name)}</h3><p>${esc(w.description)}</p><div class="npc-mini-stats">${metric('Содержание',num(w.upkeep)+' ₣/сут')}${metric(market?'Профессия':'Выносливость',market?esc(w.profession_name):w.health+'% HP · '+w.fatigue+'% уст.')}</div>${market?btn('Описание и особенности','card',w.id):''}${btn(market?'Приобрести · '+num(w.cost)+' ₣':'Карточка и управление',market?'buy':'card',w.id,true)}</div></article>`}
  function people(data){return (data.npc?.workers||[]).map(w=>{
    const s=data.sites.find(s=>s.id===w.site),leader=w.role==='leader';
    return {...w,is_npc:true,user_id:'npc_'+w.id,class_name:w.profession_name,business_id:w.site,
      role:leader?(s?.business_type==='field'?'overseer':s?.business_type==='brothel'?'manager':'leader'):'worker',
      away:w.status==='missing'||w.status==='training',expedition_active:w.status==='expedition',
      expedition_ready_at:w.ready_at,listed:false,name:w.name};
  })}
  function row(p,options){
    return '<div class="holdings-person-card"><label class="holdings-person"><input type="checkbox" data-h-person="'+p.user_id+'" aria-label="Выбрать '+esc(p.name)+'"'+(options.checked?' checked':'')+(options.disabled?' disabled':'')+'><span class="npc-roster-avatar" aria-hidden="true">'+sprite(p)+'</span><span class="holdings-person-info"><b>'+esc(p.name)+'</b>'+badge(p)+'<small>NPC · '+esc(p.profession_name)+' · ур. '+p.level+' · сила '+(p.power??'нужна оценка')+'</small>'+(p.passport?'<small>'+esc(p.passport.trait_name)+'</small>':'')+'<small>Содержание '+p.upkeep+' ₣/сут · усталость '+p.fatigue+'%</small></span><span class="holdings-job">'+esc(p.status==='work'?(p.role==='leader'||p.role==='overseer'||p.role==='manager'?'Управляющий':options.work?.title||'На работе'):states[p.status])+'</span></label>'+btn('Карточка и управление','card',p.id)+'</div>';
  }
  function overview(data){
    const n=data.npc,wf=n.workforce,events=wf.events.filter(e=>['open','playing','search'].includes(e.status));
    return '<article class="holdings-site npc-wallet"><div class="holdings-section-head"><h3>Содержание рабов</h3><b>'+num(n.daily_upkeep)+' ₣/сут</b></div><p class="muted">NPC оплачиваются автоматически из этого кошелька. Сегодня списано '+num(n.upkeep_today)+' ₣. При нехватке франков — без ухода в минус; неоплаченное содержание ухудшает условия.</p>'+btn('Условия и правила побегов','conditions')+
      (events.length?'<h3>Розыск</h3>'+events.map(e=>'<div class="npc-incident"><div><b>'+esc(e.name)+'</b><small>До '+date(e.deadline)+(e.bounty?' · награда '+num(e.bounty)+' ₣':'')+'</small></div>'+btn(e.mine?'Вернуть':'Помочь','event',e.id,true)+'</div>').join(''):'')+'</article>';
  }
  function protectionPanel(data){
    const p=data.protection;if(!p)return '';
    const events=p.events.filter(e=>e.status==='open');
    if(!events.length&&!p.outage_until)return '';
    return '<article class="holdings-site npc-protection"><h3>События предприятий</h3>'+(p.outage_until?'<div class="npc-warning">Простой до '+date(p.outage_until)+'. Выработка приостановлена, содержание продолжается.</div>':'')+events.map(e=>'<section class="npc-section"><div class="holdings-section-head"><h3>'+esc(e.name)+(e.mine?'':' · помощь соседу')+'</h3><small>До '+date(e.deadline)+'</small></div><p>'+esc(e.text)+'</p>'+(e.raid&&['lobby','active'].includes(e.raid_status)?'<p><a class="npc-raid-link" href="?tgWebAppStartParam=r_'+encodeURIComponent(e.raid)+'" target="_blank" rel="noopener">⚔️ Открыть '+(e.raid_status==='active'?'бой':'сбор защиты')+'</a></p><p class="muted">'+(e.announced?'Приглашение отправлено в чат.':'Приглашение в чат ожидает отправки. Лобби также доступно по ссылке выше.')+'</p>':e.mine?e.kind==='orcs'?'<p>Три орка A-ранга, Lv.19, 410–480 HP каждый. Фиксированная сила, 100 раундов. Владелец может остаться наблюдателем и начать бой отряда.</p>'+btn('Собрать защиту и позвать в чат','protection-raid',e.id,true):e.kind==='escape'?'<p>При игнорировании сбегут до трёх доступных работников. Затем каждому — отдельный розыск на 8 часов, без мгновенного освобождения. Экспедиции и чужие работники не затрагиваются.</p>'+btn('Улучшить условия · '+(100+25*p.workers)+' ₣ и 6 ч отдыха','protection-conditions',e.id,true):btn('Договориться · '+(100+20*p.workers)+' ₣ и 6 ч отдыха','protection-strike-paid',e.id,true)+btn('Дать 12 ч отдыха · без доплаты','protection-strike-free',e.id):'<p class="muted">Владелец ещё не открыл сбор. После его открытия появится ссылка для помощи.</p>')+'</section>').join('')+'</article>';
  }
  function protectionSettings(data){
    const p=data.protection;if(!p||!data.sites.length)return '';
    return '<footer class="npc-protection-settings"><small>'+(p.enabled?'Налог оплачивает крышу. Без неё возможны побеги, забастовки и набеги.':'Предприятия без крыши: налога на выработку нет, содержание и риски остаются.')+'</small><button type="button" class="npc-protection-switch" data-npc-act="protection-toggle">'+(p.enabled?'Отказаться от крыши':'Вернуть крышу · '+p.rejoin_fee+' ₣')+'</button><details><summary>Условия защиты</summary><p>Гильдия цивилизованного рэкета охраняет предприятия, пока ты платишь обычный прогрессивный налог. «Мы защищаем ваш бизнес от людей, которым сами сообщили о вашем бизнесе».</p><p>После первого отказа — сутки без новых угроз. Затем не чаще одной угрозы за 48 часов в этом чате и одного события на аккаунт за сутки. На решение — 24 часа. Возможны побег до трёх работников, забастовка или набег трёх орков A-ранга (защита отрядом 2–3 игроков).</p><p>Поражение или игнорирование набега/забастовки — 12 часов простоя. Беглецам запускается отдельный розыск. Возврат крыши за '+p.rejoin_fee+' ₣ не отменяет уже объявленные угрозы, розыск и простой; налоги задним числом не пересчитываются. Новый отказ — через сутки после переключения. Обычные побеги из-за плохих условий налог не предотвращает.</p>'+(p.enabled?'':'<p>Следующая угроза возможна после '+date(p.next_event)+'. Экспедиции, заказы торговца и NPC-содержание не освобождены от своих расходов.</p>')+'</details></footer>';
  }
  function expeditions(data){return (data.npc?.trips||[]).map(t=>{
    const m=data.missions.find(m=>m.id===t.mission),members=t.members||[];
    return {...t,started_at:t.started,ends_at:t.ends,quote:{name:m?.name,members,chance:Math.round((1-Math.pow(t.loss_percent/100,members.length))*100)},
      result:t.status==='active'?null:{won:!!t.survivors?.length,francs:t.francs||0,tax:t.tax||0,pages:t.pages||0,page_rarity:t.page_rarity,members:t.results||members.map(p=>({user_id:p.user_id,outcome:t.status==='cancelled'?'cancelled':'removed'}))}};
  })}
  function market(data){const n=data.npc;return '<article class="holdings-site"><h3>Рабы у торговца</h3><p class="muted">Новые NPC каждый день. Отдельного лимита количества нет. После покупки они появляются в общем списке «Рабы». Редкость раскрывается оценкой за 50 ₣.</p><div class="npc-grid">'+n.market.map(w=>card(w,true)).join('')+'</div></article>'}
  function conditions(){const n=ctx.getData().npc,wf=n.workforce;modal('Условия и побеги',
    '<p>Риск за сутки: <b>'+wf.risk.chance+'%</b>. '+(wf.risk.reasons.map(esc).join(' · ')||'Условия хорошие.')+'</p><p>Проверка условий действует 48 часов. Она не заменяет оплату содержания и отдых.</p>'+btn('Проверить условия','care','',true)+'<p>Сначала предупреждение на 24 часа, затем 8 часов на розыск. Есть мини-игра (3 минуты / 6 попыток), поисковая группа (100 ₣ / 2 часа), награда помощнику и выкуп похищенного (300 ₣).</p><p>Один суточный бросок на аккаунт: 0 / 2 / 5 / 10%. Большое число рабов само по себе не вызывает побеги. Охрана помогает против похищения, дипломат — при поиске и переговорах.</p><p>При провале игрок освобождается без потери арены, NPC становится беглецом с той же редкостью и историей. Содержание берётся из кошелька автоматически; резервов и отдельных слотов NPC нет.</p>');
  }
  async function quoteSelection(ids,users,mission){
    const r=await ctx.api('/api/holdings/'+ctx.getData().chat_id,{action:'npc_trip_quote',ids,users,mission,nonce:nonce()}),q=r.quote;
    confirm('Отправить отряд?',q.names.map(esc).join(', ')+'<br>Риск освобождения каждого: <b>'+q.loss_percent+'%</b>. Срок: '+q.duration/3600+' ч. При возвращении всех: '+q.francs+' ₣ до налога и '+q.pages+' стр. Результат фиксируется при отправке.','npc_trip','',{ids,users,mission,revision:q.revision});
  }
  function modal(title,body){ctx.modal(title,body);return document.querySelector('.holdings-dialog')}
  function wById(id){const n=ctx.getData().npc;return [...n.workers,...n.market].find(w=>w.id===id)}
  function openCard(id){details(wById(id))}
  function eventById(id){return ctx.getData().npc.workforce.events.find(e=>e.id===id)}
  function passport(w){
    const p=w.passport;if(!p)return '<p><b>Особенность:</b> '+esc(w.trait_text)+'</p><p class="muted">Обнови страницу, чтобы получить подробный паспорт NPC.</p>';
    return '<section class="holdings-passport npc-passport"><h3>'+esc(p.trait_name)+'</h3><p class="holdings-trait-flavor">«'+esc(p.trait_flavor)+'»</p><p>'+esc(p.trait_effect)+'</p>'+
      (p.rarity_bonus?'<p>Бонус редкости: <b>+'+num(p.rarity_bonus.income)+'%</b> к выработке и <b>+'+num(p.rarity_bonus.power)+'</b> к силе экспедиции до поправки на здоровье.</p>':'<div class="note">Редкость и её бонусы скрыты. Оценка у работорговца стоит 50 ₣. Открытие карточки бесплатно и ничего не списывает.</div>')+
      '<p><b>Подходящая работа: '+esc(p.preferred_work.name)+'</b> · +'+p.preferred_work.bonus+'% к выработке. Профессия сейчас добавляет +'+p.profession_bonus+'%.</p><p class="muted">Бонусы редкости, профессии, подходящей работы и особенности складываются. База NPC — 75% ставки активного работника; затем применяются здоровье и усталость.</p>'+
      '<details class="npc-fold"><summary>Выработка по предприятиям</summary><div class="npc-work-rates">'+p.workplaces.map(r=>'<div><span>'+esc(r.name)+(r.preferred?' · профиль':'')+'</span><b>'+(r.multiplier===null?'После оценки':num(Math.round(r.multiplier*10000)/100)+'% ставки')+'</b></div>').join('')+'</div><p class="muted">При текущем здоровье и усталости, до бонуса управляющего, налога и содержания. Это коэффициент выработки, не чистый доход в франках. Управляющий сам не производит доход, но даёт предприятию +20% активной выручки.</p></details>'+
      '<p><b>Редкость и особенность постоянны.</b> Обучение, отдых, освобождение и смена владельца не перебрасывают их. У NPC одна профессия и связанная с ней особенность; бонусы не создают персонажа и не усиливают арену.</p></section>';
  }
  function details(w){
    if(!w)return;const data=ctx.getData(),owned=data.npc.workers.some(p=>p.id===w.id),site=data.sites.find(s=>s.id===w.site);
    const workplace=site?(site.title+' · '+(w.role==='leader'?'Управляющий':'Работник')):'Не назначен';
    const state='<p class="npc-current-state"><b>'+esc(states[w.status]||w.status)+'</b> · '+esc(workplace)+(w.status==='expedition'&&w.ready_at?' · следующий поход после '+date(w.ready_at):'')+'</p>';
    const conditions='<details class="npc-fold"><summary>Содержание, состояние и побеги</summary><p>Содержание '+w.upkeep+' ₣/сут списывается частями каждый час из кошелька этого чата. Оплачивается и на отдыхе, и на обучении; во время экспедиции и пропажи не списывается. При нехватке франков NPC не производит доход; кошелёк не уходит в минус.</p><p>Здоровье пропорционально уменьшает выработку и силу экспедиции. Ниже 30 NPC не работает. Усталость от 70 уменьшает выработку ещё на 30%; отдых убирает 3 усталости в час. При оплаченном уходе здоровье растёт на 1, лояльность на 1 каждые 6 часов; без оплаты здоровье теряет 2, лояльность — 3.</p><p>Усталость от 80, здоровье ниже 50 или лояльность ниже 40 ухудшают условия всего хозяйства. Сначала предупреждение на 24 часа, затем возможен побег или похищение с 8 часами на розыск. Большое количество рабов само по себе не вызывает побег.</p><p>Сила экспедиции = (20 + 4 × боевой уровень + бонус редкости'+(w.profession==='paladin'?' + 10 за профессию':'')+') × здоровье / 100. Усталость напрямую не уменьшает эту силу. Точный риск зависит от миссии и отряда — проверяй перед отправкой. Проигранный розыск освобождает NPC, сохраняя его редкость и историю.</p></details>';
    const management=owned?'<div class="holdings-buttons">'+(!w.appraised?btn('Оценить · 50 ₣','appraise',w.id,true):'')+btn('Отдыхать','rest',w.id)+'</div><label>Предприятие<select id="npc-site">'+data.sites.map(s=>'<option value="'+s.id+'"'+(s.id===w.site?' selected':'')+'>'+esc(s.title)+' · '+(s.workers.length+(s.npc_count||0))+'/'+s.capacity+'</option>').join('')+'</select></label>'+btn('Назначить работником','assign',w.id,true)+'<details class="npc-fold"><summary>Обучение и история</summary><p>Работа автоматически даёт час опыта за час выработки. Каждые 240 ч — уровень профессии до 10; каждый уровень после первого даёт +2% выработки. Платное обучение: +1 уровень профессии за 12 ч и '+w.profession_level*100+' ₣; боевая подготовка: +1 уровень за 18 ч и '+w.level*100+' ₣ (до 20). Во время обучения NPC не работает, но требует содержания.</p><div class="holdings-buttons">'+btn('Обучить профессии','train-work',w.id)+btn('Боевая подготовка','train-combat',w.id)+'</div>'+(w.training?'<p>Обучение завершится '+date(w.training.ends)+'</p>':'')+(w.history||[]).map(h=>'<p><small>'+date(h.at)+'</small> · '+esc(h.text)+'</p>').join('')+'</details><hr>'+btn('Освободить NPC','release',w.id):btn('Приобрести · '+num(w.cost)+' ₣','buy',w.id,true);
    modal(w.name,portrait(w,true)+badge(w)+'<p>'+esc(w.description)+'</p>'+state+passport(w)+'<div class="npc-dashboard">'+metric('Здоровье',w.health+' / 100','Влияет на выработку и силу')+metric('Усталость',w.fatigue+' / 100','От 70: −30% выработки')+metric('Лояльность',w.loyalty+' / 100','Ниже 40: плохие условия')+metric('Сила экспедиции',w.power??'Оцени NPC','Не урон на арене')+'</div><p>Боевой уровень '+w.level+'/20 · профессия '+w.profession_level+'/10 · опыт работы '+w.experience+'/240 ч.</p>'+conditions+management);
  }
  function recovery(e){eventId=e.id;guess=[];const p=e.status==='playing';const m=modal(e.name+' · розыск',`<div class="npc-warning"><b>Внешний срок: ${date(e.deadline)}</b><p>Отсутствующий не приносит доход. Таймер идёт даже без владельца.</p><b data-npc-countdown="${p?e.game_ends:e.deadline}"></b></div>${e.status==='search'?`<p>Поиск идёт до ${date(e.search_ends)}. Результат уже зафиксирован; обновление его не меняет.</p>`:e.mine?`${p?`<p>Найди три разных символа. «На месте» — правильный символ и позиция, «рядом» — символ правильный, позиция нет. Шесть попыток.</p><div class="npc-code"><b id="npc-guess">— — —</b><div>${ctx.getData().npc.workforce.symbols.map((s,i)=>btn(esc(s),'symbol',i)).join('')}</div>${btn('Стереть','undo')}${btn('Проверить код','guess',e.id,true)}</div><ol>${e.history.map(h=>`<li>${h.guess.map(i=>ctx.getData().npc.workforce.symbols[i]).join(' ')} · на месте ${h.exact}, рядом ${h.near}</li>`).join('')}</ol>`:btn('Начать мини-игру · 3 мин','start',e.id,true)}<div class="holdings-buttons">${btn('Поисковая группа · 100 ₣','search',e.id)}${!e.bounty?btn('Объявить награду','bounty',e.id):''}${e.kind==='kidnapped'?btn('Выкупить · 300 ₣','ransom',e.id):''}</div>${btn('Отказаться от работника','abandon',e.id)}`:btn('Взять заказ · 2 ч','help',e.id,true)}`);updateTimers();return m}
  function confirm(title,body,action,id,extra={}){const d=modal(title,`<p>${body}</p>${btn('Подтвердить','confirm',id,true)}`);d._npcBody={action,id,...extra}}
  function nonce(){return crypto.randomUUID().replaceAll('-','')}
  async function send(body,reopen){const ok=await ctx.mutate({...body,nonce:nonce(),confirm:true});if(ok&&reopen){const e=eventById(reopen);if(e&&['open','playing','search'].includes(e.status))recovery(e)}return ok}
  async function click(ev){const el=ev.target.closest('[data-npc-act]');if(!el||!ctx||el.disabled)return;const act=el.dataset.npcAct,id=el.dataset.npcId,w=wById(id),e=eventById(id);ev.preventDefault();
    if(act.startsWith('protection-')){
      const p=ctx.getData().protection,t=p.events.find(e=>e.id===id);
      if(act==='protection-toggle'){
        confirm(p.enabled?'Отказаться от крыши?':'Вернуть крышу?',p.enabled?'Налог с будущей выработки отключится только у твоих предприятий этого чата. Через сутки начнутся угрозы; нужны время и сильные помощники. Содержание остаётся.':'250 ₣ за регистрацию. Уже начавшиеся события и простой остаются. Старые налоги не пересчитываются.','protection_toggle','',{enabled:!p.enabled,revision:p.revision});return;
      }
      if(!t||!t.mine)return;
      const body={id,revision:t.revision};
      if(act==='protection-raid'){await send({action:'protection_raid',...body});return}
      if(act==='protection-conditions'){confirm('Предотвратить побег?','Стоимость '+(100+25*p.workers)+' ₣, затем 6 часов оплаченного отдыха предприятий. Содержание продолжается.','protection_conditions',id,{revision:t.revision});return}
      confirm('Соглашение с работниками?',act==='protection-strike-paid'?'Стоимость '+(100+20*p.workers)+' ₣ и 6 часов простоя.':'12 часов простоя без дополнительной выплаты; содержание NPC продолжается.','protection_strike',id,{revision:t.revision,paid:act==='protection-strike-paid'});return;
    }
    if(act==='open'||act==='conditions'){conditions();return}
    if(act==='card'){details(w);return}if(act==='event'){recovery(e);return}
    if(act==='care'){await send({action:'npc_care'});return}
    if(act==='buy'){confirm('Приобрести NPC?',esc(w.name)+' · '+num(w.cost)+' ₣. Ежедневное содержание '+w.upkeep+' ₣; редкость скрыта до оценки.','npc_buy',id);return}
    if(act==='appraise'){confirm('Оценить NPC?', '50 ₣. Это раскрывает постоянную редкость; повторного розыгрыша нет.','npc_appraise',id,{revision:w.revision});return}
    if(act==='assign'){const site=Number(document.querySelector('#npc-site').value);await send({action:'npc_assign',id,site,revision:w.revision});return}
    if(act==='rest'){await send({action:'npc_rest',id,revision:w.revision});return}
    if(act.startsWith('train-')){const kind=act.slice(6);confirm('Начать обучение?',(kind==='work'?12:18)+' часов без выработки, '+100*(kind==='work'?w.profession_level:w.level)+' ₣. Содержание продолжает оплачиваться.','npc_train',id,{kind,revision:w.revision});return}
    if(act==='release'){confirm('Освободить NPC?', 'Он перестанет принадлежать тебе и станет беглецом. Денег за освобождение нет.','npc_release',id,{revision:w.revision});return}
    if(act==='confirm'){const b=document.querySelector('.holdings-dialog')._npcBody;const ok=await send(b);if(b.action==='npc_trip'&&ok)ctx.onTripStarted();return}
    if(act==='symbol'){if(guess.length<3&&!guess.includes(Number(id)))guess.push(Number(id));document.querySelector('#npc-guess').textContent=[0,1,2].map(i=>ctx.getData().npc.workforce.symbols[guess[i]]||'—').join(' ');return}
    if(act==='undo'){guess.pop();document.querySelector('#npc-guess').textContent=[0,1,2].map(i=>ctx.getData().npc.workforce.symbols[guess[i]]||'—').join(' ');return}
    if(['start','guess','search','ransom','help','abandon'].includes(act)){
      if(act==='guess'&&guess.length!==3)return;
      if(['search','ransom','abandon','help'].includes(act)){confirm('Подтвердить действие?',({search:'100 ₣, результат через 2 часа. Неудачный поиск оставляет время на другие способы.',ransom:'300 ₣ за гарантированное возвращение похищенного.',abandon:'Владение будет прекращено. NPC станет беглецом, игрок освободится.',help:'Поисковая группа вернётся через 2 часа. Награда начислится только при успехе.'})[act],'workforce_'+act,id,{revision:e.revision});return}
      await send({action:'workforce_'+act,id,revision:e.revision,...(act==='guess'?{guess:[...guess]}:{})},id);return
    }
    if(act==='bounty'){const d=modal('Награда за розыск',`<label>Франков<input id="npc-amount" type="number" value="200" min="50" max="10000"></label><p>Сумма резервируется. Получить её может другой участник этого чата при успешном поиске. При неудаче деньги возвращаются.</p>${btn('Разместить','bounty-confirm',id,true)}`);d._npcRevision=e.revision;return}
    if(act==='bounty-confirm'){await send({action:'workforce_bounty',id,revision:document.querySelector('.holdings-dialog')._npcRevision,amount:Number(document.querySelector('#npc-amount').value)},id);return}

  }
  function updateTimers(){if(!ctx?.getData())return;const stamp=ctx.stamp();for(const e of document.querySelectorAll('[data-npc-countdown]')){const s=Math.max(0,Number(e.dataset.npcCountdown)-stamp);e.textContent=Math.floor(s/3600)+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}
  setInterval(updateTimers,1000);
  function mount(c){
    ctx=c;if(!c.getData().npc)return;const data=c.getData(),wf=data.npc.workforce,screen=c.app.querySelector('#holdings-screen');
    const missing=wf.events.filter(e=>e.mine&&['open','playing','search'].includes(e.status));
    if(wf.warning||missing.length)c.app.querySelector('.holdings-tabs')?.insertAdjacentHTML('afterend','<div class="npc-warning"><b>'+(missing.length?'🚨 Пропавших работников: '+missing.length:'⚠ В хозяйстве плохие условия')+'</b><p>'+(missing.length?'Срок розыска уже идёт: 8 часов после извещения.':wf.risk.reasons.map(esc).join(' · ')+' · исправь до '+date(wf.warning.deadline))+'</p>'+btn('Условия и розыск','conditions')+(missing.length?missing.map(e=>btn('Вернуть: '+esc(e.name),'event',e.id)).join(''):'')+'</div>');
    if(c.tab==='overview')screen.insertAdjacentHTML('afterbegin',overview(data));
    if(c.tab==='overview'||c.tab==='sites')screen.insertAdjacentHTML('afterbegin',protectionPanel(data));
    if(c.tab==='sites')screen.insertAdjacentHTML('beforeend',protectionSettings(data));
    if(c.tab==='trader')screen.insertAdjacentHTML('afterbegin',market(data));
    if(!bound.has(c.app)){c.app.addEventListener('click',click);bound.add(c.app)}
  }
  document.addEventListener('click',e=>{if(e.target.closest('.holdings-dialog'))click(e)});
  return {mount,people,row,expeditions,quoteSelection,openCard,leave(){},due(data,stamp){if(!data?.npc)return false;const n=data.npc;return data.protection?.events.some(e=>e.status==='open'&&e.deadline<=stamp)||(!data.protection?.enabled&&data.protection?.next_event<=stamp)||n.trips.some(t=>t.status==='active'&&t.ends<=stamp)||n.workers.some(w=>w.training&&w.training.ends<=stamp)||n.workforce.events.some(e=>['open','playing','search'].includes(e.status)&&(e.deadline<=stamp||e.search_ends<=stamp||e.game_ends<=stamp))}};
})();
