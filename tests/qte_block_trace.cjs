const B=require('../webapp/qte-block/engine');
let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>raw+=s);process.stdin.on('end',()=>{
  const result=JSON.parse(raw).map(c=>{
    const s=B.create(c.profile,c.stats,c.seed,{hp:1000000,referenceDamage:40,endOnDeath:false,enabledStrikes:c.enabled_strikes});
    const proof={ticks:1140,inputs:[]};let encoded='';
    for(let tick=0;tick<1140;tick++){
      const next=s.events.find(e=>!e.resolved&&(!s.enabledStrikes||s.enabledStrikes[e.strike]));
      const angle=c.policy==='hold'?0:c.policy==='react'&&next?next.angle:Math.sin(tick/25)*Math.PI;
      const cmd={angle:B.angleDiff(angle,0),active:c.policy==='hold'||c.policy==='react'&&next?s.time>=next?.at-.1:c.policy==='sweep'&&tick%90<55};
      // Hold mode really holds from the start, rather than following a cue.
      if(c.policy==='hold')cmd.active=true;
      if(c.policy==='careful'){
        const visible=next&&s.time>=next.at-next.warning;
        cmd.angle=B.angleDiff(visible?next.angle:s.angle,0);
        cmd.active=!!(visible&&next.kind!=='feint'&&s.time>=next.at-.1);
      }
      cmd.active=!!cmd.active;const value=JSON.stringify(cmd);
      if(value!==encoded){proof.inputs.push({t:tick,...cmd});encoded=value;}
      B.step(s,1/120,cmd);
    }
    const contacts=s.contacts.map(c=>({id:c.id,strike:c.strike,tier:c.tier,weight:s.events.find(e=>e.id===c.id).weight*(1-c.reduction),reduction:c.reduction,blocked:c.reduction>0,outcome:c.outcome,tick:Math.round(c.time*120)}));
    return {proof,result:{mode:'block',mask:Array.from({length:s.p.strikes},(_,i)=>!contacts.some(c=>c.strike===i&&c.weight>0)),contacts}};
  });process.stdout.write(JSON.stringify(result));
});
