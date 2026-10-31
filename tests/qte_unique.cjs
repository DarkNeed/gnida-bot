const assert=require('node:assert/strict');
const E=require('../webapp/qte-unique/engine');
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);
process.stdin.on('end',()=>{
  const skills=JSON.parse(input),profiles=skills.map(E.profile),families=new Map();
  const equal={accuracy:75,evasion:25,enemyAccuracy:75,enemyEvasion:25};
  const weak={accuracy:45,evasion:0,enemyAccuracy:100,enemyEvasion:70};
  const strong={accuracy:100,evasion:90,enemyAccuracy:25,enemyEvasion:0};
  const copy=s=>JSON.parse(JSON.stringify(s));
  // Geometry and profile records are immutable; clone mutable simulation state
  // explicitly so the route search does not repeatedly serialize the catalogue.
  const copyDefense=s=>({...s,player:{...s.player},events:s.events.map(e=>({...e})),hazards:s.hazards.slice(),
    received:s.received.slice(),contacts:s.contacts.slice(),hitIds:s.hitIds.slice()});
  // Preparation and one attempt per strike are engine rules, not just UI locks.
  const timing=E.profile({id:'retry-test',base_id:'test',class_id:'thumb',name:'Test',strikes:2});
  const retry=E.attack(timing,equal,17);
  assert.equal(E.attackFrame(retry).phase,'ready');assert.equal(E.hit(retry),null);assert.deepEqual(retry.attempts,[0,0]);
  E.attackStep(retry,1.01);assert.equal(E.attackFrame(retry).phase,'cue');assert.equal(E.hit(retry),null);
  E.attackStep(retry,.25);assert.equal(E.hit(retry),false);assert.equal(retry.results[0],false);assert.equal(E.hit(retry),null);
  assert.equal(retry.attempts[0],1,'rapid second press ignored');
  assert.equal(E.attackFrame(retry).attemptsLeft,0);
  while(E.attackFrame(retry).index===0){E.attackStep(retry,1/120);if(E.attackFrame(retry).index===0)assert.equal(E.hit(retry),null,'miss cannot be retried later');}
  assert.equal(retry.results[0],false,'earlier miss is preserved');
  while(!E.attackFrame(retry).canHit||Math.abs(E.attackFrame(retry).cursor-E.attackFrame(retry).center)>retry.d.zone/3)E.attackStep(retry,1/120);
  assert.equal(E.hit(retry),true);assert.equal(retry.attempts[1],1);assert(retry.hp<retry.initialHp,'immediate damage on the next strike');
  const hp=retry.hp;assert.equal(E.hit(retry),null);assert.equal(retry.hp,hp,'successful strike cannot damage twice');
  assert.deepEqual(E.attackResult(retry).mask,[false,true]);
  const doubleMiss=E.attack({...timing,strikes:1},equal,17);E.attackStep(doubleMiss,1.26);
  assert.equal(E.hit(doubleMiss),false);E.attackStep(doubleMiss,.23);assert.equal(E.hit(doubleMiss),null);
  assert.equal(doubleMiss.results[0],false);assert(doubleMiss.ended);assert.equal(E.hit(doubleMiss),null);
  const passes=E.attack({...timing,strikes:1,drift:false},equal,17);let last=null,crossings=0;
  while(!passes.ended){const f=E.attackFrame(passes);if(f.phase==='active'){const sign=Math.sign(f.cursor-f.center);if(last!==null&&sign!==last)crossings++;last=sign;}E.attackStep(passes,1/120);}
  assert.equal(crossings,2,'cursor crosses target outward and back');
  assert.deepEqual(Object.values(E.DAMAGE_TIERS).map(t=>E.damageValue(40,t.weight)),[4,12,24,40]);
  // Several projectiles of ONE native strike hurt independently, once per physical ID.
  const contact=E.defense({...timing,strikes:1},equal,17,{damageBase:40,hp:200});contact.events=[];
  contact.preparation=0;
  contact.hazards=Object.entries(E.DAMAGE_TIERS).map(([tier,t],i)=>({type:'circle',x:contact.player.x,y:contact.player.y,r:20,start:0,end:1,at:0,strike:0,id:'hit'+i,damageId:'hit'+i,rawDamage:E.damageValue(40,t.weight),tier,weight:t.weight}));contact.projectileCount=4;
  E.defenseStep(contact,1/120);assert.equal(contact.hp,120);assert.equal(contact.damage,80);assert.equal(contact.contacts.length,4);assert.deepEqual(contact.received,[0]);
  E.defenseStep(contact,.5);assert.equal(contact.hp,120,'lingering area cannot damage every tick');assert.equal(contact.contacts.length,4);
  const lethal=E.defense(timing,equal,17,{hp:10,preparation:0});lethal.events=[];lethal.hazards=copy(contact.hazards);E.defenseStep(lethal,1/120);
  assert.equal(lethal.hp,0);assert.equal(lethal.damage,10);assert(lethal.ended);assert.equal(lethal.contacts.length,2);
  const bolt=E.defense(timing,equal,1,{preparation:0});bolt.events=[];bolt.hazards=copy(contact.hazards.slice(2));bolt.hazards.forEach(h=>h.damageId='one-discharge');E.defenseStep(bolt,1/120);assert.equal(bolt.contacts.length,1);
  const ready=E.defense(timing,weak,17),spawn={...ready.player};E.defenseStep(ready,1,{x:1,y:1});
  assert.deepEqual(ready.player,spawn);assert.equal(ready.damage,0);assert.equal(ready.contacts.length,0);assert.equal(ready.hazards.length,0);
  assert.equal(ready.duration,7.8);E.defenseStep(ready,.2,{x:1});assert(ready.player.x>spawn.x);assert(ready.hazards.length>0);
  console.log('PASS preparation, unchanged cursor motion, one attempt per strike, immediate weighted damage and one collision per projectile');
  for(const p of profiles){
    families.set(p.kind,p);
    assert(E.FAMILIES[p.kind]);assert.deepEqual(p,E.profile(p.skill));
    for(const stats of [equal,weak,strong]){
      const s=E.attack(p,stats,17);let guard=0;
      while(!s.ended){assert(++guard<4000);const f=E.attackFrame(s);if(f.canHit&&Math.abs(f.cursor-f.center)<=f.width/2)E.hit(s);else E.attackStep(s,1/120);}
      assert.equal(E.attackResult(s).hits,p.strikes,'perfect timing is reachable '+p.skill.name);
      assert.equal(s.damage,s.damageBase,'all attack marks preserve full native damage '+p.skill.name);
      assert(Math.abs(E.attackWeights(p).reduce((a,b)=>a+b,0)-1)<1e-9);
      const missed=E.attack(p,stats,17);E.attackStep(missed,100);assert.equal(E.attackResult(missed).hits,0);
      const a=E.defense(p,stats,17),b=copyDefense(a);
      while(!a.ended)E.defenseStep(a,1/30,{x:1,y:0});
      while(!b.ended)E.defenseStep(b,1/120,{x:1,y:0});
      assert.deepEqual(E.defenseResult(a),E.defenseResult(b),'fixed-step outcome '+p.skill.name);
      assert(Math.abs(a.player.x-b.player.x)<1e-6);assert(Math.abs(a.player.y-b.player.y)<1e-6);
      assert(a.received.length<=p.strikes);assert.equal(new Set(a.received).size,a.received.length);
      assert.equal(new Set(a.contacts.map(c=>c.id)).size,a.contacts.length);assert.equal(a.damage,a.initialHp-a.hp);
      assert(a.player.x>=12&&a.player.x<=708&&a.player.y>=12&&a.player.y<=308);
    }
  }
  assert(families.size>=25,'distinct pattern families included');
  assert.equal(E.family({class_id:'middle',base_id:'lei_double_slash',name:'Двойной разрез'}),'slash');
  assert.equal(E.family({class_id:'priest',base_id:'arch_priest_paladin',name:'Карающий приговор'}),'impact');
  assert.equal(E.family({class_id:'priest',base_id:'arch_priest_paladin',name:'Последний приговор'}),'thrust');
  const signatures=profiles.map(p=>{
    const s=E.defense(p,equal,17);E.defenseStep(s,s.preparation+.2);
    return JSON.stringify({times:s.events.map(e=>e.at),hazards:s.hazards});
  });
  assert.equal(new Set(signatures).size,profiles.length,'each named profile has a distinct mechanical schedule');
  assert(E.difficulty(weak).warning<E.difficulty(strong).warning);
  assert(E.difficulty(weak).zone<E.difficulty(strong).zone);
  assert.equal(E.segmentDistance(0,0,10,10,0,10,10,0),0);
  assert(E.touches({type:'line',ax:0,ay:50,bx:720,by:50,r:2,start:0},{x:300,y:20},{x:300,y:80,r:6},1,.01),'swept blade collision');
  // Test-only beam search: existence of a zero-hit path, never served to players.
  const moves=[{x:0,y:0},...Array.from({length:8},(_,i)=>({x:Math.cos(i*Math.PI/4),y:Math.sin(i*Math.PI/4)}))];
  function danger(s){
    let risk=0;
    for(const h of s.hazards)if(h.start>s.time){
      // Route patterns require reaching a future safe circle, not just dodging
      // imminent lines. A centre-biased search otherwise prunes those paths.
      if(h.type==='safe_zone'&&h.start<s.time+1.5)risk+=Math.max(0,Math.hypot(s.player.x-h.x,s.player.y-h.y)-h.r+s.player.r)/Math.max(.1,h.start-s.time)/120;
      if(h.start<s.time+.5&&E.touches(h,s.player,s.player,h.start,0))risk+=1;
    }
    return risk+Math.hypot(s.player.x-360,s.player.y-160)/3000;
  }
  function possible(p,stats,seed,limit=22){
    const initial=E.defense(p,stats,seed);E.defenseStep(initial,initial.preparation);
    let frontier=[initial];
    // Boss patterns may last longer than the original 6.8-second laboratory.
    // Include an extra tick for floating-point boundaries at exactly duration.
    const steps=Math.ceil((initial.duration-initial.time)/.1)+2;
    for(let step=0;step<steps;step++){
      const cells=new Map();
      for(const s of frontier)for(const move of moves){
        const t=copyDefense(s);E.defenseStep(t,.1,move);if(t.received.length)continue;
        const cell=Math.round(t.player.x/20)+':'+Math.round(t.player.y/20);
        const score=danger(t),old=cells.get(cell);if(!old||score<old.score)cells.set(cell,{s:t,score});
      }
      if(!cells.size)return false;
      frontier=[...cells.values()].sort((a,b)=>a.score-b.score).slice(0,limit).map(v=>v.s);
      if(frontier.some(s=>s.ended))return true;
    }
    return frontier.some(s=>s.ended);
  }
  for(const [kind,p] of families){
    assert(possible(p,equal,17)||possible(p,equal,17,88),'reachable equal '+kind+' '+p.skill.name);
    assert(possible(p,weak,29)||possible(p,weak,29,88),'reachable weak '+kind+' '+p.skill.name);
    console.log('PASS reachable defense',kind);
  }
  console.log('PASS',profiles.length,'profiles;',families.size,'families; accuracy, weighted projectile damage, deterministic steps and reachable timing');
});
