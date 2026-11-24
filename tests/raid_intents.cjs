const assert=require('node:assert/strict'),I=require('../webapp/raid-intents.js');
const player=(hp=100,withdrawn=false)=>({fighter:{hp},withdrawn});
assert.equal(I.showLines({data:{players:{a:player()},boss:{hp:100}}}),false,'solo boss');
assert.equal(I.showLines({players:{a:player()},enemies:{e:{hp:100}}}),false,'solo encounter');
assert.equal(I.showLines({players:{a:player(),b:player()},enemies:{e:{hp:100}}}),true,'party vs boss');
assert.equal(I.showLines({players:{a:player()},enemies:{e:{hp:100},f:{hp:100}}}),false,'solo vs two');
assert.equal(I.showLines({players:{a:player(),b:player(0),c:player(100,true)},enemies:{e:{hp:100},f:{hp:100}}}),false,'remaining 1 vs 2');
assert.equal(I.showLines({players:{a:player(0)},enemies:{e:{hp:100}}}),false,'defeated party');
let timeline=0,svg=0;global.document={getElementById:()=>null,createElementNS(){svg++;throw Error('Solo must not create intent SVG');}};
global.window={RaidTimeline:{mount(){timeline++;}}};global.ResizeObserver=class{constructor(){throw Error('No resize observer for hidden lines');}};
I.mount({classList:{toggle(){}},append(){throw Error('No intent overlay in 1 vs 2');}},
 {status:'active',data:{players:{a:player()},enemies:{e:{hp:100},f:{hp:100}},action_queue:{}}},()=>{});
assert.equal(svg,0);assert.equal(timeline,1,'hide lines, not the cast timeline');
console.log('PASS intent lines hidden for any solo fighter, retained in group fights, defeated/withdrawn excluded');
