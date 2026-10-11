// node --test tests/arena_audio.cjs (no browser or external packages required)
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname,'../webapp/arena-audio'),'utf8');
function harness({saved=null,storageFails=false,available=true,rejected=false}={}) {
  const handlers={},windowHandlers={},intervals=new Map(),contexts=[],sources=[],ramps=[];
  let serial=0,stored=saved;
  class Param {
    constructor(){this.value=0;}
    setValueAtTime(v){this.value=v;}
    linearRampToValueAtTime(v,t){this.value=v;ramps.push([v,t]);}
    exponentialRampToValueAtTime(v){this.value=v;}
    cancelScheduledValues(){}
  }
  class Node {
    constructor(){this.gain=new Param();this.frequency=new Param();this.detune=new Param();this.Q=new Param();this.connections=[];}
    connect(n){this.connections.push(n);return n;}
    disconnect(){this.connections=[];}
  }
  class Source extends Node {
    constructor(){super();sources.push(this);}
    start(t){this.started=t;}
    stop(t){this.stopped=t??0;if(t===undefined)this.onended?.();}
  }
  class Context {
    constructor(){this.currentTime=0;this.sampleRate=100;this.state='suspended';this.destination=new Node();contexts.push(this);}
    createGain(){return new Node();}
    createDynamicsCompressor(){const n=new Node();for(const k of ['threshold','knee','ratio'])n[k]=new Param();return n;}
    createBiquadFilter(){return new Node();}
    createOscillator(){return new Source();}
    createBufferSource(){return new Source();}
    createBuffer(){return {getChannelData:()=>new Float32Array(100)};}
    async resume(){if(rejected)throw new Error('autoplay');this.state='running';}
    async suspend(){this.state='suspended';}
  }
  const document={hidden:false,querySelectorAll:()=>[],querySelector:()=>null,getElementById:()=>null,addEventListener:(k,f)=>handlers[k]=f};
  const window={addEventListener:(k,f)=>windowHandlers[k]=f};
  if(available)window.AudioContext=Context;
  const sandbox={window,document,localStorage:{getItem(){if(storageFails)throw Error('denied');return stored;},setItem(k,v){if(storageFails)throw Error('denied');stored=v;}},setInterval(f){const id=++serial;intervals.set(id,f);return id;},clearInterval(id){intervals.delete(id);},setTimeout(){},console};
  vm.runInNewContext(code,sandbox);
  const button=attrs=>({disabled:false,dataset:{audioTest:attrs['data-audio-test']},hasAttribute:k=>k in attrs});
  const click=async attrs=>{const b=button(attrs);await handlers.click({target:{closest:()=>b}});};
  return {audio:window.ArenaAudio,document,handlers,windowHandlers,contexts,sources,intervals,ramps,click,get stored(){return stored;}};
}
test('muted default creates no context, voices, timers or requests',()=>{
  const h=harness();h.audio.scene('battle');h.audio.effect('hit');
  assert.equal(h.contexts.length,0);assert.equal(h.sources.length,0);assert.equal(h.intervals.size,0);
});
test('explicit gesture enables once; scene refresh never layers loops',async()=>{
  const h=harness();await h.click({'data-audio-toggle':''});
  assert.equal(h.contexts.length,1);assert.equal(h.intervals.size,1);
  assert.equal(JSON.parse(h.stored).muted,false);
  for(let i=0;i<30;i++)h.audio.scene('menu');
  assert.equal(h.intervals.size,1);
  const count=h.sources.length;h.audio.scene('doofenshmirtz');
  assert.equal(h.intervals.size,1);assert.ok(h.sources.length>count);
  h.audio.scene('');assert.equal(h.intervals.size,0);
});
test('mute stops all voices immediately and blocks future effects',async()=>{
  const h=harness();await h.click({'data-audio-toggle':''});h.audio.effect('victory');
  await h.click({'data-audio-toggle':''});
  assert.equal(h.intervals.size,0);assert.ok(h.sources.every(s=>s.stopped===0));
  const count=h.sources.length;h.audio.effect('hit');assert.equal(h.sources.length,count);
});
test('hidden page suspends context, stops loops and effects; visible resumes',async()=>{
  const h=harness();await h.click({'data-audio-toggle':''});
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
  const h=harness();await h.click({'data-audio-toggle':''});h.audio.scene('');
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
  const h=harness();await h.click({'data-audio-toggle':''});h.audio.scene('');
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
  const h=harness();await h.click({'data-audio-toggle':''});
  for(const theme of ['menu','battle','raid','lei_heng','doofenshmirtz']){
    h.audio.scene(theme);assert.equal(h.intervals.size,1);
    h.contexts[0].currentTime+=10;for(const fn of h.intervals.values())fn();
  }
  h.audio.scene('');
  const race=harness();const enable=race.click({'data-audio-toggle':''});
  await race.click({'data-audio-toggle':''});await enable;
  assert.equal(race.intervals.size,0);
});
