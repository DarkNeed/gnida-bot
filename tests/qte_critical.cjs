const assert=require('node:assert/strict');
const E=require('../webapp/qte-unique/engine');
const B=require('../webapp/qte-block/engine');
const W=require('../webapp/qte-watch');
const stats={accuracy:75,evasion:25,enemyAccuracy:75,enemyEvasion:25};
const skill={base_id:'test_crit',name:'Удар',class_id:'warrior',damage_type:'physical',strikes:1,tags:[]};
const p=E.profile(skill);
function criticalHit(options={}){
  const s=E.attack(p,stats,17,{damageBase:40,hp:200,...options});
  while(!s.ended){
    const f=E.attackFrame(s);
    if(f.canHit&&Math.abs(f.cursor-f.center)<f.criticalWidth/3){assert.equal(E.hit(s),true);break;}
    E.attackStep(s,1/120);
  }
  assert.deepEqual(s.criticals,[true]);
  assert.equal(s.contacts[0].critical,true);
  assert.equal(E.hit(s),null);
  return s;
}
assert.equal(criticalHit().damage,60);
assert.equal(criticalHit({criticalBase:true}).damage,40,'no double multiplier in forecast');
// Exercise the actual shared renderer, not just the contact metadata.
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const window={QTEUnique:E};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../webapp/qte-view'),'utf8'),{window});
const drawn=[],ctx=new Proxy({fillStyle:'',fillText(text){drawn.push({text,color:this.fillStyle});}},
  {get(target,key){return key in target?target[key]:()=>{};}});
const visual=criticalHit();
window.QTEView.draw(ctx,{clientWidth:720},visual);
assert.equal(drawn.find(t=>t.text==='−60').color,'#ff718e','critical damage floats in pink');
drawn.length=0;visual.contacts[0].critical=false;visual.contacts[0].tier='heavy';
window.QTEView.draw(ctx,{clientWidth:720},visual);
assert.equal(drawn.find(t=>t.text==='−60').color,'#ffd5a0','ordinary heavy damage keeps its color');
const restricted=E.attack(E.profile({...skill,tags:['no_critical']}),stats,17);
assert.equal(E.attackFrame(restricted).criticalWidth,0);
function defend(criticals,base=false){
  const s=E.defense(p,stats,17,{damageBase:40,hp:100000,criticalStrikes:criticals,criticalBase:base});
  while(!s.ended)E.defenseStep(s,1/120);
  return s;
}
const normal=defend([]),critical=defend([true]),natural=defend([true],true);
assert.deepEqual(normal.contacts.map(c=>c.id),critical.contacts.map(c=>c.id));
assert.equal(natural.damage,normal.damage);
assert(critical.damage>normal.damage);
function block(criticals,base=false){
  const s=B.create(skill,{},17,{referenceDamage:40,hp:100000,criticalStrikes:criticals,criticalBase:base});
  while(!s.ended)B.step(s,1/120,{active:false,angle:0});
  return s;
}
const nb=block([]),cb=block([true]),eb=block([true],true);
assert.equal(cb.damage,Math.round(nb.exactDamage*1.5));
assert.equal(eb.damage,nb.damage);
const watched=W.createReplay({version:2,kind:'defense',profile:skill,stats,seed:17,damage_base:40,
  target_hp:200,critical_base:true,critical_strikes:[true]});
assert.equal(watched.sim.criticalBase,true);
assert.deepEqual(watched.sim.criticalStrikes,[true]);
console.log('PASS timing crit, no stacking, immediate HP, dodge/block forecasts and spectator replay');
