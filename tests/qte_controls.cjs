const assert=require('node:assert/strict');
const T=require('../webapp/qte-input');
const E=require('../webapp/qte-lab/engine');
const rect={width:360,height:160};
const origin=T.relativeStart({x:900,y:600},{x:230,y:160});
assert.deepEqual(T.relativeTarget(origin,{x:900,y:600},rect),[230,160]);
assert.deepEqual(T.relativeTarget(origin,{x:920,y:590},rect),[270,140]);
assert.deepEqual(T.relativeTarget(origin,{x:-900,y:9000},rect),[0,320]);
assert.deepEqual(T.stickVector(1,1,40),{x:0,y:0});
assert.deepEqual(T.stickVector(100,0,40),{x:1,y:0});
const diagonal=T.stickVector(100,-100,40);assert(Math.abs(diagonal.x+diagonal.y)<.001);
const partial=T.stickVector(20,0,40);assert(partial.x>0&&partial.x<1);
const stats={accuracy:75,evasion:25,enemyAccuracy:95,enemyEvasion:25};
const result=[];
for(const pattern of ['cross','slashes','rain']){
  const s=E.defense({pattern,stats,seed:23}),inputs=[
    {t:0,target:[s.player.x,s.player.y]},
    {t:12,target:[450,160]},
    {t:60,x:0,y:0},
    {t:90,...diagonal},
    {t:150,...partial},
    {t:210,x:0,y:0},
  ];
  let index=0;
  for(let tick=0;tick<720;tick++){
    while(index+1<inputs.length&&inputs[index+1].t<=tick)index++;
    const command=inputs[index],before={...s.player};
    E.defenseStep(s,1/120,command.target?{target:{x:command.target[0],y:command.target[1]}}:command);
    assert(Math.hypot(s.player.x-before.x,s.player.y-before.y)<=240/120+1e-8,'same movement speed cap');
  }
  result.push({challenge:{kind:'defense',pattern,strikes:E.PATTERNS[pattern].hits,stats,seed:23},proof:{ticks:720,inputs},mask:Array.from({length:s.pattern.hits},(_,i)=>!s.received.includes(i))});
}
process.stdout.write(JSON.stringify(result));
