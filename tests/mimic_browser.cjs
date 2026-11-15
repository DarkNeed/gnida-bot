const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.MIMIC_URL||'http://127.0.0.1:8158';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/mimic-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:1000},isMobile:width===390,hasTouch:width===390});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)errors.push(r.status()+' '+r.url());});
   if(process.env.MIMIC_DEBUG)page.on('response',async r=>{if(r.url().includes('/api/raid/')&&r.request().method()==='POST'){const d=await r.json();console.log('POST',r.status(),d.error||JSON.stringify({qte:d.qte,choice:d.data?.players?.['10']?.choice_id,time:d.data?.action_queue?.absolute_time,log:d.data?.log?.at(-1)}));}});
   for(const mode of ['fresh','first_combo','first_combo-block','phase2','phase2-block','phase3','scroll']){
    await page.goto(origin+'/mimic-demo?mode='+mode.replace('-block','')+'&defense='+(mode.endsWith('-block')?'block':'dodge')+'&sturdy=1');
    await page.locator('.mimic-panel').waitFor();
    assert.equal(await page.locator('.mimic-slot').count(),3);
    assert.match(await page.locator('.raid-field').evaluate(el=>getComputedStyle(el).backgroundImage),/mimic_hall\.png/);
    if(mode==='phase3')assert.equal(await page.locator('.mimic-slot.locked').count(),1);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal page overflow');
    await page.screenshot({path:`output/mimic-review/${mode}-${width}.png`,fullPage:true});
    if(mode==='scroll')assert.equal(await page.locator('[data-raid="skill:plagiarism"]').count(),1);
    if(mode.startsWith('phase2')||mode.startsWith('first_combo')){
     for(let i=0;i<4&&!await page.locator('.qte-window').count();i++){
      const guard=page.locator('[data-raid="skill:defend"]');await guard.waitFor();await guard.click();
      await page.waitForTimeout(900);
     }
     try{await page.locator('.qte-window').waitFor({timeout:10000});}catch(e){console.error(errors,await page.locator('#toast').textContent());await page.screenshot({path:'output/mimic-review/qte-failure.png',fullPage:true});throw e;}
     await page.screenshot({path:`output/mimic-review/stitched-${mode}-${width}.png`,fullPage:true});
     await page.locator('.qte-abort').click();await page.waitForTimeout(600);
    }
   }
   await page.goto(origin+'/mimic-music');
   for(const phase of [1,2,3]){
    await page.locator('[data-phase="'+phase+'"]').click();
    assert.equal(await page.locator('[data-phase][aria-pressed="true"]').count(),1);
   }
   await page.screenshot({path:`output/mimic-review/music-${width}.png`,fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.locator('#stop').click();
   assert.deepEqual(errors,[]);console.log('PASS mimic battle, phases, memory, shared QTE, background and music',width);await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
