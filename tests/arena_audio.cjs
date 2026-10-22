// node --test tests/arena_audio.cjs (no browser or external packages required)
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname,'../webapp/arena-audio'),'utf8');
function harness({saved=null,storageFails=false,available=true,rejected=false,room=true,silent=false}={}) {
  const handlers={},windowHandlers={},intervals=new Map(),contexts=[],sources=[],ramps=[],nodes=[],delays=[],timeouts=[];
  const sceneLabel={textContent:''};
  let serial=0,stored=saved;
  class Param {
    constructor(){this.value=0;this.events=[];}
    setValueAtTime(v,t){this.value=v;this.events.push(['set',v,t]);}
    linearRampToValueAtTime(v,t){this.value=v;ramps.push([v,t]);this.events.push(['linear',v,t]);}
    exponentialRampToValueAtTime(v,t){this.value=v;this.events.push(['exponential',v,t]);}
    cancelScheduledValues(){}
  }
  class Node {
    constructor(){this.gain=new Param();this.frequency=new Param();this.detune=new Param();this.Q=new Param();this.connections=[];nodes.push(this);}
    connect(n){this.connections.push(n);return n;}
    disconnect(){this.connections=[];}
  }
  class Source extends Node {
    constructor(){super();sources.push(this);}
    start(t){this.started=t;}
    stop(t){this.stopped=t??0;if(t===undefined)this.onended?.();}
  }
  class Context {
    constructor(){this.currentTime=0;this.sampleRate=100;this.state='suspended';this.destination=new Node();contexts.push(this);if(!room)this.createDelay=undefined;}
    createGain(){return new Node();}
    createDynamicsCompressor(){const n=new Node();for(const k of ['threshold','knee','ratio'])n[k]=new Param();return n;}
    createBiquadFilter(){return new Node();}
    createDelay(){const n=new Node();n.delayTime=new Param();delays.push(n);return n;}
    createOscillator(){return new Source();}
    createBufferSource(){return new Source();}
    createBuffer(){return {getChannelData:()=>new Float32Array(100)};}
    async resume(){if(rejected)throw new Error('autoplay');this.state='running';}
    async suspend(){this.state='suspended';}
  }
  const opener={disabled:false,attributes:{},setAttribute(k,v){this.attributes[k]=v;}};
  const document={hidden:false,currentScript:{dataset:{audioSilent:String(silent)}},querySelectorAll:()=>[opener],querySelector:()=>null,getElementById:id=>id==='audio-scene'?sceneLabel:null,addEventListener:(k,f)=>handlers[k]=f};
  const window={addEventListener:(k,f)=>windowHandlers[k]=f};
  if(available)window.AudioContext=Context;
  const sandbox={window,document,localStorage:{getItem(){if(storageFails)throw Error('denied');return stored;},setItem(k,v){if(storageFails)throw Error('denied');stored=v;}},setInterval(f){const id=++serial;intervals.set(id,f);return id;},clearInterval(id){intervals.delete(id);},setTimeout(f){timeouts.push(f);},console};
  vm.runInNewContext(code,sandbox);
  const button=attrs=>({disabled:false,dataset:{audioTest:attrs['data-audio-test']},hasAttribute:k=>k in attrs});
  const click=async attrs=>{const b=button(attrs);await handlers.click({target:{closest:()=>b}});};
  return {audio:window.ArenaAudio,document,handlers,windowHandlers,contexts,sources,intervals,ramps,nodes,delays,timeouts,sceneLabel,opener,click,get stored(){return stored;}};
}

test('side-by-side demo keeps spectator silent without muting player or saving preferences',async()=>{
  const saved=JSON.stringify({muted:false,music:22,effects:50});
  const player=harness({saved}),watcher=harness({saved,silent:true});
  player.audio.scene('battle');watcher.audio.scene('battle');
  await player.click({});
  for(const attrs of [{},{'data-audio-toggle':''},{'data-audio-test':'hit'}])await watcher.click(attrs);
  watcher.audio.effect('hit');watcher.audio.actionStart({damage_type:'magic'});
  watcher.audio.impact({damage:30,hit:true});
  watcher.windowHandlers.pageshow();watcher.handlers.visibilitychange();
  watcher.handlers.input({target:{dataset:{audioVolume:'music'},value:'0'}});
  watcher.audio.refresh();
  assert.equal(watcher.contexts.length,0);assert.equal(watcher.sources.length,0);assert.equal(watcher.intervals.size,0);
  assert.equal(watcher.stored,saved);
  assert.equal(watcher.opener.disabled,true);
  assert.match(watcher.opener.attributes['aria-label'],/окне игрока/);
  assert.equal(player.contexts.length,1);assert.equal(player.intervals.size,1);
  assert.equal(player.opener.disabled,false);assert.ok(player.sources.length>0);
});
test('fresh and corrupt preferences default to enabled after first gesture',async()=>{
  for(const saved of [null,'broken json']){
    const h=harness({saved});h.audio.scene('battle');h.audio.effect('hit');
    assert.equal(h.contexts.length,0);assert.equal(h.sources.length,0);assert.equal(h.intervals.size,0);
    await h.click({});assert.equal(h.contexts.length,1);assert.equal(h.intervals.size,1);
    assert.ok(h.sources.length>0);
  }
});
test('saved mute is respected on load, gestures and returning to page',async()=>{
  const h=harness({saved:JSON.stringify({muted:true,music:22,effects:50})});
  h.audio.scene('battle');await h.click({});h.windowHandlers.pageshow();
  h.handlers.visibilitychange();h.audio.effect('hit');
  assert.equal(h.contexts.length,0);assert.equal(h.sources.length,0);assert.equal(h.intervals.size,0);
});
test('explicit gesture enables once; scene refresh never layers loops',async()=>{
  const h=harness({saved:JSON.stringify({muted:true})});await h.click({'data-audio-toggle':''});
  assert.equal(h.contexts.length,1);assert.equal(h.intervals.size,1);
  assert.equal(JSON.parse(h.stored).muted,false);
  for(let i=0;i<30;i++)h.audio.scene('menu');
  assert.equal(h.intervals.size,1);
  const count=h.sources.length;h.audio.scene('doofenshmirtz');
  assert.equal(h.intervals.size,1);assert.ok(h.sources.length>count);
  h.audio.scene('');assert.equal(h.intervals.size,0);
});
test('mute stops all voices immediately and blocks future effects',async()=>{
  const h=harness();await h.click({});h.audio.effect('victory');
  await h.click({'data-audio-toggle':''});
  assert.equal(h.intervals.size,0);assert.ok(h.sources.every(s=>s.stopped===0));
  const count=h.sources.length;h.audio.effect('hit');assert.equal(h.sources.length,count);
});
test('hidden page suspends context, stops loops and effects; visible resumes',async()=>{
  const h=harness();await h.click({});
  h.document.hidden=true;h.handlers.visibilitychange();
  assert.equal(h.contexts[0].state,'suspended');assert.equal(h.intervals.size,0);
  const count=h.sources.length;h.audio.effect('hit');assert.equal(h.sources.length,count);
  h.document.hidden=false;h.handlers.visibilitychange();await new Promise(setImmediate);
  assert.equal(h.intervals.size,1);
  h.windowHandlers.pagehide();assert.equal(h.intervals.size,0);
});
test('music and effects can be zero independently and preferences clamp',async()=>{
  const h=harness({saved:JSON.stringify({muted:false,music:0,effects:500})});
  await h.click({});assert.equal(h.intervals.size,0);
  const count=h.sources.length;h.audio.effect('hit');assert.ok(h.sources.length>count);
  const silent=harness({saved:JSON.stringify({muted:false,music:80,effects:0})});
  await silent.click({});assert.equal(silent.intervals.size,1);
  const before=silent.sources.length;silent.audio.effect('hit');assert.equal(silent.sources.length,before);
});
test('unavailable Web Audio, rejected autoplay and denied storage never throw',async()=>{
  for(const options of [{available:false},{storageFails:true},{rejected:true},{saved:'broken json'}]){
    const h=harness(options);await h.click({'data-audio-test':'heal'});
    assert.doesNotThrow(()=>h.audio.scene('battle'));
    assert.doesNotThrow(()=>h.audio.effect('critical'));
    assert.ok(h.contexts.length<=1);
  }
});
test('effects and action dispatch produce scheduled, bounded envelopes',async()=>{
  const h=harness();await h.click({});h.audio.scene('');
  for(const name of ['click','cast','hit','critical','miss','heal','buff','victory','defeat']){
    const n=h.sources.length;h.audio.effect(name);assert.ok(h.sources.length>n,name);
  }
  let n=h.sources.length;h.audio.actionStart({damage_type:'physical'});assert.equal(h.sources.length,n);
  h.audio.actionStart({damage_type:'magic'});assert.ok(h.sources.length>n);
  n=h.sources.length;h.audio.impact({side:'a',before:{a:{hp:10}},after:{a:{hp:20}},damage:0});assert.equal(h.sources.length-n,4);
  n=h.sources.length;h.audio.impact({hit:false,skill:'spell'});assert.equal(h.sources.length-n,2);
  assert.ok(h.sources.every(s=>s.stopped>s.started&&s.stopped-s.started<7));
  assert.ok(h.ramps.every(([value])=>value>=0&&value<=1));
});
test('combat arrangement has detuned brass, driving percussion and varied bars',async()=>{
  const h=harness();await h.click({});h.audio.scene('');
  const base=h.sources.length;h.audio.scene('battle');
  const combat=h.sources.slice(base);
  assert.ok(combat.some(s=>s.type==='sawtooth'&&s.detune.value===8));
  assert.ok(combat.some(s=>s.type==='sawtooth'&&s.detune.value===-8));
  assert.ok(combat.filter(s=>s.buffer).length>=2);
  assert.ok(combat.length>=15);
  // Scheduler never catches up an offline gap with a burst of old notes.
  let count=h.sources.length;h.contexts[0].currentTime=1000;
  for(const fn of h.intervals.values())fn();
  assert.ok(h.sources.length-count<40);
  h.audio.scene('');count=h.sources.length;h.audio.effect('hit');const hit=h.sources.length-count;
  count=h.sources.length;h.audio.effect('critical');assert.ok(h.sources.length-count>hit);
});
test('all themes work and interrupted enable cannot restart after mute',async()=>{
  const h=harness();await h.click({});
  for(const theme of ['menu','battle','raid','lei_heng','doofenshmirtz','kit_menace','kit_abyss']){
    h.audio.scene(theme);assert.equal(h.intervals.size,1);
    h.contexts[0].currentTime+=10;for(const fn of h.intervals.values())fn();
  }
  h.audio.scene('');
  const race=harness({saved:JSON.stringify({muted:true})});const enable=race.click({'data-audio-toggle':''});
  await race.click({'data-audio-toggle':''});await enable;
  assert.equal(race.intervals.size,0);
});

test('Kit menace has low martial pulse; abyss replaces melody with long formant drones',async()=>{
  const h=harness();await h.click({});h.audio.scene('');
  let start=h.sources.length;h.audio.scene('kit_menace');
  const menace=h.sources.slice(start);
  assert.ok(menace.some(s=>s.type==='sawtooth'&&s.frequency.value<100));
  assert.ok(menace.some(s=>s.buffer&&s.connections[0].frequency.value===260));
  assert.match(h.sceneLabel.textContent,/II фаза/);
  start=h.sources.length;h.audio.scene('kit_abyss');
  const abyss=h.sources.slice(start),choir=abyss.filter(s=>s.type==='sawtooth'&&s.connections[0].Q.value===3.5);
  assert.equal(choir.length,6);
  assert.ok(choir.every(s=>s.stopped-s.started>4));
  assert.ok(abyss.some(s=>s.buffer&&s.loop===true));
  assert.ok(abyss.some(s=>s.type==='sine'&&s.stopped-s.started>5));
  assert.ok(choir.every(s=>s.connections[0].connections[0].gain.events.some(([kind,,time])=>kind==='linear'&&time-s.started>.5)));
  assert.match(h.sceneLabel.textContent,/III фаза/);
  assert.ok(h.delays.some(d=>d.delayTime.value===.73));
  assert.ok(h.sources.every(s=>s.stopped-s.started<7));
  assert.ok(abyss.filter(s=>s.type).every(s=>s.frequency.value>=20&&s.frequency.value<2000));
});

test('Kit phase polling does not reset loops, fades scenes, and disposes echo graphs',async()=>{
  const h=harness();await h.click({});h.audio.scene('kit_menace');
  const count=h.sources.length,delays=h.delays.length;
  for(let i=0;i<100;i++)h.audio.scene('kit_menace');
  assert.equal(h.sources.length,count);assert.equal(h.delays.length,delays);assert.equal(h.intervals.size,1);
  const old=h.delays.slice();h.audio.scene('kit_abyss');
  assert.equal(h.intervals.size,1);assert.ok(h.sources.length>count);
  assert.ok(h.ramps.some(([,time])=>time===.8));
  for(const cleanup of h.timeouts.splice(0))cleanup();
  assert.ok(old.every(d=>d.connections.length===0));
  assert.ok(h.delays.slice(delays).every(d=>d.connections.length>0));
  await h.click({'data-audio-toggle':''});
  assert.equal(h.intervals.size,0);
  assert.ok(h.sources.every(s=>s.stopped===0));
  assert.ok(h.delays.every(d=>d.connections.length===0));
});

test('Kit ambience respects saved mute, independent music volume and old audio APIs',async()=>{
  for(const theme of ['kit_menace','kit_abyss']){
    const muted=harness({saved:JSON.stringify({muted:true})});muted.audio.scene(theme);await muted.click({});
    assert.equal(muted.contexts.length,0);
    const noMusic=harness({saved:JSON.stringify({music:0})});noMusic.audio.scene(theme);await noMusic.click({});
    assert.equal(noMusic.intervals.size,0);assert.equal(noMusic.delays.length,0);
    const fallback=harness({room:false});fallback.audio.scene(theme);await fallback.click({});
    assert.equal(fallback.intervals.size,1);assert.ok(fallback.sources.length>0);
    fallback.document.hidden=true;fallback.handlers.visibilitychange();
    assert.equal(fallback.intervals.size,0);assert.ok(fallback.sources.every(s=>s.stopped===0));
  }
});

test('Kit arrangements schedule complete evolving bars with bounded active voices',async()=>{
  for(const theme of ['kit_menace','kit_abyss']){
    const h=harness();h.audio.scene(theme);await h.click({});
    let peak=0;
    for(let i=1;i<=240;i++){
      h.contexts[0].currentTime=i/10;
      for(const fn of h.intervals.values())fn();
      for(const s of h.sources)if(!s.ended&&s.stopped<=i/10){s.ended=true;s.onended?.();}
      peak=Math.max(peak,h.sources.filter(s=>!s.ended).length);
      assert.equal(h.intervals.size,1);
    }
    assert.ok(peak<80,theme+' active voices: '+peak);
    assert.ok(h.sources.filter(s=>s.type).every(s=>Number.isFinite(s.frequency.value)&&s.frequency.value>=20));
    assert.ok(h.sources.every(s=>Number.isFinite(s.started)&&s.stopped>s.started));
  }
});

const chaplainThemes=['chaplain','chaplain_fault','chaplain_override','chaplain_root'];
test('Chaplain has four original evolving organ, choir and clock scores with bounded voices',async()=>{
  const fingerprints=new Set();
  for(const theme of chaplainThemes){
    const h=harness();h.audio.scene(theme);await h.click({});
    assert.match(h.sceneLabel.textContent,/Капеллан/);assert.equal(h.intervals.size,1);
    fingerprints.add(JSON.stringify(h.sources.filter(s=>s.type).map(s=>[s.type,s.frequency.value,s.stopped-s.started])));
    assert.ok(h.sources.some(s=>s.type==='sine'&&s.detune.value===-3),'organ fundamental');
    assert.ok(h.sources.some(s=>s.type==='sawtooth'&&s.connections[0].Q.value===3.5),'choir');
    let peak=0;
    for(let i=1;i<=800;i++){
      h.contexts[0].currentTime=i/10;for(const fn of h.intervals.values())fn();
      for(const s of h.sources)if(!s.ended&&s.stopped<=i/10){s.ended=true;s.onended?.();}
      peak=Math.max(peak,h.sources.filter(s=>!s.ended).length);assert.equal(h.intervals.size,1);
    }
    assert.ok(peak<100,theme+' active voices: '+peak);
    assert.ok(h.sources.some(s=>s.buffer&&s.stopped-s.started<.05),'clock ticks');
    assert.ok(h.sources.filter(s=>s.type).every(s=>Number.isFinite(s.frequency.value)&&s.frequency.value>=20&&s.frequency.value<4500));
    assert.ok(h.sources.every(s=>Number.isFinite(s.started)&&s.stopped>s.started&&s.stopped-s.started<7));
    h.audio.scene('');assert.equal(h.intervals.size,0);
  }
  assert.equal(fingerprints.size,4);
});
test('Chaplain phase changes crossfade once and never multiply music or bypass preferences',async()=>{
  const h=harness();h.audio.scene('chaplain');await h.click({});
  for(const theme of chaplainThemes){
    h.audio.scene(theme);const count=h.sources.length;
    for(let i=0;i<50;i++)h.audio.scene(theme);
    assert.equal(h.sources.length,count);assert.equal(h.intervals.size,1);
  }
  assert.ok(h.ramps.some(([,time])=>time===.8));
  await h.click({'data-audio-toggle':''});assert.equal(h.intervals.size,0);
  assert.ok(h.sources.every(s=>s.stopped===0));assert.ok(h.delays.every(d=>d.connections.length===0));
  for(const theme of chaplainThemes){
    for(const options of [{saved:JSON.stringify({muted:true})},{saved:JSON.stringify({music:0})},{silent:true}]){
      const noSound=harness(options);noSound.audio.scene(theme);await noSound.click({});assert.equal(noSound.intervals.size,0);
    }
    const fallback=harness({room:false});fallback.audio.scene(theme);await fallback.click({});assert.equal(fallback.intervals.size,1);
    fallback.document.hidden=true;fallback.handlers.visibilitychange();assert.equal(fallback.intervals.size,0);
  }
});
test('actual raid scenes select every Chaplain phase and keep other bosses unchanged',()=>{
  const source=fs.readFileSync(require('node:path').join(__dirname,'../webapp/battle-client'),'utf8');
  const start=source.indexOf('function raidSoundtrack'),end=source.indexOf('function raidPortrait',start),scope={};
  vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
  for(let phase=1;phase<=4;phase++)assert.equal(scope.raidSoundtrack({status:'active',boss_id:'chaplain',data:{phase}}),chaplainThemes[phase-1]);
  assert.equal(scope.raidSoundtrack({status:'lobby',boss_id:'chaplain'}),'menu');
  assert.equal(scope.raidSoundtrack({status:'finished',boss_id:'chaplain'}),'');
  assert.equal(scope.raidSoundtrack({status:'active',boss_id:'kit',data:{phase:3}}),'kit_abyss');
});
