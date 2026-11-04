const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8154';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/unified-queue-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:width===390?844:1000},isMobile:width===390,hasTouch:width===390});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   page.on('response',r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url());});
   await page.goto(origin+'/queue-lab');
   const cut=page.locator('[data-skill="assassin_cut"]');await cut.waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await page.locator('[data-info="0"]').click();
   assert.match(await page.locator('#forecast').innerText(),/Успеешь|одновременно|раньше/);
   assert.equal(await page.locator('.ghost').count(),1);
   await page.screenshot({path:`output/unified-queue-review/forecast-${width}.png`,fullPage:true});
   await cut.click();await page.locator('.qte-cover').waitFor();
   await page.locator('.qte-abort').click();
   await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Выбери следующее'));
   assert.equal(await page.locator('#log li').count(),1);
   await page.waitForTimeout(1200);
   assert.equal(await page.locator('#log li').count(),1);
   await page.locator('#scenario').selectOption('sync');await page.locator('#reset').click();
   await page.waitForFunction(()=>document.querySelector('#clock').textContent.includes('0,00'));
   await page.screenshot({path:`output/unified-queue-review/battle-${width}.png`,fullPage:true});
   assert.deepEqual(errors,[]);
   await page.close();
  }
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/queue-lab');await page.locator('[data-skill="assassin_cut"]').waitFor();
  await page.locator('#scenario').selectOption('sync');await page.locator('#reset').click();
  await page.waitForTimeout(300);
  // Queue short casts until the two pending enemy attacks reach completion.
  for(let i=0;i<4;i++){
   await page.locator('[data-skill="assassin_cut"]').click();await page.locator('.qte-cover').waitFor();
   const title=await page.locator('.qte-eyebrow').innerText();
   if(title.includes('СОВМЕСТНАЯ'))break;
   await page.locator('.qte-abort').click();
   await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Выбери следующее')||document.querySelector('.qte-eyebrow')?.textContent.includes('СОВМЕСТНАЯ'));
   if(await page.locator('.qte-cover').count())break;
  }
  assert.match(await page.locator('.qte-eyebrow').innerText(),/СОВМЕСТНАЯ/);
  await page.screenshot({path:'output/unified-queue-review/combined.png'});
  assert.deepEqual(errors,[]);
  await page.close();
  const party=await browser.newPage({viewport:{width:1280,height:1000}});
  await party.goto(origin+'/queue-lab');await party.locator('[data-skill="assassin_cut"]').waitFor();
  await party.locator('#scenario').selectOption('party');await party.locator('#reset').click();
  await party.waitForTimeout(250);
  await party.locator('[data-skill="assassin_cut"]').click();
  await party.locator('[data-skill="armor_split"]').waitFor();
  await party.locator('[data-skill="armor_split"]').click();
  await party.locator('.qte-cover').waitFor();await party.locator('.qte-abort').click();
  await party.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Выбери следующее'));
  assert.equal(await party.locator('[data-actor="h2"]').isDisabled(),true);
  assert.equal(await party.locator('[data-skill="assassin_cut"]').isEnabled(),true);
  await party.screenshot({path:'output/unified-queue-review/party.png',fullPage:true});
  await party.close();
  console.log('PASS desktop/mobile layout, forecast, real attack QTE, no auto repeat, combined defense, party choice after fast cast');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
