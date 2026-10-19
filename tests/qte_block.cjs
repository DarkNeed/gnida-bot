const assert=require('node:assert/strict');
const B=require('../webapp/qte-block/engine');
const skill={id:'block-test',name:'Стальная проверка',class_id:'warrior',damage_type:'physical',strikes:1};
const stats={physicalDefense:40,magicDefense:10,enemyAttack:30,enemyAccuracy:85};
function trial(changes={}){return B.create(skill,stats,17,{power:40,hp:5000,...changes});}
function one(s,kind='slash',angle=0,at=2){s.events=[{id:'one',at,warning:.7,angle,kind,tier:'critical',weight:1,strike:0,resolved:false}];return s;}
function advance(s,until,cmd={}){B.step(s,Math.max(0,until-s.time),cmd);}
const warm=trial();advance(warm,1,{active:true,angle:Math.PI});
assert.equal(warm.angle,0);assert.equal(warm.active,false);assert.equal(warm.damage,0);assert.equal(warm.stamina,warm.params.maxStamina);
const hit=one(trial());advance(hit,2.1);const afterArmor=hit.damage;
assert.equal(hit.misses,1);assert.equal(hit.damage,Math.round(100*100/(100+40*4)));
const normal=one(trial());advance(normal,2.1,{active:true,angle:0});
assert.equal(normal.blocks,1);assert.equal(normal.damage,Math.round(100*100/(100+40*4)*.25));
const perfect=one(trial());advance(perfect,1.9);advance(perfect,2.1,{active:true,angle:0});
assert.equal(perfect.perfects,1);assert.equal(perfect.damage,0);assert.equal(perfect.hp,5000);
const wrong=one(trial());advance(wrong,2.1,{active:true,angle:Math.PI});
assert.equal(wrong.damage,afterArmor);assert.equal(wrong.misses,1);
assert(Math.abs(perfect.player.x-360)<1e-9&&perfect.player.y===200,'blocking cannot move the marker');
const wave=one(trial(),'wave');advance(wave,2.1,{active:true,angle:0});assert.equal(wave.misses,1,'old held shield cannot catch a wave');
const freshWave=one(trial(),'wave');advance(freshWave,1.7);advance(freshWave,2.1,{active:true,angle:0});
assert.equal(freshWave.blocks,1);assert.equal(freshWave.damage,normal.damage);
const parryWave=one(trial(),'wave');advance(parryWave,1.9);advance(parryWave,2.1,{active:true,angle:Math.PI});assert.equal(parryWave.damage,0);
const same=one(trial());advance(same,2.1,{active:true,angle:0});const count=same.contacts.length;advance(same,3,{active:true,angle:0});assert.equal(same.contacts.length,count);
const broken=trial();broken.events=Array.from({length:8},(_,i)=>({id:'break:'+i,at:1.5+i*.2,warning:.5,angle:0,kind:'slash',tier:'critical',weight:1,strike:0,resolved:false}));
advance(broken,3.1,{active:true,angle:0});assert(broken.breaks>0);assert(broken.damage>0);const low=broken.stamina;advance(broken,4.3,{active:false});assert(broken.stamina>low+20);
const spam=one(trial());advance(spam,1.8,{active:true,angle:0});advance(spam,1.85,{active:false});advance(spam,2.1,{active:true,angle:0});
assert.equal(spam.perfects,0,'short release cannot refresh parry');
const rotation=one(trial());advance(rotation,1.8,{active:true,angle:Math.PI});advance(rotation,2.1,{active:true,angle:0});assert.equal(rotation.perfects,0,'turning while holding is not a fresh parry');
const zeroArmor=B.create(skill,{...stats,physicalDefense:0},17,{power:40,hp:5000});
const highArmor=B.create(skill,{...stats,physicalDefense:80},17,{power:40,hp:5000});
assert(highArmor.params.maxStamina>zeroArmor.params.maxStamina);assert(highArmor.params.arc>zeroArmor.params.arc);assert(highArmor.params.perfectWindow>zeroArmor.params.perfectWindow);
one(zeroArmor);one(highArmor);advance(zeroArmor,3);advance(highArmor,3);assert(highArmor.damage<zeroArmor.damage);
assert.deepEqual(B.parameters(B.create(skill,stats).p,{...stats,evasion:0}),B.parameters(B.create(skill,stats).p,{...stats,evasion:100}));
const magic=B.create({...skill,damage_type:'magic'},stats);assert.equal(magic.params.armor,10);
let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>raw+=s);process.stdin.on('end',()=>{
  const catalog=raw?JSON.parse(raw):[skill];
  const signatures=new Set();
  for(const entry of catalog){
    const a=B.create(entry,stats,23,{hp:5000}),b=B.create(entry,stats,23,{hp:5000});
    signatures.add(JSON.stringify(a.events));
    while(!a.ended)B.step(a,1/30,{active:true,angle:0});
    while(!b.ended)B.step(b,1/120,{active:true,angle:0});
    assert.deepEqual(B.result(a),B.result(b),'fixed timestep '+entry.name);
    assert.equal(a.contacts.length,a.events.length);assert.equal(new Set(a.contacts.map(c=>c.id)).size,a.contacts.length);
    assert.equal(a.hp+a.damage,a.initialHp);assert(a.stamina>=0&&a.stamina<=a.params.maxStamina);
  }
  assert(signatures.size>=catalog.length*.9,'named skills have different interception schedules');
  console.log('PASS guard: preparation, armor, 75% block, perfect block, direction, waves, stamina/break/recovery, anti-spam, fixed ticks, '+catalog.length+' profiles');
});
