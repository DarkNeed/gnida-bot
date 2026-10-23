const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../webapp/qte-unique/engine'),B=require('../webapp/qte-block/engine');
const sandbox={window:{QTEUnique:E},console};vm.runInNewContext(fs.readFileSync('webapp/qte-casino-view','utf8'),sandbox);
const V=sandbox.window.QTECasinoView,text=[];
const ctx=new Proxy({}, {get:(obj,key)=>key==='fillText'?(s)=>text.push(s):()=>{},set:(obj,key,value)=>{obj[key]=value;return true;}});
const rows=JSON.parse(fs.readFileSync(0,'utf8')).filter(s=>s.class_id==='gambler');
const stats={accuracy:75,enemyEvasion:10,enemyAccuracy:100,evasion:0,physicalDefense:35,magicDefense:35,enemyAttack:30};
for(const row of rows){
  const p=E.profile(row),s=E.attack(p,stats,17,{damageBase:40});s.time=1.5;text.length=0;
  assert.equal(V.drawAttack(ctx,{clientWidth:390},s),true);
  assert.ok(text.some(t=>/БРОСОК|ТУЗ|ВА-БАНК|БАРАБАН/.test(t)),row.name);
  const f=E.attackFrame(s);E.hit(s);assert.equal(s.casinoThrows.length,1);
  assert.equal(E.hit(s),null,'No second attempt');
  s.time+=.25;assert.equal(V.drawAttack(ctx,{clientWidth:390},s),true);
  const b=B.create(p,stats,17,{endOnDeath:false});b.time=2.1;text.length=0;
  assert.equal(V.drawBlock(ctx,{clientWidth:390},b),true);
  assert.ok(text.some(t=>/РУЛЕТКА|КОСТЬ|777|БАРАБАН|КОЛОДУ/.test(t)),row.name);
  assert.ok(B.casinoHint(p));
}
const normal=E.attack(E.profile({id:'plain',base_id:'bum_punch',name:'Удар бомжа',class_id:'ragamuffin',strikes:1}),stats,17);
assert.equal(V.drawAttack(ctx,{clientWidth:390},normal),false);
console.log('Casino: five themed attack widgets and five block scenes render; one attempt retained.');
