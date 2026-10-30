/* Renderer unit test: exhausted full rewards must never disable accepting orders. */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const c={id:'f_dungeon',code:'F3',rank:'F',kind:'dungeon',name:'Тестовый данж',biome:'mines',monsters:['goblin'],description:'Проверка наград',rooms:'6 комнат',recommended_party:1,level:2,reward:135,locked:false,reward_preview:{francs_base:33}};
const daily={full:false,used:3,remaining:0,limit:3,day:'2026-10-30',unlimited:true};
const view={actor_id:10,chat_id:-100,francs:1000,hunter:{rank:0,rank_name:'F',reputation:0},daily,contracts:[c],ranks:['F','E','D','C','B','A','S'],monsters:[{id:'goblin',name:'Гоблин',sprite:'/static/assets/guild/goblin-v1.png'}],lobbies:[],shop:[],bag:{},biomes:{},history:[]};
const run={id:'test-run',leader:10,chat_id:-100,status:'lobby',revision:0,contract:c,invite:{},server_time:1,expires:1801,
 members:[{actor_id:10,name:'Усталый охотник',rank:'F',hp:null,reward_preview:{...daily,francs_base:33,reputation:8}},{actor_id:20,name:'Друг',rank:'F',hp:null,reward_preview:{full:true,remaining:2,francs_base:135,reputation:28}}],history:[],results:{}};
const app={innerHTML:'',events:{},addEventListener(type,fn){this.events[type]=fn;},querySelectorAll(){return [];}};
const sandbox={window:{},console,AbortController,crypto:require('crypto').webcrypto,setInterval:()=>1,clearInterval(){},document:{hidden:false},fetch:async(path,options)=>({ok:true,json:async()=>structuredClone(path==='/api/guild/chats'?{chats:[{chat_id:-100,title:'Тест'}]}:path==='/api/guild/board?chat=-100'?view:run)})};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('webapp/guild.js','utf8'),sandbox);
(async()=>{
 await sandbox.window.GuildApp.open({app,chat:-100,initData:'test'});
 assert(app.innerHTML.includes('Число походов не ограничено'));
 assert(app.innerHTML.includes('Полных наград осталось 0 / 3'));
 assert(!/data-guild="accept:f_dungeon"[^>]*disabled/.test(app.innerHTML));
 await app.events.click({target:{closest:()=>({dataset:{guild:'accept:f_dungeon'},disabled:false})}});
 assert(app.innerHTML.includes('НАГРАДЫ КАЖДОГО УЧАСТНИКА'));
 assert(app.innerHTML.includes('Усталый охотник'));assert(app.innerHTML.includes('Повтор: 25% франков'));
 assert(app.innerHTML.includes('Друг'));assert(app.innerHTML.includes('Полная награда · осталось 2'));
 assert(app.innerHTML.includes('Поражения не расходуют награду'));
 assert(!/data-guild="start"[^>]*disabled/.test(app.innerHTML));
 assert(!app.innerHTML.includes('Допуск списывается'));
 console.log('Guild UI: unlimited acceptance/start and mixed-party reward previews passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
