/* Pure render/event tests with a tiny DOM double, not a browser automation path. */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stats={max_hp:100,physical_attack:10,magic_attack:5,physical_defense:4,magic_defense:3,speed:7,evasion:8,resource_max:100};
const names={max_hp:'HP',physical_attack:'Физ. атака',magic_attack:'Маг. атака',physical_defense:'Физ. защита',magic_defense:'Маг. защита',speed:'Скорость',evasion:'Уклонение'};
const item={id:'gear1',key:'fang',rank:'C',rarity:'epic',rarity_name:'Эпический',name:'Клык волка',slot:'weapon',min_level:10,stats:{physical_attack:2},comparison:{...stats,physical_attack:12},effect_text:'Урон по кровоточащей цели +20%.',upgrade:0,salvage:8,upgrade_cost:2,favorite:false,used_by:[],affixes:[],reroll_options:[],equipped:false};
const view={revision:0,character_slot:1,level:20,class_name:'Воин',hero:{name:'Герой',sprite_url:'/static/assets/rpg/warrior.png',fallback_url:'/static/assets/rpg/warrior.png',pixel_art:false},busy:false,equipped:{},items:[item],slots:{weapon:'Оружие',armor:'Доспех',accessory:'Аксессуар',relic:'Реликвия'},stat_names:names,base_stats:stats,stats:{...stats},stat_bonuses:Object.fromEntries(Object.keys(names).map(k=>[k,0])),materials:{C:20},ranks:['F','C'],hunter_rank:'C',catalog:[]};
let listScroll=0,request;
const app={innerHTML:'',listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},querySelector(selector){
 if(selector==='.gear-item-list')return {scrollTop:listScroll,scrollTo({top}){listScroll=top;}};
 if(selector==='.gear-right')return {scrollIntoView(){},querySelector(){return {focus(){}};}};
 return null;
}};
const context={window:{},console,AbortController,crypto:require('crypto').webcrypto,matchMedia:()=>({matches:false}),fetch:async(path,options)=>{
 if(options.body){request=JSON.parse(options.body);if(request.action==='equip'){view.equipped.weapon=item.id;item.equipped=true;item.used_by=[1];view.stats.physical_attack=12;view.stat_bonuses.physical_attack=2;view.revision++;}}
 return {ok:true,json:async()=>structuredClone(view)};
}};
vm.createContext(context);vm.runInContext(fs.readFileSync('webapp/equipment.js','utf8'),context);
const click=action=>app.listeners.click({target:{closest:()=>({dataset:{gear:action},disabled:false})}});
(async()=>{
 await context.window.GearApp.open({app,chat:-100,initData:'test',onBack(){}});
 assert(app.innerHTML.includes('gear-character-grid'));
 assert(app.innerHTML.includes('src="/static/assets/rpg/warrior.png"'));
 assert(app.innerHTML.includes('aria-label="Инвентарь экипировки"'));
 assert(!app.innerHTML.includes('aria-label="Детали предмета"'));
 assert(app.innerHTML.includes('data-zero="true">+0'));
 listScroll=74;await click('select:gear1');
 assert(app.innerHTML.includes('aria-label="Детали предмета"'));
 assert(!app.innerHTML.includes('aria-label="Инвентарь экипировки"'));
 assert(app.innerHTML.includes('data-gear="inventory"'));
 assert(app.innerHTML.includes('gear-hero-sprite'));
 await click('equip:gear1');assert.equal(request.action,'equip');
 assert(app.innerHTML.includes('Характеристики обновлены.'));
 assert(app.innerHTML.includes('class="gear-bonus">+2'));
 assert(app.innerHTML.includes('<strong>12</strong>'));
 await click('inventory');assert(app.innerHTML.includes('aria-label="Инвентарь экипировки"'));assert.equal(listScroll,74);
 await click('select:gear1');await click('filter:armor');
 assert(app.innerHTML.includes('Ничего не найдено'));assert(!app.innerHTML.includes('aria-label="Детали предмета"'));
 view.hero.sprite_url='https://invalid.example/tracker.png';
 await context.window.GearApp.open({app,chat:-100,initData:'test',onBack(){}});
 assert(app.innerHTML.includes('src="/static/assets/ragamuffin.png"'));assert(!app.innerHTML.includes('https://invalid.example'));
 console.log('Equipment UI: hero, stat bonuses, inventory/detail replacement, back navigation, equip and safe art passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
