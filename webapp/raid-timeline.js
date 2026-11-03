/* A visual clock only: authoritative cast times always come from the server. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.RaidTimeline=api;})(globalThis,function(root){
 'use strict';let current=null;
 const clamp=x=>Math.max(0,Math.min(1,x));
 function eventGroups(events){const groups=[];for(const e of events){const last=groups.at(-1),prior=last?.[0],barrier=e.chaplain_event||e.nazarick_event;
  if(!barrier&&Number.isFinite(e.cast_at)&&prior&&!prior.chaplain_event&&!prior.nazarick_event&&prior.round===e.round&&prior.cast_at===e.cast_at)last.push(e);else groups.push([e]);}return groups;}
 function model(queue,time=queue.time||0){const end=Math.max(1,...queue.entries.map(e=>e.at));return queue.entries.map((e,i)=>({...e,lane:i%4,position:clamp(1-(e.at-time)/end),done:e.at<time-.01,active:Math.abs(e.at-time)<.01&&queue.phase!=='choose'}));}
 function create(queue,names,palette,from=queue.time||0){
  const host=root.document.createElement('div');host.className='raid-timeline';host.setAttribute('aria-label','Шкала очереди действий: цветные отметки движутся к правой черте');
  const caption=root.document.createElement('div');caption.className='raid-timeline-caption';const label=root.document.createElement('span');label.textContent='ОЧЕРЕДЬ · РАУНД '+queue.round;caption.append(label);const phase=root.document.createElement('span');phase.textContent=queue.phase==='defense'?'Совместная защита · очередь ждёт':queue.phase==='resolve'?'Исполнение кастов':'Подготовка';caption.append(phase);host.append(caption);
  const track=root.document.createElement('div');track.className='raid-timeline-track';host.append(track);const end=Math.max(1,...queue.entries.map(e=>e.at)),ordered=[...queue.entries].sort((a,b)=>a.at-b.at);let previous=0;
  ordered.forEach(e=>{const segment=root.document.createElement('i');segment.className='raid-timeline-segment';segment.style.cssText=`left:${100*previous/end}%;width:${100*Math.max(.025,e.at-previous)/end}%;background:${palette[e.actor]||'#93bcd5'}`;segment.title=(names[e.actor]||e.actor)+' · '+e.at.toFixed(2)+' с';track.append(segment);previous=e.at;});
  const finish=root.document.createElement('span');finish.className='raid-timeline-finish';finish.setAttribute('aria-hidden','true');track.append(finish);
  const initial=model(queue,from),final=model(queue),dots=[];final.forEach((e,i)=>{const dot=root.document.createElement('span');dot.className='raid-timeline-dot'+(e.active?' active':'')+(e.done?' done':'');dot.dataset.actor=e.actor;dot.style.setProperty('--actor',palette[e.actor]||'#93bcd5');dot.style.top=(7+e.lane*5)+'px';dot.style.left=(2+96*initial[i].position)+'%';dot.title=(names[e.actor]||e.actor)+' · '+e.at.toFixed(2)+' с'+(e.active?' · действие сейчас':e.done?' · действие завершено':'');dot.setAttribute('aria-label',dot.title);track.append(dot);dots.push({dot,from:initial[i].position,to:e.position});});
  const clock=root.document.createElement('span');clock.className='raid-timeline-clock';clock.textContent=(queue.time||0).toFixed(2)+' с';host.append(clock);
  return {host,animate(){for(const {dot,from:a,to:b}of dots){dot.style.left=(2+96*b)+'%';if(Math.abs(a-b)>1e-8&&dot.animate)dot.animate([{left:(2+96*a)+'%'},{left:(2+96*b)+'%'}],{duration:650,easing:'ease-in-out'});}}};
 }
 function mount(field,data){
  const queue=data.data?.action_queue;current=null;if(!field||!queue)return;
  const names=Object.fromEntries([...Object.entries(data.data.players).map(([k,p])=>[k,p.fighter.name]),...Object.entries(data.data.enemies||{boss:data.data.boss}).map(([k,f])=>[k,f.name])]);
  current={queue,names,palette:queue.colors||{}};const view=create(queue,names,current.palette,queue.animate_from??queue.time??0);field.append(view.host);view.animate();
 }
 function attach(section){if(!current)return ()=>{};const {queue,names,palette}=current,view=create(queue,names,palette);view.host.classList.add('raid-timeline-mini');const heading=section.querySelector('.qte-heading');heading?heading.after(view.host):section.prepend(view.host);return ()=>view.host.remove();}
 return {model,mount,attach,eventGroups};
});
