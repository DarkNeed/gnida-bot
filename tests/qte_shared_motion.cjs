const assert=require('node:assert/strict');
const C=require('../webapp/qte-combined.js');
const member=(id,scale)=>({version:2,kind:'defense',encounter_enemy:id,name:id,seed:11,
 profile:{id:'mana_blob:shot:1:magic',base_id:'mana_blob',name:'shot',class_id:'mage',strikes:1,damage_type:'magic',tags:[]},
 strikes:1,damage_base:40,defense_preparation:1,stats:{accuracy:95,enemyEvasion:0,enemyAccuracy:95,evasion:0,controlScale:scale}});
const stage={version:4,kind:'defense',defense_mode:'dodge',shared_motion:2,duration:7.8,target_hp:1000,
 incoming_factor:.9,members:[member('e1',1),member('e2',.5)]};
const s=C.create(stage);
// Isolate the movement/collision boundary, with different movement modifiers
// and a field belonging to a secondary source. All sources must see the marker.
for(const state of s.states){state.time=1;state.events=[];}
s.time=1;
s.states[1].hazards=[{type:'well',x:420,y:160,r:8,pull:70,start:1,end:3,at:1,
 disabled:false,damageId:'pull',strike:0,weight:.2,tier:'minor',rawDamage:8}];
for(let i=0;i<100;i++){
 C.step(s,{x:0,y:1});
 for(const state of s.states){assert.equal(state.player.x,s.player.x);assert.equal(state.player.y,s.player.y);}
}
assert(s.player.x>360,'secondary-source gravity must move the displayed marker');
assert(s.player.y<280,'use one conservative control speed, not whichever source is first');
// A genuine clean field must have neither contacts nor predicted damage.
const clean=C.create(stage);clean.states.forEach(v=>v.events=[]);
for(let i=0;i<936;i++)C.step(clean,{x:1,y:0});
assert.equal(clean.contacts.length,0);assert.equal(clean.damage,0);
const tiny=C.create({...stage,members:stage.members.map(m=>({...m,damage_base:1}))});
tiny.states.forEach(v=>v.events=[]);
tiny.states[0].contacts.push({id:'tiny',strike:0,weight:.001,time:0,tier:'minor'});
C.step(tiny,{});assert.equal(tiny.damage,1,'a real low-damage collision must not be previewed as zero');
console.log('PASS shared position, secondary gravity, movement modifiers and clean dodge');
