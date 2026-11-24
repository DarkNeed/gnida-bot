const assert=require('node:assert/strict'),T=require('../webapp/raid-timeline.js');
const queue={version:3,round:1,time:0,phase:'choose',entries:[
 {actor:'weak',started:-1,at:1,duration:2,skill:'stab'},
 {actor:'mage',started:-.5,at:2.5,duration:3,skill:'spell'},
]};
const weak=T.model(queue,'weak'),mage=T.model(queue,'mage');
assert.equal(weak.progress,.5);
assert.equal(mage.remaining,2.5);
assert.equal(T.model({...queue,time:.5},'weak').progress,.75);
assert.deepEqual(T.predict(weak,0,.5),{outcome:'before',end:.75});
assert.deepEqual(T.predict(weak,0,1),{outcome:'together',end:1});
assert.deepEqual(T.predict(weak,0,1.5),{outcome:'after',end:1});
assert.equal(T.predict(mage,0,1.5).outcome,'before');
assert.equal(T.model({...queue,phase:'defense',time:1.2,entries:[{...weak,resolving:true},mage]},'weak').progress,1);
assert.equal(T.model({...queue,time:1.2},'weak'),null,'old cast is not shown after release');
assert.equal(T.model({...queue,entries:[{actor:'weak',started:0,at:2,duration:2}]},'weak').progress,0);
assert.deepEqual(T.model(queue,'weak'),weak,'progress is a pure function of server time');
const e=(round,cast_at,extra={})=>({round,cast_at,...extra});
assert.deepEqual(T.eventGroups([e(1,2),e(1,3),e(1,3),e(2,3),e(2,3,{chaplain_event:'rewind'}),e(2,3),e(2,undefined)]).map(g=>g.length),[1,2,1,1,1,1]);
console.log('PASS per-enemy progress, projected action order, exact ties and cast reset');
