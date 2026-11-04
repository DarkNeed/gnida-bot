/* Isolated experimental combat. Never imported by the production arena. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./existing.js'):root.QueueExisting);if(typeof module==='object'&&module.exports)module.exports=api;else root.ActionQueueLab=api;})(globalThis,function(Existing){
'use strict';
const W=720,H=360,PREPARATION=1.25,STEP=1/120,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const COLORS=['#72d8ed','#b6d59a','#dfc287','#ed9d79','#b5a1ef','#ed92b6'];
const SKILLS={
 shot:{name:'Мановый выстрел',cast:1.9,cost:18,kind:'damage',damage:38,motif:'orb',description:'Быстрая атака. Попадание автоматическое только в этом полигоне.'},
 erasure:{name:'Тяжёлое заклинание',cast:4.6,cost:48,kind:'damage',damage:105,motif:'orb',description:'Долгая подготовка, большой урон.'},
 interrupt:{name:'Прерывающий выстрел',cast:1.5,cost:25,kind:'interrupt',damage:22,motif:'bullet',description:'Срывает ещё не завершённый каст выбранного врага. Выпущенные снаряды остаются.'},
 barrier:{name:'Защитный барьер',cast:1.3,cost:25,kind:'barrier',shield:65,description:'Поглощает следующие 65 единиц урона после брони. Сначала его нужно успеть поставить.'},
 focus:{name:'Восстановить энергию',cast:1.7,cost:0,kind:'resource',resource:45,description:'Восстановление происходит в момент завершения каста, а не сразу после выбора.'},
 strike:{name:'Рубящий удар',cast:2.7,cost:22,kind:'damage',damage:44,motif:'cut',description:'Обычная атака союзника. Не даёт дополнительных ходов от высокой скорости.'},
 heal:{name:'Исцеляющее слово',cast:3.2,cost:30,kind:'heal',heal:58,description:'Лечит тебя при завершении каста. Павшего персонажа не воскрешает.'},
 guard:{name:'Прикрытие',cast:1.8,cost:18,kind:'barrier',shield:35,description:'Союзник даёт тебе небольшой щит.'},
 rifle:{name:'Три очереди',cast:2.5,cost:24,kind:'hostile',damage:42,dtype:'physical',pattern:'rifle',motif:'bullet',description:'Три отмеченные очереди с края поля; каждая состоит из трёх пуль.'},
 ice:{name:'Ледяные веера',cast:4.2,cost:32,kind:'hostile',damage:48,dtype:'magic',pattern:'ice',motif:'ice',description:'Два веера крупных осколков. Направление фиксируется при появлении предупреждения.'},
 slash:{name:'Двойное рассечение',cast:3.1,cost:26,kind:'hostile',damage:46,dtype:'physical',pattern:'slash',motif:'cut',description:'Две диагонали с предупреждением. Между ними можно сменить направление.'},
 lightning:{name:'Грозовой прицел',cast:4.7,cost:36,kind:'hostile',damage:52,dtype:'magic',pattern:'lightning',motif:'lightning',description:'Два столба молнии: сначала видна траектория, затем удар.'},
 basic:{name:'Обычный удар',cast:2.2,cost:0,kind:'damage',damage:20,motif:'cut',description:'Запасное действие при нехватке энергии.'},
 enemy_basic:{name:'Слабый залп',cast:2.2,cost:0,kind:'hostile',damage:18,dtype:'physical',pattern:'rifle',motif:'bullet',description:'Запасная атака при нехватке энергии.'},
};
const HERO_SKILLS=['shot','erasure','interrupt','barrier','focus'];
const ENEMY_SKILLS=['rifle','ice','slash','lightning'];
function actors(){return [
 {id:'hero',name:'Твой персонаж',role:'Маг · испытатель',team:'players',color:COLORS[0],sprite:'mage',speed:20,hp:240,maxHp:240,mp:100,maxMp:100,skill:'shot'},
 {id:'guard',name:'Рыцарь',role:'Союзник · авто',team:'players',color:COLORS[1],sprite:'warrior',speed:24,hp:280,maxHp:280,mp:100,maxMp:100,skill:'strike'},
 {id:'priest',name:'Жрец',role:'Союзник · авто',team:'players',color:COLORS[2],sprite:'priest',speed:14,hp:210,maxHp:210,mp:100,maxMp:100,skill:'heal'},
 {id:'gunner',name:'Стрелок',role:'Враг · физический',team:'enemies',color:COLORS[3],sprite:'hunter',speed:28,hp:280,maxHp:280,mp:160,maxMp:160,skill:'rifle'},
 {id:'caster',name:'Заклинатель',role:'Враг · магический',team:'enemies',color:COLORS[4],sprite:'mage',speed:15,hp:260,maxHp:260,mp:180,maxMp:180,skill:'ice'},
 {id:'duelist',name:'Дуэлянт',role:'Враг · физический',team:'enemies',color:COLORS[5],sprite:'warrior',speed:22,hp:310,maxHp:310,mp:150,maxMp:150,skill:'slash'},
];}
const PRESETS={
 duel:{name:'Один противник',hint:'Посмотри, как быстрый выстрел, удар врага и лечение попадают в одну общую очередь.',count:1},
 duo:{name:'Два атакующих',hint:'Готовые классовые мини-игры запускаются в общей очереди. Совместимые рисунки пересекаются на одном поле.',count:2},
 crossfire:{name:'Три атакующих',hint:'Три источника, одно поле. Не больше двух обычных рисунков одновременно; особая сцена ждёт отдельного окна.',count:3},
 interruption:{name:'Сорвать заклинание',hint:'Выбери заклинателя целью. Быстрый прерывающий выстрел отменит его каст, но не уже выпущенную очередь.',count:2},
 rescue:{name:'Успеть вылечить',hint:'Начни с низким HP. Подними скорость жреца или замени своё действие на барьер и сравни результат.',count:3},
};
function config(preset='duo'){
 const p=PRESETS[preset]||PRESETS.duo,a=actors().slice(0,3+p.count);
 if(preset==='interruption'){a[0].skill='interrupt';a[4].skill='lightning';}
 if(preset==='rescue'){a[0].hp=40;a[2].speed=0;a[2].castOverride=6;}
 return {preset,actors:a,target:preset==='interruption'?'caster':'gunner',mode:'dodge',evasion:15,accuracy:95,armor:12,seed:17};
}
function castTime(actor,skill){return skill.cast/(1+clamp(Number(actor.speed)||0,0,60)*.018);}
function actionSkill(input,actor,key=actor.skill){const base=SKILLS[key]||SKILLS.basic;if(['enemy_basic','basic'].includes(key)||!input.useExisting||!actor.existingSkill||!['hostile',...(input.multiTarget?['damage']:[])].includes(base.kind))return base;return {...base,name:actor.existingSkill.name,cost:actor.existingSkill.cost??base.cost};}
function buildQueue(input){return input.actors.filter(a=>a.hp>0).map((a,index)=>{
 const requested=SKILLS[a.skill]?a.skill:'basic',chosen=actionSkill(input,a,requested),key=a.mp>=chosen.cost?requested:a.team==='enemies'?'enemy_basic':'basic';
 const skill=actionSkill(input,a,key),cost=a.mp>=skill.cost?skill.cost:0;
 const timed={...skill,cast:clamp(Number(a.castOverride)||skill.cast,.6,7)};
 const support=['heal','barrier','resource'].includes(skill.kind),fallback=skill.kind==='resource'?a.id:support?'hero':a.team==='enemies'?'hero':input.target;
 const requestedTarget=input.multiTarget?(a.target||fallback):fallback,candidate=input.actors.find(f=>f.id===requestedTarget),target=candidate&&(skill.kind==='resource'?candidate.id===a.id:support?candidate.team===a.team:candidate.team!==a.team)?candidate.id:fallback;
 const targets=input.targetCounts&&a.targets?.length?[...new Set(a.targets)].filter(id=>input.actors.some(f=>f.id===id&&f.hp>0&&(support?f.team===a.team:f.team!==a.team))):[target];
 return {id:a.id,actor:a.id,name:a.name,color:a.color,team:a.team,index,skill:key,label:skill.name,cost,targets:targets.length?targets:[target],
  castStart:PREPARATION,castDuration:castTime(a,timed),at:PREPARATION+castTime(a,timed),status:'waiting',target};
 }).sort((a,b)=>a.at-b.at||a.index-b.index).map((a,i)=>({...a,order:i+1}));}
function rng(seed){let n=seed>>>0;return()=>{n=(Math.imul(n,1664525)+1013904223)>>>0;return n/4294967296;};}
function create(input,previous=null){
 const cfg=JSON.parse(JSON.stringify(input)),a=cfg.actors;
 if(previous)for(const f of a){const old=previous.actors[f.id];if(old){f.hp=old.hp;f.mp=Math.min(f.maxMp,old.mp+Math.round(f.maxMp*.08));}}
 cfg.seed=(Number(cfg.seed)||17)>>>0;cfg.mode=cfg.mode==='block'?'block':'dodge';
 const queue=buildQueue(cfg),last=Math.max(PREPARATION,...queue.map(a=>a.at));
 return {config:cfg,actors:Object.fromEntries(a.map(f=>[f.id,{...f}])),queue,time:0,ticks:0,round:previous?previous.round+1:1,
  preparation:PREPARATION,duration:last+6.6,ended:false,result:'',paid:false,hazards:[],pending:[],blockEvents:[],contacts:[],log:[],
  player:previous?{x:previous.player.x,y:previous.player.y}:{x:W/2,y:H/2},shield:0,damage:0,healed:0,totalRaw:0,
  bySource:cfg.multiTarget?{}:Object.fromEntries(a.filter(f=>f.team==='enemies').map(f=>[f.id,{name:f.name,color:f.color,damage:0,absorbed:0,contacts:0,planned:0,prevented:0}])),
  random:rng(cfg.seed+(previous?previous.round:0)*997),lastBlockAt:-100,shieldAngle:0,blockActive:false,lastRaise:-100,loweredAt:-100,
  perfectUntil:-100,brokenUntil:-100,stamina:100,staminaMax:100,blocks:0,perfects:0,misses:0,
  casts:[],projectileSerial:0,spawned:0,heavyDelays:0,blockDelays:0,existing:cfg.useExisting?Existing.init():null,
  fields:cfg.multiTarget?Object.fromEntries(a.map(f=>[f.id,{id:f.id,world:Existing.init(),player:{x:360,y:180},shield:0,damage:0,healed:0}])):null};
}
function sourceStats(s,id,target='hero'){const a=s.actors[id],key=s.fields?id+'>'+target:id;return s.bySource[key]??=( {name:a.name+(s.fields?' → '+s.actors[target].name:''),color:a.color,damage:0,absorbed:0,contacts:0,planned:0,prevented:0});}
function log(s,text,color='#a9b6ce',source=null){s.log.push({time:s.time,text,color,source});}
function actorAlive(s,id){return s.actors[id]?.hp>0;}
function cancel(s,a,reason){if(['cancelled','resolved'].includes(a.status))return;a.status='cancelled';a.reason=reason;if(s.paid)s.actors[a.actor].mp=Math.min(s.actors[a.actor].maxMp,s.actors[a.actor].mp+Math.floor(a.cost/2));log(s,a.name+': '+reason+' · возврат половины цены',a.color,a.actor);}
function budget(total,weights){let last=0,sum=0;const all=weights.reduce((n,x)=>n+x,0);return weights.map(w=>{sum+=w;const upto=Math.round(total*sum/all),part=upto-last;last=upto;return part;});}
function summon(s,action){
 const skill=SKILLS[action.skill],source=s.actors[action.actor],start=s.time,damage=skill.damage;
 if(s.existing){
  const original=['enemy_basic','basic'].includes(action.skill)?{id:'queue-free-basic',base_id:'bum_punch',name:'Удар бомжа',class_id:'ragamuffin',strikes:1,damage_type:'physical',tags:[]}:source.existingSkill;
  if(!original)throw new Error('Не выбран существующий навык для '+source.name);
  const field=s.fields?.[action.target],world=field?.world||s.existing,options=source.attackPower===undefined?s.config:{...s.config,damageBase:source.attackPower},job=Existing.enqueue(world,source,original,options,s.time);job.target=action.target;s.duration=Math.max(s.duration,job.end+.2);
  if(s.config.mode==='block'){const raw=job.state.events.reduce((n,e)=>n+e.weight*job.state.damageBase,0);sourceStats(s,source.id,action.target).planned+=raw;s.totalRaw+=raw;}
  if(job.start>s.time+.01)log(s,source.name+': сцена ожидает свободного окна · '+(job.start-s.time).toFixed(1)+' с',source.color,source.id);
  return;
 }
 const plans=skill.pattern==='rifle'?[0,.65,1.3]:[0,1.15];
 const raw=budget(damage,plans.map(()=>1));
 s.bySource[action.actor].planned=damage;s.totalRaw+=damage;
 plans.forEach((offset,i)=>s.pending.push({id:action.actor+':'+i,source:action.actor,skill:action.skill,color:source.color,
  planAt:start+offset,index:i,raw:raw[i],generated:false}));
}
function resolveAction(s,a){
 const actor=s.actors[a.actor],skill=SKILLS[a.skill];a.status='resolved';s.casts.push({actor:a.actor,time:s.time,skill:a.skill});
 if(s.fields&&['damage','hostile','interrupt'].includes(skill.kind)){
  if(!actorAlive(s,a.target)){log(s,actor.name+': цель '+s.actors[a.target].name+' уже повержена',actor.color,a.actor);return;}
  if(skill.kind==='interrupt'){const cast=s.queue.find(x=>x.actor===a.target);if(cast&&cast.at>s.time+1e-6&&!['cancelled','resolved'].includes(cast.status))cancel(s,cast,'каст прерван');}
  if(s.config.directCombat&&actor.team==='players'&&actor.directDamage!==undefined){
   const victim=s.actors[a.target],taken=Math.min(victim.hp,actor.directDamage);victim.hp-=taken;sourceStats(s,actor.id,a.target).damage+=taken;s.contacts.push({time:s.time,source:actor.id,target:a.target,damage:taken,direct:true,critical:!!actor.directCritical,color:actor.color,x:s.fields[a.target].player.x,y:s.fields[a.target].player.y});log(s,actor.name+': '+a.label+' · −'+taken+' HP → '+victim.name+(actor.directCritical?' · КРИТ':''),actor.color,actor.id);return;
  }
  for(const target of a.targets||[a.target])if(actorAlive(s,target))summon(s,{...a,target});log(s,actor.name+': '+a.label+' → '+(a.targets||[a.target]).map(id=>s.actors[id].name).join(', '),actor.color,a.actor);return;
 }
 if(actor.team==='enemies'){summon(s,a);log(s,actor.name+': '+(a.label||skill.name),actor.color,a.actor);return;}
 const recipient=s.fields?s.actors[a.target]:s.actors.hero,hero=recipient||s.actors.hero;
 if(skill.kind==='heal'){
  const amount=hero.hp>0?Math.min(hero.maxHp-hero.hp,skill.heal):0;hero.hp+=amount;s.healed+=amount;
  if(s.fields)s.fields[hero.id].healed+=amount;log(s,actor.name+': лечение +'+amount+' HP → '+hero.name+(hero.hp<=0?' · не воскрешает':''),actor.color,a.actor);return;
 }
 if(skill.kind==='barrier'){if(s.fields)s.fields[hero.id].shield+=skill.shield;else s.shield+=skill.shield;log(s,actor.name+': барьер +'+skill.shield+' → '+hero.name,actor.color,a.actor);return;}
 if(skill.kind==='resource'){actor.mp=Math.min(actor.maxMp,actor.mp+skill.resource);log(s,actor.name+': энергия восстановлена',actor.color,a.actor);return;}
 const target=s.actors[a.target];
 if(!target||target.hp<=0){log(s,actor.name+': выбранная цель уже повержена',actor.color,a.actor);return;}
 target.hp=Math.max(0,target.hp-skill.damage);log(s,actor.name+': '+skill.name+' · −'+skill.damage+' HP → '+target.name,actor.color,a.actor);
 if(skill.kind==='interrupt'){
  const cast=s.queue.find(x=>x.actor===target.id);
  if(cast&&cast.at>s.time+1e-6&&!['cancelled','resolved'].includes(cast.status))cancel(s,cast,'каст прерван');
  else log(s,'Поздно прерывать: выпущенная атака остаётся на поле',actor.color,a.actor);
 }
}
function heavyStart(s,at,duration){
 let count=0;
 while(s.hazards.filter(h=>h.heavy&&h.start<at+duration&&h.end>at).length>=2&&count++<40){at+=.22;s.heavyDelays++;}
 return at;
}
function addHazard(s,plan,h){s.hazards.push({...h,id:'h'+s.projectileSerial++,source:plan.source,color:plan.color,skill:plan.skill,hit:false});s.spawned++;}
function makeThreat(s,plan){
 const skill=SKILLS[plan.skill],accuracy=clamp(s.config.accuracy,60,100),warning=.95-(accuracy-60)*.0035,
  speed=215+(accuracy-60)*1.4,x=clamp(s.player.x+(s.random()-.5)*24,20,W-20),y=clamp(s.player.y+(s.random()-.5)*22,20,H-20),i=plan.index;
 if(s.config.mode==='block'){
  const sourceIndex=Object.keys(s.bySource).indexOf(plan.source),angle=(-Math.PI/2+sourceIndex*Math.PI*.75+i*Math.PI/2);
  let at=s.time+warning;
  if(at-s.lastBlockAt<.56){at=s.lastBlockAt+.56;s.blockDelays++;}s.lastBlockAt=at;
  s.blockEvents.push({id:'b'+s.projectileSerial++,source:plan.source,color:plan.color,skill:plan.skill,angle:Math.atan2(Math.sin(angle),Math.cos(angle)),
   at,warning:Math.max(warning,.85),raw:plan.raw,resolved:false,motif:skill.motif});
  s.duration=Math.max(s.duration,at+.8);return;
 }
 if(skill.pattern==='rifle'){
  const ys=[-36,0,36].map(offset=>clamp(y+offset,18,H-18)),raw=budget(plan.raw,[1,2,1]);
  for(let j=0;j<3;j++)addHazard(s,plan,{type:'bullet',x:-20,y:ys[j],vx:speed,vy:0,r:j===1?6:4,start:s.time+warning,end:s.time+warning+3.7,warnAt:s.time,raw:raw[j],motif:'bullet'});
 }else if(skill.pattern==='ice'){
  const bx=W+20,by=i%2?H-45:45,angle=Math.atan2(y-by,x-bx),raw=budget(plan.raw,[1,2,1]);
  for(let j=0;j<3;j++){const a=angle+(j-1)*.28;addHazard(s,plan,{type:'bullet',x:bx,y:by,vx:Math.cos(a)*speed*.79,vy:Math.sin(a)*speed*.79,r:7,start:s.time+warning,end:s.time+warning+4,warnAt:s.time,raw:raw[j],motif:'ice'});}
 }else if(skill.pattern==='slash'){
  const angle=i%2?-.55:.55,dx=Math.cos(angle)*850,dy=Math.sin(angle)*850,at=heavyStart(s,s.time+warning,.22);
  addHazard(s,plan,{type:'line',ax:x-dx,ay:y-dy,bx:x+dx,by:y+dy,r:10,start:at,end:at+.22,warnAt:s.time,raw:plan.raw,motif:'cut',heavy:true});
 }else{
  const cx=clamp(x+(i%2?85:-20),25,W-25),at=heavyStart(s,s.time+warning,.22);
  addHazard(s,plan,{type:'line',ax:cx,ay:-20,bx:cx+20,by:H+20,r:12,start:at,end:at+.22,warnAt:s.time,raw:plan.raw,motif:'lightning',heavy:true});
 }
 s.duration=Math.max(s.duration,...s.hazards.map(h=>h.end+.2));
}
function angleDiff(a,b){return Math.atan2(Math.sin(a-b),Math.cos(a-b));}
function pointSegment(px,py,ax,ay,bx,by){const dx=bx-ax,dy=by-ay,l=dx*dx+dy*dy,t=l?clamp(((px-ax)*dx+(py-ay)*dy)/l,0,1):0;return Math.hypot(px-ax-dx*t,py-ay-dy*t);}
function geometry(h,t){if(h.type!=='bullet')return h;const elapsed=Math.max(0,t-h.start);return {...h,px:h.x+h.vx*elapsed,py:h.y+h.vy*elapsed};}
function damage(s,event,outcome='hit',reduction=0){
 const target=event.target||'hero',victim=s.actors[target],field=s.fields?.[target],position=field?.player||s.player;
 const armor=clamp(s.config.armor,0,70),afterArmor=event.raw*100/(100+4*armor),source=sourceStats(s,event.source,target);
 source.exact=(source.exact||0)+afterArmor*(1-reduction);const before=source.rounded||0;source.rounded=Math.round(source.exact);let amount=source.rounded-before;
 const absorbed=Math.min(field?field.shield:s.shield,amount);if(field)field.shield-=absorbed;else s.shield-=absorbed;amount-=absorbed;
 const taken=Math.min(victim.hp,amount);victim.hp-=taken;if(target==='hero')s.damage+=taken;if(field)field.damage+=taken;source.damage+=taken;source.absorbed+=absorbed;source.contacts++;
 source.prevented+=afterArmor*reduction;
 s.contacts.push({time:s.time,source:event.source,target,damage:taken,absorbed,outcome,color:event.color,x:position.x,y:position.y,...(event.status?{status:event.status}:{})});
}
function block(s,dt,input){
 const angle=Number.isFinite(input.angle)?input.angle:s.shieldAngle;
 s.shieldAngle+=clamp(angleDiff(angle,s.shieldAngle),-Math.PI*4*dt,Math.PI*4*dt);
 const held=!!input.active&&s.time>=s.brokenUntil;
 if(held&&!s.blockActive){s.perfectUntil=s.time-s.loweredAt>=.10&&s.time-s.lastRaise>=.32?s.time+.23:-100;s.lastRaise=s.time;}
 if(!held&&s.blockActive)s.loweredAt=s.time;
 s.blockActive=held;s.stamina=clamp(s.stamina+(held?-2:28)*dt,0,s.staminaMax);
 for(const e of s.blockEvents){
  if(e.resolved||e.at>s.time+1e-8)continue;e.resolved=true;
  const facing=Math.abs(angleDiff(s.shieldAngle,e.angle))<=(115+clamp(s.config.armor,0,70)*.6)*Math.PI/360;
  if(held&&facing&&s.time<=s.perfectUntil+1e-8){s.perfects++;damage(s,e,'perfect',1);s.stamina=Math.min(100,s.stamina+4);}
  else if(held&&facing){const cost=22+e.raw*.22,share=Math.min(1,s.stamina/cost);s.stamina=Math.max(0,s.stamina-cost);s.blocks++;
   if(share<1){s.brokenUntil=s.time+.6;s.blockActive=false;s.loweredAt=s.time;damage(s,e,'break',.75*share);}else damage(s,e,'block',.75);
  }else{s.misses++;damage(s,e,'miss',0);}
 }
}
function dodge(s,dt,input){
 const old={...s.player},evasion=clamp(s.config.evasion,0,70),speed=145+evasion*.45;
 let dx=Number(input.x)||0,dy=Number(input.y)||0;if(input.target){dx=input.target[0]-s.player.x;dy=input.target[1]-s.player.y;}
 const length=Math.hypot(dx,dy);if(length){const step=input.target?Math.min(length,speed*dt):speed*dt*Math.min(1,length);s.player.x+=dx/length*step;s.player.y+=dy/length*step;}
 s.player.x=clamp(s.player.x,12,W-12);s.player.y=clamp(s.player.y,12,H-12);
 const radius=10-evasion*.045;
 for(const h of s.hazards){
  if(h.hit||s.time<h.start||s.time>h.end)continue;
  let hit=false;
  if(h.type==='bullet'){const now=geometry(h,s.time),before=geometry(h,Math.max(h.start,s.time-dt));
   hit=pointSegment(s.player.x,s.player.y,before.px,before.py,now.px,now.py)<=h.r+radius||pointSegment(now.px,now.py,old.x,old.y,s.player.x,s.player.y)<=h.r+radius;
  }else hit=Math.min(pointSegment(s.player.x,s.player.y,h.ax,h.ay,h.bx,h.by),pointSegment(old.x,old.y,h.ax,h.ay,h.bx,h.by))<=h.r+radius;
  if(hit){h.hit=true;damage(s,h);}
 }
}
function tick(s,input){
 s.ticks++;s.time=s.ticks*STEP;
 if(!s.paid&&s.time>=PREPARATION){
  s.paid=true;for(const a of s.queue){const actor=s.actors[a.actor];actor.mp=Math.max(0,actor.mp-a.cost);a.status='casting';}
  if(s.config.reactionCost){s.actors.hero.mp=Math.max(0,s.actors.hero.mp-s.config.reactionCost);log(s,'Перехват: −'+s.config.reactionCost+' энергии · одиночная атака принята за союзника',s.actors.hero.color,'hero');}
 }
 // Snapshot a simultaneous cast group before applying its effects: tied casts are simultaneous.
 for(const a of s.queue)if(a.status==='casting'&&!actorAlive(s,a.actor))cancel(s,a,'исполнитель повержен до завершения');
 const due=s.queue.filter(a=>a.status==='casting'&&a.at<=s.time+1e-8);
 for(const a of due)resolveAction(s,a);
 for(const p of s.pending)if(!p.generated&&p.planAt<=s.time+1e-8){p.generated=true;makeThreat(s,p);}
 if(s.time>=PREPARATION){
  if(s.fields){
   for(const [index,field] of Object.values(s.fields).entries()){
    let controls=input;
    if(field.id!=='hero'){
     const next=field.world.carrier?.events.find(e=>!e.resolved),accurate=Math.floor(s.time*1.7+index)%5!==0;
     controls=s.config.mode==='block'?{angle:next?(accurate?next.angle:next.angle+Math.PI/2):0,active:!!next&&s.time>=next.at-.19&&s.time<next.at+.08}:{x:Math.sin(s.time*.9+index*1.7),y:Math.cos(s.time*1.1+index)};
    }
    if(s.actors[field.id].hp<=0)controls={};
    Existing.step(field.world,s.time,field.player,controls,s.config,(job,c,reduction)=>{damage(s,{raw:c.raw,source:job.source,target:field.id,color:job.color,status:c.status},c.outcome||'hit',reduction);},(job,raw)=>{sourceStats(s,job.source,field.id).planned+=raw;s.totalRaw+=raw;});
   }
   const hero=s.fields.hero;s.player=hero.player;s.existing=hero.world;s.shield=hero.shield;
   const carrier=hero.world.carrier;if(carrier){s.stamina=carrier.stamina;s.staminaMax=carrier.params.maxStamina;s.shieldAngle=carrier.angle;s.blockActive=carrier.active;s.perfectUntil=carrier.perfectUntil;s.brokenUntil=carrier.brokenUntil;s.blocks=carrier.blocks;s.perfects=carrier.perfects;s.misses=carrier.misses;}
  }else if(s.existing){
   Existing.step(s.existing,s.time,s.player,input,s.config,(job,c,reduction)=>{damage(s,{raw:c.raw,source:job.source,color:job.color,status:c.status},c.outcome||'hit',reduction);},(job,raw)=>{s.bySource[job.source].planned+=raw;s.totalRaw+=raw;});
   const carrier=s.existing.carrier;if(carrier){s.stamina=carrier.stamina;s.staminaMax=carrier.params.maxStamina;s.shieldAngle=carrier.angle;s.blockActive=carrier.active;s.perfectUntil=carrier.perfectUntil;s.brokenUntil=carrier.brokenUntil;s.blocks=carrier.blocks;s.perfects=carrier.perfects;s.misses=carrier.misses;}
  }else if(s.config.mode==='block')block(s,STEP,input);else dodge(s,STEP,input);
 }
 const playersDefeated=Object.values(s.actors).filter(a=>a.team==='players').every(a=>a.hp<=0),enemiesDefeated=Object.values(s.actors).filter(a=>a.team==='enemies').every(a=>a.hp<=0),allJobs=s.fields?Object.values(s.fields).flatMap(f=>f.world.jobs):s.existing?.jobs;
 if(s.fields&&(playersDefeated||enemiesDefeated)){s.ended=true;s.result=playersDefeated?'Отряд повержен':'Противники повержены';}
 else if(!s.fields&&s.actors.hero.hp<=0){s.ended=true;s.result='Испытатель повержен';}
 else if(s.time>=s.duration||(!s.existing&&s.config.mode==='block'&&s.time>s.lastBlockAt+.8&&s.queue.every(a=>['resolved','cancelled'].includes(a.status))&&s.pending.every(p=>p.generated)&&s.blockEvents.every(e=>e.resolved))||(s.existing&&s.queue.every(a=>['resolved','cancelled'].includes(a.status))&&allJobs.every(j=>j.finished))){s.ended=true;s.result=enemiesDefeated?'Противники повержены':'Раунд завершён';}
}
function step(s,dt,input={}){if(s.ended)return;let n=Math.min(240,Math.max(0,Math.floor((s.remainder||0)+dt/STEP+1e-8)));s.remainder=(s.remainder||0)+dt/STEP-n;while(n--&&!s.ended)tick(s,input);}
function result(s){return {round:s.round,hp:s.actors.hero.hp,damage:s.damage,healed:s.healed,shield:s.shield,time:s.time,
  sources:JSON.parse(JSON.stringify(s.bySource)),casts:s.casts.map(x=>({...x})),blocks:s.blocks,perfects:s.perfects,misses:s.misses,
  cancelled:s.queue.filter(a=>a.status==='cancelled').map(a=>a.actor),heavyDelays:s.heavyDelays,blockDelays:s.blockDelays};}
return {W,H,STEP,PREPARATION,SKILLS,HERO_SKILLS,ENEMY_SKILLS,PRESETS,COLORS,config,actors,castTime,actionSkill,buildQueue,create,step,result,geometry,angleDiff,pointSegment,clamp};
});
