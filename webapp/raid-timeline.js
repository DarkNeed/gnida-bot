/* Per-combatant cast bars. Only server snapshots advance combat time. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.RaidTimeline=api;})(globalThis,function(root){
 'use strict';
 const EPS=.0005;
 const prompt='Наведи на навык или нажми ⓘ, чтобы увидеть, кто сработает раньше.';
 const views=new WeakMap();
 const clamp=x=>Math.max(0,Math.min(1,x));
 const seconds=x=>Number(x).toLocaleString('ru-RU',{maximumFractionDigits:2,minimumFractionDigits:0})+' с';
 function eventGroups(events){
  const groups=[];
  for(const e of events){
   const last=groups.at(-1),prior=last?.[0],barrier=e.chaplain_event||e.nazarick_event;
   if(!barrier&&Number.isFinite(e.cast_at)&&prior&&!prior.chaplain_event&&!prior.nazarick_event&&prior.round===e.round&&prior.cast_at===e.cast_at)last.push(e);
   else groups.push([e]);
  }
  return groups;
 }
 function progress(entry,time){
  const start=Number.isFinite(entry.started)?entry.started:0;
  const duration=entry.duration>0?entry.duration:entry.at-start;
  return duration>0?clamp((time-start)/duration):Number(time>=entry.at);
 }
 function model(queue,actor){
  const now=queue.time||0,entries=queue.entries.filter(e=>e.actor===String(actor));
  const release=entries.find(e=>e.resolving);
  const next=release||entries.filter(e=>e.at>=now-EPS).sort((a,b)=>a.at-b.at)[0];
  if(!next)return null;
  const remaining=Math.max(0,next.at-now),resolving=!!release||remaining<=EPS&&queue.phase!=='choose';
  return {...next,remaining,resolving,progress:resolving?1:progress(next,now)};
 }
 function predict(entry,time,duration){
  const remaining=entry.at-time,total=entry.duration>0?entry.duration:entry.at-(entry.started??0);
  const outcome=Math.abs(remaining-duration)<=EPS?'together':remaining<duration?'after':'before';
  // Use the same relative clock as the bar; its right edge is this enemy's release.
  const end=total>0?clamp(1-(remaining-duration)/total):1;
  return {outcome,end};
 }
 function node(tag,cls,text){
  const el=root.document.createElement(tag);el.className=cls;
  if(text!==undefined)el.textContent=text;
  return el;
 }
 function castKey(queue,entry){
  if(!entry)return null;
  return Number.isFinite(queue.absolute_time)&&Number.isFinite(entry.started)
   ?(queue.absolute_time+entry.started).toFixed(3)+':'+(queue.absolute_time+entry.at).toFixed(3)
   :queue.round+':'+entry.at+':'+(entry.skill||'');
 }
 function animateFill(fill,from,to){
  fill.style.transform='scaleX('+to+')';
  if(to>from+EPS&&fill.animate&&!root.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)
   fill.animate([{transform:'scaleX('+from+')'},{transform:'scaleX('+to+')'}],{duration:380,easing:'ease-out'});
 }
 function snapshot(field){
  return new Map(Array.from(views.get(field)?.bars||[],([actor,bar])=>[actor,
   {cast:bar.cast,value:bar.value,resolving:bar.resolving}]));
 }
 function render(field,queue,combatants,{casts,hold=false}={}){
  if(!field||!queue){if(field)views.delete(field);return;}
  const bars=new Map();
  views.set(field,{queue,bars});
  for(const {key,f,container,intent,ally=false} of combatants){
   if(!f||f.hp<=0||!container)continue;
   const entry=model(queue,key);
   // The normal ally status already shows "Выбирает навык".
   if(ally&&!entry)continue;
   const cast=castKey(queue,entry),past=casts?.get(String(key));
   const same=cast!==null&&past?.cast===cast;
   const declared=ally?null:f.skill_details?.find(s=>s.skill_id===entry?.skill);
   const title=ally?'Действие союзника':declared?.name||(entry&&intent?.skill===entry.skill?intent?.text?.split(':',1)[0]:null)||(entry?'Действие':'Ожидает');
   const resolving=hold&&same?past.resolving:!!entry?.resolving;
   const timing=resolving?'Сейчас':entry?seconds(entry.remaining):'—';
   const host=node('div',(ally?'ally-cast':'enemy-cast')+(resolving?' is-resolving':'')+(entry?'':' is-idle'));
   host.dataset.actor=key;
   const timer=node('b','enemy-cast-time',timing);
   const track=node('div','enemy-cast-track'),fill=node('i','enemy-cast-fill');
   const value=hold&&same?past.value:entry?.progress??0;
   track.setAttribute('role','progressbar');
   track.setAttribute('aria-label',(f.name||'Противник')+': '+title);
   track.setAttribute('aria-valuenow',String(Math.round(value*100)));
   track.setAttribute('aria-valuetext',entry?(resolving?'Действие выполняется':timing+' до действия'):'Действие не объявлено');
   track.append(fill);
   if(ally){
    host.append(track,timer);container.replaceChildren(host);
   }else{
    const label=node('div','enemy-cast-label'),skill=node('span','enemy-cast-name',title);
    skill.title=declared?.description?title+' · '+declared.description:title;
    label.append(skill,timer);host.append(label,track);container.append(host);
   }
   bars.set(String(key),{host,track,fill,timer,entry,cast,value,resolving,ally,name:f.name||'Противник'});
   animateFill(fill,!hold&&same?past.value:value,value);
  }
 }
 function mount(field,data,options){
  const d=data?.data;
  if(!field||!d?.action_queue)return;
  const article=key=>root.document.getElementById('raid-fighter-'+key);
  const combatants=Object.entries(d.enemies||(d.boss?{boss:d.boss}:{}))
    .map(([key,f])=>({key,f,container:article(key),intent:d.enemy_intents?.[key]||d.intent}));
  const active=Object.entries(d.players||{}).filter(([,p])=>!p.withdrawn&&p.fighter?.hp>0
    && (p.deported_round==null||p.deported_round!==d.round));
  if(d.action_queue.version===3&&active.length>1){
   for(const [key,p] of active){
    if(key===String(data.actor_id))continue;
    combatants.push({key,f:p.fighter,container:article(key)?.querySelector('.raid-ready'),ally:true});
   }
  }
  render(field,d.action_queue,combatants,options);
 }
 function mountSolo(field,queue,sides,enemy,options){render(field,queue,[{key:enemy,f:sides?.[enemy],container:field}],options);}
 function castTime(fighter,skill){
  if(Number.isFinite(skill?.cast_time))return skill.cast_time;
  const speed=Math.max(0,Number(fighter?.effective_stats?.speed??fighter?.stats?.speed??0)),hostile=!!(skill?.damage_type||(skill?.effects||[]).some(e=>e.target==='enemy'));
  let base=skill?.cast_base??({arch_assassin_shadow:2.65,arch_assassin_blood:3.4}[skill?.skill_id]);
  if(base==null){base=!skill?1.6:!hostile?2.4:skill.power>=35||(skill.tags||[]).includes('six_strike')?4.2:3;if(skill?.tags?.includes('quick'))base*=.8;}
  return Math.max(.75,Math.round(base/(1+speed*.035)*20)/20);
 }
 function clearPreview(field){
  const view=views.get(field);
  if(!view)return;
  for(const {host,track} of view.bars.values()){
   delete host.dataset.forecast;track.querySelector('.enemy-cast-preview')?.remove();
  }
  if(view.hint){view.hint.className='queue-forecast';view.hint.textContent=prompt;}
 }
 function preview(field,skill,fighter){
  const view=views.get(field);
  if(!skill||!view)return;
  clearPreview(field);
  const at=castTime(fighter,skill),now=view.queue.time||0,earlier=[],tied=[],later=[];
  for(const {host,track,entry,name,ally} of view.bars.values()){
   if(ally||!entry||entry.resolving)continue;
   const {outcome,end}=predict(entry,now,at);
   const mark=node('i','enemy-cast-preview');
   mark.style.left=(100*entry.progress)+'%';mark.style.right=(100*(1-end))+'%';
   mark.setAttribute('aria-hidden','true');
   host.dataset.forecast=outcome;track.append(mark);
   (outcome==='after'?earlier:outcome==='together'?tied:later).push({name,remaining:entry.remaining-at});
  }
  const hint=view.hint;
  if(!hint)return;
  const names=list=>list.map(item=>item.name).join(', ');
  const imminent=[
   earlier.length?'Раньше тебя: '+names(earlier):null,
   tied.length?'Одновременно с тобой: '+names(tied):null
  ].filter(Boolean).join('. ');
  const summary=imminent?imminent+'.':later.length
   ?'Ты успеешь первым. До ближайшего действия врага останется '+seconds(Math.min(...later.map(e=>e.remaining)))+'.'
   :'Нет объявленного действия противника.';
  hint.className='queue-forecast '+(earlier.length?'after':tied.length?'together':later.length?'before':'');
  hint.textContent=skill.name+' · '+seconds(at)+'. '+summary;
 }
 function finish(field,actor,skill,castAt){
  const view=views.get(field),bar=view?.bars.get(String(actor));
  if(!bar?.entry||bar.resolving||skill&&bar.entry.skill&&skill!==bar.entry.skill)return;
  if(Number.isFinite(castAt)&&Number.isFinite(view.queue.absolute_time)&&castAt+EPS<view.queue.absolute_time+bar.entry.at)return;
  clearPreview(field);
  bar.host.classList.add('is-resolving');
  bar.timer.textContent='Сейчас';
  bar.track.setAttribute('aria-valuenow','100');bar.track.setAttribute('aria-valuetext','Действие выполняется');
  animateFill(bar.fill,bar.value,1);
  bar.value=1;bar.resolving=true;
 }
 function bind(container,field,fighter,selector){
  const view=views.get(field);
  if(!container||!view)return;
  const entries=[...container.querySelectorAll(selector)].map(button=>{
   const sid=button.dataset.skill||button.dataset.raid?.slice(6);
   return [button,fighter.skill_details?.find(s=>s.skill_id===sid)];
  }).filter(([,skill])=>skill);
  if(!entries.length)return;
  let hint=container.querySelector('.queue-forecast');
  if(!hint){hint=node('p','queue-forecast',prompt);hint.setAttribute('role','status');container.prepend(hint);}
  view.hint=hint;
  for(const [button,skill] of entries){
   if(button.parentElement.classList.contains('queue-skill-wrap'))continue;
   const wrapper=node('div','queue-skill-wrap'),info=node('button','queue-info','ⓘ');
   info.type='button';info.setAttribute('aria-label','Прогноз: '+skill.name);
   info.onclick=e=>{e.stopPropagation();preview(field,skill,fighter);};
   button.before(wrapper);wrapper.append(button,info);
   button.addEventListener('pointerenter',e=>{if(e.pointerType!=='touch')preview(field,skill,fighter);});
   button.addEventListener('focus',()=>preview(field,skill,fighter));
   wrapper.addEventListener('pointerleave',e=>{if(e.pointerType!=='touch')clearPreview(field);});
   wrapper.addEventListener('focusout',e=>{if(!wrapper.contains(e.relatedTarget))clearPreview(field);});
  }
 }
 return {model,predict,mount,mountSolo,eventGroups,castTime,bind,finish,snapshot};
});
