/* Service regeneration must not add an attack, sound, or replay delay. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const test=require('node:test');
const source=fs.readFileSync('webapp/battle-client','utf8').replace(/boot\(\);\s*$/,'');
function harness(){
 const stats={sounds:0,dom:0,delays:[],frames:[],played:[]};
 const app={addEventListener(){}};
 const context={window:{matchMedia:()=>({matches:true}),ArenaAudio:{
  actionStart(){stats.sounds++;},impact(){stats.sounds++;},effect(){stats.sounds++;},scene(){},refresh(){}
 }},document:{getElementById(id){stats.dom++;return id==='app'?app:null;},querySelector(){stats.dom++;return null;},addEventListener(){}},
 location:{search:'',pathname:'/',hostname:'example.test'},URLSearchParams,URL,console,
 setInterval(){},setTimeout(cb,ms){stats.delays.push(ms);cb();},clearTimeout(){},stats,structuredClone};
 vm.createContext(context);vm.runInContext(source+`
 globalThis.api={isResourceRegenEvent,animateEvent,raidAnimate,applyBattle,receiveRaid};
 `,context);
 stats.dom=0;
 return {stats,context,api:context.api,run:code=>vm.runInContext(code,context)};
}
const regen=(seq=1)=>({seq,round:1,actor:'10',target:'10',text:'Энергия: +8.',
 action_kind:'resource_regen',resource_regen:{'10':8},after:{'10':{resource:28,hp:100}}});
test('marked and legacy regeneration has no attack, sound, DOM work or delay',async()=>{
 const h=harness(),old={text:'Энергия: +8.',actor:'10',target:'10'};
 for(const event of [regen(),old]){
  assert.equal(h.api.isResourceRegenEvent(event),true);
  await h.api.animateEvent(event);await h.api.raidAnimate(event);
 }
 assert.equal(h.stats.sounds,0);assert.equal(h.stats.dom,0);assert.deepEqual(h.stats.delays,[]);
});
test('damage, poison, spells and mixed combat events are never hidden',()=>{
 const h=harness();
 for(const event of [{...regen(),damage:3},{...regen(),self_damage:3},
  {...regen(),bleed_damage:3},{...regen(),burn_damage:3},{...regen(),reaction_damage:3},
  {...regen(),follower_damage:3},{...regen(),skill:'mana_shot'},
  {...regen(),skill_id:'mana_focus'},{...regen(),damage_type:'magic'},
  {text:'Чума: −3 HP. Энергия: +8.',actor:'10',target:'10'},
  {...regen(),chaplain_event:'rewind'},{...regen(),nazarick_event:'phase'}]){
  assert.equal(h.api.isResourceRegenEvent(event),false,JSON.stringify(event));
 }
});
test('direct replay consumes regeneration sequence and keeps final resource/log',async()=>{
 const h=harness();
 h.context.next={token:'test',revision:2,status:'active',state:{finished:false,sides:{a:{resource:28}},log:[{...regen(),side:'a'}]}};
 h.run(`current={token:'test',revision:1,state:{sides:{a:{resource:20}},log:[]}};
 battleScreen=data=>{current=data;stats.frames.push(data)};`);
 await h.api.applyBattle(h.context.next);
 assert.equal(h.run('lastSeq'),1);assert.equal(h.run('current.state.sides.a.resource'),28);
 assert.equal(h.run('current.state.log.length'),1);assert.equal(h.stats.frames.length,1);
 assert.deepEqual(h.stats.delays,[]);assert.equal(h.stats.sounds,0);
});
function raidHarness(events,grouped=false){
 const h=harness();
 h.context.previous={token:'raid',status:'active',boss_id:'iron',data:{round:1,log:[],
  boss:{hp:100},players:{'10':{fighter:{name:'Player',hp:100,resource:20}}}}};
 h.context.next=structuredClone(h.context.previous);h.context.next.revision=1;
 h.context.next.data.players['10'].fighter.resource=28;h.context.next.data.log=events;
 if(grouped)h.context.window.RaidTimeline={eventGroups:events=>[events]};
 h.run(`raidCurrent=previous;
 raidScreen=data=>{raidCurrent=data;stats.frames.push(data)};
 raidVisual=data=>structuredClone(data);
 raidAnimate=async event=>{stats.played.push(event.seq)};`);
 return h;
}
test('regen-only raid update has no extra frame, animation or 300ms group pause',async()=>{
 const h=raidHarness([regen()]);await h.api.receiveRaid(h.context.next);
 assert.deepEqual(h.stats.played,[]);assert.deepEqual(h.stats.delays,[]);
 assert.equal(h.stats.frames.length,1);assert.equal(h.run('raidPlaying'),false);
 assert.equal(h.run("raidCurrent.data.players['10'].fighter.resource"),28);
 assert.equal(h.run('raidCurrent.data.log.length'),1);
});
test('simultaneous attack plus regen still animates the attack once',async()=>{
 const attack={...regen(1),action_kind:'skill',skill:'bum_punch',actor:'boss',target:'10',damage:3,text:'Hit'};
 const h=raidHarness([attack,regen(2)],true);await h.api.receiveRaid(h.context.next);
 assert.deepEqual(h.stats.played,[1]);assert.deepEqual(h.stats.delays,[50]); // reduced-motion attack pause only
 assert.equal(h.run('raidCurrent.data.log.length'),2);assert.equal(h.run('raidPlaying'),false);
});
