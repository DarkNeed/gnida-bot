const assert=require('node:assert/strict');
const W=require('../webapp/qte-watch');
const E=require('../webapp/qte-unique/engine');
const B=require('../webapp/qte-block/engine');
const profile={id:'hunter_shot:Shot:1:physical',base_id:'hunter_shot',name:'Shot',class_id:'hunter',branch:'moon',damage_type:'physical',strikes:1,tags:[]};
const stats={accuracy:95,enemyEvasion:5,enemyAccuracy:95,evasion:5,physicalDefense:35,magicDefense:20,enemyAttack:30};
for(const [version,kind] of [[2,'attack'],[2,'defense'],[3,'defense']]){
  const stage={id:'test',version,kind,profile,stats,seed:23,target_hp:180,damage_base:40,defense_preparation:kind==='defense'?1:0};
  const options={hp:180,damageBase:40,referenceDamage:40,endOnDeath:false,preparation:stage.defense_preparation};
  const direct=version===3?B.create(profile,stats,23,options):(kind==='attack'?E.attack:E.defense)(E.profile(profile),stats,23,options);
  let live=W.createReplay(stage),late=W.createReplay(stage),inputs=[],clicks=[],last='',lastInputs=0,lastClicks=0;
  const total=Math.ceil(direct.duration*120-1e-7);
  for(let t=0;t<total;t++){
    if(kind==='attack'){
      const f=E.attackFrame(direct);
      if(f.canHit&&Math.abs(f.cursor-f.center)<f.width/2){E.hit(direct);clicks.push(t);}
      E.attackStep(direct,Math.min(direct.duration,(t+1)/120)-direct.time);
    }else{
      const c=version===3?{active:t%110<70,angle:Math.sin(t/50)*Math.PI}:
        t<300?{x:-.4,y:.6}:t<650?{target:[650,50]}:{x:.7,y:-.3};
      if(JSON.stringify(c)!==last){last=JSON.stringify(c);inputs.push({t,...c});}
      if(version===3)B.step(direct,1/120,c);
      else E.defenseStep(direct,1/120,c.target?{target:{x:c.target[0],y:c.target[1]}}:c);
    }
    const tick=t+1;
    if(tick%24===0||tick===total){
      live=W.extendReplay(live,{id:'test',tick,inputs:inputs.slice(lastInputs),clicks:clicks.slice(lastClicks),ended:tick===total});
      lastInputs=inputs.length;lastClicks=clicks.length;W.stepReplay(live,tick);
      late=W.extendReplay(late,{id:'test',tick,inputs,clicks,reset:true,ended:tick===total});W.stepReplay(late,tick);
      for(const model of [live,late]){
        assert.deepEqual(model.sim.contacts,direct.contacts);
        assert.deepEqual(model.sim.results,direct.results);
        assert.deepEqual(model.sim.player,direct.player);
        assert.equal(model.sim.hp,direct.hp);
        assert.equal(model.sim.stamina,direct.stamina);
      }
    }
  }
  assert.equal(W.extendReplay(live,{id:'wrong',tick:0}),live);
}
// A final successful click may finish the attack without another simulation tick.
let model=W.createReplay({id:'boundary',version:2,kind:'attack',profile,stats,seed:23});
let t=0;while(!E.attackFrame(model.sim).canHit||Math.abs(E.attackFrame(model.sim).cursor-E.attackFrame(model.sim).center)>E.attackFrame(model.sim).width/3){
  model.knownTick=++t;W.stepReplay(model,t);
}
model=W.extendReplay(model,{id:'boundary',tick:t,clicks:[t],ended:true});W.stepReplay(model,t);
assert.deepEqual(model.sim.results,[true]);
assert.match(W.buttons('battle','x"<',[],{10:'<img onerror="x">'}),/&lt;img/);
assert.match(W.buttons('battle','x',[]),/Автопросмотр мини-игр/);
assert.match(W.buttons('battle','x',[]),/aria-pressed="false"/);
assert.doesNotThrow(()=>W.source({version:2},{token:'x'},()=>{throw Error('unused');}).finish());
// Real browser publisher path: no event upload before demand; errors cannot
// prevent the player's proof from finishing. Fake only the network/timers.
const original={WebSocket:globalThis.WebSocket,Telegram:globalThis.Telegram,location:globalThis.location,
  setInterval,clearInterval,setTimeout,clearTimeout};
let fake,flush,cleared=false;
try{
  globalThis.location={protocol:'https:',host:'localhost'};
  globalThis.Telegram={WebApp:{initData:'signed-test-only'}};
  globalThis.setInterval=fn=>(flush=fn,1);globalThis.setTimeout=()=>2;
  globalThis.clearInterval=()=>{cleared=true;};globalThis.clearTimeout=()=>{};
  globalThis.WebSocket=class{
    constructor(url){fake=this;this.url=url;this.readyState=1;this.sent=[];}
    send(value){if(this.fail)throw Error('network closed');this.sent.push(JSON.parse(value));}
    close(){this.readyState=3;this.onclose?.();}
  };
  let tick=0,inputs=[];
  const source=W.source({version:3,id:'publish'},{scope:'battle',token:'room'},()=>({tick,inputs}));
  fake.onopen();assert.equal(fake.sent.length,1);assert.equal(fake.sent[0].role,'source');
  flush();assert.equal(fake.sent.length,1);
  fake.onmessage({data:JSON.stringify({type:'demand',active:true})});
  tick=24;inputs.push({t:0,angle:0,active:true});flush();
  assert.equal(fake.sent[1].reset,true);assert.deepEqual(fake.sent[1].inputs,inputs);
  tick=48;inputs.push({t:24,angle:1,active:true});flush();
  assert.equal(fake.sent[2].reset,false);assert.deepEqual(fake.sent[2].inputs,[inputs[1]]);
  fake.onmessage({data:JSON.stringify({type:'demand',active:false})});
  tick=72;flush();assert.equal(fake.sent.length,3);
  fake.onmessage({data:JSON.stringify({type:'demand',active:true})});flush();
  assert.equal(fake.sent[3].reset,true);assert.equal(fake.sent[3].inputs.length,2);
  fake.fail=true;assert.doesNotThrow(()=>source.finish());assert.equal(cleared,true);
}finally{Object.assign(globalThis,original);}
console.log('Spectator replay: attack, dodge, block, snapshots, deltas and boundary clicks passed.');
