/* Actual settlement renderer, with authenticated API responses replaced by fixtures. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
let input='';process.stdin.on('data',data=>input+=data);process.stdin.on('end',async()=>{
 const view=JSON.parse(input),source=fs.readFileSync('webapp/kingdom.js','utf8');
 async function start({chat=-100,value=view,error=false}={}){
  const app={innerHTML:'',events:{},addEventListener(type,fn){this.events[type]=fn;},querySelector(){return null;}};
  const sandbox={window:{},console,AbortController,crypto:require('node:crypto').webcrypto,setInterval:()=>1,clearInterval(){},document:{hidden:false},
   fetch:async path=>({ok:!error,json:async()=>error?{error:'API <сломалось>'}:path==='/api/kingdom/chats'?{chats:[{chat_id:-100,title:'Наш чат'}]}:structuredClone(value)})};
  vm.createContext(sandbox);for(const file of ['kingdom-map','kingdom-army','kingdom-diplomacy','kingdom-budget'])vm.runInContext(fs.readFileSync('webapp/'+file+'.js','utf8'),sandbox);vm.runInContext(source,sandbox);await sandbox.window.KingdomApp.open({app,chat,initData:'test'});
  return {app,click:action=>app.events.click({target:{closest:selector=>selector==='[data-k]'?{dataset:{k:action},disabled:false}:null}})};
 }
 try{
  const owner=await start();assert.equal((owner.app.innerHTML.match(/data-k-tile=/g)||[]).length,165);
  assert(owner.app.innerHTML.includes('Рассвет'));assert(owner.app.innerHTML.includes('ТВОЁ ВЛАДЕНИЕ'));
  assert(owner.app.innerHTML.includes('k-map-time'));assert(!owner.app.innerHTML.includes('k-vignette'));
  const timed=view.map_events[0];assert(timed);
  await owner.click('timedfocus:'+timed.id);assert(owner.app.innerHTML.includes('Отправить разведчиков'));
  await owner.click('explore:'+timed.id);assert(owner.app.innerHTML.includes('role="dialog"'));assert(owner.app.innerHTML.includes('никаких франков'));
  await owner.click('cancel');
  await owner.click('tab:buildings');assert(owner.app.innerHTML.includes('data-k="build:barracks"'));
  await owner.click('tab:budget');assert(owner.app.innerHTML.includes('ДВЕ РАЗНЫЕ КАССЫ'));assert(owner.app.innerHTML.includes('Кошелёк → бюджет'));assert(!owner.app.innerHTML.includes('NaN'));
  assert(owner.app.innerHTML.includes('Запас на сутки'));assert(!owner.app.innerHTML.includes('budget_withdraw'));assert(!owner.app.innerHTML.includes('Бюджет → кошелёк'));assert(!owner.app.innerHTML.includes('одно поселение Telegram-аккаунта'));
  await owner.click('tab:buildings');
  await owner.click('build:barracks');assert(owner.app.innerHTML.includes('role="dialog"'));assert(owner.app.innerHTML.includes('9 000 ₣'));
  await owner.click('cancel');assert(!owner.app.innerHTML.includes('role="dialog"'));
  await owner.click('tab:events');assert(owner.app.innerHTML.includes('Союз свободных теплотрасс'));assert(owner.app.innerHTML.includes('event:bounty'));
  await owner.click('tab:army');assert(owner.app.innerHTML.includes('Боевой строй'));assert(owner.app.innerHTML.includes('Бархатные агенты'));
  await owner.click('tab:campaigns');assert(owner.app.innerHTML.includes('Диванная баррикада'));assert(owner.app.innerHTML.includes('Тактика армии'));
  await owner.click('tab:council');assert(owner.app.innerHTML.includes('Военная держава'));assert(owner.app.innerHTML.includes('Культ Предков'));assert(!owner.app.innerHTML.includes('undefined'));
  await owner.click('tab:wars');assert(owner.app.innerHTML.includes('Корона остаётся'));assert(owner.app.innerHTML.includes('Оборонительная тактика'));assert(!owner.app.innerHTML.includes('NaN'));
  await owner.click('tab:events');
  const novice=structuredClone(view);novice.towns.forEach(t=>t.own=false);novice.eligibility.allowed=false;novice.eligibility.level=7;
  const locked=await start({value:novice});assert(locked.app.innerHTML.includes('7/15 · уровень'));
  assert(locked.app.innerHTML.includes('<span>От героя</span><span>к правителю.</span>'));
  assert(owner.app.innerHTML.includes('k-factions'));
  const chooser=await start({chat:null});assert(chooser.app.innerHTML.includes('У каждого чата своя история'));assert(!chooser.app.innerHTML.includes('undefined'));
  const failed=await start({error:true});assert(failed.app.innerHTML.includes('Не удалось открыть карту'));assert(failed.app.innerHTML.includes('API &lt;сломалось&gt;'));
  console.log('PASS: actual map renderer, construction confirmation, incidents, eligibility, chat chooser and API errors');
 }catch(error){console.error(error);process.exitCode=1;}
});
