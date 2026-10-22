// Exercise every phase renderer without a browser, canvas automation or accounts.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const E=require('../webapp/qte-unique/engine'),B=require('../webapp/qte-block/engine');
const W=require('../webapp/qte-watch');
const context={window:{},QTEUnique:E,QTEBlock:B};vm.createContext(context);
vm.runInContext(fs.readFileSync('webapp/qte-block-view','utf8'),context);
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);
process.stdin.on('end',()=>{
  const catalog=JSON.parse(input),labels=new Set(),calls=new Set();
  const ctx=new Proxy({fillText:t=>labels.add(t)}, {get:(o,key)=>key in o?o[key]:(...args)=>{calls.add(key);assert(args.every(x=>typeof x!=='number'||Number.isFinite(x)),key);}});
  for(const skill of catalog){
    const stats={physicalDefense:35,magicDefense:35,enemyAttack:30,enemyAccuracy:100};
    const s=B.create(skill,stats,23,{hp:5000,referenceDamage:40,endOnDeath:false});
    const stage={id:'chaplain-guard',version:3,kind:'defense',profile:skill,stats,seed:23,target_hp:5000,damage_base:40};
    let watcher=W.createReplay(stage),inputs=[];
    assert(s.chaplain?.hint);
    for(let tick=0;tick<1140;tick++){
      const cmd={active:tick%80<40,angle:B.angleDiff(tick/120,0)};inputs.push({t:tick,...cmd});B.step(s,1/120,cmd);
      if(tick%12===0)context.window.QTEBlockView.draw(ctx,{clientWidth:350},s);
      if((tick+1)%24===0||tick===1139){
        watcher=W.extendReplay(watcher,{id:stage.id,tick:tick+1,inputs,reset:true,ended:tick===1139});W.stepReplay(watcher,tick+1);
        assert.deepEqual(watcher.sim.contacts,s.contacts);assert.equal(watcher.sim.hp,s.hp);assert.equal(watcher.sim.stamina,s.stamina);
      }
    }
    assert(s.ended);assert.equal(s.contacts.length,s.events.length);
  }
  for(const text of ['ПАУЗА','ЛОЖНЫЙ','ADMIN / WRITE','XII','ВОЛНА · ПОДНИМИ ЩИТ ЗАНОВО'])assert(labels.has(text),text);
  for(const call of ['arc','lineTo','strokeRect','fillRect'])assert(calls.has(call),call);
  console.log('Chaplain guard view: all twelve scores, pause, clock, system windows and light render at phone width.');
});
