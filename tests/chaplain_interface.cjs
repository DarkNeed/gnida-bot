// Pure DOM-contract checks; no browser automation or real game account.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('webapp/battle-client','utf8');
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const raidButton=(label,action,cls='',disabled=false)=>`<button data-raid="${action}" class="${cls}"${disabled?' disabled':''}>${label}</button>`;
function block(start,end){return src.slice(src.indexOf(start),src.indexOf(end,src.indexOf(start)));}
const context={esc,raidButton,raidCurrent:null};vm.createContext(context);
vm.runInContext(block('function chaplainSkills','function raidPhaseSprite').split('let chaplainHold')[0],context);
const f={name:'Player',hp:87,class_avatar_url:'/player.png',sprite_url:'/sprites/player.png',pixel_art:true,resource_name:'Мана',resource:100,cooldowns:{},skill_details:[
  {skill_id:'a',name:'Alpha',damage_type:'magic',cost:10},{skill_id:'b',name:'Beta',cost:0} ]};
const boss={name:'Boss',hp:720,class_avatar_url:'/boss.png'};
const data={token:'test',actor_id:10,boss_id:'chaplain',data:{phase:4,round:4,boss,players:{10:{fighter:f}},chaplain:{ui_order:{10:['b','a']},ui_scramble:true,swap_target:'10'}}};
context.raidCurrent=data;
const before=JSON.stringify(data),html=context.chaplainSkills(data,f);
assert.ok(html.indexOf('skill:b')<html.indexOf('skill:a'));
assert.ok(html.includes('ДОСТУП ▓▒░')&&html.includes('chaplain-real-name'));
assert.ok(html.includes('10 Мана')&&html.includes('0 Мана'));
const switched=context.chaplainArt(f,'10');
assert.equal(switched.class_avatar_url,'/boss.png');assert.equal(switched.hp,87);assert.equal(switched.name,'Player');
assert.equal(context.chaplainArt(boss,'boss').sprite_url,'/sprites/player.png');
assert.equal(JSON.stringify(data),before);
data.data.phase=1;assert.ok(!context.raidPhaseLabel(data).includes('ФАЗА'));
data.data.phase=2;assert.ok(!context.raidPhaseLabel(data).includes('ФАЗА'));
data.data.phase=4;data.phase_count=4;assert.ok(context.raidPhaseLabel(data).includes('4 / 4'));
const handlers={},calls=[],timers=new Map();let ident=0;
const holdContext={app:{addEventListener:(type,fn)=>{(handlers[type]??=[]).push(fn)}},setTimeout:(fn,ms)=>{assert.equal(ms,420);timers.set(++ident,fn);return ident},clearTimeout:id=>timers.delete(id),showChaplainSkill:id=>calls.push(id)};
vm.runInNewContext(block('let chaplainHold','function raidPhaseSprite'),holdContext);
const button={dataset:{raid:'skill:mana_shot'},closest(selector){return selector==='.chaplain-obscured'||selector==='[data-chaplain-read]'&&this.dataset.chaplainRead?this:null}};
handlers.pointerdown[0]({target:button});handlers.pointerup[0]();assert.equal(timers.size,0);assert.equal(calls.length,0);
handlers.pointerdown[0]({target:button});[...timers.values()][0]();assert.deepEqual(calls,['mana_shot']);
let prevented=false,stopped=false;handlers.click[0]({target:button,preventDefault:()=>prevented=true,stopImmediatePropagation:()=>stopped=true});
assert.ok(prevented&&stopped);assert.equal(button.dataset.chaplainRead,undefined);
// A denied inspection never renders statistics, closes itself, and cannot be bypassed by reopening.
const dialogs=new Map(),cutTimers=new Map();let nextTimer=0,rendered=0;
const detailContext={raidCurrent:data,raidInspect:null,
  document:{getElementById:id=>dialogs.get(id),body:{append:el=>dialogs.set(el.id,el)},
    createElement:()=>({open:false,innerHTML:'',classList:{add(){}},append(){},setAttribute(){},addEventListener(){},
      showModal(){this.open=true},close(){this.open=false},remove(){dialogs.delete(this.id)}})},
  petDetails:()=>'',fighterDetails:()=>{rendered++;return 'SECRET STATS'},
  setTimeout:(fn,ms)=>{assert.equal(ms,450);cutTimers.set(++nextTimer,fn);return nextTimer},
  clearTimeout:id=>cutTimers.delete(id)};
vm.createContext(detailContext);
vm.runInContext(block('let raidDetailsCutTimer','async function raidAction'),detailContext);
for(const phase of [1,2,3,4])for(let repeat=0;repeat<2;repeat++){
  data.data.phase=phase;detailContext.showRaidDetails('boss');
  const dialog=dialogs.get('raid-details');assert.ok(dialog.open);assert.ok(dialog.innerHTML.includes('Доступ прерван'));
  assert.ok(!dialog.innerHTML.includes('SECRET STATS'));assert.equal(rendered,0);
  detailContext.showRaidDetails('boss');assert.equal(cutTimers.size,1); // Polling cannot extend the cut.
  [...cutTimers.values()][0]();assert.equal(dialogs.size,0);assert.equal(detailContext.raidInspect,null);assert.equal(cutTimers.size,0);
}
detailContext.showRaidDetails('boss');const staleCut=[...cutTimers.values()][0];
detailContext.closeRaidDetails();detailContext.showRaidDetails('10');staleCut();
assert.ok(dialogs.get('raid-details').open);assert.equal(rendered,1);assert.equal(cutTimers.size,0);
detailContext.closeRaidDetails();data.boss_id='kit';detailContext.showRaidDetails('boss');
assert.ok(dialogs.get('raid-details').innerHTML.includes('SECRET STATS'));assert.equal(rendered,2);assert.equal(cutTimers.size,0);
console.log('Chaplain interface: shuffle, concealment, safe hold, sprite identity, phase masking and denied inspection OK');
