const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.CHEST_MIMIC_URL||'http://127.0.0.1:8160';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/chest-mimic-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:1000},isMobile:width===390,hasTouch:width===390});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)errors.push(r.status()+' '+r.url());});
   await page.goto(origin+'/chest-mimic-review');
   await page.frameLocator('iframe').locator('[data-guild="choice:open"]').waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:`output/chest-mimic-review/event-${width}.png`,fullPage:true});
   await page.goto(origin+'/chest-mimic-demo?mode=treasure');
   await page.locator('[data-guild="choice:open"]').click();
   await page.waitForFunction(()=>document.body.textContent.includes('Сундук оказался сундуком'));
   assert.equal(await page.locator('[data-guild="battle"]').count(),0);
   await page.goto(origin+'/chest-mimic-demo?mode=mimic&party=1');
   await page.locator('[data-guild="choice:open"]').click();
   await page.locator('[data-guild="battle"]').click();
   await page.locator('.raid-sprite[src*="chest_mimic"]').waitFor();
   await page.screenshot({path:`output/chest-mimic-review/battle-${width}.png`,fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   for(const defense of ['dodge','block']){
    await page.goto(origin+'/chest-mimic-demo?mode=battle&phase=2&defense='+defense+'&sturdy=1');
    await page.locator('.raid-sprite[src*="chest_mimic"]').waitFor();
    for(let i=0;i<4&&!await page.locator('.qte-window').count();i++){
     await page.locator('[data-raid="skill:defend"]').click();await page.waitForTimeout(800);
    }
    await page.locator('.qte-window').waitFor({timeout:12000});
    await page.screenshot({path:`output/chest-mimic-review/live-${defense}-${width}.png`,fullPage:true});
    await page.locator('.qte-abort').click();await page.waitForTimeout(800);
   }
   for(const mode of ['defense','block']){
    for(const skill of ['bite','tongue','coins','devour','ravenous_bite','ravenous_coins']){
     const path=mode==='block'?'/qte-lab/block/?skill=':'/qte-lab/unique/?mode=defense&skill=';
     await page.goto(origin+path+'guild_chest_'+skill);
     await page.locator('#start').click();
     await page.waitForTimeout(2400);
     if(await page.locator('#resume:visible').count())await page.locator('#resume').click();
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
     await page.screenshot({path:`output/chest-mimic-review/${mode}-${skill}-${width}.png`,fullPage:true});
    }
   }
   assert.deepEqual(errors,[]);console.log('PASS chest events, party battle, phases, native QTEs and mobile layout',width);await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
