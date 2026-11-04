const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8154';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/native-queue-review',{recursive:true});
 try{
  for(const width of [1280,390])for(const scenario of ['solo','mixed','party']){
   const page=await browser.newPage({viewport:{width,height:width===390?844:1000},isMobile:width===390,hasTouch:width===390});
   const errors=[],live=[];page.on('pageerror',e=>errors.push(e.message));
   page.on('response',r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url());});
   page.on('request',r=>{if(r.url().includes('/api/'))live.push(r.url());});
   await page.goto(origin+'/arena-queue-review?scenario='+scenario);
   const cut=page.locator('[data-skill="assassin_cut"],[data-raid="skill:assassin_cut"]');await cut.waitFor();
   assert.equal(await page.locator(scenario==='solo'?'.battle .field':'.raid-field.encounter-field').count(),1);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   assert.equal(await page.locator('.setup').count(),0);
   await page.locator('[data-uq-info="assassin_cut"]').click();
   assert.match(await page.locator('#uq-forecast').innerText(),/Успеешь|одновременно|раньше/);
   await page.screenshot({path:`output/native-queue-review/${scenario}-${width}.png`,fullPage:true});
   const stats=page.locator(scenario==='solo'?'[data-inspect="b"]':'[data-raid="inspect:e1"]');
   await stats.click();await page.locator('dialog[open]').waitFor();
   await page.locator('dialog[open] button').first().click();
   if(scenario==='solo'){
    await cut.click();await page.locator('.qte-cover').waitFor();await page.locator('.qte-abort').click();
    // Enemy may finish first or follow immediately: skip defensive checks, not choices.
    for(let i=0;i<4;i++){
     await page.waitForTimeout(1400);
     if(await page.locator('.qte-cover').count())await page.locator('.qte-abort').click();else break;
    }
    await page.waitForFunction(()=>document.querySelector('[data-skill="assassin_cut"]:not(:disabled)'));
    const count=await page.locator('.uq-battle-log p').count();await page.waitForTimeout(2100);
    assert.equal(await page.locator('.uq-battle-log p').count(),count);
   }
   await page.waitForTimeout(1900);assert.deepEqual(live,[]);assert.deepEqual(errors,[]);
   await page.close();
  }
  const block=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  await block.route('**/queue-review/session',async route=>{
   const response=await route.fetch(),body=await response.json();
   // Controlled display fixture: the original effect renderer/dialog, not a
   // stub. Actual engine application is covered by Python combat tests.
   body.fighters.e1.arena.effects.push({id:'review_bleed',kind:'bleed',value:2,duration:3});
   await route.fulfill({response,json:body});
  });
  await block.goto(origin+'/arena-queue-review?defense=block');
  await block.locator('[data-skill="assassin_cut"]').waitFor();
  await block.locator('.status-row.enemy [data-status-id]').first().click();
  await block.locator('.effect-dialog[open]').waitFor();
  assert.match(await block.locator('.effect-dialog').innerText(),/Кровотечение/);
  await block.locator('[data-close-effect]').click();
  await block.locator('[data-skill="assassin_cut"]').click();
  await block.locator('.qte-attack').waitFor();await block.locator('.qte-abort').click();
  await block.waitForFunction(()=>document.querySelector('[data-skill="assassin_cut"]:not(:disabled)'));
  await block.locator('[data-skill="assassin_cut"]').click();
  await block.locator('.qte-block').waitFor();
  await block.screenshot({path:'output/native-queue-review/block-mobile.png'});
  await block.close();
  console.log('PASS native solo/party renderers at 1280/390, native stats/effects, forecast, attack/block QTE, no auto-repeat, no live API calls');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
