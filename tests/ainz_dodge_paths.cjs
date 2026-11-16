// Reachability smoke test, not a proof for every seed or party combination.
const E=require('../webapp/qte-unique/engine'),assert=require('node:assert/strict');
const dirs=[{x:0,y:0},...Array.from({length:16},(_,i)=>({x:Math.cos(i*Math.PI/8),y:Math.sin(i*Math.PI/8)}))];
function run(id,seed,smart){
 const p=E.profile({id,base_id:id,name:id,class_id:'raid',damage_type:'physical',strikes:1});
 const s=E.defense(p,{accuracy:100,enemyEvasion:0,enemyAccuracy:100,evasion:0},seed,{hp:100000,damageBase:40,endOnDeath:false});s.player.x=360;
 while(!s.ended){
  let input={x:0,y:0};
  if(smart&&s.time>=s.preparation){let best=Infinity;
   for(const dir of dirs){const n=structuredClone(s);E.defenseStep(n,.30,dir);let score=(n.contacts.length-s.contacts.length)*10000;
    for(const h of n.hazards){if(h.disabled||h.visualOnly||h.start-n.time>1.4||h.end<n.time||n.hitIds.includes(h.damageId))continue;
     const t=Math.max(n.time,h.start+.01),point={...n.player};
     if(E.touches(h,point,point,t,1/120))score+=200/(.25+Math.max(0,h.start-n.time));
     if(h.type==='safe_zone'){const g=E.geometry(h,t);score+=Math.max(0,Math.hypot(g.x-point.x,g.y-point.y)-g.r+point.r)*4/(.3+Math.max(0,h.start-n.time));}
     for(const ahead of[.2,.45,.75]){const future=n.time+ahead;if(future<h.start||future>h.end)continue;
      const q={...point,x:Math.max(12,Math.min(708,point.x+dir.x*n.d.moveSpeed*ahead)),y:Math.max(12,Math.min(308,point.y+dir.y*n.d.moveSpeed*ahead))};
      if(E.touches(h,point,q,future,1/120))score+=80/(.3+ahead);
     }
     if(h.type==='bullet'){const g=E.geometry(h,n.time+.30);score+=4/Math.max(4,Math.hypot(g.x-point.x,g.y-point.y));}
    }
    score+=.001*Math.hypot(n.player.x-360,n.player.y-160);if(score<best){best=score;input=dir;}
   }
  }E.defenseStep(s,.10,input);
 }return s.contacts.length;
}
function recordedRoute(id){
 const f=require('./fixtures/ainz-harvest-route.json');if(id!==f.challenge.profile.base_id)return false;
 const c=f.challenge,s=E.defense(E.profile(c.profile),c.stats,c.seed,{hp:100000,endOnDeath:false,preparation:c.defense_preparation});Object.assign(s.player,c.initial_player);
 let index=0,input={};for(let tick=0;tick<f.proof.ticks;tick++){if(f.proof.inputs[index]?.t===tick)input=f.proof.inputs[index++];E.defenseStep(s,1/120,input);}
 console.log(id,'beam-search recorded route',s.contacts.length);return s.contacts.length===0;
}
let count=0,failures=[];
for(const [phase,moves]of [[1,[0,1,3]],[2,[0,1,2,3]],[3,[0,1,2,3]],[4,[0,1,2,3]],[5,[0,1,2,3]],[6,[0,1,2,3]]])for(const move of moves){
 const id=`nz_ainz6_p${phase}_${move}`;if(process.env.AINZ_PATTERN&&process.env.AINZ_PATTERN!==id)continue;
 const idle=run(id,42,false),moving=[42,81,123].map(seed=>run(id,seed,true));
 console.log(id,'idle',idle,'moving',moving.join('/'));
 assert(idle>0,'stationary safe exploit: '+id);
 if(Math.min(...moving)!==0&&!recordedRoute(id))failures.push(id);count++;
}
assert.deepEqual(failures,[],'no sampled zero-contact path');
console.log(`PASS ${count} patterns: sampled zero-contact paths, no stationary safe exploit.`);
