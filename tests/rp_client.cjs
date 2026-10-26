// Exercise the real controller's DOM events and request payloads without a browser.
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const copy=v=>JSON.parse(JSON.stringify(v));
const handlers={},elements=new Map(),timers=new Map(),requests=[];
let timerId=0,failPreview=false,holdPreview=false,releasePreview;
let template={id:'hero',kind:'character',revision:1,definition:{
  name:'Маг',description:'',class_id:'mage',level:20,archclass_id:'mage_archmage',
  archclass_stage:20,skills:['mana_shot'],passives:[],stats:{},flip:false,scale:1,
}};
const app={addEventListener(name,fn){handlers[name]=fn;},set innerHTML(value){
  elements.clear();
  for(const match of value.matchAll(/id="([^"]+)"/g))elements.set(match[1],{innerHTML:'',textContent:''});
  if(elements.has('rp-stats'))elements.get('rp-stats').innerHTML='Вычисляем…';
}};
const document={getElementById:id=>elements.get(id),activeElement:null};
const window={};
const fetch=async(url,options)=>{
  const body=options.body?JSON.parse(options.body):null;
  requests.push({url,body});
  let result;
  if(url==='/api/rp/catalog')result={classes:[{id:'mage',name:'Маг',branches:[{
    id:'mage_archmage',name:'Архимаг',final_name:'Пустотный маг',
  }]}],skills:[],passives:[],mobs:[]};
  else if(url==='/api/rp/chats')result={chats:[]};
  else if(url==='/api/rp/templates')result={templates:[copy(template)]};
  else if(url==='/api/rp/preview'){
    assert.equal(typeof body.definition.archclass_stage,'number');
    if(holdPreview){holdPreview=false;await new Promise(resolve=>releasePreview=resolve);}
    if(failPreview)return {ok:false,json:async()=>({error:'Ступень ветки: 10 или 20.'})};
    result={stats:{max_hp:123,resource_max:100},skills:[]};
  }else if(url==='/api/rp/templates/hero'){
    assert.equal(typeof body.definition.archclass_stage,'number');
    template={...template,definition:copy(body.definition),revision:template.revision+1};
    result={template};
  }else throw Error('Unexpected URL: '+url);
  return {ok:true,json:async()=>result};
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../webapp/rp-client'),'utf8'),{
  window,document,fetch,AbortController,crypto:{randomUUID:()=> 'nonce'},confirm:()=>true,
  setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);},
});
const click=action=>handlers.click({target:{closest:()=>({dataset:{rp:action},disabled:false})}});
const flush=async()=>{const tasks=[...timers.values()];timers.clear();await Promise.all(tasks.map(fn=>fn()));};
const field=(key,value,type='select-one')=>({dataset:{field:key},value,type});
async function run(){
  await window.RPApp.open({app,initData:'test'});
  await click('edit:hero');await flush();
  assert.match(elements.get('rp-stats').innerHTML,/123/);
  // Native selects emit strings; check both event paths and both branch options.
  const stage=field('archclass_stage','10');
  handlers.input({target:stage});await handlers.change({target:stage});await flush();
  assert.equal(requests.at(-1).body.definition.archclass_stage,10);
  stage.value='20';await handlers.change({target:stage});await flush();
  assert.equal(requests.at(-1).body.definition.archclass_stage,20);
  await click('save');await click('edit:hero');await flush();
  assert.equal(template.definition.archclass_stage,20);
  assert.match(elements.get('rp-warnings').innerHTML,/Сборка проверена/);
  // Rejected calculations must stop displaying a permanent loading placeholder.
  failPreview=true;
  handlers.input({target:field('level','21','number')});await flush();
  assert.doesNotMatch(elements.get('rp-stats').innerHTML,/Вычисляем/);
  assert.match(elements.get('rp-stats').innerHTML,/Повторить расчёт/);
  assert.match(elements.get('rp-warnings').textContent,/Ступень ветки/);
  failPreview=false;
  handlers.input({target:field('level','20','number')});await click('retry-preview');await flush();
  assert.match(elements.get('rp-stats').innerHTML,/123/);
  // A previous response cannot overwrite a newly scheduled edit during debounce.
  holdPreview=true;await click('retry-preview');
  const pending=flush();await Promise.resolve();
  const oldStats=elements.get('rp-stats');oldStats.innerHTML='New edit pending';
  handlers.input({target:field('name','Новое имя','text')});releasePreview();await pending;
  assert.equal(oldStats.innerHTML,'New edit pending');await flush();
  assert.match(oldStats.innerHTML,/123/);
  console.log('RP client: numeric branch paths, save/reopen, preview errors, retry and stale responses OK');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
