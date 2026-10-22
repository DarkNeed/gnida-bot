// Observer session lifecycle without browser/network dependencies.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const E=require('../webapp/qte-unique/engine'),B=require('../webapp/qte-block/engine');
const code=fs.readFileSync(require('node:path').join(__dirname,'../webapp/qte-watch'),'utf8');
function harness(){
  const intervals=new Map(),timers=new Map(),frames=new Map(),sockets=[],events={},covers=[];
  let serial=0,locks=0;
  const element=()=>({hidden:false,isConnected:true,textContent:'',dataset:{},attributes:{},listeners:{},
    classList:{toggle(){}},setAttribute(k,v){this.attributes[k]=v;},focus(){},
    addEventListener(k,f){this.listeners[k]=f;}});
  const button=element();button.dataset={qteWatch:'battle',watchToken:'room',watchNames:'{"10":"First","20":"Second"}'};
  const document={hidden:false,activeElement:element(),listeners:{},
    addEventListener(k,f){this.listeners[k]=f;},querySelectorAll(){return [button];},
    body:{append(c){covers.push(c);}},createElement(){
      const cover=element(),parts={};
      for(const name of ['canvas','.qte-live-status','h2','.qte-watch-players','.qte-watch-close'])parts[name]=element();
      parts.canvas.getContext=()=>({});cover.querySelector=q=>parts[q];cover.querySelectorAll=()=>[parts['.qte-watch-close']];
      cover.remove=()=>{cover.isConnected=false;};return cover;
    }};
  class Socket{
    constructor(){sockets.push(this);this.readyState=0;this.sent=[];}
    open(){this.readyState=1;this.onopen();}
    send(value){this.sent.push(JSON.parse(value));}
    emit(value){this.onmessage({data:JSON.stringify(value)});}
    close(){this.readyState=3;this.onclose?.({code:1000});}
  }
  const root={document,AbortController,WebSocket:Socket,QTEUnique:E,QTEBlock:B,
    Telegram:{WebApp:{initData:'test-signature'}},location:{protocol:'http:',host:'localhost'},
    ArenaMiniGames:{active:false},QTETouch:{lockViewport(){locks++;return ()=>locks--; }},
    addEventListener(k,f){events[k]=f;},
    setInterval(f){const id=++serial;intervals.set(id,f);return id;},clearInterval(id){intervals.delete(id);},
    setTimeout(f,ms){const id=++serial;timers.set(id,{f,ms});return id;},clearTimeout(id){timers.delete(id);},
    requestAnimationFrame(f){const id=++serial;frames.set(id,f);return id;},cancelAnimationFrame(id){frames.delete(id);}};
  vm.runInNewContext(code,root);
  return {root,W:root.ArenaQTEWatch,sockets,covers,intervals,timers,frames,events,button,document,
    frame(){const todo=[...frames];frames.clear();for(const [,f] of todo)f(16);},
    expire(ms){for(const [id,t] of [...timers])if(t.ms===ms){timers.delete(id);t.f();}},get locks(){return locks;}};
}
const stage=(id,actor)=>({id,actor,version:2,kind:'attack',seed:23,name:'Shot',
  profile:{id:'hunter_shot:Shot:1:physical',base_id:'hunter_shot',class_id:'hunter',name:'Shot',strikes:1,tags:[],damage_type:'physical'},
  stats:{accuracy:90,enemyEvasion:10},target_hp:100,damage_base:30});
const h=harness();h.W.watch('battle','room');
assert.equal(h.W.active,true);assert.equal(h.covers[0].hidden,true);assert.equal(h.frames.size,0);
let ws=h.sockets[0];ws.open();assert.equal(ws.sent[0].follow,true);assert.equal(ws.sent[0].actor,0);
ws.emit({type:'waiting'});assert.equal(h.covers[0].hidden,true);
ws.emit({type:'begin',stage:stage('first',10)});assert.equal(h.covers[0].hidden,false);assert.equal(h.locks,1);
ws.emit({type:'data',id:'first',tick:0,ended:true});h.frame();h.expire(650);
assert.equal(h.covers[0].hidden,true);assert.equal(h.W.active,true);assert.equal(ws.readyState,1);
assert.equal(h.locks,0);assert.equal(h.frames.size,0);
ws.emit({type:'begin',stage:stage('second',20)});assert.equal(h.covers[0].hidden,false);
assert.equal(h.sockets.length,1);assert.equal(h.locks,1);
h.W.pause();assert.equal(h.covers[0].hidden,true);assert.equal(h.W.active,true);assert.equal(ws.readyState,3);
assert.equal(h.frames.size,0);assert.equal(h.intervals.size,0);assert.equal(h.locks,0);
h.events.keydown({code:'Escape',preventDefault(){throw Error('hidden viewer intercepted own QTE');}});
h.W.resume();ws=h.sockets[1];ws.open();assert.equal(ws.sent[0].follow,true);
ws.emit({type:'begin',stage:stage('third',10)});assert.equal(h.covers[0].hidden,false);
h.W.context('battle','room',true);assert.equal(h.W.active,true);
h.covers[0].querySelector('.qte-watch-close').listeners.click();assert.equal(h.W.active,false);
assert.equal(h.covers[0].isConnected,false);assert.equal(h.intervals.size,0);assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);
ws.emit({type:'begin',stage:stage('stale',20)});assert.equal(h.W.active,false);assert.equal(h.locks,0);
h.W.watch('raid','new');h.W.context('raid','new',false);assert.equal(h.W.active,false);
h.W.watch('battle','other');h.W.context('raid','different');assert.equal(h.W.active,false);
const own=harness();own.root.ArenaMiniGames.active=true;own.W.watch('battle','room');assert.equal(own.sockets.length,0);
console.log('Continuous QTE viewing: idle, automatic next stage, own-game pause/resume and cleanup passed.');
