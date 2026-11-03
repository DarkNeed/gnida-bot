const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const ctx={window:{},document:{addEventListener(){}},setInterval(){},console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('webapp/npc-workers.js','utf8'),ctx);
function render(tab,{enabled=true,event=false,outage=false}={}){
  const fragments=[];
  const screen={insertAdjacentHTML:(where,html)=>fragments.push({where,html})};
  const app={querySelector:s=>s==='#holdings-screen'?screen:null,addEventListener(){}};
  const data={sites:[{id:1}],npc:{workforce:{events:[]}},protection:{enabled,workers:1,events:event?[{id:'x',name:'Орки',text:'Риск',kind:'orcs',status:'open',mine:true,deadline:2000000000}]:[],outage_until:outage?2000000000:null,next_event:2000000000,rejoin_fee:250}};
  ctx.window.NpcWorkers.mount({tab,app,getData:()=>data});
  return fragments;
}
let fragments=render('sites');
assert.equal(fragments.find(f=>f.where==='afterbegin').html,'','No large protection card when nothing is happening');
const footer=fragments.find(f=>f.where==='beforeend').html;
assert.match(footer,/<footer class="npc-protection-settings">/);
assert.match(footer,/class="npc-protection-switch"/);
assert.match(footer,/Отказаться от крыши/);
assert.ok(!footer.includes('class="primary"'));
assert.ok(!render('overview').some(f=>f.html.includes('protection-toggle')),'No refusal button on overview');
assert.ok(!render('people').some(f=>f.html.includes('protection-toggle')),'No refusal button in the shared roster');
assert.match(render('sites',{enabled:false}).find(f=>f.where==='beforeend').html,/Вернуть крышу/);
assert.match(render('sites',{event:true}).find(f=>f.where==='afterbegin').html,/Собрать защиту и позвать в чат/);
assert.match(render('sites',{outage:true}).find(f=>f.where==='afterbegin').html,/Простой до/);
console.log('Protection footer, hidden idle panel, alerts and return-to-protection: OK');
