// node --test tests/sprite_editor.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../webapp/battle-client'),'utf8').split('boot();').slice(0,-1).join('boot();');
const custom='/sprites/'+'a'.repeat(64)+'.png';
function harness({demo=false}={}){
  const handlers={},requests=[],revoked=[],messages=[];
  function node(){return {disabled:false,checked:false,textContent:'',style:{},dataset:{},classList:{toggle(){},remove(){}},setAttribute(k,v){this[k]=v;}};}
  const nodes=Object.fromEntries(['upload-preview','sprite-pixels','sprite-filename'].map(id=>[id,node()]));
  nodes['sprite-pixels'].checked=false;
  const flip=node(),save=node(),app={innerHTML:'',addEventListener(k,fn){const previous=handlers[k];handlers[k]=e=>{previous?.(e);return fn(e);};}};
  const c=vm.createContext({window:{matchMedia:()=>({matches:true})},location:{search:demo?'?demo=1':'',hostname:demo?'127.0.0.1':'example.test'},
    document:{getElementById:id=>id==='app'?app:nodes[id]||null,querySelector:s=>s.includes('flip_sprite')?flip:s.includes('upload_sprite')?save:null,
      querySelectorAll:()=>[flip,save],addEventListener(){}},URLSearchParams,URL:{createObjectURL:()=> 'blob:new',revokeObjectURL:u=>revoked.push(u)},
    setInterval(){},setTimeout(){},clearTimeout(){},console,messages,
    fetch:async(url,options)=>{requests.push({url,options});return c.reply(url,options);},
    reply:async()=>({ok:true,json:async()=>({menu:{personal:{}},notice:'Сохранено'})})});
  vm.runInContext(source,c);
  const run=code=>vm.runInContext(code,c);
  run('menu={chat_id:1,personal:{sprite:"jock",sprite_url:null,pixel_art:false}};chat=1;page="appearance";toast=m=>messages.push(m);');
  return {c,run,nodes,flip,save,requests,revoked,messages,handlers,app};
}

test('new PNG mirror toggles twice without changing its upload data',()=>{
  const h=harness();h.run('spriteDraft={file:{name:"a.png"},url:"blob:a",flip:false,pixelArt:true,slot:1};');
  h.run('flipSpritePreview();');assert.equal(h.nodes['upload-preview'].style.transform,'scaleX(-1)');
  assert.equal(h.flip['aria-pressed'],'true');assert.equal(h.save.disabled,false);
  h.run('flipSpritePreview();');assert.equal(h.nodes['upload-preview'].style.transform,'none');
  assert.equal(h.run('spriteDraft.file.name'),'a.png');assert.equal(h.flip['aria-pressed'],'false');
});

test('already installed art can be mirrored and saved without choosing a file',async()=>{
  const h=harness();h.c.custom=custom;h.run('menu.personal.sprite_url=custom;menu.characters={active_slot:2};');
  h.run('flipSpritePreview();');assert.equal(h.requests.length,0);
  assert.equal(h.run('spriteDraft.slot'),2);assert.equal(h.nodes['upload-preview'].src,custom);
  const blob={png:true};h.c.reply=async(url,options)=>options?{ok:true,json:async()=>({menu:{personal:{}},notice:'Сохранено'})}:{ok:true,blob:async()=>blob};
  h.run('menuScreen=data=>{menu=data;};');await h.run('saveSprite();');
  assert.equal(h.requests[0].url,custom);const req=h.requests[1];
  assert.match(req.url,/character_slot=2$/);assert.equal(req.options.headers['X-Flip-Horizontal'],'true');
  assert.equal(req.options.headers['X-Pixel-Art'],'false');assert.equal(req.options.body,blob);
  assert.equal(h.run('spriteDraft'),null);assert.equal(h.run('page'),'personal');
});

test('selecting another file resets mirror and retains the pixel-art checkbox',()=>{
  const h=harness();h.nodes['sprite-pixels'].checked=true;
  h.run('spriteDraft={file:{name:"old.png"},url:"blob:old",flip:true,pixelArt:false,slot:1};');
  const file={name:'new.png',size:123};h.handlers.change({target:{id:'sprite-file',files:[file]}});
  assert.equal(h.run('spriteDraft.flip'),false);assert.equal(h.run('spriteDraft.pixelArt'),true);
  assert.equal(h.nodes['upload-preview'].style.transform,'none');assert.deepEqual(h.revoked,['blob:old']);
});

test('failed upload preserves the draft, flip choice and retry button',async()=>{
  const h=harness();h.run('spriteDraft={file:{name:"a.png"},url:"blob:a",flip:true,pixelArt:false,slot:1};');
  h.c.reply=async()=>({ok:false,json:async()=>({error:'Ошибка'})});await h.run('saveSprite();');
  assert.equal(h.run('spriteDraft.flip'),true);assert.equal(h.save.disabled,false);assert.equal(h.flip.disabled,false);
  assert.equal(h.nodes['upload-preview'].style.transform,'scaleX(-1)');assert.equal(h.revoked.length,0);
  assert.equal(h.messages.at(-1),'Ошибка');
});

test('new file submits its pixels once, with explicit orientation and captured character slot',async()=>{
  const h=harness();h.run('spriteDraft={file:{name:"new.png"},url:"blob:new",flip:false,pixelArt:true,slot:3};menuScreen=data=>{menu=data;};');
  h.nodes['sprite-pixels'].checked=true;
  const file=h.run('spriteDraft.file');await h.run('saveSprite();');
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].options.body,file);
  assert.equal(h.requests[0].options.headers['X-Flip-Horizontal'],'false');
  assert.equal(h.requests[0].options.headers['X-Pixel-Art'],'true');
  assert.match(h.requests[0].url,/character_slot=3$/);assert.deepEqual(h.revoked,['blob:new']);
});

test('appearance hint, existing pixel setting and stale-slot draft cleanup',()=>{
  const h=harness();h.c.custom=custom;
  h.run('spriteDraft={file:null,url:custom,flip:true,pixelArt:false,slot:1};menuScreen({chat_id:1,personal:{sprite:"jock",sprite_url:custom,pixel_art:false},characters:{active_slot:2}});');
  assert.equal(h.run('spriteDraft'),null);assert.equal(h.revoked.length,0);
  assert.match(h.app.innerHTML,/Лучше, чтобы спрайт смотрел вправо/);assert.match(h.app.innerHTML,/Отразить по горизонтали/);
  assert.ok(!h.app.innerHTML.includes('id="sprite-pixels" checked'));
});

test('foreign URLs are never fetched and demo does not submit uploads',async()=>{
  const h=harness();h.run('spriteDraft={file:null,url:"https://other.test/file.png",flip:true,slot:1};');
  await h.run('saveSprite();');assert.equal(h.requests.length,0);assert.match(h.messages.at(-1),/Выбери/);
  const demo=harness({demo:true});demo.run('spriteDraft={file:{name:"a.png"},url:"blob:a",flip:true,slot:1};');
  await demo.run('saveSprite();');assert.equal(demo.requests.length,0);assert.match(demo.messages.at(-1),/Демо/);
});
