/* The map is a view. Every price, claim, incident and reward is server-owned. */
(()=>{
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const number=n=>Number(n||0).toLocaleString('ru-RU');
 const duration=s=>s>=86400?(Math.round(s/8640)/10)+' дн.':s>=3600?(Math.round(s/360)/10)+' ч.':Math.ceil(s/60)+' мин.';
 const ranks=['F','E','D','C','B','A','S'];
 const resourceNames={food:'Продовольствие',wood:'Древесина',stone:'Камень'};
 const resourceUnits={food:'пищи',wood:'древесины',stone:'камня'};
 const paths={
  hall:'M5 27V12L16 5l11 7v15M3 27h26M10 27V16h12v11M16 9v3M12 20h8',
  farm:'M16 29V3M16 12C3 13 4 5 5 4c8-1 11 4 11 8Zm0 7c13 1 12-7 11-8-8-1-11 4-11 8Zm0 8c-13 1-12-7-11-8 8-1 11 4 11 8Z',
  sawmill:'M10 4 3 16h4l-5 8h17l-5-8h4L10 4Zm0 20v6M21 4l7 9-6 5-7-9 6-5Zm1 14-4 11',
  quarry:'m2 27 8-16 5 8 7-15 9 23H2Zm6-12 4 3m8-9 3 6 3-1M7 27l10-3 7 3',
  barracks:'M7 3h18v17l-9 9-9-9V3Zm9 4v15M11 13h10',
  warehouse:'M3 13 16 3l13 10v16H3V13Zm7 16V16h12v13M10 18l12 9m0-9-12 9',
  people:'M12 14a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm-9 15v-6c0-7 18-7 18 0v6m1-14c8-1 10 4 9 10',
  crown:'m3 9 4 17h18l4-17-9 7-4-12-4 12-9-7Zm4 20h18',
  skull:'M7 21C-1 6 7 2 16 2s17 4 9 19l-3 1v7H10v-7l-3-1Zm3-7h2m8 0h2m-6 5v3m-2 3v4m4-4v4',
  pin:'M16 30S4 20 4 12a12 12 0 0 1 24 0c0 8-12 18-12 18Zm0-12a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z',
  ruin:'M3 29h26M6 29V14l5-7 5 7v15m-5-8h10m0 8V10l7-5v24M5 14h11',
  fire:'M15 2c2 11 12 11 12 20a11 11 0 0 1-22 0c0-6 5-9 6-13 0 7 4 8 5 6 3-5-1-9-1-13Zm0 16c-8 12 8 13 7 4',
 };
 const icon=(key,cls='')=>'<svg class="k-icon '+cls+'" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true"><path d="'+(paths[key]||paths.pin)+'"/></svg>';
 const btn=(text,action,disabled=false,cls='')=>'<button type="button" data-k="'+esc(action)+'" class="'+cls+'"'+(disabled?' disabled':'')+'>'+text+'</button>';
 function mapNames(entries){
  // Place whole nameplates, not independent text fragments. No two plates overlap.
  const placed=[],icons=entries.map(e=>({x:e.x-22,y:e.y-24,w:44,h:43,key:e.key}));
  const intersects=(a,b,gap=5)=>a.x<b.x+b.w+gap&&a.x+a.w+gap>b.x&&a.y<b.y+b.h+gap&&a.y+a.h+gap>b.y;
  const offsets=[[0,31],[0,-55],[85,0],[-85,0],[0,63],[0,-85],[110,37],[-110,37],[110,-52],[-110,-52],[0,93],[150,0],[-150,0]];
  for(const e of entries.slice().sort((a,b)=>b.priority-a.priority||a.y-b.y||a.x-b.x)){
   const words=e.text.trim().split(/\s+/),lines=[];let line='';
   for(const word of words){if(line&&(line+' '+word).length>23){lines.push(line);line=word;}else line+=(line?' ':'')+word;}
   if(line)lines.push(line);
   const shown=lines.slice(0,2).map(s=>s.length>25?s.slice(0,24)+'…':s);
   if(lines.length>2)shown[1]=shown[1].slice(0,23)+'…';
   const w=Math.max(86,Math.min(176,Math.max(...shown.map(s=>s.length))*6+18)),h=shown.length*13+10;
   let box;
   for(const[dx,dy]of offsets){const candidate={x:Math.max(8,Math.min(956-w,e.x+dx-w/2)),y:Math.max(8,Math.min(644-h,e.y+dy)),w,h};
    if(!placed.some(p=>intersects(candidate,p))&&!icons.some(i=>i.key!==e.key&&intersects(candidate,i,2))){box=candidate;break;}}
   if(!box)continue;
   placed.push({...box,entry:e,lines:shown});
  }
  return placed.map(p=>{
   const e=p.entry,cx=p.x+p.w/2,far=Math.hypot(cx-e.x,p.y+p.h/2-e.y)>55;
   return '<g class="k-name-label'+(e.selected?' k-selected-label':'')+'" data-label-rect="'+[p.x,p.y,p.w,p.h].join(',')+'" pointer-events="none" aria-hidden="true">'+(far?'<path class="k-name-leader" d="M'+e.x+' '+(e.y+15)+' L'+Math.max(p.x,Math.min(p.x+p.w,e.x))+' '+Math.max(p.y,Math.min(p.y+p.h,e.y))+'"/>':'')+'<text class="k-map-label" x="'+cx+'" y="'+(p.y+14)+'">'+p.lines.map((s,i)=>'<tspan x="'+cx+'" dy="'+(i?13:0)+'">'+esc(s)+'</tspan>').join('')+'</text></g>';
  }).join('');
 }
 let previous;
 window.KingdomApp={open};

 async function open(context){
  previous?.abort();const controller=new AbortController();previous=controller;
  const app=context.app,init=context.initData??window.Telegram?.WebApp?.initData??'';
  let chat=context.chat??null,view=null,chats=[],selected=null,tab='map',busy=false,pending=null,error='',zoom=1.2,timer;
  let reportId='',reportCursor=0,playing=false,replayTimer;
  let renderedTownId=null,cameraFocus=true,pan=null,ignoreMapClickUntil=0;
  let inspecting=false;
  let savedNames=true;try{savedNames=window.localStorage?.getItem('gnida_kingdom_map_names')!=='off';}catch{}
  const mapLayers={sites:true,camps:true,events:true,names:savedNames};
  const groups={map:['map','camps'],town:['town','buildings','specials','budget','lands'],military:['military','army','campaigns','wars'],government:['government','council','events','journal']};
  const groupLabels={map:'Карта',town:'Владение',military:'Армия',government:'Совет'};
  const pageLabels={camps:'Лагеря',buildings:'Хозяйственные постройки',specials:'Особые постройки',budget:'Казна и налоги',lands:'Земли и оформление',army:'Отряды и строй',campaigns:'Походы и отчёты',wars:'Войны',council:'Политика и вера',events:'События',journal:'Летопись'};
  const currentGroup=()=>Object.keys(groups).find(k=>groups[k].includes(tab))||'map';
  const own=()=>view?.towns.find(t=>t.own);
  const municipal=()=>own()?.budget?.balance||0;
  const spendingView=()=>({...view,balance:municipal()});
  const selectedTile=()=>view?.tiles.find(t=>t.q===selected?.q&&t.r===selected?.r);
  const selectedTown=()=>view?.towns.find(t=>t.id===selectedTile()?.town);
  const currentReport=()=>{const reports=(own()?.military.reports||[]).filter(r=>tab!=='wars'||r.kind==='siege');return reports.find(r=>r.id===reportId)||reports.at(-1);};
  const remaining=t=>duration(Math.max(0,t-(view?.now||Date.now()/1000)));
  async function api(path,body){
   const response=await fetch(path,{method:body?'POST':'GET',signal:controller.signal,
    headers:{'X-Telegram-Init-Data':init,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
   const data=await response.json();if(!response.ok)throw Error(data.error||'Не удалось связаться с картой.');return data;
  }
  function header(){return '<header class="k-header"><div class="k-brand">'+icon('crown')+'<div><span>ГНИДА · НОВАЯ ЗЕМЛЯ</span><h1>Королевства</h1></div></div><div class="k-header-actions">'+(view?'<div class="k-dual-wallet"><span class="k-wallet">'+number(view.balance)+' <small>₣</small><em>кошелёк игрока</em></span>'+(own()?'<span class="k-wallet">'+number(municipal())+' <small>₣</small><em>бюджет поселения</em></span>':'')+'</div>':'')+btn('↻','refresh',busy,'k-round')+btn('Арена','arena',false,'k-quiet')+'</div></header>';}
  function navigation(){return '<nav class="k-nav k-primary-nav" aria-label="Разделы королевства">'+Object.entries(groupLabels).map(([key,label])=>btn(label+(key==='government'&&view?.towns.some(t=>t.event)?' <i class="k-dot"></i>':''),'section:'+key,false,currentGroup()===key?'active':'')).join('')+'</nav>';}
  function trail(){const group=currentGroup();return tab===group?'':'<div class="k-section-trail">'+btn('← '+groupLabels[group],'section:'+group,false,'k-quiet')+'<span>'+esc(pageLabels[tab]||'')+'</span></div>';}
  function overview(){
   const t=own();if(!t)return '';
   return '<div class="k-status-strip"><button data-k="section:town" type="button"><small>ТВОЁ ВЛАДЕНИЕ</small><strong>'+esc(t.name)+'</strong></button><span title="Население">'+icon('people')+t.population+'</span><span>Порядок <b>'+t.order+'%</b></span>'+Object.entries(t.resources).map(([k,v])=>'<span title="'+resourceNames[k]+'">'+icon(k==='food'?'farm':k==='wood'?'sawmill':'quarry')+number(v)+'</span>').join('')+'</div>';
  }
  function hubCard(title,subtitle,target,kind){return '<button type="button" class="k-hub-card" data-k="tab:'+target+'">'+icon(kind)+'<span><strong>'+title+'</strong><small>'+esc(subtitle)+'</small></span><i>›</i></button>';}
  function townHub(){
   const t=own();if(!t)return emptyEstate();
   const job=t.estate.job||t.construction,jobName=t.estate.job?t.estate.catalog[t.estate.job.special].name:t.building_options.find(b=>b.id===t.construction?.building)?.name;
   return '<section class="k-panel k-hub-heading"><span class="k-kicker">'+esc(t.stage_name)+' · '+t.tiles.length+'/'+t.territory_cap+' земель</span><h2>'+esc(t.name)+'</h2><p>'+esc(t.description||'Развитие, оформление и казна твоего владения.')+'</p><div class="k-hub-facts"><span>Население <b>'+t.population+'/'+t.population_cap+'</b></span><span>Гарнизон <b>'+t.defense+'</b></span><span>Престиж <b>'+t.prestige+'</b></span></div>'+btn('Изменить имя и описание','rename',busy,'k-quiet')+(job?'<div class="k-note">'+esc(jobName)+' · осталось '+remaining(job.finish)+'</div>':'')+'</section><div class="k-hub-grid">'+hubCard('Постройки','Производство и оборона','buildings','hall')+hubCard('Особые сооружения',t.estate.specials.length+'/'+t.estate.capacity+' мест занято','specials','crown')+hubCard('Земли и оформление','Области, знамя и облик столицы','lands','pin')+hubCard('Казна и налоги',number(municipal())+' ₣ в бюджете','budget','warehouse')+'</div><details class="k-hub-details" data-k-detail="development"><summary>Следующий этап развития</summary>'+progression(t)+'</details>';
  }
  function militaryHub(){
   const t=own();if(!t)return emptyEstate();const m=t.military;
   return '<section class="k-panel k-hub-heading"><span class="k-kicker">ВОЕННОЕ ДЕЛО</span><h2>Армия и приказы.</h2><div class="k-hub-facts"><span>Отрядов <b>'+m.units.length+'/'+m.capacity+'</b></span><span>В строю <b>'+m.formation.filter(Boolean).length+'/5</b></span><span>Слава <b>'+m.glory+'</b></span></div>'+(m.campaign?'<div class="k-note">'+esc(m.campaign.name)+' · возвращение через '+remaining(m.campaign.finish)+'</div>':'<p>Армия ждёт приказа.</p>')+'</section><div class="k-hub-grid">'+hubCard('Отряды и строй','Найм, лечение и сочетания бойцов','army','people')+hubCard('Походы и отчёты','NPC-заставы и результаты набегов','campaigns','barracks')+hubCard('Войны','Оборона и осады владений','wars','crown')+hubCard('Живые лагеря','Выбрать общую цель на карте','camps','ruin')+'</div>';
  }
  function governmentHub(){
   return '<section class="k-panel k-hub-heading"><span class="k-kicker">УПРАВЛЕНИЕ</span><h2>Дела государства.</h2><p>Решения, события и история владения.</p></section><div class="k-hub-grid">'+hubCard('Политика и вера','Курс государства и верование','council','crown')+hubCard('События',view.towns.filter(t=>t.event).length+' текущих событий в мире','events','fire')+hubCard('Летопись','Решения и результаты действий','journal','hall')+'</div>';
  }
  function shell(body){
   if(controller.signal.aborted)return;
   app.innerHTML='<div class="kingdom">'+header()+'<div class="k-chat"><label>ЗЕМЛИ ЧАТА <select id="k-chat" aria-label="Чат карты">'+chats.map(c=>'<option value="'+c.chat_id+'"'+(c.chat_id===chat?' selected':'')+'>'+esc(c.title||c.chat_id)+'</option>').join('')+'</select></label><span>Один мир на чат · столицы защищены · осады с предупреждением</span></div>'+(view?navigation():'')+(error?'<div class="k-error" role="alert">'+esc(error)+'</div>':'')+body+(pending?confirmation():'')+'</div>';
  }
  function sidebar(){
   const t=own();if(!t)return '<aside class="k-sidebar"><section class="k-panel k-founder">'+icon('crown')+'<span class="k-kicker">ПРАВО НА СВОЮ ЗЕМЛЮ</span><h2><span>От героя</span><span>к правителю.</span></h2><p>Выбери свободную клетку. Жители сами не прокормятся, а казна не станет печатать деньги.</p><div class="k-requirements"><span class="'+(view.eligibility.level>=15?'ok':'')+'">'+view.eligibility.level+'/15 · уровень</span><span class="'+(view.eligibility.rank>=3?'ok':'')+'">'+ranks[view.eligibility.rank]+'/C · ранг охотника</span><span class="'+(view.balance>=view.eligibility.price?'ok':'')+'">'+number(view.eligibility.price)+' ₣ · основание</span></div><p class="k-muted">Одна столица владения на игрока в чате. Деревня — до 3 земель, город — до 5, столица — до 7. Общие тракты и места приключений не захватываются.</p></section></aside>';
   return '<aside class="k-sidebar"><section class="k-panel k-ruler"><div class="k-town-emblem">'+icon(t.stage===1?'hall':'crown')+'</div><span class="k-kicker">'+esc(t.stage_name.toUpperCase())+' · ТВОЁ ВЛАДЕНИЕ</span><h2>'+esc(t.name)+'</h2><p>'+esc(t.description||'Земля, за которую теперь отвечаешь ты.')+'</p><div class="k-townline"><span>'+icon('people')+t.population+' / '+t.population_cap+'</span><span>Порядок <b>'+t.order+'%</b></span></div><div class="k-meter"><i style="width:'+t.order+'%"></i></div><div class="k-townline"><span>Гарнизон <b>'+t.defense+'</b></span><span>Земли <b>'+t.tiles.length+'/'+t.territory_cap+'</b></span></div>'+btn('Название и описание','rename',busy,'k-text-button')+'</section><section class="k-panel k-resources"><span class="k-kicker">ХОЗЯЙСТВО · ВНУТРЕННИЕ ЗАПАСЫ</span>'+Object.entries(t.resources).map(([key,value])=>'<div class="k-resource"><div>'+icon(key==='food'?'farm':key==='wood'?'sawmill':'quarry')+'<span>'+resourceNames[key]+'<small>'+value+' / '+t.capacity+'</small></span><b class="'+(t.rates[key]<0?'negative':'')+'">'+(t.rates[key]>=0?'+':'')+t.rates[key]+'<small>/час</small></b></div><div class="k-meter"><i style="width:'+Math.min(100,100*value/t.capacity)+'%"></i></div></div>').join('')+'<p>Пища учитывает жителей. Прирост: один житель за '+(t.government.policy==='communal'?4:6)+' часов при достатке пищи и порядке ≥50. '+(t.budget.active?'Множитель роста от налогов: ×'+t.budget.quote.growth+'. ':'')+'Запасы не продаются.</p>'+btn('Караван снабжения · 2 500 ₣','supplies',busy||municipal()<2500,'k-secondary')+'</section>'+progression(t)+'</aside>';
  }
  function progression(t){const p=t.promotion;return '<section class="k-panel k-stage"><span class="k-kicker">ДОЛГИЙ ПУТЬ · БЕЗ ПЛАТНОЙ ПЕРЕМОТКИ</span><h3>'+(p?esc(p.name):'Столица основана')+'</h3>'+(p?'<div class="k-requirements">'+p.checks.map(c=>'<span class="'+(c.ok?'ok':'')+'">'+(c.ok?'✓ ':'○ ')+esc(c.text)+'</span>').join('')+'</div><p>'+(p.ready_at>view.now?'До требуемого возраста: '+remaining(p.ready_at)+' ':'')+'Таймер нельзя купить за франки. После перехода: до '+p.lands+' земель и постройки '+p.building_cap+' уровня.</p>'+btn('Новый этап · '+number(p.price)+' ₣','promote',busy||!p.allowed||!!t.construction||municipal()<p.price,'k-secondary'):'<p>Жёсткий предел: семь земель. Казна и победы над NPC не расширяют его. Курс и верование — в Совете. Осады — во вкладке «Войны».</p>')+'</section>';}
  function mapArt(tile){
   const town=view.towns.find(t=>t.id===tile.town),e=town?.estate,decoration=e?.tiles?.[tile.q+':'+tile.r]?.decoration;
   let art=window.KingdomAtlas.art({...tile,site:mapLayers.sites?tile.site:null,camp:mapLayers.camps?(view.camps||[]).find(c=>c.q===tile.q&&c.r===tile.r):null},view.towns);
   if(town?.q===tile.q&&town?.r===tile.r){
    if(decoration&&decoration!=='none')art+='<g transform="translate(-13 18) scale(.52)">'+window.KingdomAtlas.decor(decoration,e.color)+'</g>';
    if(inspecting&&tile.q===selected?.q&&tile.r===selected?.r)art+=(e?.specials||[]).map((s,i)=>'<g transform="translate('+(i*15-15)+' 23)"><circle r="7" fill="#142333" stroke="#d5b17a" stroke-width=".7"/><text text-anchor="middle" y="3" font-size="9" fill="#e2cb9a">'+({academy:'⚔',caravan:'♞',watchtower:'♜',temple:'✧',siegeworks:'⚒',wonder:'♛'}[s]||'')+'</text></g>').join('');
   }
   return art;
  }
  function map(){
   const t=own(),env=view.environment||{phase:'day',name:'День',clock:'—',timezone:'МСК'};
   const nameEntries=[];let svg='<svg class="k-world-svg k-atlas k-time-'+env.phase+'" style="width:'+(zoom?Math.round(964*zoom)+'px':'100%')+'" viewBox="0 0 964 652" role="group" aria-label="Карта земель чата">';
   svg+='<g class="k-map-scene">'+window.KingdomAtlas.background(view);
   for(const tile of view.tiles){
    const x=45+tile.q*60+(tile.r%2)*30,y=46+tile.r*52,town=view.towns.find(t=>t.id===tile.town),chosen=inspecting&&tile.q===selected?.q&&tile.r===selected?.r;
    const points=Array.from({length:6},(_,i)=>{const a=(i*60-30)*Math.PI/180;return (Math.cos(a)*34).toFixed(2)+','+(Math.sin(a)*34).toFixed(2);}).join(' ');
    const timed=(view.map_events||[]).find(e=>e.q===tile.q&&e.r===tile.r);
    const camp=(view.camps||[]).find(c=>c.q===tile.q&&c.r===tile.r),land=town?.estate?.tiles?.[tile.q+':'+tile.r];
    const label=(camp?.name||land?.name||timed?.name||tile.site?.name||town?.name||view.terrains[tile.terrain].name)+' · '+tile.q+':'+tile.r;
    svg+='<g class="k-hex '+(town?'claimed ':'')+(town?.own?'self ':'')+(t&&tile.can_annex?'claimable ':'')+(chosen?'selected':'')+'" data-k-tile="'+tile.q+':'+tile.r+'" role="button" tabindex="0" aria-label="'+esc(label)+'" transform="translate('+x+' '+y+')"><title>'+esc(label)+'</title><polygon points="'+points+'" fill="'+view.terrains[tile.terrain].color+'"/>'+mapArt(tile)+(timed&&mapLayers.events?window.KingdomAtlas.marker(timed):'')+'</g>';
    if(town?.estate?.color)svg+='<g transform="translate('+x+' '+y+')" pointer-events="none"><polygon points="'+points+'" fill="'+town.estate.color+'" fill-opacity=".10" stroke="'+town.estate.color+'" stroke-opacity=".65" stroke-width="1.5"/></g>';
    const capital=town&&town.q===tile.q&&town.r===tile.r;
    const objectName=mapLayers.camps&&camp?camp.name:capital?(land?.name||town.name):land?.name||((mapLayers.events&&timed)?timed.name:null)||((mapLayers.sites&&tile.site)?tile.site.name:null);
    if(objectName||chosen)nameEntries.push({key:tile.q+':'+tile.r,x,y,text:objectName||view.terrains[tile.terrain].name,selected:chosen,priority:chosen?100:capital?80:camp?60:tile.site?40:20});
   }
   svg+='</g>'+window.KingdomAtlas.lights(view)+window.KingdomAtlas.foreground+(mapLayers.names?mapNames(nameEntries):'')+'</svg>';
   return '<section class="k-map-card"><div class="k-map-toolbar"><span class="k-map-time">'+esc(env.name)+' · '+esc(env.clock)+' '+esc(env.timezone)+'</span><button type="button" class="k-names-toggle" data-k="layer:names" aria-pressed="'+mapLayers.names+'" title="Показать или скрыть названия объектов">Aa · Названия</button><div class="k-map-controls">'+btn('−','zoomout',false,'k-round')+btn('Вся карта','zoomfit',false,'k-quiet')+btn('+','zoomin',false,'k-round')+(t?btn('⌂','homecamera',false,'k-round'):'')+'</div></div><div class="k-map-scroll '+(zoom?'':'fit')+'">'+svg+'</div><div class="k-map-legend"><span><i class="self"></i>Твои земли</span><span><i class="other"></i>Соседи</span><small>Нажми на объект, чтобы открыть подробности</small></div><details class="k-map-options" data-k-detail="layers"><summary>Слои и объекты карты</summary><div class="k-layer-switches">'+Object.entries({sites:'Приключения',camps:'Лагеря',events:'Встречи'}).map(([k,name])=>'<button type="button" data-k="layer:'+k+'" aria-pressed="'+mapLayers[k]+'">'+(mapLayers[k]?'✓ ':'')+name+'</button>').join('')+'</div><div class="k-map-directory">'+btn('Живые лагеря · '+(view.camps||[]).filter(c=>c.status==='active').length,'tab:camps',false,'k-secondary')+(view.map_events||[]).map(e=>btn((e.claimed?'✓ ':'◇ ')+esc(e.name),'timedfocus:'+e.id,false,'k-quiet')).join('')+'</div></details></section>';
  }
  function tilePanel(){
   const tile=selectedTile(),t=own(),town=selectedTown();if(!tile||!inspecting)return '<section class="k-panel k-inspector k-map-help"><span class="k-kicker">КАРТА МИРА</span><h2>Выбери объект.</h2><p>Нажми на поселение, лагерь или свободную землю. Здесь появятся его описание и доступные действия.</p>'+btn('Живые лагеря','tab:camps',false,'k-secondary')+'<details data-k-detail="maphelp"><summary>Как читать карту</summary><p>Границы показывают владельца земли. Название отображается только у выбранного объекта. Двигай карту мышью или пальцем.</p></details></section>';
   const timed=(view.map_events||[]).find(e=>e.q===tile.q&&e.r===tile.r);
   const camp=(view.camps||[]).find(c=>c.q===tile.q&&c.r===tile.r);
   if(camp)return '<section class="k-panel k-inspector">'+campCard(camp)+'</section>';
   if(town?.own){const land=town.estate.tiles[tile.q+':'+tile.r]||{};return '<section class="k-panel k-inspector"><span class="k-kicker">ТВОЯ ОБЛАСТЬ · '+tile.q+':'+tile.r+'</span><h2>'+esc(land.name||town.name)+'</h2><p>'+esc(land.description||town.description)+'</p><div class="k-note">'+esc(view.terrains[tile.terrain].name)+' · '+esc(town.estate.styles[town.estate.style])+'<br>Правитель: '+esc(town.owner_name)+'</div>'+btn('Оформить эту землю','decor:'+tile.q+':'+tile.r,false,'k-primary')+btn('Особые постройки','tab:specials',false,'k-secondary')+btn('Хозяйство','tab:buildings',false,'k-quiet')+'</section>';}
   if(timed)return '<section class="k-panel k-inspector"><span class="k-kicker">'+(timed.period==='day'?'ДНЕВНАЯ':'НОЧНАЯ')+' ВСТРЕЧА · '+tile.q+':'+tile.r+'</span><h2>'+esc(timed.name)+'</h2><p>'+esc(timed.text)+'</p><div class="k-note">Исчезнет через '+remaining(timed.ends)+' · Только припасы поселения: '+Object.entries(timed.grant).map(([k,v])=>v+' '+resourceUnits[k]).join(', ')+'. Избыток сверх амбаров не сохраняется.</div>'+btn(timed.claimed?'Уже посещено':'Отправить разведчиков','explore:'+timed.id,busy||!t||timed.claimed,'k-primary')+(!t?'<p>Для посещения нужно своё поселение в этом чате.</p>':'')+'</section>';
   if(tile.site?.kind==='war')return '<section class="k-panel k-inspector"><span class="k-kicker">NPC-ЗАСТАВА · '+esc(tile.site.rank)+'</span><div class="k-inspector-art danger">'+icon('barracks')+'</div><h2>'+esc(tile.site.name)+'</h2><p>'+esc(tile.site.text)+'</p><div class="k-note">Цель для армии поселения. Не бой героя арены и не город игрока. Захвата клетки и обычных наград арены нет.</div>'+btn('Разведка и подготовка','target:'+tile.site.target,false,'k-primary')+'</section>';
   if(tile.site?.kind==='faction'){const f=view.factions[tile.site.target],score=t?.factions[tile.site.target]||0;return '<section class="k-panel k-inspector"><span class="k-kicker">НЕЙТРАЛЬНОЕ ВЛАДЕНИЕ · ФРАКЦИЯ</span><div class="k-inspector-art">'+icon('crown')+'</div><h2>'+esc(tile.site.name)+'</h2><p>'+esc(tile.site.text)+'</p><div class="k-note"><b>'+esc(f.name)+'</b><br>'+esc(f.motto)+'</div><div class="k-info-row"><span>Отношения твоего поселения</span><b>'+(score>0?'+':'')+score+' / 10</b></div><p class="k-muted">Решения событий меняют отношения и открывают особые отряды. Доступны армии и походы против NPC. Верование — в Совете; войны — в отдельной вкладке. Эту землю нельзя присоединить.</p></section>';}
   if(town)return '<section class="k-panel k-inspector"><span class="k-kicker">'+(town.stage===1?'ДЕРЕВНЯ':'ГОРОД')+' · '+tile.q+' / '+tile.r+'</span><div class="k-inspector-art">'+icon(town.stage===1?'hall':'crown')+'</div><h2>'+esc(town.name)+'</h2><p>'+esc(town.description||'На этих землях уже строят свою историю.')+'</p><div class="k-info-row"><span>Правитель</span><b>'+esc(town.owner_name)+'</b></div><div class="k-info-row"><span>Население</span><b>'+town.population+'</b></div><div class="k-info-row"><span>Гарнизон</span><b>'+town.defense+'</b></div><div class="k-info-row"><span>Престиж</span><b>'+town.prestige+'</b></div>'+(town.own?btn('Управлять постройками','tab:buildings',false,'k-primary'):'<div class="k-note">Поселение другого игрока. Столица защищена; осада пограничных земель — во вкладке «Войны».</div>')+(!town.own?btn('Границы и осады','tab:wars',false,'k-secondary'):'')+(town.event?eventCard(town,true):'')+'</section>';
   if(tile.site)return '<section class="k-panel k-inspector"><span class="k-kicker">'+(tile.site.kind==='guild'?'ПОДЗЕМЕЛЬЕ':'РЕЙД-БОСС')+' · '+esc(tile.site.rank)+'</span><div class="k-inspector-art danger">'+icon(tile.site.kind==='guild'?'ruin':'skull')+'</div><h2>'+esc(tile.site.name)+'</h2><p>'+esc(tile.site.text)+'</p><div class="k-note">Обычный бой, обычные требования доступа. Награды и ограничения общие на аккаунт — карта не обходит их.</div>'+btn('Собрать отряд','activity',busy,'k-primary')+'</section>';
   const terrain=view.terrains[tile.terrain];
   return '<section class="k-panel k-inspector"><span class="k-kicker">СВОБОДНАЯ ЗЕМЛЯ · '+tile.q+' / '+tile.r+'</span><div class="k-inspector-art">'+icon(tile.terrain==='forest'?'sawmill':tile.terrain==='hills'?'quarry':'farm')+'</div><h2>'+esc(terrain.name)+'</h2><p>'+(terrain.resource?'После присоединения: +'+terrain.bonus+' '+resourceNames[terrain.resource].toLowerCase()+' в час.':'Река разделяет берега. В первой версии строительство на воде недоступно.')+'</p>'+(tile.claim_reason?'<div class="k-note">'+esc(tile.claim_reason)+'</div>':'')+(terrain.buildable?(t?btn('Присоединить · '+number(t.annex_price)+' ₣','annex',busy||!tile.can_annex||municipal()<t.annex_price,'k-primary'):
    btn('Основать деревню · '+number(view.eligibility.price)+' ₣','found',busy||!tile.can_found||!view.eligibility.allowed||view.balance<view.eligibility.price,'k-primary')):'')+'<p class="k-muted">Границы и расстояние до соседей проверяются сервером.</p></section>';
  }
  function buildings(){
   const t=own();if(!t)return '<section class="k-panel"><h2>Сначала — своя земля.</h2><p>На карте выбери свободную клетку и основай деревню.</p>'+btn('К карте','tab:map',false,'k-primary')+'</section>';
   return '<section class="k-building-section"><div class="k-section-heading"><span class="k-kicker">ХОЗЯЙСТВО И ОБОРОНА</span><h2>Построено на твоих решениях.</h2><p>Одна стройка: I — 6 часов, II — сутки, III — 3 дня, IV — неделя. Ускорения за деньги нет. Ратуша и фермы I входят в основание деревни.</p>'+(t.construction?'<div class="k-note">'+esc(t.building_options.find(b=>b.id===t.construction.building)?.name)+' · осталось '+remaining(t.construction.finish)+'. Остальные стройки ждут завершения.</div>':'')+'</div><div class="k-building-grid">'+t.building_options.map(b=>'<article class="k-building"><div class="k-building-art '+b.id+'">'+icon(b.icon)+'</div><div class="k-building-head"><h3>'+b.name+'</h3><span>'+['—','I','II','III','IV'][b.level]+'</span></div><p>'+esc(b.text)+'</p>'+(b.allowed?'<div class="k-building-cost"><b>'+number(b.quote.price)+' ₣</b><span>'+b.quote.wood+' древесины · '+b.quote.stone+' камня</span><span>'+duration(b.quote.finish-b.quote.started)+'</span></div>'+btn((b.level?'Улучшить до ':'Построить · ')+['','I','II','III','IV'][b.quote.level],'build:'+b.id,busy||!!t.construction||municipal()<b.quote.price||t.resources.wood<b.quote.wood||t.resources.stone<b.quote.stone,'k-secondary'):'<div class="k-badge">'+(t.stage<3?'Дальше нужен следующий этап':'Максимальный уровень')+'</div>')+'</article>').join('')+'</div></section>';
  }
  const options=(catalog,current)=>Object.entries(catalog).map(([k,v])=>'<option value="'+esc(k)+'"'+(k===current?' selected':'')+'>'+esc(v)+'</option>').join('');
  function emptyEstate(){return '<section class="k-panel"><h2>Сначала — своя земля.</h2>'+btn('К карте','tab:map',false,'k-primary')+'</section>';}
  function lands(){
   const t=own();if(!t)return emptyEstate();const e=t.estate;
   return '<section class="k-panel k-estate-editor"><span class="k-kicker">ТВОЯ ЗЕМЛЯ · ТВОЙ ХАРАКТЕР</span><h2>Знамя, под которым живут.</h2><p>Оформление бесплатно и не меняет производство, местность или боевые характеристики. У каждого участка может быть своё имя и украшение.</p><div class="k-estate-form"><label>Облик владения<select id="k-estate-style">'+options(e.styles,e.style)+'</select></label><label>Символ<select id="k-estate-emblem">'+options(e.emblems,e.emblem)+'</select></label><label>Цвет границ<input id="k-estate-color" type="color" value="'+e.color+'"></label></div>'+btn('Применить оформление','style_save',busy,'k-primary')+'</section><div class="k-land-grid">'+t.tiles.map(tile=>{const land=e.tiles[tile.q+':'+tile.r]||{};return '<article class="k-panel"><span class="k-kicker">ОБЛАСТЬ '+tile.q+':'+tile.r+'</span><h3>'+esc(land.name||view.terrains[tile.terrain].name)+'</h3><p>'+esc(land.description||'Эта земля ещё ждёт своего имени.')+'</p><small>'+esc(e.decorations[land.decoration||'none'])+' · '+esc(view.terrains[tile.terrain].name)+'</small>'+btn('Имя и украшение','decor:'+tile.q+':'+tile.r,busy,'k-secondary')+btn('На карте','landfocus:'+tile.q+':'+tile.r,false,'k-quiet')+'</article>';}).join('')+'</div>';
  }
  function specials(){
   const t=own();if(!t)return emptyEstate();const e=t.estate,job=e.job,occupied=e.specials.length,building=job&&job.kind==='build';
   return '<section class="k-section-heading"><span class="k-kicker">НЕ ПРОСТО ЕЩЁ ОДНА ЛЕСОПИЛКА</span><h2>Особые постройки.</h2><p>Места: '+occupied+'/'+e.capacity+' · Трофеи лагерей: '+e.trophies+'. Город — 2 места, столица — 3. Одна общая очередь с обычными стройками. Бонусы работают только в королевствах; потраченные средства не возвращаются.</p>'+(job?'<div class="k-note">'+(building?'Строительство':'Снос')+': '+esc(e.catalog[job.special].name)+' · осталось '+remaining(job.finish)+'</div>':'')+'</section><div class="k-building-grid">'+Object.entries(e.catalog).map(([key,s])=>{const built=e.specials.includes(key),locked=t.stage<(s.stage||2)||occupied>=e.capacity||e.trophies<(s.trophies||0)||!!job||!!t.construction;return '<article class="k-building k-special '+key+'"><div class="k-special-symbol">'+({academy:'⚔',caravan:'♞',watchtower:'♜',temple:'✧',siegeworks:'⚒',wonder:'♛'}[key])+'</div><span class="k-kicker">'+(built?'ВОЗВЕДЕНО':key==='wonder'?'ЧУДО СТОЛИЦЫ':'ОСОБОЕ МЕСТО')+'</span><h3>'+esc(s.name)+'</h3><p>'+esc(s.text)+'</p><div class="k-building-cost"><b>'+number(s.price)+' ₣</b><span>'+s.wood+' дерева · '+s.stone+' камня'+(s.trophies?' · '+s.trophies+' трофея':'')+'</span><span>'+s.hours+' ч. · содержание '+s.upkeep+' ₣/сутки при включённых налогах</span></div>'+btn(built?'Разобрать · 24 часа':'Заложить постройку',(built?'special_remove:':'special_build:')+key,busy||!!job||!!t.construction||(!built&&(locked||municipal()<s.price||t.resources.wood<s.wood||t.resources.stone<s.stone)),'k-secondary')+'</article>';}).join('')+'</div>';
  }
  function campCard(c){
   const t=own(),alive=c.status==='active',ready=t&&!t.military.campaign&&!t.military.siege_lock&&t.military.formation.some(Boolean);
   return '<article class="k-camp-card"><span class="k-kicker">'+(alive?'ЖИВОЙ ЛАГЕРЬ · СТУПЕНЬ '+c.stage:'РУИНЫ · ЛАГЕРЬ УНИЧТОЖЕН')+' · '+c.q+':'+c.r+'</span><h2>'+esc(c.name)+'</h2><p>'+esc(c.text)+'</p><div class="k-camp-wall"><b>'+c.hp+' / '+c.max_hp+'</b><span>Прочность укреплений</span><div class="k-meter"><i style="width:'+(100*c.hp/c.max_hp)+'%;background:'+c.color+'"></i></div></div><div class="k-camp-garrison">'+c.garrison.map(u=>'<div><span>'+esc(u.name)+'</span><b>'+u.hp+'/'+u.max_hp+'</b></div>').join('')+'</div><p class="k-muted">Твой вклад: '+c.contribution+' урона укреплениям · набегов всего '+c.raids+'. '+(alive?'Гарнизон и стены не восстанавливаются между набегами. Нетронутый лагерь усиливается до III ступени. Начиная со II — раз в сутки тревожит владения в радиусе 3 клеток.':'Руины исчезнут через '+remaining(c.ruin_until)+'.')+'</p>'+(c.scout?'<div class="k-note">Разведсводка: '+c.garrison.filter(u=>u.hp>0).length+' живых отрядов. Башня вдвое снижает ущерб от налётов лагеря.</div>':'')+(alive?'<label>Тактика набега<select id="k-camp-tactic-'+c.id+'">'+Object.entries(t?.military.tactics||{guard:{name:'Оборона'}}).map(([k,v])=>'<option value="'+k+'">'+esc(v.name)+'</option>').join('')+'</select></label>'+btn(c.busy?'Другой отряд уже в пути':'Начать набег · 6 часов','camp_march:'+c.id,busy||c.busy||!ready,'k-primary')+'<small>Нужен строй из готовых отрядов. Победа: −25% исходной прочности, с мастерской −35%. Слабый набег может проиграть; потери настоящие.</small>':'')+btn('Показать на карте','campfocus:'+c.id,false,'k-quiet')+(c.history.length?'<details><summary>Последние набеги</summary>'+c.history.slice().reverse().map(h=>'<p>'+esc(h.town)+' · '+(h.won?'победа':'отступление')+' · укрепления −'+h.damage+'</p>').join('')+'</details>':'')+'</article>';
  }
  function livingCamps(){return '<section class="k-section-heading"><span class="k-kicker">МИР НЕ ЖДЁТ ПРАВИТЕЛЯ</span><h2>Непрошеные соседи.</h2><p>Общие для всего чата. До четырёх лагерей, новые появляются раз в 12 часов при наличии места. Один набег за раз на лагерь; повреждения сохраняются. После разрушения припасы делятся по вкладу, трофей получают участники, снявшие хотя бы 20% исходной прочности. Франков в кошелёк, XP и предметов арены нет.</p></section><div class="k-camps-grid">'+((view.camps||[]).map(c=>'<section class="k-panel">'+campCard(c)+'</section>').join('')||'<section class="k-panel">Лагерей пока нет. Они появятся после основания первого поселения.</section>')+'</div>';}
  function eventCard(t,compact=false){
   const e=t.event;if(!e)return '';
   let body='<article class="k-event '+esc(e.faction||e.kind)+'"><div class="k-event-type">'+icon(e.kind==='fire'?'fire':e.kind==='bandits'?'barracks':e.faction?'crown':'farm')+'<span>'+esc(e.type)+' · '+remaining(e.deadline)+'</span></div><h3>'+esc(e.name)+'</h3><p>'+esc(e.text)+'</p><p class="k-muted">'+esc(t.name)+' · '+(t.own?'Твоё поселение':esc(t.owner_name))+'</p>';
   if(e.battle)body+='<div class="k-note">Вылазка уже идёт.</div>'+btn('Открыть бой','battle:'+e.battle,false,'k-primary');
   else if(t.own){
    body+=e.choices.map(c=>'<div class="k-choice">'+btn(esc(c.name)+(c.francs?' · '+number(c.francs)+' ₣':'')+(c.food?' · '+c.food+' пищи':'')+(c.wood?' · '+c.wood+' дерева':'')+(c.stone?' · '+c.stone+' камня':''),'event:'+c.id,busy||c.francs>municipal()||['food','wood','stone'].some(k=>(c[k]||0)>t.resources[k])||c.id==='garrison'&&t.defense<e.threat||c.id==='reserve'&&!t.buildings.warehouse,'k-secondary')+((c.favor||c.followup)?'<small>'+(c.favor?'Отношения '+(c.favor>0?'+':'')+c.favor+'. ':'')+(c.followup?'Открывает продолжение истории.':'')+'</small>':'')+'</div>').join('');
    if(e.kind==='bandits')body+=btn('Выступить лично · бой на арене','event:hero',busy,'k-primary')+(e.escrow?'<div class="k-note">Заказ размещён. Помощник получит 4 500 ₣ после победы. 5 000 ₣ уже зарезервированы.</div>':btn('Нанять игрока · резерв 5 000 ₣','event:bounty',busy||municipal()<5000,'k-secondary'));
   }else if(e.can_help)body+='<div class="k-bounty">'+number(e.payout)+' ₣ <span>из бюджета поселения · после победы</span></div>'+btn('Помочь · начать вылазку','help:'+t.id,busy,'k-primary');
   else body+='<div class="k-note">'+(e.kind!=='bandits'?'Решение принимает владелец этого поселения.':e.escrow?'Заказ уже недоступен тебе или твоя попытка использована.':'Правитель ещё не разместил заказ на помощь.')+'</div>';
   return body+(compact?'':'<p class="k-muted">Если не успеть: ограниченная потеря запасов и порядка. Дома и поселение не исчезают. Гарнизон и амбары уменьшают ущерб.</p>')+'</article>';
  }
  function events(){const towns=view.towns.filter(t=>t.event),t=own();return '<section><div class="k-section-heading"><span class="k-kicker">НЕ ВСЁ РЕШАЕТСЯ ЗОЛОТОМ</span><h2>У власти плохая компания.</h2><p>На решение — сутки. Следующее событие через 18 часов после развязки; выбранная история может получить продолжение. Обычные пожары и неурожай редки. Эротические намёки относятся только к взрослым NPC.</p></div><div class="k-factions">'+Object.entries(view.factions).map(([key,f])=>'<article class="k-faction '+key+'"><span>'+esc(f.name)+'</span><b>'+((t?.factions[key]||0)>0?'+':'')+(t?.factions[key]||0)+'</b><small>'+esc(f.motto)+'</small></article>').join('')+'</div><div class="k-events">'+(towns.map(t=>eventCard(t)).join('')||'<div class="k-panel k-empty">В землях спокойно. Самое время подготовиться к тому, что обязательно случится.</div>')+'</div></section>';}
  function journal(){const t=own();return '<section class="k-panel k-journal"><span class="k-kicker">ЛЕТОПИСЬ ПОСЕЛЕНИЯ</span><h2>Сначала было имя.</h2>'+(t?t.history.slice().reverse().map(h=>'<article><time>'+esc(new Date(h.at*1000).toLocaleString('ru-RU'))+'</time><p>'+esc(h.text)+'</p></article>').join(''):'<p>Здесь появится история твоего поселения.</p>')+'</section>';}
  function confirmation(){
   return '<div class="k-modal-backdrop"><section class="k-modal" role="dialog" aria-modal="true" aria-label="Подтверждение действия"><span class="k-kicker">РЕШЕНИЕ ПРАВИТЕЛЯ</span><h2>'+esc(pending.title)+'</h2>'+pending.body+(pending.payload.action==='found'||pending.payload.action==='rename'?'<label>Название<input id="k-name" maxlength="32" value="'+esc(pending.payload.action==='rename'?own().name:'Новый рассвет')+'"></label>'+(pending.payload.action==='rename'?'<label>Описание<textarea id="k-description" maxlength="180">'+esc(own().description)+'</textarea></label>':''):'')+estateFields()+'<div class="k-modal-actions">'+btn('Подтвердить','confirm',busy,'k-primary')+btn('Отмена','cancel',busy,'k-quiet')+'</div></section></div>';
  }
  function estateFields(){
   if(pending.payload.action!=='land_decor')return '';
   const p=pending.payload,e=own().estate,land=e.tiles[p.q+':'+p.r]||{};
   return '<label>Название области<input id="k-land-name" maxlength="32" value="'+esc(land.name)+'"></label><label>Описание<textarea id="k-land-description" maxlength="180">'+esc(land.description)+'</textarea></label><label>Украшение<select id="k-land-decoration">'+options(e.decorations,land.decoration||'none')+'</select></label>';
  }
  function choiceDetails(c){
   if(!c)return '<p>Выбранное решение проверит сервер.</p>';
   const costs=[...(c.francs?[number(c.francs)+' ₣']:[]),...['food','wood','stone'].filter(k=>c[k]).map(k=>c[k]+' '+resourceNames[k].toLowerCase())];
   return '<p>'+(costs.length?'Списать: <b>'+costs.join(', ')+'</b>. ':'')+(c.favor?'Отношения '+(c.favor>0?'+':'')+c.favor+'. ':'')+(c.followup?'Откроется продолжение истории.':'')+'</p><p>'+esc(c.text)+'</p>'+Object.entries(c.grant||{}).map(([k,v])=>'<p>Награда: '+v+' '+resourceUnits[k]+' (избыток сверх амбаров не сохраняется).</p>').join('');
  }
  function render(){
   if(!view)return;
   const scroll=app.querySelector('.k-map-scroll'),position=scroll?{x:scroll.scrollLeft,y:scroll.scrollTop}:null;
   const keepDraft=renderedTownId===own()?.id;
   const formationDraft=keepDraft?Array.from(app.querySelectorAll?.('[data-army-slot]')||[]).map(el=>el.value):[];
   const tacticDraft=keepDraft?['k-tactic','k-defense','k-siege-tactic'].map(id=>[id,app.querySelector('#'+id)?.value]):[];
   const amountDraft=keepDraft?app.querySelector('#k-budget-amount')?.value:null;
   const estateDraft=keepDraft?['k-estate-style','k-estate-emblem','k-estate-color','k-land-name','k-land-description','k-land-decoration',...(view.camps||[]).map(c=>'k-camp-tactic-'+c.id)].map(id=>[id,app.querySelector('#'+id)?.value]):[];
   const openDetails=Array.from(app.querySelectorAll?.('details[data-k-detail]')||[]).filter(el=>el.open).map(el=>el.dataset.kDetail);
   const screens={map,lands,specials,camps:livingCamps,buildings,town:townHub,military:militaryHub,government:governmentHub,
    budget:()=>window.KingdomBudget.render(own(),view,busy),army:()=>window.KingdomArmy.army(own(),spendingView(),busy),
    campaigns:()=>window.KingdomArmy.campaigns(own(),spendingView(),busy,reportId,reportCursor),
    council:()=>window.KingdomDiplomacy.council(own(),spendingView(),busy),wars:()=>window.KingdomDiplomacy.wars(own(),spendingView(),busy,reportId,reportCursor),events,journal};
   shell(overview()+trail()+'<div class="k-layout k-clean-layout '+(tab==='map'?'k-clean-map':'')+'"><main class="k-main">'+(screens[tab]||map)()+(tab==='map'&&!own()?sidebar():'')+'</main>'+(tab==='map'?'<aside class="k-inspector-column">'+tilePanel()+'</aside>':'')+'</div>');
   const next=app.querySelector('.k-map-scroll');if(next&&position){next.scrollLeft=position.x;next.scrollTop=position.y;}
   if(next&&cameraFocus){
    const focus=selected||own()||{q:7,r:5},factor=next.querySelector('svg').getBoundingClientRect().width/964;
    next.scrollLeft=(45+focus.q*60+(focus.r%2)*30)*factor-next.clientWidth/2;
    next.scrollTop=(46+focus.r*52)*factor-next.clientHeight/2;cameraFocus=false;
   }
   if(formationDraft.length)Array.from(app.querySelectorAll('[data-army-slot]')).forEach((el,i)=>{if(Array.from(el.options).some(o=>o.value===formationDraft[i]))el.value=formationDraft[i];});
   for(const[id,value]of tacticDraft)if(value&&app.querySelector('#'+id))app.querySelector('#'+id).value=value;
   if(amountDraft!=null&&app.querySelector('#k-budget-amount'))app.querySelector('#k-budget-amount').value=amountDraft;
   for(const[id,value]of estateDraft)if(value!=null&&app.querySelector('#'+id))app.querySelector('#'+id).value=value;
   for(const key of openDetails){const el=app.querySelector('details[data-k-detail="'+key+'"]');if(el)el.open=true;}
   renderedTownId=own()?.id??null;
  }
  async function load(){const requested=chat,value=await api('/api/kingdom/world?chat='+requested);if(controller.signal.aborted||requested!==chat)return;view=value;if(!selected){const t=own(),land=view.tiles.find(t=>t.can_found);selected=t?{q:t.q,r:t.r}:land?{q:land.q,r:land.r}:{q:7,r:5};}render();}
  function ask(action,payload,title,body,town=own()){
   pending={title,body,payload:{action,...payload,chat,nonce:crypto.randomUUID().replace(/-/g,''),confirm:true,
    ...(town?{town:town.id,revision:town.revision}:{})}};render();
  }
  async function send(){
   if(!pending||busy)return;
   if(['found','rename'].includes(pending.payload.action))pending.payload.name=app.querySelector('#k-name').value;
   if(pending.payload.action==='rename')pending.payload.description=app.querySelector('#k-description').value;
   if(pending.payload.action==='land_decor')Object.assign(pending.payload,{name:app.querySelector('#k-land-name').value,description:app.querySelector('#k-land-description').value,decoration:app.querySelector('#k-land-decoration').value});
   busy=true;render();
   try{const result=await api('/api/kingdom/world',pending.payload);pending=null;view=result.view;error='';context.toast?.(result.notice);if(result.battle){controller.abort();await context.onRaid?.(result.battle);return;}}
   catch(e){error=e.message;pending=null;try{view=await api('/api/kingdom/world?chat='+chat);}catch{}}
   finally{busy=false;if(!controller.signal.aborted)render();}
  }
  app.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('[data-k-tile]'))e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));},{signal:controller.signal});
  // Mouse drag pans the viewport. Touch keeps native two-axis momentum scroll.
  app.addEventListener('pointerdown',e=>{
   const viewport=e.target.closest('.k-map-scroll');
   if(viewport&&e.pointerType==='mouse'&&e.button===0)pan={id:e.pointerId,viewport,x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false};
  },{signal:controller.signal});
  app.addEventListener('pointermove',e=>{
   if(!pan||e.pointerId!==pan.id)return;
   const dx=e.clientX-pan.x,dy=e.clientY-pan.y;
   if(!pan.moved&&Math.hypot(dx,dy)>7){pan.moved=true;app.setPointerCapture(e.pointerId);pan.viewport.classList.add('dragging');}
   if(pan.moved){e.preventDefault();pan.viewport.scrollLeft=pan.left-dx;pan.viewport.scrollTop=pan.top-dy;}
  },{signal:controller.signal});
  const stopPan=e=>{
   if(!pan||e.pointerId!==pan.id)return;
   if(pan.moved){ignoreMapClickUntil=Date.now()+250;pan.viewport.classList.remove('dragging');if(app.hasPointerCapture(e.pointerId))app.releasePointerCapture(e.pointerId);}
   pan=null;
  };
  app.addEventListener('pointerup',stopPan,{signal:controller.signal});
  app.addEventListener('pointercancel',stopPan,{signal:controller.signal});
  app.addEventListener('change',async e=>{
   if(e.target.id==='k-chat'&&!busy){chat=Number(e.target.value);view=null;selected=null;pending=null;inspecting=false;cameraFocus=true;try{await load();}catch(e){error=e.message;shell('<div class="k-panel">'+esc(e.message)+'</div>');}}
  },{signal:controller.signal});
  app.addEventListener('click',async e=>{
   const tile=e.target.closest('[data-k-tile]');if(tile&&!busy){if(Date.now()<ignoreMapClickUntil)return;const[q,r]=tile.dataset.kTile.split(':').map(Number);selected={q,r};inspecting=true;cameraFocus=true;render();return;}
   const element=e.target.closest('[data-k]');if(!element||element.disabled||busy)return;
   const[cmd,...parts]=element.dataset.k.split(':'),arg=parts.join(':');const t=own();error='';
   if(cmd==='section'&&groups[arg]){tab=arg;playing=false;render();return;}
   if(cmd==='layer'&&Object.hasOwn(mapLayers,arg)){mapLayers[arg]=!mapLayers[arg];if(arg==='names')try{window.localStorage?.setItem('gnida_kingdom_map_names',mapLayers.names?'on':'off');}catch{}render();return;}
   if(cmd==='tab'){tab=arg;playing=false;render();return;}
   if(cmd==='campfocus'){const c=(view.camps||[]).find(c=>c.id===arg);if(c){selected={q:c.q,r:c.r};tab='map';inspecting=true;cameraFocus=true;render();}return;}
   if(cmd==='landfocus'){const[q,r]=arg.split(':').map(Number);selected={q,r};tab='map';inspecting=true;cameraFocus=true;render();return;}
   if(cmd==='style_save'){ask('land_style',{style:app.querySelector('#k-estate-style').value,emblem:app.querySelector('#k-estate-emblem').value,color:app.querySelector('#k-estate-color').value},'Применить оформление владения?','<p>Изменятся внешний вид столицы, знамя и границы. Бесплатно, без изменения характеристик.</p>');return;}
   if(cmd==='decor'){const[q,r]=arg.split(':').map(Number);ask('land_decor',{q,r},'Оформить область '+q+':'+r,'<p>Имя, описание и украшение видны всем участникам чата. Это косметика, без скрытых бонусов.</p>');return;}
   if(cmd==='special_build'||cmd==='special_remove'){
    const s=t.estate.catalog[arg];if(!s)return;
    ask(cmd,{special:arg},(cmd==='special_build'?'Заложить: ':'Разобрать: ')+s.name,cmd==='special_build'?'<p>'+esc(s.text)+'</p><p>Из бюджета '+number(s.price)+' ₣; '+s.wood+' дерева, '+s.stone+' камня'+(s.trophies?', '+s.trophies+' трофея':'')+'. Строительство '+s.hours+' часов. Занимает одно особое место и общую очередь. Дополнительное содержание '+s.upkeep+' ₣/сутки при включённых налогах. Ускорения и возврата затрат нет.</p>':'<p>Снос займёт сутки. До завершения бонус действует. Затем место освободится, а бонус исчезнет. Стоимость и трофеи не возвращаются. Во время похода или осады снос запрещён.</p>');return;
   }
   if(cmd==='camp_march'){
    const c=(view.camps||[]).find(c=>c.id===arg);if(!c||!t)return;
    const tactic=app.querySelector('#k-camp-tactic-'+c.id)?.value||'guard';
    ask('camp_march',{camp:c.id,camp_revision:c.revision,tactic},'Набег: '+c.name,'<p>Поход с возвращением — 6 часов. Снабжение: '+t.military.supplies+' пищи. <b>Погибшие отряды теряются навсегда.</b> Строй фиксируется при отправке; отмены нет.</p><p>Победа разрушит '+(t.estate.specials.includes('siegeworks')?'35':'25')+'% исходной прочности. Даже после поражения сохраняются потери гарнизона. После разрушения добыча делится по вкладу; трофей — за вклад от 20%. Излишки припасов сверх амбаров теряются. Никаких франков в кошелёк и наград арены.</p>');return;
   }
   if(cmd==='target'){tab='campaigns';playing=false;render();app.querySelector('[data-k="march:'+arg+'"]')?.scrollIntoView({block:'center'});return;}
   if(cmd==='report'){reportId=arg;reportCursor=0;playing=false;render();return;}
   if(cmd==='replay'){
    const r=currentReport();if(!r)return;
    if(arg==='play'){playing=!playing;if(reportCursor>=r.events.length)reportCursor=0;}
    else{playing=false;reportCursor=arg==='start'?0:arg==='end'?r.events.length:Math.min(r.events.length,reportCursor+1);}
    render();return;
   }
   if(cmd==='choose'){chat=Number(arg);try{await load();}catch(e){error=e.message;shell('<div class="k-panel">'+esc(e.message)+'</div>');}return;}
   if(cmd==='arena'){controller.abort();context.onArena?.(chat);return;}
   if(cmd==='cancel'){pending=null;render();return;}
   if(cmd==='confirm'){await send();return;}
   if(cmd==='zoomin'||cmd==='zoomout'||cmd==='zoomfit'){zoom=cmd==='zoomfit'?0:Math.max(.7,Math.min(2.2,(zoom||1)+(cmd==='zoomin'?.2:-.2)));cameraFocus=true;render();return;}
   if(cmd==='homecamera'){selected={q:t.q,r:t.r};inspecting=true;cameraFocus=true;render();return;}
   if(cmd==='timedfocus'){const point=(view.map_events||[]).find(e=>e.id===arg);if(point){tab='map';selected={q:point.q,r:point.r};inspecting=true;cameraFocus=true;render();}return;}
   if(cmd==='explore'){const point=(view.map_events||[]).find(e=>e.id===arg);if(point)ask('explore',{event:arg},point.name,'<p>'+esc(point.text)+'</p><p>Получить: '+Object.entries(point.grant).map(([k,v])=>v+' '+resourceUnits[k]).join(', ')+'. Избыток сверх вместимости амбаров не сохраняется. Одно посещение на поселение за появление; никаких франков, XP или усиления героя.</p>');}
   if(cmd==='refresh'){try{if(chat)await load();}catch(e){error=e.message;render();}return;}
   if(cmd==='battle'){controller.abort();await context.onRaid?.(arg);return;}
   if(cmd==='activity'){
    busy=true;render();try{const result=await api('/api/kingdom/activity',{chat,q:selected.q,r:selected.r,nonce:crypto.randomUUID().replace(/-/g,'')});controller.abort();if(result.kind==='guild')await context.onGuild?.(chat,result.id);else await context.onRaid?.(result.id);}
    catch(e){error=e.message;}finally{busy=false;if(!controller.signal.aborted)render();}return;
   }
   if(cmd==='found')ask('found',{q:selected.q,r:selected.r},'Основать деревню?','<p>Списать <b>'+number(view.eligibility.price)+' ₣</b>. Ты получишь ратушу, фермы, 36 жителей и начальные запасы. Новый бюджет будет пустым. Пополни его вручную, а затем при желании включи налоги.</p>',null);
   if(cmd==='budget_deposit'){
    const amount=Number(app.querySelector('#k-budget-amount')?.value);
    if(!Number.isSafeInteger(amount)||amount<1||amount>2000000000){error='Укажи целую сумму от 1 до 2 000 000 000 ₣.';render();return;}
    ask(cmd,{amount},'Безвозвратно пополнить бюджет?','<p>Внести '+number(amount)+' ₣ из личного кошелька этого чата в бюджет поселения. При долге сначала оплачивается содержание. Прямого вывода обратно в кошелёк нет.</p>');return;
   }
   if(cmd==='tax_activate'){ask('tax_activate',{},'Включить налоги и содержание?','<p>Доход и содержание начнут начисляться только с этого момента. Ставка — обычная: 16 ₣ с жителя в сутки × этап. Текущий прогноз содержания: '+number(t.budget.quote.upkeep.total)+' ₣/сутки. Каждое поселение включает налоги независимо; другие владения не отключаются. Налоги остаются в казне, личный кошелёк автоматически не списывается.</p>');return;}
   if(cmd==='tax_rate'){
    const rate=t.budget.rates[arg];if(rate)ask('tax_rate',{rate:arg},'Налоги: '+rate.name+'?','<p>'+rate.rate+' ₣ с жителя в сутки × этап. Изменение порядка: '+(rate.order>=0?'+':'')+rate.order+' за сутки. Рост населения ×'+rate.growth+'. Новая смена — через 24 часа, прошлые часы не пересчитываются. Низкий порядок уменьшает собираемость, ниже 30 начинается забастовка.</p>');return;
   }
   if(cmd==='reform'){
    const[field,choice]=arg.split(':'),g=t.government,catalog=field==='policy'?g.policies:g.religions,price=field==='policy'?g.policy_price:g.religion_price;
    ask('reform',{field,choice},'Реформа: '+catalog[choice].name,'<p>Из бюджета списать '+number(price)+' ₣. Завершение через сутки; затем семь дней без новых реформ. До завершения действуют прежние правила. Ускорения и возврата затрат нет.</p><p>'+esc(catalog[choice].text)+'</p>');
   }
   if(cmd==='defense'){const tactic=app.querySelector('#k-defense').value;ask('defense',{tactic},'Сохранить оборонительную тактику?','<p>'+esc(t.military.tactics[tactic].text)+' Во время предупреждения её можно менять; после начала боя она фиксируется.</p>');}
   if(cmd==='siege'){
    const[defender,q,r]=arg.split(':'),target=view.diplomacy.targets.find(x=>x.defender===defender&&x.q===Number(q)&&x.r===Number(r));
    if(!target)return;const tactic=app.querySelector('#k-siege-tactic')?.value||'guard';
    ask('siege',{defender,q:Number(q),r:Number(r),tactic},'Объявить осаду: '+target.name+'?',
      '<p>Цель '+q+':'+r+'. Из бюджета списать '+number(view.diplomacy.fee)+' ₣ и '+t.military.supplies+' пищи. Тактика: '+esc(t.military.tactics[tactic].name)+'.</p><p>Сутки подготовки начнутся только после сообщения в Telegram, затем 6 часов боя. Строй нападающего фиксируется сейчас. Погибшие отряды исчезнут навсегда; победа передаёт одну клетку, не столицу. После доставки предупреждения затраты не возвращаются даже при отзыве.</p>');
   }
   if(cmd==='cancel_siege')ask('cancel_siege',{siege:arg},'Отозвать осаду?','<p>Можно только до начала боя. После доставки предупреждения пошлина и припасы не возвращаются. Повторный вызов этого соседа останется ограничен неделей.</p>');
   if(cmd==='recruit'){
    const u=t.military.catalog[arg];ask('recruit',{unit:arg},'Нанять: '+u.name,'<p>Из бюджета списать '+number(u.price)+' ₣, '+u.food+' пищи и '+u.wood+' древесины. Обучение '+u.hours+' ч. Один отряд занимает место в резерве; возврата стоимости при роспуске нет.</p>');
   }
   if(cmd==='formation'){
    const formation=Array.from(app.querySelectorAll('[data-army-slot]')).map(el=>el.value||null);
    ask('formation',{formation},'Сохранить боевой строй?','<p>Пять позиций: две впереди, две в тылу и поддержка. Один и тот же отряд нельзя выбрать дважды. Синергии пересчитаются по сохранённому составу.</p>');
   }
   if(cmd==='recover'||cmd==='dismiss'){
    const u=t.military.units.find(u=>u.id===arg);if(!u)return;
    ask(cmd,{unit:arg},cmd==='recover'?'Восстановить отряд?':'Распустить отряд?',cmd==='recover'?'<p>Списать '+(30+Math.ceil((100-u.condition)/2))+' пищи. Восстановление займёт 3 часа и очередь казарм.</p>':'<p>Отряд будет удалён из резерва и строя. Деньги, припасы и время обучения не возвращаются. Действие необратимо.</p>');
   }
   if(cmd==='march'){
    const m=t.military,p=m.outposts.find(p=>p.id===arg),tactic=app.querySelector('#k-tactic')?.value||'guard',count=m.formation.filter(Boolean).length;
    ask('march',{target:arg,tactic},'Поход: '+p.name,'<p>Тактика: '+esc(m.tactics[tactic].name)+'. Списать '+m.supplies+' пищи. Поход и возвращение — 6 часов. Отправленный строй нельзя менять.</p><p><b>Погибшие отряды теряются навсегда.</b> Выжившие вернутся ранеными. Отмены похода нет. Добыча — только внутренние ресурсы; франки, XP и предметы арены не выдаются.</p>');
   }
   if(cmd==='rename')ask('rename',{},'Имя твоего владения','<p>Название и описание видны участникам этого чата.</p>');
   if(cmd==='supplies')ask('supplies',{},'Заказать снабжение?','<p>Из бюджета 2 500 ₣: 120 пищи, 80 древесины и 60 камня. Избыток сверх вместимости амбаров не сохраняется.</p>');
   if(cmd==='annex')ask('annex',{q:selected.q,r:selected.r},'Расширить границы?','<p>Списать '+number(t.annex_price)+' ₣. Земля должна прилегать к территории и быть свободной.</p>');
   if(cmd==='promote'){const p=t.promotion;ask('promote',{},'Новый этап: '+p.name,'<p>Списать '+number(p.price)+' ₣. Предел — '+p.lands+' земель, постройки до '+p.building_cap+' уровня. Смена этапа необратима. Часть тяжёлых войск требует города и отношений с фракциями. Столицы и связность владений защищены при осадах.</p>');}
   if(cmd==='build'){const b=t.building_options.find(b=>b.id===arg);ask('build',{building:arg},b.name+' · уровень '+b.quote.level,'<p>Списать '+number(b.quote.price)+' ₣, '+b.quote.wood+' древесины, '+b.quote.stone+' камня. Строительство займёт '+duration(b.quote.finish-b.quote.started)+'. Платного ускорения нет.</p>');}
   if(cmd==='event'){const choice=t.event.choices.find(c=>c.id===arg);ask('event',{choice:arg},arg==='bounty'?'Разместить заказ?':arg==='hero'?'Возглавить вылазку?':choice?.name||'Решить событие',arg==='bounty'?'<p>Зарезервировать 5 000 ₣ из бюджета. Другой игрок получит 4 500 ₣ после победы. Если заказ не выполнен, резерв вернётся.</p>':arg==='hero'?'<p>Бой против своры теплотрассы на существующей арене. Без XP, предметов, рейтинга и реальных расходников. Одна личная попытка на событие.</p>':choiceDetails(choice));}
   if(cmd==='help'){const target=view.towns.find(t=>t.id===arg);ask('help',{},'Принять заказ на зачистку?','<p>Награда — 4 500 ₣ из резерва поселения, только после победы. Одна попытка, без обычных наград арены.</p>',target);}
  },{signal:controller.signal});
  controller.signal.addEventListener('abort',()=>{clearInterval(timer);clearInterval(replayTimer);});
  try{
   shell('<div class="k-panel k-empty">Разворачиваем карту северных земель…</div>');
   chats=(await api('/api/kingdom/chats')).chats;
   if(chat)await load();else shell('<section class="k-panel k-choose"><span class="k-kicker">ВЫБЕРИ МИР</span><h2>У каждого чата своя история.</h2><p>Персонаж остаётся общим, поселения и кошелёк принадлежат выбранному чату.</p>'+chats.map(c=>btn(esc(c.title||c.chat_id),'choose:'+c.chat_id,false,'k-secondary')).join('')+(!chats.length?'<p>Напиши /королевство в группе, где включена арена.</p>':'')+'</section>');
   timer=setInterval(async()=>{if(chat&&!busy&&!pending&&!pan&&!document.hidden){try{await load();}catch(e){error=e.message;render();}}},20000);
   replayTimer=setInterval(()=>{
    if(!playing||!['campaigns','wars'].includes(tab)||pending||busy||document.hidden)return;
    const r=currentReport();if(!r){playing=false;return;}
    reportCursor=Math.min(reportCursor+1,r.events.length);if(reportCursor>=r.events.length)playing=false;render();
   },650);
  }catch(e){if(!controller.signal.aborted){error=e.message;shell('<section class="k-panel k-empty"><h2>Не удалось открыть карту</h2><p>'+esc(e.message)+'</p>'+btn('Повторить','refresh')+'</section>');}}
 }
})();
