/* Account-owned equipment. Rolls, comparisons and mutations stay server-side. */
(()=>{
 'use strict';let previous;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const number=v=>Number(Number(v||0).toFixed(2)).toLocaleString('ru-RU');
 const symbols={weapon:'<path d="m10 35 23-23 5-2-2 6-23 23M9 29l13 13M8 40l6-6"/>',armor:'<path d="m14 10 10 4 10-4 7 8-7 5v17H14V23l-7-5z"/>',accessory:'<circle cx="24" cy="30" r="11"/><path d="m17 17 7-9 7 9-7 7z"/>',relic:'<path d="m24 6 14 18-14 18L10 24zM10 24h28M24 6l6 18-6 18-6-18z"/>'};
 const special={
  staff:'<path d="m12 42 17-27M23 7l7-3 8 8-4 9-9-1-5-7zM23 7l3 10 8 4M26 17l12-5"/>',
  fang:'<path d="M9 10c14-3 28 1 29 12-7-1-7 18-26 21 8-10 10-17 3-20-5-3-7-7-6-13zM15 15l6 4"/>',
  heart:'<path d="M24 40C-2 22 10 7 21 15l3 3 3-3c12-8 25 7-3 25zM24 17l-5 11 8-3-3 15"/>',
  eye:'<path d="M4 24Q24 3 44 24 24 45 4 24z"/><circle cx="24" cy="24" r="8"/><path d="M24 18v12M10 9l5 6M38 9l-5 6M24 4v8"/>',
  flask:'<path d="M18 5h12M20 5v12L10 36q-1 6 5 6h18q6 0 5-6L28 17V5M15 28h18M22 33l4 3"/>',
  brick:'<path d="m6 18 22-8 15 9-23 10-14-8zM6 21v10l14 9 23-10V19M20 29v11M16 24l22-10"/>',
  candle:'<path d="M17 23h14v18H17zM24 5c-8 8-8 13 0 14 9-1 5-10 0-14zM12 42h24M21 26v6"/>',
  helmet:'<path d="M10 25C7 4 41 4 38 25v12l-11 6v-9h-6v9l-11-6zM10 25l11 4v-6M38 25l-11 4v-6M24 8v13"/>'
 };
 const art=i=>'<span class="gear-icon"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'+(special[i.key]||(['shaman','thorn','ember'].includes(i.key)?special.staff:symbols[i.slot]))+'</svg></span>';
 const button=(name,action,disabled=false,cls='')=>'<button type="button" data-gear="'+esc(action)+'" class="'+cls+'"'+(disabled?' disabled':'')+'>'+name+'</button>';
 const safeArt=url=>/^\/(?:sprites\/[0-9a-f]{64}|static\/assets\/(?:(?:archclasses|rpg|casino)\/)?[a-z_]+)\.png$/.test(url||'');
 window.GearApp={open};

 async function open(context){
  previous?.abort();const abort=new AbortController();previous=abort;
  let view,selected='',filter='all',rarity='all',search='',tab='inventory',confirm='',busy=false,message='',inventoryScroll=0;
  const app=context.app;
  async function api(body){
   const res=await fetch('/api/equipment'+(body?'':'?chat='+context.chat),{
    method:body?'POST':'GET',signal:abort.signal,
    headers:{'X-Telegram-Init-Data':context.initData||'',...(body?{'Content-Type':'application/json'}:{})},
    body:body?JSON.stringify(body):undefined});
   const data=await res.json();if(!res.ok)throw Error(data.error||'Не удалось открыть снаряжение.');return data;
  }
  function chips(stats){return Object.entries(stats).map(([k,v])=>'<span>'+esc(view.stat_names[k]||k)+' <b>+'+number(v)+'</b></span>').join('');}
  function slot(key){
   const i=view.items.find(i=>i.id===view.equipped[key]);
   const inactive=i&&view.level<i.min_level;
   return '<button class="gear-slot '+(i?'rarity-'+i.rarity:'')+(i?.id===selected?' selected':'')+'" data-gear="'+(i?'select:'+i.id:'filter:'+key)+'" aria-label="'+esc(view.slots[key]+': '+(i?.name||'пустой слот'))+'" title="'+esc(i?.name||view.slots[key])+'">'+art(i||{slot:key})+
    '<span class="gear-slot-label">'+esc(view.slots[key])+'</span>'+(i?'<span class="gear-slot-rank">'+i.rank+(i.upgrade?' +'+i.upgrade:'')+'</span>':'<span class="gear-slot-empty">＋</span>')+
    (inactive?'<span class="gear-slot-warning">Lv. '+i.min_level+'+</span>':'')+'</button>';
  }
  function character(){
   const hero=view.hero||{},src=safeArt(hero.sprite_url)?hero.sprite_url:'/static/assets/ragamuffin.png';
   return '<section class="gear-character-grid" aria-label="Персонаж и характеристики">'+
    '<section class="gear-character gear-panel"><div class="gear-panel-title"><div><p class="gear-kicker">ТВОЙ ПЕРСОНАЖ</p><h2>'+esc(hero.name||'Твой герой')+'</h2></div><span class="gear-level-pill">LV. '+view.level+'</span></div>'+
    '<p class="gear-class">'+esc(view.class_name)+' <span>· Слот №'+view.character_slot+'</span></p>'+
    '<div class="gear-doll"><div class="gear-slot-column">'+slot('weapon')+slot('armor')+'</div>'+
    '<div class="gear-hero-stage"><div class="gear-hero-ring" aria-hidden="true"></div><img class="gear-hero-sprite'+(hero.pixel_art?' pixel-art':'')+'" src="'+esc(src)+'" alt="Спрайт: '+esc(hero.name||view.class_name)+'"><span class="gear-hero-shadow" aria-hidden="true"></span></div>'+
    '<div class="gear-slot-column">'+slot('accessory')+slot('relic')+'</div></div>'+
    '<p class="gear-character-hint">Выбери слот или предмет справа.<br>Твой спрайт не меняется от экипировки.</p></section>'+stats()+'</section>';
  }
  function stats(){
   return '<section class="gear-stats gear-panel" aria-label="Характеристики и бонусы экипировки"><p class="gear-kicker">ПАРАМЕТРЫ ГЕРОЯ</p><h2>Характеристики</h2>'+
    '<div class="gear-stats-legend"><span>Основа</span><span class="gear-bonus">+ вещи</span><span>Итого</span></div>'+
    '<div class="gear-stats-list">'+Object.entries(view.stat_names).map(([k,n])=>{
     const bonus=view.stat_bonuses?.[k]??Math.round(((view.stats[k]||0)-(view.base_stats[k]||0))*100)/100;
     return '<div class="gear-stat-row"><span class="gear-stat-label">'+esc(n)+'</span><div class="gear-stat-values"><span>'+number(view.base_stats[k])+'</span><span class="gear-bonus"'+(bonus===0?' data-zero="true"':'')+'>'+(bonus>=0?'+':'')+number(bonus)+'</span><strong>'+number(view.stats[k])+'</strong></div></div>';
    }).join('')+'</div><div class="gear-stats-note"><span>＋</span><p>Бонусы надетого снаряжения уже включены в итоговые значения.</p></div>'+
    '<div class="gear-energy-note"><span>Энергия</span><b>'+number(view.stats.resource_max)+'</b><small>Регенерация 8% за ход — без изменений</small></div></section>';
  }
  function itemCard(i){
   return '<button class="gear-item rarity-'+i.rarity+'" data-gear="select:'+i.id+'" aria-label="'+esc(i.rarity_name+' '+i.name)+'">'+
    '<span class="gear-item-top"><small>'+i.rank+' · '+esc(i.rarity_name)+'</small><span class="gear-flags">'+(i.favorite?'★':'')+(i.equipped?' ✓':'')+'</span></span>'+art(i)+
    '<strong>'+esc(i.name)+(i.upgrade?' <em>+'+i.upgrade+'</em>':'')+'</strong><span class="gear-item-bottom">'+esc(view.slots[i.slot])+'<small>Lv. '+i.min_level+'+</small></span></button>';
  }
  function inventory(){
   const rows=view.items.filter(i=>(filter==='all'||i.slot===filter)&&(rarity==='all'||i.rarity===rarity)&&i.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
   return '<section class="gear-inventory gear-panel" aria-label="Инвентарь экипировки"><div class="gear-panel-title"><div><p class="gear-kicker">ОБЩИЙ СКЛАД АККАУНТА</p><h2>Инвентарь</h2></div><span class="gear-count">'+rows.length+' / '+view.items.length+'</span></div>'+
    '<div class="gear-filters"><input id="gear-search" type="search" placeholder="Найти предмет…" aria-label="Поиск экипировки" value="'+esc(search)+'">'+
    '<select id="gear-slot-filter" aria-label="Слот"><option value="all">Все слоты</option>'+Object.entries(view.slots).map(([k,n])=>'<option value="'+k+'"'+(filter===k?' selected':'')+'>'+esc(n)+'</option>').join('')+'</select>'+
    '<select id="gear-rarity" aria-label="Редкость">'+[['all','Все редкости'],['common','Обычные'],['uncommon','Необычные'],['rare','Редкие'],['epic','Эпические'],['legendary','Легендарные']].map(([k,n])=>'<option value="'+k+'"'+(rarity===k?' selected':'')+'>'+n+'</option>').join('')+'</select></div>'+
    '<div class="gear-item-list">'+rows.map(itemCard).join('')+(rows.length?'':'<div class="gear-empty"><span>◇</span><h3>'+(view.items.length?'Ничего не найдено':'Твоя добыча ещё впереди')+'</h3><p>'+(view.items.length?'Измени поиск или фильтры.':'В конце подземелья каждый участник получает одну гарантированную вещь.')+'</p></div>')+'</div>'+
    '<details class="gear-rules"><summary>Как добывать экипировку</summary><p>Охота: 15%. Особый заказ: 45%. За данж — одна гарантированная вещь и ещё 25% за каждый пройденный сундук или элитную комнату. Дроп личный, после успешного возвращения.</p><p>Улучшение до +5 без поломок. Особые эффекты не усиливаются заточкой и не складываются с одинаковыми. Надетые и избранные вещи защищены от разборки.</p></details></section>';
  }
  function detail(){
   const i=view.items.find(i=>i.id===selected);if(!i){selected='';return inventory();}
   const no=busy||view.busy,mat=view.materials[i.rank]||0;
   const comparison=Object.entries(view.stat_names).map(([k,n])=>{
    const delta=Math.round(((i.comparison[k]||0)-(view.stats[k]||0))*100)/100;
    return '<tr><td>'+esc(n)+'</td><td>'+number(view.stats[k])+'</td><td class="'+(delta>0?'positive':delta<0?'negative':'')+'">'+(delta>0?'+':'')+number(delta)+'</td></tr>';
   }).join('');
   return '<section class="gear-detail gear-panel rarity-'+i.rarity+'" aria-label="Детали предмета">'+
    '<div class="gear-detail-top">'+button('← Инвентарь','inventory',false,'gear-back-inventory')+'<span>РАНГ '+i.rank+'</span></div><div class="gear-detail-heading">'+art(i)+'<div><p class="gear-kicker">'+esc(i.rarity_name)+' · '+esc(view.slots[i.slot])+'</p><h2>'+esc(i.name)+(i.upgrade?' <em>+'+i.upgrade+'</em>':'')+'</h2></div></div>'+
    '<div class="gear-detail-scroll"><p class="gear-level">Уровень '+i.min_level+'+ · '+(i.equipped?'Надето на этом персонаже':i.used_by.length?'В сборках: №'+i.used_by.join(', №'):'В общем инвентаре')+'</p><div class="gear-properties">'+chips(i.stats)+'</div>'+
    (i.effect_text?'<div class="gear-effect"><small>ОСОБЫЙ ЭФФЕКТ</small><p>'+esc(i.effect_text)+'</p></div>':'<p class="gear-muted">Особый эффект появляется у эпических и легендарных версий.</p>')+
    '<h3>Если надеть</h3><table class="gear-compare"><thead><tr><th>Характеристика</th><th>Сейчас</th><th>Разница</th></tr></thead><tbody>'+comparison+'</tbody></table>'+
    '<div class="gear-detail-actions">'+button(i.equipped?'Снять':'Надеть',i.equipped?'unequip:'+i.id:'equip:'+i.id,no||!i.equipped&&view.level<i.min_level,'primary')+
    button(i.favorite?'★ В избранном':'☆ В избранное','favorite:'+i.id,busy)+button(i.upgrade>=5?'Улучшено до +5':'Улучшить до +'+(i.upgrade+1)+' · '+i.upgrade_cost+' оск. '+i.rank,'upgrade:'+i.id,no||i.upgrade>=5||mat<i.upgrade_cost)+
    button('Разобрать · +'+i.salvage+' оск. '+i.rank,'ask:'+i.id,no||i.favorite||i.used_by.length>0,'danger')+'</div>'+
    (confirm===i.id?'<div class="gear-confirm"><b>Разобрать без возврата?</b><p>Вещь исчезнет. Ты получишь материалы её ранга.</p>'+button('Да, разобрать','salvage:'+i.id,no,'danger')+button('Оставить','cancel')+'</div>':'')+
    (i.affixes.length&&!i.rerolled?'<details class="gear-reroll"><summary>Заменить одно свойство · 5 оск. '+i.rank+'</summary><p>Один раз для этой вещи. Выбери свойство и новый вариант.</p><label>Заменить<select id="gear-affix">'+i.affixes.map((k,x)=>'<option value="'+x+'">'+esc(view.stat_names[k])+'</option>').join('')+'</select></label><label>На<select id="gear-choice">'+i.reroll_options.map(k=>'<option value="'+k+'">'+esc(view.stat_names[k])+'</option>').join('')+'</select></label>'+button('Подтвердить замену','reroll:'+i.id,no||mat<5)+'</details>':'')+'</div></section>';
  }
  function workshop(){return '<section class="gear-workshop"><div class="gear-workshop-heading"><p class="gear-kicker">БЕЗ ЛОТЕРЕИ · БЕЗ ПОЛОМОК</p><h2>Мастерская снаряжения</h2><p>8 осколков — необычный предмет. 40 — эпический с особым эффектом. Ранг не выше твоего ранга гильдии. Дополнительные свойства случайны.</p><label>Ранг<select id="gear-craft-rank">'+view.ranks.filter((r,x)=>x<=view.ranks.indexOf(view.hunter_rank)).map(r=>'<option>'+r+'</option>').join('')+'</select></label></div><div class="gear-catalog">'+view.catalog.map(i=>'<article class="gear-panel">'+art(i)+'<small>'+esc(view.slots[i.slot])+'</small><h3>'+esc(i.name)+'</h3><p>'+esc(i.description)+'</p>'+button('Необычный · 8 оск.','buy:'+i.key,view.busy||busy)+button('Эпический · 40 оск.','craft:'+i.key,view.busy||busy)+'</article>').join('')+'</div></section>';}
  function render(){
   if(abort.signal.aborted||!view)return;
   app.innerHTML='<section class="gear"><header class="gear-header"><div><p class="gear-kicker">ГНИДА / ПЕРСОНАЖ</p><h1>Снаряжение</h1><p>Сила складывается из деталей.</p></div>'+button('← Назад','back')+'</header>'+
    '<div class="gear-toolbar"><nav class="gear-tabs" aria-label="Разделы снаряжения">'+button('Персонаж и инвентарь','tab:inventory',false,tab==='inventory'?'active':'')+button('Мастерская','tab:workshop',false,tab==='workshop'?'active':'')+'</nav><div class="gear-materials"><span>ОСКОЛКИ</span>'+view.ranks.map(r=>'<span><b>'+r+'</b> '+(view.materials[r]||0)+'</span>').join('')+'</div></div>'+
    (message?'<div class="gear-notice" role="status">'+esc(message)+'</div>':'')+(view.busy?'<div class="gear-notice">Идёт бой или поход. Комплект зафиксирован до его завершения.</div>':'')+
    (tab==='workshop'?workshop():'<div class="gear-layout">'+character()+'<div class="gear-right">'+(selected?detail():inventory())+'</div></div>')+
    '<footer class="gear-footer"><span>ОБЩИЙ ИНВЕНТАРЬ · ОТДЕЛЬНЫЙ КОМПЛЕКТ КАЖДОГО ПЕРСОНАЖА</span><span>Экипировка не меняет внешний вид героя.</span></footer></section>';
   app.querySelector('.gear-item-list')?.scrollTo({top:inventoryScroll});
  }
  async function load(){view=await api();render();}
  function focusRight(){
   const panel=app.querySelector('.gear-right');
   if(matchMedia('(max-width:900px)').matches)panel?.scrollIntoView({behavior:'smooth',block:'start'});
   panel?.querySelector('button')?.focus({preventScroll:true});
  }
  app.addEventListener('click',async e=>{
   const b=e.target.closest('[data-gear]');if(!b||b.disabled||busy)return;
   const [cmd,arg]=b.dataset.gear.split(':');
   if(cmd==='back'){abort.abort();await context.onBack();return;}
   if(cmd==='select'){inventoryScroll=app.querySelector('.gear-item-list')?.scrollTop??inventoryScroll;selected=arg;confirm='';render();focusRight();return;}
   if(cmd==='inventory'){selected='';confirm='';render();focusRight();return;}
   if(cmd==='filter'){selected='';filter=arg;inventoryScroll=0;render();focusRight();return;}
   if(cmd==='tab'){tab=arg;render();return;}
   if(cmd==='ask'){confirm=arg;render();return;}
   if(cmd==='cancel'){confirm='';render();return;}
   const body={chat:context.chat,action:cmd,item:arg,revision:view.revision,character_slot:view.character_slot,nonce:crypto.randomUUID()};
   if(cmd==='reroll'){body.index=Number(app.querySelector('#gear-affix').value);body.choice=app.querySelector('#gear-choice').value;}
   if(['craft','buy'].includes(cmd)){body.key=arg;body.rank=app.querySelector('#gear-craft-rank').value;}
   busy=true;message='';
   try{
    view=await api(body);confirm='';
    if(['craft','buy'].includes(cmd)){selected=view.items[0]?.id||'';tab='inventory';}
    if(cmd==='salvage')selected='';
    message=({equip:'Предмет надет. Характеристики обновлены.',unequip:'Предмет снят. Характеристики обновлены.',salvage:'Вещь разобрана. Материалы получены.',upgrade:'Улучшение выполнено.',reroll:'Свойство заменено.',craft:'Эпический предмет создан.',buy:'Необычный предмет создан.'})[cmd]||'Сохранено.';
   }catch(error){message=error.message;try{view=await api();}catch{} }
   finally{busy=false;render();}
  },{signal:abort.signal});
  app.addEventListener('change',e=>{
   if(e.target.id==='gear-slot-filter')filter=e.target.value;else if(e.target.id==='gear-rarity')rarity=e.target.value;else return;
   inventoryScroll=0;render();
  },{signal:abort.signal});
  app.addEventListener('input',e=>{
   if(e.target.id!=='gear-search')return;const pos=e.target.selectionStart;search=e.target.value;inventoryScroll=0;render();
   const input=app.querySelector('#gear-search');input.focus({preventScroll:true});if(pos!==null)input.setSelectionRange(pos,pos);
  },{signal:abort.signal});
  app.addEventListener('error',e=>{
   if(!e.target.classList?.contains('gear-hero-sprite'))return;
   const fallback=view?.hero?.fallback_url;
   if(safeArt(fallback)&&e.target.getAttribute('src')!==fallback)e.target.src=fallback;
  },{capture:true,signal:abort.signal});
  try{await load();}catch(error){app.innerHTML='<section class="gear"><h1>Снаряжение недоступно</h1><p>'+esc(error.message)+'</p>'+button('← Назад','back')+'</section>';}
 }
})();
