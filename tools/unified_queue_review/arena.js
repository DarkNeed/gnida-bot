// Local adapter over the real arena renderers, not a second battle interface.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n).toFixed(2).replace('.',',');
const colors={h1:'#79c8df',h2:'#a8d5ad',e1:'#b39ce5',e2:'#dc9279'};
let ui,state,catalog,actor='h1',target='e1',busy=false,lastLog=0,previous={},axis=5;
const app=()=>document.getElementById('app');
const map=k=>k==='h1'?'1':k==='h2'?'2':k;
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'Не удалось загрузить демо');return data;}
function notice(text){const el=document.getElementById('toast');el.textContent=text;el.hidden=false;setTimeout(()=>el.hidden=true,6000);}
function nativeView(){
 const hero=state.fighters[actor].arena,enemy=state.fighters.e1.arena;
 if(state.heroes.length===1&&state.enemies.length===1){
  return {token:state.token,chat_id:-1,actor_id:hero.controller_id,own_side:'a',mode:'personal',status:state.finished?'finished':'active',revision:state.revision,
   state:{turn:1+Object.values(state.fighters).reduce((n,f)=>n+f.arena.own_turns,0),active_side:'a',finished:state.finished,winner:state.finished?(hero.hp>0?'a':'b'):null,
    sides:{a:hero,b:enemy},log:state.log.map((e,i)=>({seq:i+1,text:e.text}))},
   qte:state.stage?{waiting:true,actor:hero.controller_id,kind:state.stage.kind}:null};
 }
 const players=Object.fromEntries(state.heroes.map(k=>[map(k),{actor_id:state.fighters[k].arena.controller_id,fighter:state.fighters[k].arena,
  ready:!state.idle.includes(k),withdrawn:false,deported_round:-1,personal:true}]));
 const enemies=Object.fromEntries(state.enemies.map(k=>[k,state.fighters[k].arena]));
 const intents=Object.fromEntries(state.pending.filter(e=>state.enemies.includes(e.actor)).map(e=>[e.actor,{skill:e.skill,targets:[map(e.target)],text:catalog.skills.find(s=>s.id===e.skill)?.name||e.skill}]));
 return {token:state.token,chat_id:-1,actor_id:hero.controller_id,status:state.finished?'finished':'active',revision:state.revision,kind:'encounter',boss_id:'queue_review',
  boss_name:'Бой',participants:state.heroes.map(k=>({actor_id:state.fighters[k].arena.controller_id,personal:true})),
  qte:state.stage?{waiting:true,actor:hero.controller_id,kind:state.stage.kind}:null,
  data:{players,enemies,boss:enemy,enemy_intents:intents,intent:{text:'',targets:[]},round:1+Object.values(state.fighters).reduce((n,f)=>n+f.arena.own_turns,0),phase:1,
    action_queue:{colors:Object.fromEntries(Object.entries(colors).map(([k,v])=>[map(k),v])),phase:'resolve',time:0,round:1,
      entries:state.pending.map(e=>({actor:map(e.actor),at:e.end-state.time}))},
    finished:state.finished,rewards:{},result:hero.hp>0?'Победа':'Отряд повержен',log:state.log.map((e,i)=>({seq:i+1,round:fmt(e.at),text:e.text,actor:map(e.actor||'h1')}))}};
}
function timeline(field){
 const events=[...state.pending,...state.group];
 axis=Math.max(5,...events.map(e=>e.end-state.time),...state.fighters[actor].arena.skill_details.map(s=>s.cast_time));
 const host=document.createElement('div');host.className='uq-timeline';host.setAttribute('aria-label','Завершение действий: сейчас слева, будущие касты справа');
 host.innerHTML='<div class="uq-axis"><span>Сейчас · '+fmt(state.time)+'</span><span>+'+fmt(axis)+'</span></div><div class="uq-track"></div><div class="uq-marks"></div>';
 field.append(host);const marks=host.querySelector('.uq-marks'),positions={};
 events.forEach((e,i)=>{const pos=Math.max(0,Math.min(100,(e.end-state.time)/axis*100)),key=e.actor+':'+e.end,
  offset=events.slice(0,i).filter(p=>p.end===e.end).length*8;
  const dot=document.createElement('i');dot.className='uq-mark';dot.style.cssText='left:calc('+pos+'% + '+offset+'px);--unit:'+colors[e.actor];
  dot.title=state.fighters[e.actor].name+' · '+(catalog.skills.find(s=>s.id===e.skill)?.name||e.skill)+' · через '+fmt(e.end-state.time);
  dot.setAttribute('aria-label',dot.title);marks.append(dot);
  if(!offset){const label=document.createElement('span');label.textContent=fmt(e.end-state.time);dot.append(label);}
  if(previous[key]!=null&&Math.abs(previous[key]-pos)>.01&&!matchMedia('(prefers-reduced-motion: reduce)').matches)dot.animate([{left:previous[key]+'%'},{left:dot.style.left}],{duration:450,easing:'ease-in-out'});
  positions[key]=pos;
 });previous=positions;
}
function forecast(skill){
 const message=document.getElementById('uq-forecast'),track=document.querySelector('.uq-track');if(!message||!track||!skill)return;
 const incoming=state.pending.filter(e=>state.enemies.includes(e.actor)&&e.target===actor),end=state.time+skill.cast_time,
  delta=incoming.length?Math.min(...incoming.map(e=>e.end))-end:null,
  kind=delta===null?'none':Math.abs(delta)<.001?'together':delta>0?'before':'after';
 message.className='uq-forecast '+kind;
 message.textContent=skill.name+' · '+fmt(skill.cast_time)+' времени. '+(delta===null?'По тебе сейчас нет входящей атаки.':kind==='before'?'Успеешь · до удара останется '+fmt(delta)+'.':kind==='together'?'Одновременно с врагом.':'Враг ударит раньше на '+fmt(-delta)+'. Каст продолжится.');
 track.innerHTML='<span class="uq-ghost '+kind+'" style="width:'+Math.min(100,skill.cast_time/axis*100)+'%"></span>';
}
function render(){
 if(!state.idle.includes(actor)&&!state.stage)actor=state.idle[0]||actor;
 if(state.fighters[target]?.hp<=0)target=state.enemies.find(k=>state.fighters[k].hp>0)||'e1';
 const solo=state.heroes.length===1&&state.enemies.length===1;
 if(solo)ui.battleScreen(nativeView());else ui.raidScreen(nativeView());
 document.body.classList.add('queue-native');
 const header=app().querySelector('.top');
 header.querySelector('h1').textContent='Арена';header.querySelector('.eyebrow').textContent='ДЕМО · НОВАЯ ОЧЕРЕДЬ';
 for(const button of header.querySelectorAll('[data-raid="refresh"]')){button.removeAttribute('data-raid');button.setAttribute('data-uq-settings','');button.textContent='Новый бой';}
 for(const button of app().querySelectorAll('[data-combat-open]')){button.removeAttribute('data-combat-open');button.setAttribute('data-uq-settings','');button.setAttribute('aria-label','Настройки демо');button.title='Настройки демо';}
 app().querySelectorAll('[data-do="menu"],[data-raid="rp"],[data-do="surrender"],[data-raid="skill:surrender"],[data-raid="skill:defend"]').forEach(el=>el.remove());
 document.getElementById('raid-timer')?.remove();
 const field=app().querySelector(solo?'.field':'.raid-field');timeline(field);
 if(!solo)ui.target(target);
 const actions=app().querySelector(solo?'#panel':'.raid-actions');
 if(state.finished){actions.innerHTML='<div class="battlelog">'+(state.heroes.some(k=>state.fighters[k].hp>0)?'Победа!':'Отряд повержен.')+'</div><p class="muted">Демо завершено · без наград и изменений персонажа.</p><button class="primary" data-uq-settings>Новый бой</button>';}
 else{
  const lead=document.createElement('div');lead.className='uq-guidance';
  const incoming=state.pending.filter(e=>state.enemies.includes(e.actor)&&e.target===actor);
  lead.innerHTML='<div class="row"><span class="muted">'+(state.stage?'Боевые часы на паузе · мини-игра':state.idle.includes(actor)?'Твой выбор':'Готовится действие')+'</span><b class="uq-incoming">'+(incoming.length?'До удара: '+fmt(Math.min(...incoming.map(e=>e.end))-state.time):'Нет входящей атаки')+'</b></div><p id="uq-forecast" class="uq-forecast" role="status">Наведи на навык или нажми ⓘ: увидишь, успеет ли он до удара.</p>';
  if(state.heroes.length>1)lead.innerHTML+='<div class="uq-heroes">'+state.heroes.map(k=>'<button class="small '+(k===actor?'primary':'')+'" data-uq-hero="'+k+'" '+(!state.idle.includes(k)||busy?'disabled':'')+'>'+esc(state.fighters[k].name)+(state.idle.includes(k)?'':' · каст')+'</button>').join('')+'</div>';
  actions.prepend(lead);
  for(const button of actions.querySelectorAll('[data-skill],[data-raid^="skill:"]')){
   const sid=button.dataset.skill||button.dataset.raid.slice(6),skill=state.fighters[actor].arena.skill_details.find(s=>s.skill_id===sid);if(!skill)continue;
   const wrapper=document.createElement('div');wrapper.className='uq-skill-wrap';button.before(wrapper);wrapper.append(button);
   // The normal skill renderer supplies costs, descriptions and disabled rules.
   if(!solo){const time=document.createElement('small');time.className='uq-duration';time.textContent=fmt(skill.cast_time)+' времени';button.append(time);}
   else for(const line of button.querySelectorAll('span'))if(/ · \d+(?:\.\d+)? с/.test(line.textContent))line.textContent=line.textContent.replace(/ · \d+(?:\.\d+)? с/,' · '+fmt(skill.cast_time)+' времени');
   const info=document.createElement('button');info.type='button';info.className='uq-info';info.dataset.uqInfo=sid;info.setAttribute('aria-label','Прогноз: '+skill.name);info.textContent='ⓘ';wrapper.append(info);
   button.addEventListener('pointerenter',()=>forecast(skill));button.addEventListener('focus',()=>forecast(skill));
   if(busy||!state.idle.includes(actor))button.disabled=true;
  }
 }
 for(const key of [...state.heroes,...state.enemies]){
  const name=solo?app().querySelector('.hud.'+(key===actor?'player':'enemy')+' .name'):document.getElementById('raid-fighter-'+map(key))?.querySelector('.raid-hud strong');
  name?.querySelectorAll('.raid-order-dot').forEach(dot=>dot.remove());
  if(name&&!name.querySelector('.uq-dot')){const dot=document.createElement('i');dot.className='uq-dot';dot.style.background=colors[key];name.prepend(dot);}
 }
 // The native raid renderer supplies portrait placement and colored intent
 // lines, but its legacy timeline must not attach itself to a v3 mini-game.
 window.RaidTimeline?.mountSolo(null,null);
 if(solo){const log=document.createElement('details');log.className='card uq-battle-log';log.innerHTML='<summary>Ход боя</summary>'+state.log.slice(-10).map(e=>'<p class="muted"><b>'+fmt(e.at)+'</b> '+esc(e.text)+'</p>').join('');app().querySelector('.battle').append(log);}
}
async function receive(next){
 const fresh=next.log.slice(lastLog); // review logs are bounded to 40 entries
 for(const entry of fresh){if(!entry.event)continue;
  const solo=state.heroes.length===1&&state.enemies.length===1;
  if(solo){const a=entry.actor===actor?'a':'b',b=a==='a'?'b':'a',event=entry.event;
   await ui.animateEvent({...event,seq:lastLog+1,side:a,after:{[a]:event.after.a,[b]:event.after.b},status_after:{[a]:event.status_after.a,[b]:event.status_after.b}});
  }else await ui.raidAnimate({...entry.event,actor:map(entry.actor),target:map(entry.target),skill:entry.event.skill_id});
 }
 lastLog=next.log.length;state=next;render();
}
async function stages(){while(state.stage){
 ui.close();
 const stage=state.stage;
 // A local tester takes control of whichever hero is currently defending.
 const defender=state.heroes.find(k=>state.fighters[k].arena.controller_id===stage.actor);if(defender)actor=defender;
 render();const proof=await window.ArenaMiniGames.play(stage,{scope:'queue-review',token:state.token,
  casinoRoll:(challenge_id,choice)=>api('/queue-review/session/'+state.token+'/casino',{challenge_id,choice})});
 await receive(await api('/queue-review/session/'+state.token,{action:'qte',challenge_id:stage.id,proof,revision:state.revision}));
}}
function settings(){
 let dialog=document.getElementById('uq-settings');if(dialog){dialog.showModal();return;}
 dialog=document.createElement('dialog');dialog.id='uq-settings';dialog.className='stats-dialog';
 const params=new URLSearchParams(location.search),cls=params.get('fighter')||'assassin',arch=params.get('arch')??(cls==='assassin'?'assassin_shadow':'');
 dialog.innerHTML='<header class="stats-header"><b>Настройки демо</b><button class="small" data-uq-close>Закрыть ✕</button></header><p class="muted">Настоящие характеристики и навыки класса · новая очередь только здесь.</p><div class="form"><label>Класс<select id="uq-class">'+catalog.classes.map(c=>'<option value="'+esc(c.id)+'">'+esc(c.name)+'</option>').join('')+'</select></label><label>Ветка<select id="uq-arch"></select></label><label>Бой<select id="uq-scenario"><option value="solo">Один на один · маг</option><option value="mixed">Бомж + маг</option><option value="sync">Бомж + маг · первый залп вместе</option><option value="party">Два героя против двух врагов</option></select></label><label>Защита<select id="uq-defense"><option value="dodge">Уклонение</option><option value="block">Блок</option></select></label><button class="primary" data-uq-new>Начать новый бой</button></div>';
 document.body.append(dialog);document.getElementById('uq-class').value=cls;
 const branches=()=>{const c=catalog.classes.find(c=>c.id===document.getElementById('uq-class').value);document.getElementById('uq-arch').innerHTML='<option value="">Начальный класс</option>'+c.branches.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+'</option>').join('');};
 document.getElementById('uq-class').onchange=branches;branches();if([...document.getElementById('uq-arch').options].some(o=>o.value===arch))document.getElementById('uq-arch').value=arch;
 dialog.showModal();
}
async function newBattle(options){
 if(busy)return;busy=true;
 try{ui.close();state=await api('/queue-review/session',{native:true,...options});actor='h1';target='e1';previous={};lastLog=0;}
 catch(error){notice(error.message);}
 finally{busy=false;if(state)render();}
}
export async function start(native){
 ui=native;window.ArenaQTEWatch=undefined;
 const link=document.createElement('link');link.rel='stylesheet';link.href='/queue-review/ui/arena.css';document.head.append(link);
 // Capture only review actions. Native status, stats and sound controls remain
 // untouched, and no event may send a review token to the live battle API.
 document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled||!app().contains(button)&&!button.closest('#uq-settings'))return;
  if(button.hasAttribute('data-uq-settings')){event.preventDefault();event.stopImmediatePropagation();if(!busy)settings();return;}
  if(button.hasAttribute('data-uq-close')){document.getElementById('uq-settings').close();return;}
  if(button.hasAttribute('data-uq-new')){document.getElementById('uq-settings').close();await newBattle({class_id:document.getElementById('uq-class').value,arch:document.getElementById('uq-arch').value,scenario:document.getElementById('uq-scenario').value,defense:document.getElementById('uq-defense').value});return;}
  if(button.dataset.uqHero){actor=button.dataset.uqHero;render();return;}
  if(button.dataset.uqInfo){forecast(state.fighters[actor].arena.skill_details.find(s=>s.skill_id===button.dataset.uqInfo));return;}
  if(button.dataset.raid?.startsWith('target:')){target=button.dataset.raid.slice(7);ui.target(target);return;}
  const sid=button.dataset.skill||(button.dataset.raid?.startsWith('skill:')?button.dataset.raid.slice(6):null);
  if(!sid)return;event.preventDefault();event.stopImmediatePropagation();if(busy||!state.idle.includes(actor))return;
  busy=true;app().querySelectorAll('[data-skill],[data-raid^="skill:"]').forEach(b=>b.disabled=true);
  try{await receive(await api('/queue-review/session/'+state.token,{action:'skill',actor,target,skill:sid,revision:state.revision}));await stages();}
  catch(error){notice(error.message);}
  finally{busy=false;render();}
 },true);
 catalog=await api('/queue-review/catalog');const p=new URLSearchParams(location.search);
 const cls=p.get('fighter')||'assassin';
 await newBattle({class_id:cls,arch:p.get('arch')??(cls==='assassin'?'assassin_shadow':''),scenario:p.get('scenario')||'solo',defense:p.get('defense')||'dodge'});
}
