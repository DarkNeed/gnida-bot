// Reachability smoke test using the actual simulator and its speed limits.
// This does not replace human difficulty testing or prove every random mix fair.
const E=require('../webapp/qte-unique/engine'),assert=require('node:assert/strict');
const stats={accuracy:100,enemyEvasion:0,enemyAccuracy:100,evasion:0};
const dirs=[{x:0,y:0},...Array.from({length:8},(_,i)=>({x:Math.cos(i*Math.PI/4),y:Math.sin(i*Math.PI/4)}))];
function run(id,seed,smart){
 const p=E.profile({id,base_id:id,name:id,class_id:'raid',damage_type:'physical',strikes:id.includes('cocytus_p2_4')?5:id.includes('sebas')&&id.endsWith('_4')?3:1});
 const s=E.defense(p,stats,seed,{hp:100000,damageBase:40,endOnDeath:false});
 s.player.x=360; // Native shared-defense entry point, including a single enemy.
 while(!s.ended){
  let input={x:0,y:0};
  if(smart&&s.time>=s.preparation){
   let best=Infinity;
   for(const dir of dirs){const n=structuredClone(s);E.defenseStep(n,.20,dir);let score=(n.contacts.length-s.contacts.length)*10000;
    // Respond to visible telegraphs, including the actual corridor collision.
    for(const h of n.hazards){if(h.disabled||h.start-n.time>1.0||h.end<n.time||n.hitIds.includes(h.damageId))continue;
     const t=Math.max(n.time,h.start+.01),g=E.geometry(h,t),point={...n.player};
     if(E.touches(h,point,point,t,1/120))score+=200/(.25+Math.max(0,h.start-n.time));
     if(h.type==='bullet'){const future=E.geometry(h,n.time+.30),dist=Math.hypot(future.x-point.x,future.y-point.y);score+=4/Math.max(4,dist);}
    }
    score+=.001*Math.hypot(n.player.x-360,n.player.y-160);
    if(score<best){best=score;input=dir;}
   }
  }
  E.defenseStep(s,.10,input);
 }
 return s.contacts.length;
}
let count=0,perfect=0;
for(const id of ['nz_gargantua_p1_0','nz_gargantua_p2_4','nz_cocytus_p1_2','nz_cocytus_p2_2','nz_cocytus_p1_4','nz_cocytus_p2_4','nz_aura_p1_1','nz_mare_p2_2','nz_mare_p2_4','nz_sebas_p1_0','nz_sebas_p1_2','nz_sebas_p2_0','nz_sebas_p2_2','nz_sebas_p2_4','nz_victim_p2_4']){
 const idle=run(id,42,false),dodges=[42,81,123].map(seed=>run(id,seed,true));
 console.log(id,'idle',idle,'moving',dodges.join('/'));count++;if(Math.min(...dodges)===0)perfect++;
 if(id==='nz_aura_p1_1'||id.startsWith('nz_sebas'))assert(idle>0,'stationary safe exploit: '+id);
 if(id==='nz_cocytus_p1_2'||id==='nz_mare_p2_2')assert(Math.min(...dodges)===0,'corridor must have a reachable path: '+id);
}
console.log('Checked',count,'patterns; zero-contact path found for',perfect,'using constrained movement.');
