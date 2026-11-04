const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8157',out='output/nzd-revision-review';
(async()=>{
 fs.mkdirSync(out,{recursive:true});const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const p=await b.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});p.on('pageerror',e=>errors.push(e.message));
  await p.goto(origin+'/nzd-demo?mode=fight&room=3&phase=2');await p.locator('.raid-enemy .raid-sprite').waitFor();
  assert(await p.locator('.raid-enemy .raid-sprite').evaluate(n=>getComputedStyle(n).scale.startsWith('-1')),'Gargantua must actually be mirrored relative to the rejected pose');
  await p.locator('[data-combat-open]').click();
  await p.locator('button[data-joystick-side=right]').waitFor();assert.equal(await p.locator('button[data-joystick-side=right]').getAttribute('aria-pressed'),'true');
  await p.locator('button[data-joystick-side=left]').click();await p.locator('[data-combat-close]').click();await p.reload();
  await p.locator('[data-combat-open]').click();await p.locator('button[data-joystick-side=left]').waitFor();assert.equal(await p.locator('button[data-joystick-side=left]').getAttribute('aria-pressed'),'true');
  await p.locator('button[data-joystick-side=right]').click();await p.screenshot({path:out+'/settings-mobile.png'});await p.locator('[data-combat-close]').click();
  await p.locator('.queue-info').first().click();const range=p.locator('.raid-timeline-preview-range');await range.waitFor();assert((await range.boundingBox()).width>15);await p.screenshot({path:out+'/cast-range-mobile.png'});
  await p.goto(origin+'/nzd-demo?mode=pattern&room=3&who=gargantua&phase=2&move=0&defense=dodge');await p.locator('.qte-cover').waitFor();
  const canvas=await p.locator('.qte-cover canvas').boundingBox(),right=await p.locator('.qte-cover .qte-stick').boundingBox();assert(right.x+right.width/2>canvas.x+canvas.width/2);
  await p.screenshot({path:out+'/gargantua-mobile.png'});await p.evaluate(()=>QTETouch.setSide('left'));
  const left=await p.locator('.qte-cover .qte-stick').boundingBox();assert(left.x+left.width/2<canvas.x+canvas.width/2);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await p.screenshot({path:out+'/stick-left-mobile.png'});await p.evaluate(()=>QTETouch.setSide('right'));await p.close();
  for(const [who,room,phase,move]of[['cocytus',4,1,2],['cocytus',4,2,2],['cocytus',4,2,4],['aura',5,1,1],['mare',5,2,4],['sebas',11,1,2],['sebas',11,2,4],['victim',7,2,4]]){
   const page=await b.newPage({viewport:{width:1100,height:900}});page.on('pageerror',e=>errors.push(e.message));
   await page.goto(origin+`/nzd-demo?mode=pattern&who=${who}&room=${room}&phase=${phase}&move=${move}`);await page.locator('.qte-cover').waitFor();await page.waitForTimeout(who==='cocytus'&&move===2?1750:2200);await page.screenshot({path:out+`/${who}-${phase}-${move}.png`});await page.close();
  }
  for(const mode of ['dodge','block']){
   const page=await b.newPage({viewport:{width:1100,height:900}});page.on('pageerror',e=>errors.push(e.message));
   await page.goto(origin+'/nzd-demo?mode=fight&room=9&phase=1&defense='+mode);
   await page.locator('[data-raid="skill:mana_shot"]').click();await page.locator('.qte-abort').click();
   await page.waitForFunction(()=>document.querySelector('.qte-cover h2')?.textContent.includes('Юри')&&document.querySelector('.qte-cover h2')?.textContent.includes('Нарберал'));
   const title=await page.locator('.qte-cover h2').innerText();assert.match(title,/Люпусрегина/);
   await page.waitForTimeout(1800);await page.screenshot({path:out+'/pleiades-joint-'+mode+'.png'});await page.close();
  }
  assert.deepEqual(errors,[]);console.log('PASS handedness, settings persistence, duration line, revised native QTEs, mobile layout');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
