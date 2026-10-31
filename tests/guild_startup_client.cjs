/* A chat chooser and an API error screen must work before a hunter is loaded. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('webapp/guild.js','utf8');
const board={chat_id:-100,francs:0,hunter:{rank:0,rank_name:'F',reputation:123},
 daily:{remaining:3,limit:3},contracts:[],ranks:['F','E','D','C','B','A','S'],monsters:[],lobbies:[]};
async function start({chats=[{chat_id:-100,title:'Тестовый чат'}],chat=null,failChats=false,failBoard=false}={}){
 const app={innerHTML:'',events:{},addEventListener(type,fn){this.events[type]=fn;}};
 const calls=[];
 const sandbox={window:{},console,AbortController,setInterval:()=>1,clearInterval(){},
  fetch:async path=>{calls.push(path);const list=path==='/api/guild/chats',failed=list?failChats:failBoard;
   return {ok:!failed,json:async()=>failed?{error:'Тестовая ошибка <сервера>'}:list?{chats}:structuredClone(board)};}};
 vm.createContext(sandbox);vm.runInContext(source,sandbox);
 await sandbox.window.GuildApp.open({app,chat,initData:'test'});
 return {app,calls};
}
(async()=>{
 const chooser=await start();
 assert(chooser.app.innerHTML.includes('Выбери чат для заказов'));
 assert(chooser.app.innerHTML.includes('data-guild="choose:-100"'));
 assert(!chooser.app.innerHTML.includes('Избыток репутации'));
 assert.deepEqual(chooser.calls,['/api/guild/chats']);
 await chooser.app.events.click({target:{closest:()=>({dataset:{guild:'choose:-100'},disabled:false})}});
 assert(chooser.app.innerHTML.includes('ЛИЦЕНЗИЯ ОХОТНИКА'));
 assert(chooser.app.innerHTML.includes('123 / 100 репутации'));
 assert(chooser.app.innerHTML.includes('Избыток репутации сохраняется'));
 const empty=await start({chats:[]});
 assert(empty.app.innerHTML.includes('Напиши /гильдия в группе'));
 for(const options of [{failChats:true},{chat:-100,failBoard:true}]){
  const failed=await start(options);
  assert(failed.app.innerHTML.includes('Не удалось открыть гильдию'));
  assert(failed.app.innerHTML.includes('Тестовая ошибка &lt;сервера&gt;'));
  assert(failed.app.innerHTML.includes('data-guild="reload"'));
  assert(!failed.app.innerHTML.includes("reading 'hunter'"));
 }
 console.log('PASS: chat chooser, empty chats, selection, reputation hint and original API errors');
})().catch(error=>{console.error(error);process.exitCode=1;});
