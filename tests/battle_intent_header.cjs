const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('webapp/battle-client','utf8');
const start=source.indexOf('function mountBattleTimeline('),end=source.indexOf('function renderActions(',start);
let banners=[],timelines=0;
const context={near:'a',app:{querySelector:()=>({before:node=>banners.push(node)})},
 document:{createElement:()=>({setAttribute(){}})},window:{RaidTimeline:{mountSolo(field,q,sides,far){if(field){assert.equal(far,'b');assert.equal(sides[far].name,'Враг');timelines++;}}}}};
const mount=vm.runInNewContext('('+source.slice(start,end)+')',context);
const state={sides:{a:{name:'Игрок',controller_id:10},b:{name:'Враг',controller_id:0,
 skill_details:[{skill_id:'mana_blob',name:'Сгусток маны',description:'Описание'}]}},
 action_queue:{entries:[{actor:'b',skill:'mana_blob',at:2.5}]}};
mount(state);
assert.equal(banners.length,1);assert.match(banners[0].textContent,/Сгусток маны.*2\.50/);
assert.equal(banners[0].title,'Описание');assert.equal(timelines,1);
banners=[];state.sides.b.controller_id=20;mount(state);
assert.equal(banners.length,0,'never disclose a human opponent private skill');
state.sides.b.controller_id=0;state.finished=true;mount(state);
assert.equal(banners.length,0,'no obsolete intent after battle');
assert.equal(timelines,2,'no cast bar in a finished battle');
console.log('PASS solo enemy announcement, timing, PvP privacy and finished battle');
