const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8157';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const errors=[];fs.mkdirSync('output/nzd-guardian-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const p=await browser.newPage({viewport:{width,height:width<500?844:1000},isMobile:width<500,hasTouch:width<500});
   p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
   for(const [room,who] of [[3,'gargantua'],[4,'cocytus'],[9,'pleiades'],[10,'pleiades2']]){
    await p.goto(origin+`/nzd-demo?mode=fight&room=${room}&phase=1&party=1`);
    await p.locator('.nzd-field').waitFor();await p.waitForTimeout(400);
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    const field=p.locator('.nzd-field');
    if(who.startsWith('pleiades')){
     const bottoms=await field.locator('.raid-enemy .raid-art').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().bottom));
     assert.equal(bottoms.length,3);assert(Math.max(...bottoms)-Math.min(...bottoms)<2);
    }else{
     if(who==='gargantua')assert.match(await field.locator('.raid-enemy .raid-sprite').getAttribute('src'),/gargantua-v2/);
     const h=await field.locator('.raid-enemy .raid-art').evaluate(n=>n.getBoundingClientRect().height);
     assert(h>180);
    }
    await p.screenshot({path:`output/nzd-guardian-review/${who}-${width}.png`,fullPage:true});
    await p.locator('[data-raid="inspect:e1"]').click();
    await p.locator('dialog[open]').waitFor();
    const text=await p.locator('dialog[open]').innerText();assert.match(text,/Легендарный|Эпический/);assert.match(text,/Пассив/);
   }
   await p.close();
  }
  for(const [who,room,defense] of [['cocytus',4,'dodge'],['cocytus',4,'block'],['narberal',9,'dodge'],['mare',5,'block']]){
   const p=await browser.newPage({viewport:{width:1100,height:900}});p.on('pageerror',e=>errors.push(e.message));
   await p.goto(origin+`/nzd-demo?mode=pattern&who=${who}&room=${room}&phase=2&move=4&defense=${defense}`);
   await p.locator('.qte-cover').waitFor();await p.waitForTimeout(1600);
   await p.screenshot({path:`output/nzd-guardian-review/${who}-${defense}.png`});
   await p.close();
  }
  assert.deepEqual(errors,[]);
  console.log('PASS guardian formation, scale, rarity/passives, mobile/desktop, native dodge/block signature patterns');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
