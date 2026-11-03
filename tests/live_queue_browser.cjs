const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8155';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/live-queue-review',{recursive:true});
 const errors=[];
 async function page(width=1280){const p=await browser.newPage({viewport:{width,height:900},isMobile:width<500,hasTouch:width<500});p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});return p;}
 const skill=p=>p.locator('[data-skill="assassin_cut"],[data-raid="skill:assassin_cut"]');
 try{
  for(const width of [1280,390])for(const mode of ['solo','encounter','raid']){
   const p=await page(width);
   await p.goto(origin+'/live-queue-review?mode='+mode+'&qte=0');
   await skill(p).waitFor();
   await p.locator('.queue-info').first().click();
   assert.match(await p.locator('.queue-forecast').innerText(),/времени/);
   assert.equal(await p.locator('.raid-timeline-v3').count(),1);
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await p.screenshot({path:`output/live-queue-review/${mode}-${width}.png`,fullPage:true});
   await skill(p).click();
   await p.waitForTimeout(3300);
   await skill(p).waitFor();
   // No automatic repetition while the human is choosing the next action.
   const before=await p.locator('#round,.raid-log').allTextContents();
   await p.waitForTimeout(2000);
   assert.deepEqual(await p.locator('#round,.raid-log').allTextContents(),before);
   await p.close();
  }
  for(const mode of ['pvp','party']){
   const a=await page(),b=await page();
   await a.goto(origin+'/live-queue-review?mode='+mode+'&qte=0');
   await skill(a).waitFor();
   await b.goto(a.url()+'&actor=20');
   await b.locator('[data-skill="bum_punch"],[data-raid="skill:bum_punch"]').waitFor();
   await skill(a).click();
   await b.locator('[data-skill="bum_punch"],[data-raid="skill:bum_punch"]').click();
   await a.waitForTimeout(4200);
   try{await skill(a).waitFor();}catch(e){console.log(mode,await a.locator('body').innerText(),errors);await a.screenshot({path:'output/live-queue-review/failure-'+mode+'.png',fullPage:true});throw e;}
   assert.equal(await a.locator('.raid-timeline-v3').count(),1);
   await a.close();await b.close();
  }
  const p=await page(390);
  await p.goto(origin+'/live-queue-review?mode=solo&qte=1&defense=block');
  await skill(p).waitFor();await skill(p).click();
  await p.locator('.qte-cover').waitFor();
  await p.screenshot({path:'output/live-queue-review/qte-mobile.png'});
  await p.locator('.qte-abort').click();
  await p.waitForTimeout(1800);
  assert.deepEqual(errors,[]);
  await p.close();
  console.log('PASS production APIs/native UI: solo, encounter, raid, PvP, party; mobile/desktop, forecast, no auto-repeat, native QTE');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
