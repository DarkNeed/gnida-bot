const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.CHEST_MIMIC_URL||'http://127.0.0.1:8160';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/guild-scenery-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:1000},isMobile:width===390,hasTouch:width===390}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   page.on('response',r=>{if(r.status()>=400&&r.url().includes('/static/assets/guild/'))errors.push(r.status()+' '+r.url());if(r.status()>=500)errors.push(r.status()+' '+r.url());});
   await page.goto(origin+'/chest-mimic-demo?mode=mimic&rank=C');
   await page.locator('.guild-room-scenery[data-scenery=hall]').waitFor();
   assert.match(await page.locator('.guild-room-scenery').evaluate(e=>getComputedStyle(e).backgroundImage),/hall-v1\.png/);
   await page.screenshot({path:`output/guild-scenery-review/chest-event-${width}.png`,fullPage:true});
   await page.reload();await page.locator('.guild-room-scenery[data-scenery=hall]').waitFor();
   await page.locator('[data-guild="choice:open"]').click();await page.locator('[data-guild="battle"]').click();
   await page.locator('.guild-field[data-scenery=hall]').waitFor();
   await page.locator('.raid-sprite[src*="chest_mimic-v2.png"]').waitFor();
   assert.equal(await page.locator('.raid-sprite[src*="chest_mimic-v2.png"]').evaluate(e=>getComputedStyle(e).objectPosition),'50% 100%');
   assert.match(await page.locator('.guild-field').evaluate(e=>getComputedStyle(e).backgroundImage),/hall-v1\.png/);
   assert.equal(await page.locator('.guild-field').evaluate(e=>getComputedStyle(e).backgroundSize),'cover');
   const compact=page.locator('.encounter-enemy .encounter-compact-hud');await compact.waitFor();
   assert.equal(await compact.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
   assert.equal(await compact.locator('strong,.muted').count(),0);
   const hudStyle=await page.locator('.guild-field').evaluate(field=>{
    const enemy=field.querySelector('.enemy-0'),art=enemy.querySelector('.raid-art').getBoundingClientRect(),hud=enemy.querySelector('.encounter-compact-hud').getBoundingClientRect(),effects=enemy.querySelector('.raid-effects').getBoundingClientRect(),bar=enemy.querySelector('.encounter-compact-hud .bar'),ally=field.querySelector('.raid-ally'),allyBar=ally.querySelector('.raid-hud .bar'),allyImage=ally.querySelector('.raid-sprite');
    return {below:hud.top>=art.bottom,effectsBelow:effects.top>=hud.bottom,barHeight:getComputedStyle(bar).height,allyBarHeight:getComputedStyle(allyBar).height,outline:getComputedStyle(bar).outlineStyle,fill:getComputedStyle(bar.firstElementChild).backgroundImage,allyFill:getComputedStyle(allyBar.firstElementChild).backgroundImage,allyArtHeight:ally.querySelector('.raid-art').getBoundingClientRect().height,allyImageWidth:allyImage.getBoundingClientRect().width,allyBoxWidth:ally.querySelector('.raid-art').getBoundingClientRect().width};
   });
   assert(hudStyle.below&&hudStyle.effectsBelow,'Health and effects stay below the enemy');
   assert.equal(hudStyle.barHeight,hudStyle.allyBarHeight);assert.equal(hudStyle.outline,'none');assert.equal(hudStyle.fill,hudStyle.allyFill);
   assert(hudStyle.allyArtHeight>=(width===390?150:200),'Restore the player art container');
   if(width===390)assert(hudStyle.allyImageWidth/hudStyle.allyBoxWidth>.9,'Phone player sprite no longer shrinks twice');
   const ground=await page.locator('.guild-field').evaluate(f=>{const r=f.getBoundingClientRect(),g=f.querySelector('.enemy-0 .raid-ground').getBoundingClientRect();return(g.y+g.height/2-r.y)/r.height;});
   assert(ground>.52&&ground<.65,'Enemy stands on the existing stone floor');
   await compact.locator('[data-raid="inspect:e1"]').click();await page.locator('#raid-details[open]').waitFor();
   assert((await page.locator('#raid-details').innerText()).includes('Сундук-мимик'));
   await page.locator('#raid-details [data-close-raid]').click();
   await page.locator('.guild-field').screenshot({path:`output/guild-scenery-review/mimic-hall-${width}.png`});
   await page.reload();await page.locator('[data-guild="battle"]').click();await page.locator('.guild-field[data-scenery=hall]').waitFor();
   for(const [rank,expected] of [['C','catacombs'],['F','cavern'],['D','biome'],['A','biome']]){
    await page.goto(origin+'/chest-mimic-demo?mode=battle&room=battle&rank='+rank);
    const field=page.locator('.guild-field[data-scenery='+expected+']');await field.waitFor();
    const bg=await field.evaluate(e=>getComputedStyle(e).backgroundImage);
    if(expected==='biome')assert(!bg.includes('/guild/backgrounds/'));
    else{
     assert(bg.includes(expected+'-v1.png'),bg);
     const path='/static/assets/guild/backgrounds/'+expected+'-v1.png';
     assert(await page.evaluate(async path=>{const i=new Image();i.src=path;await i.decode();return i.naturalWidth>1000&&i.naturalHeight>600;},path));
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await field.screenshot({path:`output/guild-scenery-review/${rank}-${expected}-${width}.png`});
   }
   await page.goto(origin+'/chest-mimic-demo?mode=battle&room=boss&rank=C');
   await page.locator('.guild-field[data-scenery=hall]').waitFor();
   assert.equal(await page.locator('.encounter-enemy .encounter-compact-hud').count(),0);
   await page.locator('.encounter-enemy .raid-hud strong').waitFor();
   assert.notEqual(await page.locator('.encounter-enemy .raid-hud').evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
   await page.locator('.guild-field').screenshot({path:`output/guild-scenery-review/boss-full-card-${width}.png`});
   await page.goto(origin+'/chest-mimic-review');await page.frameLocator('iframe').locator('[data-guild="choice:open"]').waitFor();
   assert.equal(await page.locator('[data-scenery-demo]').count(),5);
   assert.deepEqual(errors,[]);console.log('PASS saved room backgrounds, approved mimic sprite, original biomes and mobile layout',width);await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
