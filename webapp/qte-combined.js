/* Native patterns on one field. No attack family is reimplemented here. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./qte-unique/engine'):root.QTEUnique,typeof module==='object'&&module.exports?require('./qte-block/engine'):root.QTEBlock);if(typeof module==='object'&&module.exports)module.exports=api;else root.QTECombined=api;})(globalThis,function(E,B){
 'use strict';
 const SHIELD=['stamina','angle','active','requested','raisedAt','lastRaise','loweredAt','perfectUntil','brokenUntil'];
 function create(stage){
  const block=stage.defense_mode==='block',states=stage.members.map(m=>{const options={hp:1000000,damageBase:m.damage_base,referenceDamage:m.damage_base,criticalBase:m.critical_base,criticalStrikes:m.critical_strikes,endOnDeath:false,enabledStrikes:m.enabled_strikes,preparation:m.defense_preparation??1};return block?B.create(m.profile,m.stats,m.seed,options):E.defense(E.profile(m.profile),m.stats,m.seed,options);});
  let carrier=null;if(block){let lead=0;stage.members.forEach((m,i)=>{if((m.stats.enemyAttack||0)>(stage.members[lead].stats.enemyAttack||0))lead=i;});carrier=B.create(stage.members[lead].profile,stage.members[lead].stats,stage.members[lead].seed,{hp:1000000,endOnDeath:false});carrier.events=states.flatMap((s,i)=>s.events.map(e=>({...e,id:i+'/'+e.id}))).sort((a,b)=>a.at-b.at);carrier.duration=stage.duration;}
  return {stage,states,block,carrier,player:{x:360,y:160,r:6,vx:0,vy:0},time:0,duration:stage.duration,ended:false,contacts:[],damage:0,hp:stage.target_hp,initialHp:stage.target_hp,seen:states.map(()=>0)};
 }
 function step(s,input={}){
  if(s.ended)return;s.time+=1/120;let moved=null;
  if(s.block){const c=s.carrier;B.step(c,1/120,input);for(let i=0;i<s.states.length;i++){const state=s.states[i];state.time=Math.min(s.time,state.duration);for(const k of SHIELD)state[k]=c[k];state.events.forEach(e=>{e.resolved=c.events.find(v=>v.id===i+'/'+e.id)?.resolved||false;});}}
  else{const base={...s.player};s.states.forEach(state=>{if(state.ended)return;state.player={...base};E.defenseStep(state,1/120,input.target?{target:{x:input.target[0],y:input.target[1]}}:input);if(!moved&&state.time>state.preparation+1e-8)moved={...state.player};});if(moved)s.player=moved;}
  s.states.forEach((state,i)=>{const m=s.stage.members[i],contacts=s.block?s.carrier.contacts.filter(c=>c.id.startsWith(i+'/')):state.contacts;for(const c of contacts.slice(s.seen[i])){const event=s.block?s.carrier.events.find(e=>e.id===c.id):null,weight=s.block?(event.kind==='feint'?0:event.weight*(1-c.reduction)):c.weight;const damage=Math.max(0,Math.round(m.damage_base*weight*(m.critical_strikes?.[c.strike]&&!m.critical_base?1.5:1)));s.contacts.push({...c,weight,source:m.encounter_enemy,damage});s.damage+=damage;}s.seen[i]=contacts.length;});
  s.hp=Math.max(0,s.initialHp-s.damage);s.ended=s.time>=s.duration-1e-8;
 }
 function layerContext(ctx){let skipStroke=false;return new Proxy(ctx,{get(target,key){
  if(key==='clearRect')return ()=>{};
  if(key==='fillRect')return (x,y,w,h)=>{if(x===0&&y===0&&w===720&&(h===320||h===400))return;if(x===-5&&y===-5&&w===10&&h===10&&target.fillStyle==='#92e2ce')return;target.fillRect(x,y,w,h);};
  if(key==='fillText')return (text,...args)=>{if(/^(КАСАНИЯ |−\d|ПРИГОТОВЬСЯ|ЗАТЕМ —|ПАЛЕЦ \/|ЩИТ ПОДНЯТ|ОПУСТИ ЩИТ —)/.test(String(text)))return;target.fillText(text,...args);};
  if(key==='beginPath')return ()=>{skipStroke=false;target.beginPath();};
  if(key==='arc')return (x,y,r,...args)=>{if(x===360&&y===200&&[48,92,145].includes(r))skipStroke=true;target.arc(x,y,r,...args);};
  if(key==='stroke')return (...args)=>{if(skipStroke||['#1b3040','#162b3b'].includes(target.strokeStyle))return;target.stroke(...args);};
  const v=Reflect.get(target,key,target);return typeof v==='function'?v.bind(target):v;
 },set(target,key,value){Reflect.set(target,key,value,target);return true;}});}
 function draw(ctx,canvas,s){
  const height=s.block?400:320;ctx.fillStyle='#091320';ctx.fillRect(0,0,720,height);ctx.strokeStyle='#1b2c40';ctx.lineWidth=.5;for(let x=0;x<720;x+=30){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}for(let y=0;y<height;y+=30){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(720,y);ctx.stroke();}
  const proxy=layerContext(ctx);s.states.forEach(state=>{if(state.time<state.preparation)return;ctx.save();const view={...state,contacts:[],player:s.block?state.player:s.player};(s.block?globalThis.QTEBlockView:globalThis.QTEView).draw(proxy,canvas,view);ctx.restore();});
  ctx.save();if(s.block){const c=s.carrier;ctx.translate(360,200);ctx.rotate(c.angle);ctx.beginPath();ctx.arc(0,0,48,-c.params.arc/2,c.params.arc/2);ctx.strokeStyle=c.active?'#9cd9e7':'#546575';ctx.lineWidth=c.active?8:3;ctx.stroke();}else{ctx.translate(s.player.x,s.player.y);ctx.rotate(Math.PI/4);ctx.fillStyle='#a1e5d9';ctx.shadowColor='#8fe6dd';ctx.shadowBlur=12;ctx.fillRect(-5,-5,10,10);}ctx.restore();
  if(s.time<1){ctx.fillStyle='#0c1725bb';ctx.fillRect(0,0,720,height);ctx.fillStyle='#e8ca86';ctx.font='bold 24px Segoe UI';ctx.textAlign='center';ctx.fillText('ПРИГОТОВЬСЯ · '+(1-s.time).toFixed(1),360,height/2);}
 }
 return {create,step,draw,layerContext};
});
