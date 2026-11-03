/* A visual clock only: authoritative cast times always come from the server. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.RaidTimeline=api;})(globalThis,function(root){
 'use strict';let current=null;
 const clamp=x=>Math.max(0,Math.min(1,x));
 function eventGroups(events){const groups=[];for(const e of events){const last=groups.at(-1),prior=last?.[0],barrier=e.chaplain_event||e.nazarick_event;
  if(!barrier&&Number.isFinite(e.cast_at)&&prior&&!prior.chaplain_event&&!prior.nazarick_event&&prior.round===e.round&&prior.cast_at===e.cast_at)last.push(e);else groups.push([e]);}return groups;}
 function horizon(queue){return Math.max(1,queue.horizon||0,...queue.entries.map(e=>e.at));}
 function model(queue,time=queue.time||0){const end=horizon(queue);return queue.entries.map((e,i)=>({...e,lane:i%4,position:clamp(queue.version===3?(e.at-time)/end:1-(e.at-time)/end),done:e.at<time-.01,active:Math.abs(e.at-time)<.01&&queue.phase!=='choose'}));}
 function create(queue,names,palette,from=queue.time||0){
  const solo=queue.version===3||new Set(queue.entries.map(e=>e.actor)).size<=2;
  const host=root.document.createElement('div');host.className='raid-timeline'+(solo?' raid-timeline-solo':'');host.setAttribute('aria-label','Шкала очереди действий: цветные отметки движутся к правой черте');
  if(queue.version===3){host.classList.add('raid-timeline-v3');host.dataset.now='Сейчас · '+Number(queue.absolute_time||0).toFixed(2);host.setAttribute('aria-label','Шкала завершения действий: сейчас слева, будущее справа');}
  if(!solo){const caption=root.document.createElement('div');caption.className='raid-timeline-caption';const label=root.document.createElement('span');label.textContent='ОЧЕРЕДЬ · РАУНД '+queue.round;caption.append(label);const phase=root.document.createElement('span');phase.textContent=queue.phase==='defense'?'Совместная защита · очередь ждёт':queue.phase==='resolve'?'Исполнение кастов':'Подготовка';caption.append(phase);host.append(caption);}
  const track=root.document.createElement('div');track.className='raid-timeline-track';host.append(track);const end=horizon(queue),ordered=[...queue.entries].sort((a,b)=>a.at-b.at);let previous=0;
  ordered.forEach(e=>{const segment=root.document.createElement('i');segment.className='raid-timeline-segment';segment.style.cssText=`left:${100*previous/end}%;width:${100*Math.max(.025,e.at-previous)/end}%;background:${palette[e.actor]||'#93bcd5'}`;segment.title=(names[e.actor]||e.actor)+' · '+e.at.toFixed(2)+' с'+(e.follow_up?' · ускоренное действие':'' );track.append(segment);previous=e.at;});
  const finish=root.document.createElement('span');finish.className='raid-timeline-finish';finish.setAttribute('aria-hidden','true');track.append(finish);
  const initial=model(queue,from),final=model(queue),dots=[];final.forEach((e,i)=>{const dot=root.document.createElement('span');dot.className='raid-timeline-dot'+(e.active?' active':'')+(e.done?' done':'')+(e.follow_up?' fast':'');dot.dataset.actor=e.actor;dot.style.setProperty('--actor',palette[e.actor]||'#93bcd5');dot.style.top=(7+e.lane*5)+'px';dot.style.left=(2+96*initial[i].position)+'%';dot.title=(names[e.actor]||e.actor)+' · '+e.at.toFixed(2)+' с'+(e.follow_up?' · ускоренное действие':'')+(e.active?' · действие сейчас':e.done?' · действие завершено':'');dot.setAttribute('aria-label',dot.title);track.append(dot);dots.push({dot,from:initial[i].position,to:e.position});});
  if(!solo){const clock=root.document.createElement('span');clock.className='raid-timeline-clock';clock.textContent=(queue.time||0).toFixed(2)+' с';host.append(clock);}
  return {host,animate(){for(const {dot,from:a,to:b}of dots){dot.style.left=(2+96*b)+'%';if(Math.abs(a-b)>1e-8&&dot.animate)dot.animate([{left:(2+96*a)+'%'},{left:(2+96*b)+'%'}],{duration:650,easing:'ease-in-out'});}}};
 }
 function mount(field,data){
  const queue=data.data?.action_queue;current=null;if(!field||!queue)return;
  const names=Object.fromEntries([...Object.entries(data.data.players).map(([k,p])=>[k,p.fighter.name]),...Object.entries(data.data.enemies||{boss:data.data.boss}).map(([k,f])=>[k,f.name])]);
  current={queue,names,palette:queue.colors||{}};const view=create(queue,names,current.palette,queue.animate_from??queue.time??0);field.append(view.host);view.animate();
 }
 function mountSolo(field,queue,names){
  current=null;if(!field||!queue)return;
  current={queue,names:names||{},palette:queue.colors||{}};
  const view=create(queue,current.names,current.palette,queue.animate_from??queue.time??0);
  field.append(view.host);view.animate();
 }
 function attach(section){if(!current)return ()=>{};const {queue,names,palette}=current,view=create(queue,names,palette);view.host.classList.add('raid-timeline-mini');const heading=section.querySelector('.qte-heading');heading?heading.after(view.host):section.prepend(view.host);return ()=>view.host.remove();}
 function castTime(fighter,skill){if(Number.isFinite(skill?.cast_time))return skill.cast_time;const speed=Math.max(0,Number(fighter?.effective_stats?.speed??fighter?.stats?.speed??0)),hostile=!!(skill?.damage_type||(skill?.effects||[]).some(e=>e.target==='enemy'));let base=skill?.cast_base??({arch_assassin_shadow:2.65,arch_assassin_blood:3.4}[skill?.skill_id]);if(base==null){base=!skill?1.6:!hostile?2.4:skill.power>=35||(skill.tags||[]).includes('six_strike')?4.2:3;if(skill?.tags?.includes('quick'))base*=.8;}return Math.max(.75,Math.round(base/(1+speed*.035)*20)/20);}
 function preview(field,actor,fighter,skill){if(!field||!current)return;const {queue,names,palette}=current,track=field.querySelector('.raid-timeline-track');if(!track)return;clearPreview(field);const at=castTime(fighter,skill),end=horizon(queue),dot=root.document.createElement('span');dot.className='raid-timeline-preview';dot.style.setProperty('--actor',palette[String(actor)]||'#c9a7ea');dot.style.left=(2+96*clamp(queue.version===3?at/end:1-at/end))+'%';const text=(skill?.name||'Защита')+' · '+at.toFixed(2)+' времени';dot.title=text;dot.setAttribute('aria-label',text);track.append(dot);
  if(queue.version===3){const hint=field.closest('.battle,.raid-screen')?.querySelector('.queue-forecast'),incoming=queue.entries.filter(e=>e.actor!==String(actor)&&(e.targets||[]).includes(String(actor))),f=skill?.queue_forecast;
   const remaining=f?.remaining??(incoming.length?Math.min(...incoming.map(e=>e.at))-at:null),kind=remaining===null?'none':Math.abs(remaining)<.001?'together':remaining>0?'before':'after';
   if(hint){hint.className='queue-forecast '+kind;hint.textContent=text+'. '+(remaining===null?'Нет объявленного входящего каста.':kind==='before'?'Успеешь · останется '+remaining.toFixed(2)+'.':kind==='together'?'Одновременно с атакой врага.':'Враг ударит раньше на '+(-remaining).toFixed(2)+'.');}
  }
 }
 function bind(container,field,actor,fighter,selector){if(!current||current.queue.version!==3||!container)return;let hint=container.querySelector('.queue-forecast');if(!hint){hint=root.document.createElement('p');hint.className='queue-forecast';hint.setAttribute('role','status');hint.textContent='Наведи на навык или нажми ⓘ — увидишь, успеет ли он до врага.';container.prepend(hint);}
  container.querySelectorAll(selector).forEach(button=>{const sid=button.dataset.skill||button.dataset.raid?.slice(6),skill=fighter.skill_details?.find(s=>s.skill_id===sid);if(!skill)return;
   if(!button.parentElement.classList.contains('queue-skill-wrap')){const wrapper=root.document.createElement('div');wrapper.className='queue-skill-wrap';button.before(wrapper);wrapper.append(button);const info=root.document.createElement('button');info.className='queue-info';info.type='button';info.textContent='ⓘ';info.setAttribute('aria-label','Прогноз: '+skill.name);info.onclick=e=>{e.stopPropagation();preview(field,actor,fighter,skill);};wrapper.append(info);}
   button.addEventListener('pointerenter',()=>preview(field,actor,fighter,skill));button.addEventListener('focus',()=>preview(field,actor,fighter,skill));
  });
 }
 function clearPreview(field){field?.querySelector('.raid-timeline-preview')?.remove();}
 return {model,mount,mountSolo,attach,eventGroups,preview,clearPreview,castTime,bind};
});
