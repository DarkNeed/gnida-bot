'use strict';
const $=id=>document.getElementById(id),colors={h1:'#79c8df',h2:'#a8d5ad',e1:'#b39ce5',e2:'#dc9279'};
let catalog=null,state=null,actor='h1',target='e1',busy=false,scale=5,previousPositions={};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n).toFixed(2).replace('.',',');
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка сервера');return d;}
function branches(){const c=catalog.classes.find(c=>c.id===$('class').value);$('arch').innerHTML='<option value="">Начальный класс</option>'+c.branches.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+'</option>').join('');}
function position(key){const hero=state.heroes.includes(key),i=(hero?state.heroes:state.enemies).indexOf(key),mobile=innerWidth<=700;return hero?{x:state.heroes.length===1?25:20+i*29,y:165+i*9}:{x:state.enemies.length===1?74:(mobile?60:62)+i*(mobile?23:24),y:55+i*25};}
function render(){
 $('battle').hidden=false;
 if(!state.idle.includes(actor))actor=state.idle[0]||state.heroes[0];
 if(state.fighters[target]?.hp<=0)target=state.enemies.find(k=>state.fighters[k].hp>0)||'e1';
 $('clock').textContent='ВРЕМЯ '+fmt(state.time);scale=Math.max(5,...state.pending.map(e=>e.end-state.time),...(state.fighters[actor]?.skills||[]).map(s=>s.duration));
 $('horizon').textContent='+'+fmt(scale)+' боевого времени';
 $('fighters').innerHTML=Object.entries(state.fighters).map(([k,f])=>{const p=position(k),event=state.pending.find(e=>e.actor===k),skill=catalog.skills.find(s=>s.id===event?.skill);return '<div class="unit '+(state.heroes.includes(k)?'hero':'enemy')+(f.hp<=0?' dead':'')+'" style="left:'+p.x+'%;top:'+p.y+'px;--unit:'+colors[k]+'"><h3><i class="dot"></i>'+esc(f.name)+'</h3><p>HP '+f.hp+'/'+f.max_hp+' · энергия '+f.resource+'</p><div class="casting">'+(event?esc(skill?.name||event.skill)+'<br>через '+fmt(event.end-state.time):f.hp<=0?'Повержен':'Выбирает действие')+'</div><img src="'+esc(f.sprite)+'" alt="'+esc(f.name)+'"><div class="effects">'+f.effects.map(e=>(e.kind==='bleed'?'🩸':e.kind==='burn'?'🔥':'◆')+' '+esc(e.kind)+' '+esc(e.value)).join(' · ')+'</div>'+(!state.heroes.includes(k)&&f.hp>0?'<button class="target '+(target===k?'selected':'')+'" data-target="'+k+'">'+(target===k?'Цель выбрана':'Выбрать цель')+'</button>':'')+'</div>';}).join('');
 $('intents').innerHTML=state.pending.filter(e=>state.enemies.includes(e.actor)&&state.fighters[e.target]?.hp>0).map(e=>{const a=position(e.actor),b=position(e.target);return '<line x1="'+a.x*10+'" y1="'+(a.y+75)+'" x2="'+b.x*10+'" y2="'+(b.y+75)+'" stroke="'+colors[e.actor]+'" opacity=".4" stroke-dasharray="5 8" stroke-width="2"/>';}).join('');
 const marks=[...state.pending,...state.group],positions={};
 $('track').innerHTML='';$('markers').innerHTML=marks.map((e,i)=>{
  const percent=Math.max(0,Math.min(100,(e.end-state.time)/scale*100)),id=e.actor+':'+e.end;
  const siblings=marks.slice(0,i).filter(other=>other.end===e.end).length;
  positions[id]=percent;
  return '<div class="marker" data-mark="'+esc(id)+'" style="left:calc('+percent+'% + '+siblings*9+'px);--unit:'+colors[e.actor]+'" title="'+esc(state.fighters[e.actor].name)+' · '+fmt(e.end-state.time)+'">'+(!siblings?'<span>'+fmt(e.end-state.time)+'</span>':'')+'</div>';
 }).join('');
 if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)for(const dot of $('markers').children){const key=dot.dataset.mark;if(previousPositions[key]!=null&&Math.abs(previousPositions[key]-positions[key])>.01)dot.animate([{left:previousPositions[key]+'%'},{left:dot.style.left}],{duration:500,easing:'ease-in-out'});}
 previousPositions=positions;
 const incoming=state.pending.filter(e=>state.enemies.includes(e.actor)&&e.target===actor);
 $('enemy-time').textContent=incoming.length?'До удара по герою: '+fmt(Math.min(...incoming.map(e=>e.end))-state.time):'Нет входящего каста по герою';
 $('actor-tabs').innerHTML=state.heroes.map(k=>'<button data-actor="'+k+'" '+(!state.idle.includes(k)?'disabled':'')+' class="'+(actor===k?'primary':'')+'">'+esc(state.fighters[k].name)+(state.idle.includes(k)?' · выбирает':' · готовит каст')+'</button>').join('');
 $('turn').textContent=state.finished?'Бой завершён':state.stage?'Проверка завершившегося каста':state.fighters[actor].name+' · выбери навык';
 $('actions').innerHTML=state.finished?'<p>Начни новый бой для повторной проверки.</p>':(state.fighters[actor].skills||[]).map((s,i)=>'<div class="action-wrap"><button class="skill" data-skill="'+esc(s.id)+'" '+(busy||s.reason?'disabled':'')+'><b>'+esc(s.name)+'</b><span class="cast">'+fmt(s.duration)+' времени</span><span>'+s.cost+' энергии'+(s.reason?' · '+esc(s.reason):'')+'</span></button><button class="info" data-info="'+i+'" aria-label="Прогноз '+esc(s.name)+'">ⓘ</button></div>').join('');
 $('log').innerHTML=state.log.map(e=>'<li><b>'+fmt(e.at)+'</b> '+esc(e.text)+'</li>').join('');$('log').scrollTop=$('log').scrollHeight;
 resetForecast();
}
function resetForecast(){$('forecast').className='';$('forecast').textContent='Наведи на навык или нажми ⓘ — увидишь, успеет ли он до атаки врага.';$('track').innerHTML='';}
function preview(s){
 if(!s)return;const f=s.forecast;
 $('forecast').className=f.outcome;
 const message={before:'Успеешь раньше врага · останется '+fmt(f.remaining),after:'Враг ударит раньше завершения каста на '+fmt(-f.remaining),together:'Завершится одновременно с атакой врага',none:'По этому герою сейчас нет входящей атаки'}[f.outcome];
 $('forecast').textContent=s.name+' · '+fmt(s.duration)+' времени. '+message+'.';
 $('track').innerHTML='<div class="ghost" style="width:'+Math.min(100,s.duration/scale*100)+'%;background:'+({before:'#9be4b866',after:'#ff929966',together:'#f7ca7566'}[f.outcome]||'#d2c2fc99')+'"></div>';
}
async function stages(){
 while(state.stage){render();const stage=state.stage;$('notice').textContent='Боевые часы на паузе · '+stage.name;
  const proof=await window.ArenaMiniGames.play(stage,{scope:'queue-review',token:state.token,
   casinoRoll:(challenge_id,choice)=>api('/queue-review/session/'+state.token+'/casino',{challenge_id,choice})});
  state=await api('/queue-review/session/'+state.token,{action:'qte',proof,challenge_id:stage.id,revision:state.revision});
 }
}
async function start(){if(busy)return;busy=true;$('reset').disabled=true;try{state=await api('/queue-review/session',{class_id:$('class').value,arch:$('arch').value,scenario:$('scenario').value,defense:$('defense').value});actor='h1';target='e1';$('notice').textContent='Демо не меняет обычные бои. Нажатие на навык сразу начинает его подготовку.';render();}catch(e){$('notice').textContent=e.message;}finally{busy=false;$('reset').disabled=false;if(state)render();}}
document.addEventListener('pointerover',e=>{const button=e.target.closest('[data-skill]');if(button)preview(state.fighters[actor].skills.find(s=>s.id===button.dataset.skill));});
document.addEventListener('focusin',e=>{const button=e.target.closest('[data-skill]');if(button)preview(state.fighters[actor].skills.find(s=>s.id===button.dataset.skill));});
document.addEventListener('click',async e=>{
 const button=e.target.closest('button');if(!button||button.disabled||busy)return;
 if(button.dataset.target){target=button.dataset.target;render();return;}
 if(button.dataset.actor){actor=button.dataset.actor;render();return;}
 if(button.hasAttribute('data-info')){preview(state.fighters[actor].skills[Number(button.dataset.info)]);return;}
 if(!button.dataset.skill)return;
 busy=true;$('reset').disabled=true;
 try{state=await api('/queue-review/session/'+state.token,{action:'skill',actor,skill:button.dataset.skill,target,revision:state.revision});render();await stages();$('notice').textContent=state.finished?'Бой завершён. Награды в демо отключены.':'Выбери следующее действие — повтор не запускается автоматически.';}
 catch(error){$('notice').textContent=error.message;}
 finally{busy=false;$('reset').disabled=false;render();}
});
function atlas(){const q=$('search').value.toLowerCase();const rows=catalog.skills.filter(s=>(s.name+' '+s.class_id+' '+s.id).toLowerCase().includes(q));$('catalog-list').innerHTML='<p class="muted">Всего '+catalog.skills.length+' · найдено '+rows.length+'</p>'+rows.map(s=>'<div class="catalog-row"><div>'+esc(s.name)+'<br><small>'+esc(s.class_id)+' · '+esc(s.id)+'</small></div><b>'+fmt(s.base)+'</b></div>').join('');}
$('class').onchange=branches;$('reset').onclick=start;$('search').oninput=atlas;
(async()=>{try{catalog=await api('/queue-review/catalog');$('class').innerHTML=catalog.classes.map(c=>'<option value="'+esc(c.id)+'">'+esc(c.name)+'</option>').join('');$('class').value='assassin';branches();$('arch').value='assassin_shadow';atlas();await start();}catch(error){$('notice').textContent=error.message;}})();
