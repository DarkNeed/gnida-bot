const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8164';
const output='output/enemy-casts-review';

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync(output,{recursive:true});
 const errors=[];
 try{
  for(const width of [1240,390]){
   const p=await browser.newPage({viewport:{width,height:930},isMobile:width<500,hasTouch:width<500});
   p.on('pageerror',e=>errors.push(e.message));
   p.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
   await p.goto(origin+'/live-queue-review?mode=bars&qte=0');
   const bars=p.locator('.enemy-cast'),cut=p.locator('[data-raid="skill:assassin_cut"]');
   const cast=key=>p.locator('#raid-fighter-'+key+' > .enemy-cast');
   const values=()=>bars.getByRole('progressbar').evaluateAll(nodes=>nodes.map(n=>+n.getAttribute('aria-valuenow')));
   await cut.waitFor();
   assert.equal(await bars.count(),2);
   assert.equal(await p.locator('.raid-timeline').count(),0);
   const names=await bars.locator('.enemy-cast-name').allTextContents();
   assert(names.every(n=>n&&n!=='Действие'),names);
   assert.notDeepEqual(await cast('e1').locator('.enemy-cast-time').innerText(),await cast('e2').locator('.enemy-cast-time').innerText());
   assert.equal(await p.locator('.raid-intent-lines').count(),0,'intents are hidden in 1 vs 2');
   const colors=await bars.locator('.enemy-cast-fill').evaluateAll(nodes=>nodes.map(n=>getComputedStyle(n).backgroundColor));
   assert.deepEqual(colors,['rgb(255, 255, 255)','rgb(255, 255, 255)'],'all cast bars are white');
   assert.deepEqual(await values(),[0,0]);
   await p.waitForTimeout(600);
   assert.deepEqual(await values(),[0,0],'idle wall time must not advance the bars');

   const info=p.locator('.queue-skill-wrap').filter({has:cut}).locator('.queue-info');
   await info.click();
   assert.equal(await p.locator('.enemy-cast-preview').count(),2);
   assert.match(await p.locator('.queue-forecast').innerText(),/Ты успеешь первым/);
   await cut.click();
   await p.waitForFunction(()=>document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])')
      && Array.from(document.querySelectorAll('.enemy-cast-track')).every(n=>+n.getAttribute('aria-valuenow')>0));
   const filled=await values();
   assert(filled[0]>filled[1]&&filled[1]>0,filled);
   await info.click();
   assert.equal(await cast('e1').getAttribute('data-forecast'),'after');
   assert.equal(await cast('e2').getAttribute('data-forecast'),'before');
   assert.match(await p.locator('.queue-forecast').innerText(),/Раньше тебя: Гоблин/);
   assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   for(const key of ['e1','e2']){
    const strip=await cast(key).boundingBox(),art=await p.locator('#raid-fighter-'+key+' .raid-art').boundingBox();
    assert(strip.y>=art.y+art.height-2,[key,strip,art]);
   }
   await p.locator('.raid-field').screenshot({path:output+'/'+width+'.png'});
   await cut.click();
   await p.waitForFunction(previous=>{
    const nodes=[...document.querySelectorAll('.enemy-cast-track')],next=nodes.map(n=>+n.getAttribute('aria-valuenow'));
    return document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])')
      && next[0]<previous[0]&&next[1]>previous[1];
   },filled);
   const after=await values();
   assert(after[0]<filled[0]&&after[1]>filled[1],JSON.stringify({filled,after}));
   await p.close();
  }
  const solo=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  solo.on('pageerror',e=>errors.push(e.message));
  await solo.goto(origin+'/live-queue-review?mode=solo&qte=1');
  await solo.locator('.battle .field > .enemy-cast').waitFor();
  await solo.locator('[data-skill=assassin_cut]').click();
  await solo.locator('.qte-cover').waitFor();
  assert.equal(await solo.locator('.raid-timeline').count(),0);
  await solo.close();
  const party=await browser.newPage();
  party.on('pageerror',e=>errors.push(e.message));
  await party.goto(origin+'/live-queue-review?mode=party&qte=0');
  await party.locator('.raid-intent-link').first().waitFor();
  await party.close();
  for(const boss of ['lei_heng','mimic']){
   const p=await browser.newPage({viewport:{width:1200,height:960},reducedMotion:'reduce'});
   p.on('pageerror',e=>errors.push(e.message));
   await p.goto(origin+'/live-queue-review?mode=raid&qte=0&boss='+boss);
   const bar=p.locator('#raid-fighter-boss > .enemy-cast');
   await bar.waitFor();
   assert.equal(await bar.locator('.enemy-cast-fill').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
   assert.equal(await p.locator('.raid-intent-lines').count(),0);
   await p.locator('[data-raid="skill:assassin_cut"]').click();
   await p.waitForFunction(()=>document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])')
     && +document.querySelector('#raid-fighter-boss .enemy-cast-track')?.getAttribute('aria-valuenow')>0
     && !document.querySelector('#raid-fighter-boss .enemy-cast.is-resolving'));
   const strip=await bar.boundingBox(),art=await p.locator('#raid-fighter-boss .raid-art').boundingBox();
   assert(strip.y>=art.y+art.height-2,JSON.stringify({boss,strip,art}));
   await p.locator('.raid-field').screenshot({path:output+'/'+boss+'.png'});
   await p.close();
  }
  assert.deepEqual(errors,[]);
  console.log('PASS real fight: mobile and desktop bars, idle pause, cast forecast, enemy action and reset');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
