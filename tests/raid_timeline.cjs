const assert=require('node:assert/strict'),T=require('../webapp/raid-timeline.js');
const q={round:1,time:0,phase:'choose',entries:[{actor:'p',at:2},{actor:'weak',at:3.5},{actor:'mage',at:3.5}]};
const before=T.model(q),during=T.model({...q,phase:'resolve'},2),released=T.model({...q,phase:'defense'},3.5);
assert(before.every(x=>x.position<1));assert(during.every((x,i)=>x.position>before[i].position));
assert(during[0].active);assert(!during[1].active);assert.equal(released[1].position,released[2].position);
assert(released[1].active&&released[2].active);assert.notEqual(released[1].lane,released[2].lane);
assert(released[0].done);assert.equal(T.model(q)[0].position,before[0].position);
assert(T.model(q,100).every(x=>x.position===1));assert(T.model(q,-10).every(x=>x.position===0));
console.log('PASS moving cast markers, simultaneous group, distinct lanes, completion and next-round reset');
