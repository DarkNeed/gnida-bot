/* Lab orchestration only. Original pattern engines are imported, not copied. */
(function(root,factory){const api=typeof module==='object'&&module.exports?factory(require('../../webapp/qte-unique/engine'),require('../../webapp/qte-block/engine'),require('../../webapp/nazarick-qte.js')):factory(root.QTEUnique,root.QTEBlock,root.NazarickQTE);if(typeof module==='object'&&module.exports)module.exports=api;else root.QueueExisting=api;})(globalThis,function(E,B,NZ){
'use strict';
const STEP=1/120,SHIELD=['stamina','angle','active','requested','raisedAt','lastRaise','loweredAt','perfectUntil','brokenUntil'];
const cache=new Map();
function stats(cfg){return {accuracy:85,enemyEvasion:0,evasion:cfg.evasion,enemyAccuracy:cfg.accuracy,physicalDefense:cfg.armor,magicDefense:cfg.armor,enemyAttack:0};}
function createState(skill,cfg,seed){const power=cfg.damageBase??40;return cfg.mode==='block'?B.create(skill,stats(cfg),seed,{hp:5000,power,endOnDeath:false}):E.defense(E.profile(skill),stats(cfg),seed,{hp:1000000,damageBase:power,endOnDeath:false});}
function compatibility(skill,cfg,seed=17){
 const key=JSON.stringify([skill,cfg.mode,cfg.evasion,cfg.accuracy,seed]);if(cache.has(key))return cache.get(key);
 const s=createState(skill,cfg,seed),p=s.p;let reason='';
 if(NZ?.identity(p)||p.chaplain||p.kit||(skill.base_id||'').startsWith('chaplain_'))reason='Особые правила босса — отдельное окно';
 else if(p.kind.startsWith('casino_'))reason='Самостоятельная сцена казино';
 else if(cfg.mode!=='block'){
  // Inspect actual generated primitives. No catalogue of rewritten skill patterns.
  while(!s.ended&&!reason){E.defenseStep(s,1/60,{});for(const h of s.hazards){
   if(['safe_zone','well','ring'].includes(h.type))reason='Атака задаёт собственную безопасную область';
   if(h.type==='rect'&&(h.w>=E.W*.7||h.h>=E.H*.7))reason='Перестройка всего поля';
  }}
 }
 const value={exclusive:!!reason,reason:reason||'Совместима с другим рисунком'};cache.set(key,value);return value;
}
function init(){return {jobs:[],carrier:null,serial:0,mode:null};}
function intersects(a,b){return a.start<b.end-1e-7&&b.start<a.end-1e-7;}
function blockConflict(candidate,prior){
 for(const e of candidate.state.events)for(const job of prior)for(const o of job.state.events){
  const dt=Math.abs(candidate.start+e.at-job.start-o.at),turn=Math.abs(B.angleDiff(e.angle,o.angle));
  if(dt<.24&&(e.kind==='feint'||o.kind==='feint'||e.kind==='wave'||o.kind==='wave'))return true;
  if(e.kind!=='wave'&&o.kind!=='wave'&&dt<turn/(Math.PI*4)+.12)return true;
 }return false;
}
function enqueue(world,actor,skill,cfg,now){
 const seed=(Number(cfg.seed)||17)+world.serial++*997,state=createState(skill,cfg,seed),policy=compatibility(skill,cfg,seed);
 const job={id:actor.id+':'+world.serial,source:actor.id,name:actor.name,color:actor.color,skill,state,policy,requested:now,start:now,end:now+state.duration,seen:0,seenHazards:new Set(),finished:false,announced:false};
 let iterations=0;
 while(!cfg.strictOverlap&&iterations++<200){const overlapping=world.jobs.filter(x=>intersects(job,x));
  if(overlapping.some(x=>x.policy.exclusive)||policy.exclusive&&overlapping.length||overlapping.length>=2){job.start=Math.min(...overlapping.map(x=>x.end))+.15;}
  else if(cfg.mode==='block'&&blockConflict(job,overlapping))job.start+=.25;
  else break;
  job.end=job.start+state.duration;
 }
 // Conservative serial fallback. This shifts the entire scene, never its projectiles.
 if(iterations>=200){job.start=Math.max(now,...world.jobs.map(x=>x.end))+.15;job.end=job.start+state.duration;}
 world.jobs.push(job);world.mode=cfg.mode;
 if(cfg.mode==='block'){
  if(!world.carrier){world.carrier=B.create(skill,stats(cfg),seed,{hp:5000,power:40,endOnDeath:false});Object.assign(world.carrier,{events:[],duration:100000,time:now-STEP,preparation:0,ended:false,contacts:[]});}
  for(const e of state.events){const event={...e,weight:e.weight*state.damageBase/world.carrier.damageBase,id:job.id+'/'+e.id,source:actor.id,at:e.at+job.start};if(e.freezeStart!==undefined){event.freezeStart=e.freezeStart+job.start;event.freezeEnd=e.freezeEnd+job.start;}world.carrier.events.push(event);}
  world.carrier.events.sort((a,b)=>a.at-b.at);
 }
 return job;
}
function activeJobs(world,time){return world.jobs.filter(j=>!j.finished&&time>=j.start-1e-8&&time<=j.end+1e-8);}
function step(world,time,player,input,cfg,onContact,onPlanned){
 const jobs=activeJobs(world,time),height=cfg.mode==='block'?B.H:E.H;
 if(cfg.mode==='block'&&world.carrier){
  const c=world.carrier,current=jobs.find(j=>j.policy.exclusive)||jobs[0];
  c.time=time-STEP;c.ended=false;c.preparation=current?current.start+current.state.preparation:0;
  c.p=current?current.state.p:{skill:{base_id:''},kind:'mana'};
  const before=c.contacts.length;B.step(c,STEP,input);
  for(const contact of c.contacts.slice(before)){const job=world.jobs.find(j=>contact.id.startsWith(j.id+'/'));onContact(job,{...contact,raw:contact.raw||0},contact.reduction||0);}
  for(const job of jobs){job.state.time=Math.min(job.state.duration,time-job.start);for(const key of SHIELD)job.state[key]=['raisedAt','lastRaise','loweredAt','perfectUntil','brokenUntil'].includes(key)?c[key]-job.start:c[key];job.state.events.forEach(e=>{e.resolved=world.carrier.events.find(o=>o.id===job.id+'/'+e.id)?.resolved||false;});}
 }else if(cfg.mode!=='block'){
  const base={x:player.x,y:player.y*height/360,r:6,vx:player.vx||0,vy:player.vy||0};let moved=null;
  const move=input.target?{target:{x:input.target[0],y:input.target[1]*height/360}}:input;
  for(const job of jobs){const s=job.state;s.player={...base};const before=s.contacts.length;E.defenseStep(s,STEP,move);if(s.time>s.preparation+1e-8)moved??={...s.player};
   for(const h of s.hazards)if(!h.disabled&&!job.seenHazards.has(h.damageId)){job.seenHazards.add(h.damageId);onPlanned(job,h.rawDamage);}
   for(const c of s.contacts.slice(before))onContact(job,{...c,time:job.start+c.time,y:c.y*360/height},0);
  }
  if(moved){player.x=moved.x;player.y=moved.y*360/height;player.vx=moved.vx;player.vy=moved.vy;}
  else if(!jobs.length){const d=E.difficulty(stats(cfg)),length=Math.hypot(move.target?move.target.x-base.x:move.x||0,move.target?move.target.y-base.y:move.y||0);player.vx=0;player.vy=0;if(length){const dx=move.target?move.target.x-base.x:move.x,dy=move.target?move.target.y-base.y:move.y,travel=Math.min(move.target?length:Infinity,d.moveSpeed*STEP*Math.min(1,move.target?1:length));player.x=E.clamp(base.x+dx/length*travel,12,E.W-12);player.y=E.clamp(base.y+dy/length*travel,12,E.H-12)*360/height;}}
 }
 for(const job of world.jobs)job.finished=time>=job.end-1e-8;
 return {active:jobs,finished:world.jobs.every(j=>j.finished),carrier:world.carrier};
}
return {init,enqueue,step,activeJobs,compatibility,createState,stats,E,B,NZ};
});
