/* Saved ten-floor dungeon. No localStorage progress or client-side rewards. */
window.NazarickDungeonApp=(()=>{
 let opts,view,run,busy=false,poller;
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const button=(label,action,disabled=false,style='')=>'<button class="'+style+'" data-nzd="'+esc(action)+'" '+(disabled?'disabled':'')+'>'+label+'</button>';
 async function api(path,body){const r=await fetch('/api/nazarick'+path,{method:body?'POST':'GET',headers:{'X-Telegram-Init-Data':opts.initData||'','Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});let d;try{d=await r.json();}catch{throw Error('Сервер не ответил. Обнови страницу.');}if(!r.ok)throw Error(d.error||'Не удалось открыть подземелье');return d;}
 function selectedRoom(){return run?.room||view.floors.flatMap(f=>f.rooms).find(r=>r.index===view.progress.checkpoint)||view.floors[0].rooms[0];}
 function rewards(){const r=run?.rewards||view.rewards;return '<details class="nzd-rewards"><summary>Трофеи за завершение</summary><p>Гарантированный билет смены класса, один трактат и один предмет на выбор. Благословение уменьшает только франки и XP.</p><div class="nzd-prizes"><label>Трактат<select id="nzd-treatise">'+r.treatises.map(t=>'<option value="'+t.id+'">'+esc(t.name)+'</option>').join('')+'</select></label><label>Снаряжение<select id="nzd-gear">'+r.equipment.map(t=>'<option value="'+t.key+'">'+esc(t.name)+'</option>').join('')+'</select></label></div><div id="nzd-prize-description"></div>'+(run?.can_claim?button('Получить выбранные трофеи','claim',busy,'primary'):'')+'</details>';}
 function render(){
  if(!view)return;const room=selectedRoom(),floor=view.floors.find(f=>f.number===room.floor),me=view.actor,leader=run?.leader===me;
  const current=run?.checkpoint??view.progress.checkpoint,complete=run?.status==='completed';
  const floors=view.floors.map(f=>{const first=f.rooms[0].index,last=f.rooms.at(-1).index,done=complete||current>last,active=!complete&&current>=first&&current<=last;
   return '<div class="nzd-floor '+(active?'active':done?'cleared':'')+'"><span>'+String(f.number).padStart(2,'0')+'</span><div><b>'+esc(f.name)+'</b><small>'+esc(f.rooms.map(r=>r.name).join(' · '))+'</small></div><i>'+(done?'✓':active?'◆':'·')+'</i></div>';}).join('');
  let actions='';
  if(!run)actions=button('Собрать отряд · с сохранения','create',busy,'primary');
  else if(!run.is_member&&['lobby','ready'].includes(run.status))actions=button('Вступить в отряд','join',busy,'primary');
  else if(run.status==='battle')actions=button('Вернуться в бой','battle',busy,'primary');
  else if(['lobby','ready','failed'].includes(run.status)&&run.is_member){
   if(leader)actions=button(run.status==='failed'?'Повторить комнату':run.status==='lobby'?'Начать поход':'Продолжить спуск','start',busy,'primary');
   else actions='<p class="muted">Лидер выбирает момент продолжения. Сохранение не исчезает со временем.</p>';
   if(room.floor===9&&run.treasury==='available'&&leader)actions+=button('Ответвление · Сокровищница','treasury',busy);
   if(run.blessing_available)actions+='<div class="nzd-blessing"><b>Сюжетная броня</b><p>Входящий урон −50% до конца похода. Франки и XP −50%; билет и трофеи остаются. Нужно согласие всех.</p>'+button('Принять благословение · '+run.blessing_votes.length+'/'+run.members.length,'blessing',busy||run.blessing_votes.includes(me))+'</div>';
  }else if(complete)actions='<h2>Тронный зал покорён</h2><p>'+(run.claim?'Трофеи уже получены. Следующий поход начнётся с первого этажа.':'Выбери личную награду ниже — у каждого участника свой выбор.')+'</p>';
  opts.app.innerHTML='<section class="nzd"><header class="nzd-head"><div><p class="nzd-kicker">ВЕЛИКАЯ ГРОБНИЦА · СОХРАНЯЕМОЕ ПОДЗЕМЕЛЬЕ</p><h1>Назарик</h1></div>'+button('Арена ↗','arena',false,'small')+'</header><div class="nzd-layout"><aside class="nzd-floors">'+floors+'</aside><div class="nzd-main"><section class="nzd-scene" style="--nzd-bg:url(\''+floor.background+'\')"><div><span class="nzd-kicker">ЭТАЖ '+String(room.floor).padStart(2,'0')+' / 10'+(run?.blessed?' · СЮЖЕТНАЯ БРОНЯ':'')+'</span><h2>'+esc(room.name)+'</h2><p>'+(run?.status==='battle'?'Бой продолжается':complete?'Вы дошли до короля-колдуна.':'Контрольная точка сохранена. Можно выйти и продолжить позже.')+'</p></div></section><div class="nzd-content"><div class="nzd-actions">'+actions+'</div>'+(run?'<div class="nzd-party"><h3>Отряд <small>'+run.members.length+' / 3</small></h3>'+run.members.map(m=>'<div><span class="nzd-member">'+esc(m.name)+'</span><small>'+(m.actor===run.leader?'Лидер':'Участник')+'</small></div>').join('')+(run.is_member&&run.status!=='battle'&&run.status!=='completed'?button('Выйти из похода · сохранить этаж','leave',busy,'small quiet'):'')+'<p class="muted">Для приглашения: /рейд назарик в чате или ссылка на этот поход.</p></div>':'<p>1–3 игрока. После каждой контрольной точки — полное восстановление отряда. Поражение не стирает пройденные этажи.</p>')+rewards()+(run?'<details><summary>Летопись похода</summary>'+run.history.map(t=>'<p>'+esc(t)+'</p>').join('')+'</details>':'')+'</div></div></div>'+
   (!run&&view.lobbies.length?'<section class="nzd-other"><h2>Отряды в этом чате</h2>'+view.lobbies.map(r=>button(esc(r.members[0]?.name)+' · этаж '+r.room.floor,'open:'+r.id,false,'small')).join('')+'</section>':'')+
   (!run&&view.history.some(r=>r.can_claim)?'<section class="nzd-other"><h2>Неполученные трофеи</h2>'+view.history.filter(r=>r.can_claim).map(r=>button('Выбрать награду','open:'+r.id)).join('')+'</section>':'')+'</section>';
  if(run?.can_claim)opts.app.querySelector('.nzd-rewards').open=true;
  updateDescriptions();
 }
 function updateDescriptions(){const box=document.getElementById('nzd-prize-description');if(!box)return;const r=run?.rewards||view.rewards,t=r.treatises.find(t=>t.id===document.getElementById('nzd-treatise').value),g=r.equipment.find(g=>g.key===document.getElementById('nzd-gear').value);box.innerHTML='<p><b>'+esc(t?.name)+'</b> · '+esc(t?.description)+'</p><p><b>'+esc(g?.name)+'</b> · '+esc(g?.description)+'</p>';}
 async function refresh(){view=await api('?chat='+opts.chat);if(run)run=await api('/runs/'+run.id);else run=view.active;render();}
 async function action(a){if(busy)return;busy=true;try{
  if(a==='arena'){clearInterval(poller);return opts.onArena(opts.chat);}
  if(a==='battle'){clearInterval(poller);return opts.onRaid(run.battle);}
  if(a==='create'){run=await api('',{chat:opts.chat});}
  else if(a.startsWith('open:'))run=await api('/runs/'+a.slice(5));
  else if(a==='claim'){await api('/runs/'+run.id,{action:'claim',treatise:document.getElementById('nzd-treatise').value,equipment:document.getElementById('nzd-gear').value});opts.toast('Трактат, билет и снаряжение получены.');}
  else if(!['arena','battle'].includes(a)){run=await api('/runs/'+run.id,{action:a,revision:run.revision});if(a==='leave'){run=null;}}
  await refresh();
 }catch(e){opts.toast(e.message);}finally{busy=false;render();}}
 async function open(o){clearInterval(poller);opts=o;run=null;view=null;opts.app.innerHTML='<div class="loading">Открываем врата Назарика…</div>';
  opts.app.onclick=e=>{const b=e.target.closest('[data-nzd]');if(b){e.preventDefault();action(b.dataset.nzd);}};
  opts.app.onchange=updateDescriptions;
  try{if(o.runId){run=await api('/runs/'+o.runId);opts.chat=run.chat;}
   if(!opts.chat){const r=await fetch('/api/guild/chats',{headers:{'X-Telegram-Init-Data':opts.initData||''}});const d=await r.json();opts.chat=d.chats?.[0]?.chat_id;if(!opts.chat)throw Error('Сначала открой арену из своего чата.');}
   await refresh();poller=setInterval(async()=>{if(!document.querySelector('.nzd')){clearInterval(poller);return;}if(busy||document.hidden)return;try{if(run){const next=await api('/runs/'+run.id);if(next.revision!==run.revision||next.status!==run.status){run=next;render();}}}catch{}},5000);
  }catch(e){opts.app.innerHTML='<div class="card"><h2>Не удалось открыть Назарик</h2><p>'+esc(e.message)+'</p></div>';}
 }
 return {open};
})();
