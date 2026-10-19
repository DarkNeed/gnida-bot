const E=require('../webapp/qte-unique/engine');
const clone=s=>({...s,player:{...s.player},events:s.events.map(e=>({...e})),hazards:s.hazards.slice(),received:s.received.slice(),contacts:s.contacts.slice(),hitIds:s.hitIds.slice()});
function safeRoute(initial,limit=28){
  const moves=[{x:0,y:0},...Array.from({length:8},(_,i)=>({x:Math.cos(i*Math.PI/4),y:Math.sin(i*Math.PI/4)}))];
  const start=clone(initial);E.defenseStep(start,start.preparation||0);
  let frontier=[{s:start,route:[]}];
  for(let step=0;step<68;step++){
    const cells=new Map();
    for(const f of frontier)for(const move of moves){
      const s=clone(f.s);E.defenseStep(s,.1,move);if(s.contacts.length)continue;
      let score=Math.hypot(s.player.x-360,s.player.y-160)/3000;
      for(const h of s.hazards)if(h.start>s.time&&h.start<s.time+.5&&E.touches(h,s.player,s.player,h.start,0))score++;
      const cell=Math.round(s.player.x/20)+':'+Math.round(s.player.y/20),old=cells.get(cell);
      if(!old||score<old.score)cells.set(cell,{s,score,route:[...f.route,move]});
    }
    if(!cells.size)return null;
    frontier=[...cells.values()].sort((a,b)=>a.score-b.score).slice(0,limit);
  }
  return frontier[0]?.route;
}
function record(c){
  const p=E.profile(c.profile),s=(c.kind==='attack'?E.attack:E.defense)(p,c.stats,c.seed,{damageBase:0,hp:1000000,endOnDeath:false,enabledStrikes:c.enabled_strikes,preparation:c.defense_preparation??0});
  if(c.kind==='attack'){
    const proof={ticks:0,clicks:[]};let retry=false;
    for(let tick=0;tick<=Math.ceil(s.duration*120);tick++){
      E.attackStep(s,Math.min(s.duration,tick/120)-s.time);const f=E.attackFrame(s);
      const miss=c.retry&&!retry&&f.canHit&&Math.abs(f.cursor-f.center)>f.width;
      if(f.canHit&&(miss||Math.abs(f.cursor-f.center)<f.width/3)){
        E.hit(s);proof.clicks.push(tick);if(miss)retry=true;
      }
      if(s.ended){proof.ticks=tick;break;}
    }
    const mask=s.results.map(Boolean);
    return {proof,result:{mask,weights:mask.map((v,i)=>v?E.impact(p,i).weight:0)}};
  }
  let route;if(c.perfect){route=safeRoute(s)||safeRoute(s,110);if(!route)throw new Error('No safe route '+p.skill.name);}
  const proof={ticks:Math.round(s.duration*120),inputs:[]},readyTicks=Math.round(s.preparation*120);let last='';
  for(let tick=0;tick<proof.ticks;tick++){
    const active=tick-readyTicks,move=active<0?{x:0,y:0}:route?.[Math.min(route.length-1,Math.floor(active/12))];
    const cmd=move||{x:active<240?-1:active<480?1:0,y:active<240?0:active<480?1:-1};
    const value=JSON.stringify(cmd);if(value!==last){proof.inputs.push({t:tick,...cmd});last=value;}
    E.defenseStep(s,1/120,cmd);
  }
  return {proof,result:{mask:Array.from({length:p.strikes},(_,i)=>!s.contacts.some(c=>c.strike===i)),contacts:s.contacts.map(c=>({id:c.id,strike:c.strike,weight:c.weight,tier:c.tier,tick:Math.round(c.time*120)}))}};
}
module.exports=record;
if(require.main===module){
  if(process.argv[2])process.stdout.write(JSON.stringify(record(JSON.parse(process.argv[2]))));
  else{let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(input).map(record))));}
}
