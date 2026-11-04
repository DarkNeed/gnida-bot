const assert=require('node:assert/strict'),Q=require('../tools/action_queue_lab/existing.js'),A=require('../tools/action_queue_lab/engine.js');
let raw='';process.stdin.on('data',b=>raw+=b);process.stdin.on('end',()=>{
const catalog=JSON.parse(raw),find=id=>catalog.find(s=>s.base_id===id&&s.origin==='Базовый навык')||catalog.find(s=>s.base_id===id),base={mode:'dodge',armor:12,evasion:15,accuracy:95,seed:17};let profiles=0;
for(const skill of catalog){
 const world=Q.init(),job=Q.enqueue(world,{id:'source',name:'Источник',color:'#aaa'},skill,base,0),old=Q.createState(skill,base,17),player={x:360,y:180,vx:0,vy:0};old.player.x=360;old.player.y=160;let contacts=[];
 for(let tick=1;tick<=Math.ceil(old.duration*120);tick++){
  const input={x:Math.sin(tick/110),y:Math.cos(tick/160)};Q.step(world,tick/120,player,input,base,(_,c)=>contacts.push(c),()=>{});Q.E.defenseStep(old,1/120,input);
  assert(Math.abs(player.x-old.player.x)<1e-5&&Math.abs(player.y*320/360-old.player.y)<1e-5,'Movement changed: '+skill.name);
 }
 assert.deepEqual(contacts.map(c=>[c.id,c.raw,c.status]),old.contacts.map(c=>[c.id,c.raw,c.status]),'Collisions changed: '+skill.name);
 assert.equal(job.state.p.kind,old.p.kind);assert.equal(job.state.events.length,old.events.length);profiles++;
}
const c={...base,mode:'block'};for(const skill of [find('warning_shot'),find('mana_shot'),...catalog.filter(s=>(s.base_id||'').startsWith('chaplain_')).slice(0,4),...catalog.filter(s=>(s.base_id||'').startsWith('nz_ainz')).slice(0,4)]){
 const w=Q.init(),job=Q.enqueue(w,{id:'s',name:'s',color:'#aaa'},skill,c,0),old=Q.createState(skill,c,17);let contacts=[];
 for(let i=1;i<=Math.ceil(old.duration*120);i++){const input={angle:i/150,active:i%120<65};Q.step(w,i/120,{x:360,y:180},input,c,(_,hit)=>contacts.push(hit),()=>{});Q.B.step(old,1/120,input);}
 assert.deepEqual(contacts.map(x=>[x.raw,x.damage,x.outcome]),old.contacts.map(x=>[x.raw,x.damage,x.outcome]),'Solo block changed: '+skill.name);assert(Math.abs(w.carrier.stamina-old.stamina)<1e-5);
}
// Multiple states must never multiply movement or shield recovery.
const w=Q.init(),skill=find('mana_shot'),actor=i=>({id:'s'+i,name:'s'+i,color:'#aaa'});Q.enqueue(w,actor(1),skill,base,0);Q.enqueue(w,actor(2),skill,base,0);const p={x:360,y:180};for(let i=1;i<=150;i++)Q.step(w,i/120,p,{x:1,y:0},base,()=>{},()=>{});assert(p.x<425,'Duplicated movement');
const blocks=Q.init();Q.enqueue(blocks,actor(1),skill,c,0);Q.enqueue(blocks,actor(2),skill,c,0);const carrier=blocks.carrier;carrier.stamina=0;for(let i=1;i<=120;i++)Q.step(blocks,i/120,{x:360,y:180},{},c,()=>{},()=>{});assert(carrier.stamina<=carrier.params.recovery+.01,'Duplicated shield recovery');
const reserved=Q.init();const special=catalog.find(s=>s.base_id==='chaplain_hand');const a=Q.enqueue(reserved,actor(1),special,base,0),b=Q.enqueue(reserved,actor(2),skill,base,.1);assert(a.policy.exclusive);assert(b.start>=a.end);assert.equal(b.state.duration,Q.createState(skill,base,17).duration);
// Integration uses the existing state adapter, not the four synthetic patterns.
const cfg=A.config('duo');cfg.useExisting=true;for(const f of cfg.actors.filter(f=>f.team==='enemies'))f.existingSkill=find(f.id==='gunner'?'warning_shot':'mana_shot');const sim=A.create(cfg);while(!sim.ended&&sim.time<60)A.step(sim,1/60,{x:0,y:0});assert(sim.ended);assert.equal(sim.hazards.length,0);assert.equal(sim.existing.jobs.length,2);assert(sim.existing.jobs.some(j=>j.state.hazards.length||j.state.projectileCount));assert.equal(sim.contacts.reduce((n,c)=>n+c.damage,0),sim.damage);
const depleted=JSON.parse(JSON.stringify(cfg));for(const f of depleted.actors)f.mp=0;assert(A.buildQueue(depleted).filter(a=>a.team==='enemies').every(a=>a.skill==='enemy_basic'&&a.cost===0));
console.log(JSON.stringify({originalDodgeProfiles:profiles,soloBlockCases:10,sharedMovement:true,sharedStamina:true,exclusiveScheduling:true,queueIntegration:true}));
});
