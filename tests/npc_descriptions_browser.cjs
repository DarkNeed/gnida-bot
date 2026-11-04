const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8139';
(async()=>{
 const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 fs.mkdirSync('output/npc-descriptions',{recursive:true});
 try{
  for(const width of [1200,390]){
   const p=await b.newPage({viewport:{width,height:width<500?844:1000},isMobile:width<500,hasTouch:width<500});
   p.on('pageerror',e=>errors.push(e.message));
   p.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
   await p.goto(origin+'/npc-review');
   await p.locator('[data-npc-act="card"]').first().waitFor();
   const before=await p.evaluate(async()=>await(await fetch('/api/holdings/-100')).json());
   for(const profession of ['miner','skeleton']){
    const w=before.npc.workers.find(w=>w.profession===profession);assert(w);
    await p.locator(`[data-npc-act="card"][data-npc-id="${w.id}"]`).first().click();
    const dialog=p.locator('.holdings-dialog');await dialog.waitFor();
    const text=await dialog.innerText();
    for(const label of ['Подходящая работа','Редкость и особенность постоянны','Содержание, состояние и побеги','Обучение и история'])assert(text.includes(label),label);
    assert.equal(await dialog.locator('.npc-passport h3').innerText(),w.passport.trait_name);
    if(w.appraised)assert(text.includes('Бонус редкости:'));else assert(text.includes('Редкость и её бонусы скрыты'));
    await dialog.locator('summary').filter({hasText:'Выработка по предприятиям'}).click();
    assert.equal(await dialog.locator('.npc-work-rates>div').count(),6);
    if(!w.appraised)assert.equal(await dialog.locator('.npc-work-rates').innerText().then(t=>(t.match(/После оценки/g)||[]).length),6);
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    assert.equal(await dialog.evaluate(n=>n.scrollWidth<=n.clientWidth+1),true);
    await p.screenshot({path:`output/npc-descriptions/${profession}-${width}.png`});
    await p.keyboard.press('Escape');
   }
   const after=await p.evaluate(async()=>await(await fetch('/api/holdings/-100')).json());assert.equal(after.balance,before.balance);
   for(const w of before.npc.workers){const now=after.npc.workers.find(v=>v.id===w.id);assert.equal(now.revision,w.revision);assert.equal(now.appraised,w.appraised);}
   await p.locator('[data-h="tab:trader"]').click();
   await p.locator('.npc-card [data-npc-act="card"]').first().click();
   const market=p.locator('.holdings-dialog');await market.waitFor();
   assert.equal(await market.locator('[data-npc-act="buy"]').count(),1);
   assert.equal(await market.locator('[data-npc-act="release"],[data-npc-act="assign"],[data-npc-act="appraise"]').count(),0);
   await p.close();
  }
  assert.deepEqual(errors,[]);console.log('PASS NPC passports: known/hidden rarity, six workplaces, free read-only viewing, market ownership controls, mobile/desktop');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
