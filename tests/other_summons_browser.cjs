const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const host=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8170';

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
  await page.goto(host+'/summons-review');
  const gallery=page.locator('.art img');
  assert.equal(await gallery.count(),4);
  await gallery.evaluateAll(nodes=>Promise.all(nodes.map(n=>n.decode())));
  const go=unit=>page.goto(host+'/live-queue-review?mode=summons&qte=0&unit='+unit);
  const summon=kind=>page.locator('.combat-summon[data-kind="'+kind+'"]');
  const use=async id=>{
   const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/raid/')&&r.request().postDataJSON().skill===id);
   await page.locator('[data-raid="skill:'+id+'"]').tap();
   const r=await response;
   assert.equal(r.status(),200);
   return (await r.json()).data;
  };
  await go('skeleton');
  await use('mana_barrier');
  await summon('skeleton').waitFor();
  assert.match(await summon('skeleton').innerText(),/Скелет/);
  await page.locator('.raid-timeline-dot[data-actor*=":skeleton:"]').waitFor();
  await go('servants');
  const state=await use('mana_barrier');
  assert.deepEqual(new Set(Object.values(state.summons).map(u=>u.kind)),new Set(['warden','executioner']));
  await summon('warden').waitFor();
  await summon('executioner').waitFor();
  const left=await summon('warden').boundingBox(),right=await summon('executioner').boundingBox();
  assert(left.x+left.width<=right.x,'both target cards fit on mobile without overlap');
  if(process.env.SUMMON_SCREENSHOT)await page.screenshot({path:process.env.SUMMON_SCREENSHOT,fullPage:true});
  await page.getByRole('button',{name:'Подробности: Страж'}).tap();
  assert.match(await page.getByRole('dialog',{name:'Страж'}).innerText(),/35%/);
  await page.goto(host+'/live-queue-review?mode=summons&qte=0&unit=effigy&ready=1');
  await summon('effigy').waitFor();
  const ward=await use('unfinished_portrait');
  assert.equal(Object.values(ward.summons).find(u=>u.kind==='effigy')?.guarding,20);
  await summon('effigy').locator('.brood-stance').getByText('20%').waitFor();
  const bite=await use('first_stroke');
  assert(bite.action_queue.entries.some(e=>e.skill==='summon_effigy'));
  await page.setViewportSize({width:320,height:740});
  await page.goto(host+'/live-queue-review?mode=summons&qte=0&unit=servants&ready=1');
  await summon('warden').waitFor();
  await summon('executioner').waitFor();
  const cards=await page.locator('.combat-summon').evaluateAll(nodes=>nodes.map(el=>{
   const name=el.querySelector('.brood-title>span'),box=el.getBoundingClientRect();
   return {left:box.left,right:box.right,textFits:name.scrollWidth<=name.clientWidth+1};
  }));
  assert(cards[0].right<=cards[1].left&&cards[0].left>=0&&cards[1].right<=320);
  assert(cards.every(c=>c.textFits),'the two names fit on a 320px screen');
  assert.deepEqual(errors,[]);
 } finally {await browser.close();}
 console.log('Other summons: all four arts and actual Necromancer/Fauvist skills verified on mobile.');
})().catch(e=>{console.error(e);process.exitCode=1;});
