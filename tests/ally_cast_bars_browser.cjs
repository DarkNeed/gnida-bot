const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8165';
const output='output/enemy-casts-review';

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync(output,{recursive:true});
 try{
  for(const width of [1200,390]){
   const a=await browser.newPage({viewport:{width,height:900},isMobile:width<500,hasTouch:width<500});
   const b=await browser.newPage();
   const errors=[];
   for(const p of [a,b])p.on('pageerror',e=>errors.push(e.message));
   await a.goto(origin+'/live-queue-review?mode=party&qte=0');
   const cut=a.locator('[data-raid="skill:assassin_cut"]');
   await cut.waitFor();
   await b.goto(a.url()+'&actor=20');
   const heal=b.locator('[data-raid="skill:priest_heal"]');
   await heal.waitFor();
   assert.equal(await a.locator('.ally-cast').count(),0);
   assert.match(await a.locator('#raid-fighter-20 .raid-ready').innerText(),/Выбирает навык/);

   await cut.click();
   const first=b.locator('#raid-fighter-10 .ally-cast');
   await first.waitFor();
   assert.equal(await b.locator('.ally-cast').count(),1);
   assert.match(await first.innerText(),/^\d+(,\d+)?\s+с$/);
   assert.equal(await first.getByRole('progressbar').getAttribute('aria-valuenow'),'0');
   assert.match(await first.getByRole('progressbar').getAttribute('aria-label'),/Действие союзника$/);
   assert.equal(await first.locator('.enemy-cast-name,[title],[data-skill]').count(),0);
   assert.equal(await a.locator('#raid-fighter-10 .ally-cast').count(),0,'no duplicate self timer');
   const privateState=await b.evaluate(async()=>{
    const token=new URLSearchParams(location.search).get('tgWebAppStartParam').slice(2);
    const {data}=await fetch('/api/raid/'+token,{headers:{'X-Telegram-Init-Data':window.Telegram.WebApp.initData}}).then(r=>r.json());
    return {selected:data.players['10'].selected,entry:data.action_queue.entries.find(e=>e.actor==='10')};
   });
   assert.equal(privateState.selected,null);
   assert.equal(privateState.entry.skill,null);
   assert(privateState.entry.at>0);
   await b.waitForTimeout(400);
   assert.equal(await first.getByRole('progressbar').getAttribute('aria-valuenow'),'0');

   await heal.click();
   const second=a.locator('#raid-fighter-20 .ally-cast'),bar=second.getByRole('progressbar');
   await a.waitForFunction(()=>+document.querySelector('#raid-fighter-20 .ally-cast [role=progressbar]')?.getAttribute('aria-valuenow')>0
      && document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])'));
   const value=+await bar.getAttribute('aria-valuenow');
   assert(value>0&&value<100,value);
   assert.match(await second.innerText(),/^\d+(,\d+)?\s+с$/);
   assert.equal(await second.locator('.enemy-cast-fill').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
   const allyTrack=await bar.boundingBox(),enemyTrack=await a.locator('.enemy-cast-track').first().boundingBox();
   assert.equal(allyTrack.height,3);
   assert(enemyTrack.height>=allyTrack.height);
   await a.locator('.queue-skill-wrap').filter({has:cut}).locator('.queue-info').click();
   assert.equal(await second.locator('.enemy-cast-preview').count(),0);
   assert.equal(await a.locator('.enemy-cast-preview').count(),2);
   assert(await a.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await a.locator('.raid-field').screenshot({path:output+'/allies-'+width+'.png'});
   assert.deepEqual(errors,[]);
   await a.close();await b.close();
  }
  console.log('PASS two views of a real team fight: private skill, timing, live cast progress and mobile layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
