const E=require('../webapp/qte-lab/engine');
const safePath=require('./qte_lab_path.cjs');
const config=JSON.parse(process.argv[2]);
if(config.version===2){process.stdout.write(JSON.stringify(require('./qte_patterns_trace.cjs')(config)));}
else if(config.kind==='attack'){
  const n=config.strikes,slot=n>1?.95:2.8,s=E.attack({spec:{hits:n,slot,damage:0},stats:config.stats,seed:config.seed});
  const proof={ticks:0,clicks:[]};
  for(let tick=0;tick<=Math.ceil(s.duration*120);tick++){
    E.attackStep(s,Math.min(s.duration,tick/120)-s.time);
    const f=E.attackFrame(s);
    if(s.results[f.index]===null&&Math.abs(f.cursor-f.center)<f.width/3){E.hit(s);proof.clicks.push(tick);}
    if(s.ended){proof.ticks=tick;break;}
  }
  process.stdout.write(JSON.stringify({proof,result:s.results}));
}else{
  const s=E.defense({pattern:config.pattern,stats:config.stats,seed:config.seed});
  const proof={ticks:720,inputs:[]};let route;
  if(config.perfect)route=safePath(s);
  if(config.perfect&&!route)throw new Error('No safe path');
  let last='';
  for(let tick=0;tick<720;tick++){
    const point=route?.[Math.min(route.length-1,Math.floor(tick/2))];
    const cmd=point?{target:[point.x,point.y]}:{x:tick<240?-1:tick<480?1:0,y:tick<240?0:tick<480?1:-1};
    const encoded=JSON.stringify(cmd);
    if(encoded!==last){proof.inputs.push({t:tick,...cmd});last=encoded;}
    E.defenseStep(s,1/120,point?{target:point}:cmd);
  }
  const n=config.strikes,visual=s.pattern.hits;
  const result=Array.from({length:n},(_,i)=>!s.received.some(j=>Math.min(n-1,Math.floor(j*n/visual))===i));
  process.stdout.write(JSON.stringify({proof,result}));
}
