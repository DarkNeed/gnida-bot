const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8139';
(async()=>{
 const b=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const p=await b.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),errors=[];
  p.on('pageerror',e=>errors.push(e.message));
  await p.goto(origin+'/npc-review');await p.locator('[data-h="tab:trader"]').waitFor();
  const get=()=>p.evaluate(async()=>await(await fetch('/api/holdings/-100')).json());
  const before=await get(),w=before.npc.workers.find(w=>!w.appraised);
  assert(w);assert.equal(before.worker_counts.total,before.people.length+before.npc.workers.length);
  await p.locator('[data-h="tab:overview"]').click();
  assert.equal(await p.locator('.holdings-summary>div').first().locator('strong').innerText(),String(before.worker_counts.total));
  await p.locator('[data-h="tab:trader"]').click();
  async function choose(id){
   await p.locator('[data-h="trader-appraise"]').click();
   await p.locator('#trader-worker').selectOption('npc_'+id);
   await p.locator('[data-h="trader-confirm:trader_appraise"]').click();
   await p.locator('.npc-passport').waitFor();
  }
  const saved=p.waitForResponse(r=>r.url().includes('/api/holdings/-100')&&r.request().method()==='POST');
  await choose(w.id);assert.equal((await saved).status(),200);
  const known=await get();assert.equal(known.balance,before.balance-50);
  assert.equal(known.npc.workers.find(v=>v.id===w.id).appraised,true);
  await p.keyboard.press('Escape');await choose(w.id);
  const read=await get();assert.equal(read.balance,known.balance);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await p.keyboard.press('Escape');
  // Render the NPC-only client case against the real owned NPCs. This must
  // not enable human-only sale/order/wager workflows for fictional workers.
  await p.route('**/api/holdings/-100',async route=>{
   if(route.request().method()!=='GET')return route.continue();
   const response=await route.fetch(),data=await response.json();data.people=[];
   data.worker_counts={human:0,npc:data.npc.workers.length,total:data.npc.workers.length};
   await route.fulfill({response,json:data});
  });
  await p.reload();await p.locator('[data-h="tab:trader"]').click();
  assert.equal(await p.locator('[data-h="trader-appraise"]').isEnabled(),true);
  assert.equal(await p.locator('[data-h="trader-list"]').isEnabled(),false);
  await p.locator('[data-h="trader-appraise"]').click();
  const values=await p.locator('#trader-worker option').evaluateAll(ns=>ns.map(n=>n.value));
  assert(values.length>0&&values.every(v=>v.startsWith('npc_')));
  assert.deepEqual(errors,[]);
  console.log('PASS mixed appraisal list, NPC assessment costs 50 once, repeat view free, combined counter and mobile UI');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
