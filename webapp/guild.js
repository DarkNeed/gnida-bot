/* Hunter guild UI. All ranks, votes, loot and encounters are server-owned. */
(()=>{
  'use strict';
  let previous;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={hunt:'Охота',elite:'Особый заказ',dungeon:'Подземелье',calibration:'Квалификация'};
  const states={lobby:'Сбор отряда',active:'В пути',completed:'Выполнено',failed:'Поражение',retreated:'Отступление',cancelled:'Отменено'};
  const rooms={entry:'Вход',battle:'Бой',elite:'Элита',boss:'Хозяин',event:'Событие',treasure:'Сокровища',rest:'Привал',unknown:'Неизвестно'};
  const sigil='<svg viewBox="0 0 100 100" fill="none" aria-hidden="true"><path d="M50 9 80 26v40L50 91 20 66V26z"/><path d="m33 30 17 40 17-40M24 17l10 27 16 8 16-8 10-27M19 32l18 12m44-12L63 44M38 78l12-8 12 8"/><circle cx="50" cy="32" r="6"/></svg>';
  const icon=kind=>'<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">'+({
    entry:'<path d="M7 26V8l9-4 9 4v18M12 26V13h8v13"/>',
    battle:'<path d="m6 4 20 24M26 4 6 28M3 22l8 7m10 0 8-7M6 4l6 2-4 4m18-6-6 2 4 4"/>',
    elite:'<path d="m16 2 12 14-12 14L4 16zM9 16h14M16 8v16"/>',
    boss:'<path d="M7 21 4 7l8 5 4-8 4 8 8-5-3 14zM8 26h16"/>',
    event:'<path d="M11 10a5 5 0 1 1 9 3l-4 3v4"/><circle cx="16" cy="25" r="1"/>',
    treasure:'<path d="M4 13h24v14H4zM4 13l4-7h16l4 7M14 13v6h4v-6"/>',
    rest:'<path d="M13 4c7 9-7 11-1 19 0-5 7-6 7-12 13 14 0 22-8 16-6-4-7-13 2-23zM5 30h22"/>',
    unknown:'<path d="m16 3 12 7v13l-12 6-12-6V10z"/><path d="M13 13a3 3 0 1 1 5 2l-2 2v2m0 3v1"/>',
  })[kind]+'</svg>';
  const button=(text,action,style='',disabled=false)=>'<button type="button" data-guild="'+esc(action)+'" class="'+style+'"'+(disabled?' disabled':'')+'>'+text+'</button>';
  const badge=(rank,small=false)=>'<span class="guild-rank'+(small?' tiny':'')+'" data-rank="'+esc(rank)+'">'+esc(rank)+'</span>';
  const monsterArt=m=>m.sprite;
  window.GuildApp={open};

  async function open(context){
    previous?.abort();const abort=new AbortController();previous=abort;
    const app=context.app,init=context.initData??window.Telegram?.WebApp?.initData??'';
    let chat=context.chat??null,view,run=null,chats=[],tab='board',filter='all',rankFilter='recommended',busy=false,runId=context.runId||'',timer;
    const avatarCache=new Map();
    const toast=m=>context.toast?.(m);
    async function api(path,body){
      const res=await fetch(path,{method:body?'POST':'GET',signal:abort.signal,headers:{'X-Telegram-Init-Data':init,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
      const value=await res.json();if(!res.ok)throw Error(value.error||'Не удалось связаться с гильдией.');return value;
    }
    function header(){return '<header class="guild-header"><div class="guild-brand">'+sigil+'<div><small>ГНИДА · НОВАЯ ИСТОРИЯ</small><h1>Гильдия охотников</h1></div></div><div class="guild-header-right">'+(view?'<span class="guild-money">'+view.francs+' <small>₣</small></span>':'')+button('Арена','arena','guild-quiet')+'</div></header>';}
    function shell(body){
      if(abort.signal.aborted)return;
      body='<div style="display:flex;justify-content:flex-end;margin:12px 0">'+button('◇ Снаряжение · общий инвентарь','equipment','guild-quiet')+'</div>'+body;
      app.innerHTML='<section class="guild">'+header()+'<div class="guild-chatline"><label>Отделение <select id="guild-chat" aria-label="Чат гильдии">'+chats.map(c=>'<option value="'+c.chat_id+'"'+(c.chat_id===chat?' selected':'')+'>'+esc(c.title||c.chat_id)+'</option>').join('')+'</select></label><span>Ранг и полные награды общие · кошелёк выбранного чата</span></div>'+body+'<footer class="guild-footer">ГИЛЬДИЯ / F — S <span>Походы без лимита · полные награды обновляются в 00:00 МСК</span></footer></section>';
    }
    function navigation(){return '<nav class="guild-nav" aria-label="Разделы гильдии">'+[['board','Заказы'],['dungeons','Подземелья'],['hunter','Удостоверение'],['shop','Лавка'],['bestiary','Бестиарий'],['top','Зал славы']].map(([id,n])=>button(n,'tab:'+id,tab===id?'active':'')).join('')+'</nav>';}
    function hero(){
      const h=view.hunter,d=view.daily;
      return '<section class="guild-hero"><div class="guild-hero-copy"><p class="guild-kicker">КОНТРАКТЫ · РЕПУТАЦИЯ · ЭКСПЕДИЦИИ</p><h2>У каждого чудовища<br>есть своя цена.</h2><p>Охоться один. Собери отряд. Выбери тропу,<br>с которой сумеешь вернуться.</p></div><div class="guild-license">'+sigil+badge(h.rank_name)+'<small>ЛИЦЕНЗИЯ ОХОТНИКА</small><strong>'+h.reputation+' / 100 репутации</strong><div class="guild-meter"><i style="width:'+h.reputation+'%"></i></div><p>Полных наград: '+d.remaining+' / '+d.limit+' на сегодня<br>Число походов не ограничено</p></div></section>';
    }
    function orderCard(c){
      const monster=view.monsters.find(m=>m.id===(c.kind==='hunt'?c.monsters[0]:c.monsters.at(-1)));
      return '<article class="guild-order'+(c.locked?' locked':'')+'"><div class="guild-order-head">'+badge(c.rank,true)+'<span>'+esc(labels[c.kind])+'</span><small>'+esc(c.code||c.id)+' · '+esc(c.rooms)+'</small></div><div class="guild-order-art">'+(monster?'<img src="'+monsterArt(monster)+'" alt="'+esc(monster.name)+'">':'')+'<div class="guild-art-lines"></div></div><div class="guild-order-copy"><h3>'+esc(c.name)+'</h3><p>'+esc(c.description)+'</p><div class="guild-order-tags"><span>Lv. '+c.level+'</span><span>'+(c.recommended_party>1?'Отряд '+c.recommended_party+'–3':'Соло / отряд')+'</span><span>Без подстройки уровня</span></div><div class="guild-order-reward"><strong>'+(c.reward_preview?.francs_base??c.reward)+' ₣</strong><span>'+esc(view.daily.full?(c.kind==='hunt'?'Припас в награду':'Припас + трактат'):'25% франков · дроп вещей прежний')+'</span></div>'+button(c.locked?'Нужен ранг '+view.ranks[Math.max(0,view.ranks.indexOf(c.rank)-1)]:'Принять заказ','accept:'+c.id,c.locked?'':'primary',c.locked||busy||!!view.active)+'</div></article>';
    }
    function lobbyCard(r){return '<article class="guild-lobby"><div>'+badge(r.contract.rank,true)+'<span><strong>'+esc(r.contract.name)+'</strong><small>'+r.members.map(p=>esc(p.name)).join(' · ')+' · '+r.members.length+'/3</small></span></div>'+button('К отряду','run:'+r.id,'guild-quiet')+'</article>';}
    function board(){
      const orders=view.contracts.filter(c=>(tab==='dungeons'?c.kind==='dungeon':filter==='all'||c.kind===filter)&&
        (rankFilter==='all'||(rankFilter==='recommended'?(c.rank===view.hunter.rank_name||c.rank===view.ranks[Math.min(6,view.hunter.rank+1)]):c.rank===rankFilter)));
      const rankSelect='<label class="guild-rank-filter">Ранг заказа <select id="guild-rank" aria-label="Ранг заказа">'+[['recommended','Рекомендуемые'],['all','Все ранги'],...view.ranks.map(r=>[r,'Ранг '+r])].map(([id,name])=>'<option value="'+id+'"'+(rankFilter===id?' selected':'')+'>'+name+'</option>').join('')+'</select></label>';
      const active=view.active?'<section class="guild-resume"><div><span class="guild-kicker">'+esc(states[view.active.status])+'</span><h3>'+esc(view.active.contract.name)+'</h3><p>Сохранённый поход · '+view.active.members.length+' охотника</p></div>'+button('Продолжить →','run:'+view.active.id,'primary')+'</section>':'';
      const trial=view.hunter.calibration_rank?'<div class="guild-trial"><div><b>Ты уже умеешь сражаться?</b><p>Одноразовое одиночное испытание на ранг '+view.hunter.calibration_rank+'. Доступно до первого результата в гильдии. Начало не расходует полную награду.</p></div>'+button('Пройти квалификацию','accept:calibration','guild-quiet',!!view.active)+'</div>':'';
      shell((context.boardOnly?'':hero())+navigation()+active+trial+'<div class="guild-section-title"><div><p class="guild-kicker">'+(tab==='dungeons'?'ВЫБЕРИ МАРШРУТ':'ДОСКА ГИЛЬДИИ')+'</p><h2>'+(tab==='dungeons'?'За порогом безопасных дорог':'Чудовища не ждут')+'</h2></div>'+rankSelect+(tab==='board'?'<div class="guild-filters">'+[['all','Все'],['hunt','Охота'],['elite','Особые']].map(([id,n])=>button(n,'filter:'+id,filter===id?'active':'')).join('')+'</div>':'')+'</div><p class="guild-hint">Доступны заказы до ранга '+view.ranks[Math.min(6,view.hunter.rank+1)]+'. Походы без лимита. Полных наград осталось '+view.daily.remaining+' / 3. Далее: 25% франков, 30% репутации, половина материалов (минимум 1), без припаса и трактата. Дроп экипировки прежний.</p><div class="guild-orders">'+orders.map(orderCard).join('')+'</div><section class="guild-section"><div class="guild-section-title"><h2>Отряды отделения</h2>'+button('Обновить','reload','guild-quiet')+'</div><p>Выбери заказ → «Позвать в чат». Друзья смогут вступить прямо по кнопке. Команды: /охота F1 и /позвать.</p>'+view.lobbies.map(lobbyCard).join('')+(view.lobbies.length?'':'<div class="guild-empty">Сейчас здесь тихо. Первый заказ может стать твоим.</div>')+'</section>');
    }
    function hunter(){
      const h=view.hunter,total=h.wins+h.losses;
      shell(navigation()+'<section class="guild-certificate"><div>'+sigil+badge(h.rank_name)+'<p class="guild-kicker">УДОСТОВЕРЕНИЕ ОХОТНИКА</p><h2>Твоё имя ещё запомнят.</h2><p>Лучший достигнутый ранг: '+h.peak_rank_name+'</p></div><div class="guild-statgrid">'+[['Успешных заказов',h.wins],['Неудач',h.losses],['Подземелий',h.dungeons],['Успешность',total?Math.round(100*h.wins/total)+'%':'—']].map(([n,v])=>'<article><strong>'+v+'</strong><span>'+n+'</span></article>').join('')+'</div></section><div class="guild-panels"><section class="guild-panel"><h3>Путь к следующему рангу</h3><div class="guild-meter"><i style="width:'+h.reputation+'%"></i></div><p>'+h.reputation+'/100 репутации · '+h.rank_wins+'/3 зачётных побед · '+(h.clearance?'✓ Особый заказ пройден':'Нужна победа в особом заказе или подземелье')+'</p><p>За свой ранг: +28. На ранг выше: +40. Более лёгкие задания не повышают репутацию. После 100 очков, трёх зачётных побед и особого заказа — повышение.</p></section><section class="guild-panel"><h3>Право на ошибку</h3><p>Провал: −12 репутации. Понижение на один ранг возможно только при нуле репутации и трёх неудачах подряд. Купленные предметы не отбираются.</p><p>Закрытие приложения не считается поражением. На поход — 48 часов, на сбор — 30 минут. Во время боя обычный таймер раунда: две минуты.</p></section></div><section class="guild-section"><h2>Последние заказы</h2>'+view.history.map(r=>'<div class="guild-history"><span>'+esc(r.name)+'</span><span>'+esc(states[r.status])+'</span>'+button('Итоги','run:'+r.id,'guild-quiet')+'</div>').join('')+(view.history.length?'':'<p>Здесь появятся завершённые походы.</p>')+'</section>');
    }
    function shop(){shell(navigation()+'<div class="guild-section-title"><div><p class="guild-kicker">ЛАВКА · РАНГ '+view.hunter.rank_name+'</p><h2>Вернуться — тоже мастерство.</h2></div><strong>'+view.francs+' ₣</strong></div><p class="guild-hint">Припасы хранятся на аккаунте и используются только в походах гильдии, вне боя. Один припас на участника между комнатами. Франки списываются из выбранного чата.</p><div class="guild-shop-grid">'+view.shop.map(s=>'<article class="guild-panel"><div class="guild-order-head">'+badge(s.rank,true)+'<small>В рюкзаке: '+(view.bag[s.id]||0)+'</small></div><h3>'+esc(s.name)+'</h3><p>'+esc(s.description)+'</p>'+button(s.locked?'Откроется на ранге '+s.rank:'Купить · '+s.price+' ₣','buy:'+s.id,s.locked?'':'primary',s.locked||busy||view.francs<s.price)+'</article>').join('')+'</div>');}
    function bestiary(){shell(navigation()+'<div class="guild-section-title"><div><p class="guild-kicker">ПОЛЕВОЙ СПРАВОЧНИК</p><h2>Знай свою добычу.</h2></div><small>'+view.monsters.length+' видов</small></div><div class="guild-bestiary">'+view.monsters.map(m=>'<article class="guild-panel">'+badge(m.rank,true)+'<img src="'+monsterArt(m)+'" alt="'+esc(m.name)+'" loading="lazy" decoding="async"><h3>'+esc(m.name)+'</h3><p>'+esc(m.role)+'</p><small>Основа: '+m.hp+' HP · атака '+m.attack+' · защита '+m.armor+' · уклонение '+m.evasion+'%</small></article>').join('')+'</div><p class="guild-hint">В особых заказах цель усилена: HP ×1,45. На двух/трёх охотников HP ×1,6/×2,2. Уровень и атака не зависят от уровня отряда. Шаман лечит союзников; стая выбирает раненых; огонь подавляет восстановление тролля.</p>');}
    function leaderboard(){shell(navigation()+'<div class="guild-section-title"><div><p class="guild-kicker">ЗАЛ СЛАВЫ · ОБЩИЙ ДЛЯ ВСЕХ ЧАТОВ</p><h2>Они возвращались.</h2></div></div><div class="guild-ranking">'+view.leaderboard.map((h,i)=>'<article><b class="guild-place">'+String(i+1).padStart(2,'0')+'</b>'+badge(h.rank_name,true)+'<div><strong>'+esc(h.name||h.actor_id)+'</strong><small>'+h.reputation+' репутации · '+h.wins+' заказов · '+h.dungeons+' подземелий</small></div><span>'+((h.wins+h.losses)?Math.round(h.wins/(h.wins+h.losses)*100)+'%':'—')+'<small>успех</small></span></article>').join('')+'</div><p class="guild-hint">Сортировка: текущий ранг → репутация → выполненные заказы. Лёгкие заказы не заменяют высокие ранги. SS, SSS и легендарные лицензии пока не введены.</p>');}
    function render(){if(run){renderRun();return;}if(tab==='hunter')hunter();else if(tab==='shop')shop();else if(tab==='bestiary')bestiary();else if(tab==='top')leaderboard();else board();}
    function party(r){return '<div class="guild-party">'+r.members.map(p=>{
      const initials=(p.name.match(/[\p{L}\p{N}]+/gu)||[]).slice(0,2).map(w=>Array.from(w)[0]).join('').toUpperCase()||'?';
      return '<article><span class="guild-member-avatar" data-avatar-user="'+p.actor_id+'" role="img" aria-label="Аватар: '+esc(p.name)+'"><span class="guild-avatar-fallback" aria-hidden="true">'+esc(initials)+'</span></span><div class="guild-member-info"><div class="guild-member-heading"><b>'+esc(p.name)+'</b><span class="guild-member-rank" title="Ранг охотника: '+esc(p.rank)+'" aria-label="Ранг охотника '+esc(p.rank)+'">'+esc(p.rank)+'</span>'+(p.actor_id===r.leader?'<small class="guild-member-leader">Лидер</small>':'')+'</div>'+(p.hp!==null?'<div class="guild-mini-hp"><i style="width:'+100*p.hp/p.max_hp+'%"></i></div><small>'+p.hp+'/'+p.max_hp+' HP · '+p.resource+'/'+p.resource_max+' энергии'+(p.withdrawn?' · покинул отряд':'')+'</small>':'<small>Обычный персонаж · снимок при старте</small>')+'</div></article>';
    }).join('')+'</div>';}
    async function avatarUrl(user,ident){
      if(!avatarCache.has(user)){
        const entry={url:null,promise:null};avatarCache.set(user,entry);
        entry.promise=(async()=>{
          try{
            const res=await fetch('/api/guild/runs/'+encodeURIComponent(ident)+'/avatars/'+user,{signal:abort.signal,headers:{'X-Telegram-Init-Data':init}});
            if(!res.ok)return null;
            const blob=await res.blob();if(abort.signal.aborted||!['image/jpeg','image/png','image/webp'].includes(blob.type))return null;
            entry.url=URL.createObjectURL(blob);return entry.url;
          }catch{return null;}
        })();
      }
      return avatarCache.get(user).promise;
    }
    function hydrateAvatars(){
      const ident=run?.id;if(!ident)return;
      for(const node of app.querySelectorAll('.guild-member-avatar')){
        avatarUrl(Number(node.dataset.avatarUser),ident).then(url=>{
          if(!url||abort.signal.aborted||!node.isConnected)return;
          const image=document.createElement('img');image.alt='';image.setAttribute('aria-hidden','true');
          image.onload=()=>node.classList.add('has-photo');image.onerror=()=>image.remove();image.src=url;node.append(image);
        });
      }
    }
    function map(r){
      const coord=n=>({x:72+n.layer*145,y:68+n.lane*88});
      let paths='';for(const n of r.nodes)for(const id of n.links){const next=r.nodes.find(v=>v.id===id),a=coord(n),b=coord(next);paths+='<path d="M'+a.x+' '+a.y+'C'+(a.x+70)+' '+a.y+' '+(b.x-70)+' '+b.y+' '+b.x+' '+b.y+'" class="'+(n.cleared?'passed':'')+'"/>';}
      const current=r.nodes.find(n=>n.id===r.position),links=!r.battle&&!r.pending&&current?.cleared?current.links:[];
      return '<div class="guild-map-scroll"><div class="guild-map"><svg class="guild-map-lines" viewBox="0 0 870 340" aria-hidden="true">'+paths+'</svg>'+r.nodes.map(n=>{const p=coord(n),can=links.includes(n.id)&&r.status==='active'&&r.members.some(m=>m.actor_id===view.actor_id&&m.hp>0&&!m.withdrawn)&&!r.votes[view.actor_id];return '<button data-guild="node:'+n.id+'" class="guild-node '+(n.cleared?'cleared ':'')+(n.id===r.position?'current ':'')+(can?'available ':'')+'" style="left:'+p.x+'px;top:'+p.y+'px"'+(!can?' disabled':'')+' aria-label="'+esc(rooms[n.kind])+' · '+n.id+(can?' · выбрать':'')+'">'+icon(n.kind)+'<span>'+esc(rooms[n.kind])+'</span></button>';}).join('')+'</div></div>';
    }
    function renderRun(){
      const r=run,c=r.contract,member=r.members.some(p=>p.actor_id===view.actor_id),leader=r.leader===view.actor_id;
      const inviteWait=Math.max(0,Math.ceil(((r.invite?.available_at||0)-r.server_time)/60));
      const canInvite=leader&&!c.calibration&&r.members.length<3;
      const top='<div class="guild-run-title"><div>'+badge(c.rank)+'<div><p class="guild-kicker">'+esc(states[r.status])+' · '+esc(labels[c.kind])+'</p><h2>'+esc(c.code||view.contracts.find(x=>x.id===c.id)?.code||'')+' · '+esc(c.name)+'</h2></div></div>'+button('← К заказам','back','guild-quiet')+'</div>';
      let body=top+party(r);
      if(r.status==='lobby')body+='<section class="guild-panel guild-reward-preview"><p class="guild-kicker">НАГРАДЫ КАЖДОГО УЧАСТНИКА</p>'+r.members.map(p=>{
        const reward=p.reward_preview;
        return '<div class="guild-history"><b>'+esc(p.name)+'</b><span>'+(reward?.full?'Полная награда · осталось '+reward.remaining:'Повтор: 25% франков · 30% репутации')+'</span><span>'+(reward?.francs_base??c.reward)+' ₣ + находки · '+(reward?.reputation??0)+' репутации</span></div>';
      }).join('')+'<p>Первые три победы в день: полные награды. Далее — 25% франков, 30% репутации и половина материалов (минимум 1), без трактата и бесплатного припаса. Экипировка и редкость не урезаются; в данже гарантированная вещь остаётся.</p><small>Счётчик общий на аккаунт. Поражения не расходуют награду. Учитывается день победы, сброс в 00:00 МСК.</small></section>';
      if(r.status==='lobby')body+='<div class="guild-panels"><section class="guild-panel guild-lobby-note"><p class="guild-kicker">ПОХОДЫ БЕЗ ЛИМИТА</p><h2>Последняя проверка снаряжения.</h2><p>'+esc(c.description)+'</p><p>Рекомендуется '+c.recommended_party+'–3 охотника. Начать можно одному. Персональные награды указаны выше.</p><p>Для вступления: ранг не ниже '+view.ranks[Math.max(0,view.ranks.indexOf(c.rank)-1)]+'. Нужен личный персонаж с завершённым выбором класса. RP-сборки и боевые рабы недоступны.</p><div class="guild-actions">'+(leader?button(r.members.length===1?'Начать одному →':'Начать поход →','start','primary',busy)+(canInvite?button(r.invite?.posted?'📣 Позвать ещё раз':'📣 Позвать в чат','invite','guild-quiet',busy||inviteWait>0):'')+button('Отменить сбор','leave','guild-quiet'):member?button('Выйти из отряда','leave','guild-quiet'):button('Вступить в отряд','join','primary',busy||r.members.length>=3))+'</div></section><section class="guild-panel"><h3>Как позвать друзей</h3><p>Нажми «Позвать в чат» или напиши /позвать. Бот отправит карточку: друзья вступают по кнопке без поиска заказа. Повторное приглашение — раз в 5 минут.</p><p>Начало похода не расходует полную награду. До старта можно свободно выйти или отменить сбор.</p>'+(inviteWait>0?'<p>Повторно позвать можно через '+inviteWait+' мин.</p>':'')+'<p>Сбор закроется через '+Math.max(0,Math.ceil((r.expires-r.server_time)/60))+' мин.</p></section></div>';
      else if(r.status==='active'){
        const biome=view.biomes[c.biome],current=r.nodes.find(n=>n.id===r.position);
        body+='<section class="guild-map-panel" data-biome="'+esc(c.biome)+'"><div class="guild-map-heading"><div><p class="guild-kicker">'+esc(biome.name)+'</p><h3>'+esc(biome.subtitle)+'</h3></div><span>Мешок: '+r.finds+' ₣ / участник</span></div>'+map(r)+'</section><div class="guild-panels"><section class="guild-panel guild-room">';
        if(r.battle)body+='<p class="guild-kicker">'+esc(rooms[current?.kind]||'Бой')+'</p><h2>Оружие наготове.</h2><p>Впереди противники. Бой проходит на обычной арене с выбранной защитой и мини-играми.</p>'+button(member?'Войти в бой →':'Наблюдать бой →','battle','primary');
        else if(r.pending)body+='<p class="guild-kicker">'+(r.pending.kind==='event'?'СОБЫТИЕ':'ВОССТАНОВЛЕНИЕ')+'</p><h2>'+esc(r.pending.name)+'</h2><p>'+esc(r.pending.text)+'</p><div class="guild-choices">'+r.pending.choices.map(ch=>button('<b>'+esc(ch.name)+'</b><small>'+esc(ch.hint)+'</small>','choice:'+ch.id,'',busy||!member||!!r.votes[view.actor_id])).join('')+'</div>';
        else body+='<p class="guild-kicker">КОМНАТА ЗАВЕРШЕНА</p><h2>Выбери следующий шаг.</h2><p>Светлые узлы доступны для перехода. Каждый живой участник голосует. При равенстве учитывается голос лидера; через 40 секунд решают поданные голоса.</p>';
        if(Object.keys(r.votes).length)body+='<p class="guild-votes">Голоса: '+Object.keys(r.votes).length+' · осталось '+Math.max(0,r.vote_deadline-r.server_time)+' с</p>';
        body+='</section><section class="guild-panel"><p class="guild-kicker">ПОХОДНЫЙ РЮКЗАК</p><h3>Не забывай дышать.</h3><p>Один припас на участника между комнатами. Припасы покупаются в лавке и сохраняются после похода.</p><label>Помочь <select id="guild-target" aria-label="Цель припаса">'+r.members.map(p=>'<option value="'+p.actor_id+'"'+(p.actor_id===view.actor_id?' selected':'')+'>'+esc(p.name)+'</option>').join('')+'</select></label><div class="guild-bag">'+view.shop.filter(s=>r.bag[s.id]>0).map(s=>button(esc(s.name)+' ×'+r.bag[s.id],'supply:'+s.id,'guild-quiet',!member||busy||!!r.battle||!!r.supplies_used[view.actor_id+':'+r.position])).join('')+(Object.values(r.bag).some(q=>q>0)?'':'<p>Рюкзак пуст. В следующий поход возьми припасы.</p>')+'</div>'+(leader?button('Отступить · сохранить 50% находок','retreat','guild-danger',!!r.battle||busy):'')+'<p class="guild-hint">Отступление не даёт основную награду и считается неудачным заказом. Обычный инвентарь не теряется.</p></section></div>';
      }else body+='<section class="guild-result"><div class="guild-result-seal">'+sigil+'</div><p class="guild-kicker">'+esc(states[r.status])+'</p><h2>'+esc(r.reason||'Сбор отряда завершён.')+'</h2>'+Object.entries(r.results).map(([key,result])=>'<article><b>'+esc(r.members.find(p=>String(p.actor_id)===key)?.name||key)+'</b><strong>+'+result.francs+' ₣</strong><span>'+esc(result.loot||'Без припаса и трактата')+'</span><small>Ранг '+result.rank+' · '+(result.reputation>0?'+':'')+result.reputation+' репутации'+(result.rank!==result.rank_before?' · раньше '+result.rank_before:'')+(result.won?' · '+(result.full_reward?'Полная награда':'Повторная награда'):'')+'</small></article>').join('')+button('Новый заказ','back','primary')+'</section>';
      const drops=r.results?.[view.actor_id]?.equipment_loot||[];
      if(drops.length)body+='<section class="guild-section"><p class="guild-kicker">ТВОЯ ЛИЧНАЯ ДОБЫЧА</p><h2>Вернулся не с пустыми руками.</h2><div class="guild-shop-grid">'+drops.flatMap(d=>d.items).map(i=>'<article class="guild-panel"><small>'+esc(i.rarity_name)+' · ранг '+i.rank+' · Lv. '+i.min_level+'+</small><h3>'+esc(i.name)+'</h3><p>'+esc(i.effect_text||'Характеристики и дополнительные свойства')+'</p></article>').join('')+'</div><p>Материалы: '+drops.filter(d=>d.materials>0).map(d=>d.materials+' оск. '+d.rank).join(' + ')+'. Добыча уже сохранена в общем инвентаре.</p>'+button('Осмотреть и сравнить','equipment','primary')+'</section>';
      body+='<section class="guild-section"><h3>Дневник похода</h3><ol class="guild-journal">'+r.history.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ol></section>';shell(body);hydrateAvatars();
    }
    async function loadBoard(){view=await api('/api/guild/board?chat='+chat);if(abort.signal.aborted)return;render();}
    async function loadRun(id){run=await api('/api/guild/runs/'+encodeURIComponent(id));chat=run.chat_id;if(!view||view.chat_id!==chat)view=await api('/api/guild/board?chat='+chat);renderRun();}
    app.addEventListener('click',async event=>{
      const el=event.target.closest('[data-guild]');if(!el||busy)return;
      const [cmd,...args]=el.dataset.guild.split(':'),arg=args.join(':');
      if(cmd==='tab'){run=null;tab=arg;render();return;}
      if(cmd==='filter'){filter=arg;render();return;}
      if(cmd==='arena'){abort.abort();context.onArena?.(chat);return;}
      if(cmd==='battle'){abort.abort();await context.onRaid(run.battle);return;}
      if(cmd==='retreat'&&!confirm('Отступить всем отрядом? Сохранится половина найденных франков. Награды заказа не будет, репутация снизится.'))return;
      busy=true;el.disabled=true;
      try{
        if(cmd==='back'){run=null;await loadBoard();}
        else if(cmd==='equipment'){abort.abort();await context.onEquipment?.(chat,run?.id);return;}
        else if(cmd==='reload')await loadBoard();
        else if(cmd==='accept'){run=await api('/api/guild/runs',{chat,contract:arg,nonce:crypto.randomUUID()});renderRun();}
        else if(cmd==='run')await loadRun(arg);
        else if(cmd==='choose'){chat=Number(arg);await loadBoard();}
        else if(cmd==='invite'){run=await api('/api/guild/runs/'+run.id+'/invite',{});renderRun();toast('Приглашение отправлено в чат.');}
        else if(cmd==='buy'){view=await api('/api/guild/buy',{chat,item:arg,nonce:crypto.randomUUID()});render();toast('Припас куплен.');}
        else{
          const action=['choice','node'].includes(cmd)?'vote':cmd;
          const extra=action==='vote'?{choice:arg}:action==='supply'?{item:arg,target:Number(document.getElementById('guild-target')?.value||view.actor_id)}:{};
          run=await api('/api/guild/runs/'+run.id,{action,revision:run.revision,...extra});renderRun();
        }
      }catch(error){toast(error.message);try{if(run)await loadRun(run.id);else await loadBoard();}catch{} }
      finally{busy=false;if(!abort.signal.aborted&&view)render();}
    },{signal:abort.signal});
    app.addEventListener('change',async e=>{if(e.target.id==='guild-rank'&&!busy){rankFilter=e.target.value;render();}else if(e.target.id==='guild-chat'&&!busy){chat=Number(e.target.value);run=null;try{await loadBoard();}catch(error){toast(error.message);}}},{signal:abort.signal});
    abort.signal.addEventListener('abort',()=>{clearInterval(timer);for(const entry of avatarCache.values())if(entry.url)URL.revokeObjectURL(entry.url);avatarCache.clear();});
    try{
      chats=(await api('/api/guild/chats')).chats;
      if(runId){await loadRun(runId);}
      else{
        if(!chat){shell('<div class="guild-empty"><h2>Выбери чат для заказов</h2><p>Ранг и полные награды общие. Сбор отряда и франки относятся к выбранному чату.</p><div class="guild-actions">'+chats.map(c=>button(esc(c.title||c.chat_id),'choose:'+c.chat_id,'primary')).join('')+'</div>'+(!chats.length?'<p>Напиши /гильдия в группе, где включена арена, и вернись сюда.</p>':'')+'</div>');}
        else await loadBoard();
      }
      timer=setInterval(async()=>{
        if(busy||document.hidden||abort.signal.aborted||!run||!['lobby','active'].includes(run.status))return;
        try{const fresh=await api('/api/guild/runs/'+run.id);const rewardChanged=fresh.members.some((p,i)=>p.reward_preview?.day!==run.members[i]?.reward_preview?.day||p.reward_preview?.full!==run.members[i]?.reward_preview?.full);if(fresh.revision!==run.revision||rewardChanged||run.status==='lobby'&&Math.ceil(Math.max(0,(fresh.invite?.available_at||0)-fresh.server_time)/60)!==Math.ceil(Math.max(0,(run.invite?.available_at||0)-run.server_time)/60)){run=fresh;if(!['lobby','active'].includes(run.status))view=await api('/api/guild/board?chat='+chat);renderRun();}}
        catch(error){if(!abort.signal.aborted)toast(error.message);}
      },3000);
    }catch(error){if(!abort.signal.aborted)shell('<div class="guild-empty"><h2>Не удалось открыть гильдию</h2><p>'+esc(error.message)+'</p>'+button('Повторить','reload','primary')+'</div>');}
  }
})();
