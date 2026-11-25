const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const host=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8169';
const test='/live-queue-review?mode=cultist&patron=cultist_shub&qte=0';

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
  await page.goto(host+'/cultist-review');
  const icons=page.locator('.status-preview img');
  assert.equal(await icons.count(),7);
  await icons.evaluateAll(nodes=>Promise.all(nodes.map(img=>img.decode())));
  await page.goto(host+test+'&summon=1');
  const brood=page.locator('.combat-summon');
  await brood.waitFor();
  const img=brood.locator('img');
  await img.evaluate(el=>el.decode());
  const initial=await page.locator('.raid-intent').innerText();
  assert.match(initial,/Гоблин[^\n]+Отпрыск/i);
  assert.match(await brood.innerText(),/Защитник\s+30\/30 HP/);
  assert.equal(await page.locator('.raid-field .raid-ally').count(),1);
  const field=await page.locator('.raid-field').boundingBox(),bounds=await brood.boundingBox();
  assert(bounds.x>=field.x&&bounds.x+bounds.width<=field.x+field.width);
  await brood.getByRole('button',{name:'Подробности: отпрыск'}).click();
  const details=page.getByRole('dialog',{name:'Отпрыск Шуб-Ниггурата'});
  await details.waitFor();
  assert.match(await details.innerText(),/30%/);
  await details.getByRole('button',{name:'Закрыть подробности'}).click();
  assert.match(await brood.locator('.brood-stance image').getAttribute('href'),/brood_guard\.png$/);
  assert.match(await page.locator('[data-status-id="cult:fanaticism"] image').getAttribute('href'),/cult_fanaticism\.png$/);
  await page.evaluate(()=>{
    window.broodWatch={image:document.querySelector('.brood-sprite'),missing:0,replaced:0};
    const sample=()=>{
      const img=document.querySelector('.brood-sprite'),watch=window.broodWatch;
      if(!img)watch.missing++;
      else if(img!==watch.image)watch.replaced++;
      watch.raf=requestAnimationFrame(sample);
    };
    sample();
  });
  const raidIntercept=()=>page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/raid/')
    &&r.request().postDataJSON().action==='intercept');
  let intercepted=raidIntercept();
  await page.getByRole('button',{name:/Взять удар на себя/}).click();
  assert.deepEqual((await (await intercepted).json()).data.enemy_intents.e1.targets,['10']);
  intercepted=raidIntercept();
  await page.getByRole('button',{name:'Отменить перехват'}).click();
  assert.match((await (await intercepted).json()).data.enemy_intents.e1.targets[0],/^brood:10:/);
  if(process.env.SUMMON_SCREENSHOT)await page.screenshot({path:process.env.SUMMON_SCREENSHOT,fullPage:true});
  const raidPost=skill=>page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/raid/')
    &&r.request().postDataJSON().skill===skill);
  const shift=raidPost('arch_cultist_shub');
  await page.locator('[data-raid="skill:arch_cultist_shub"]').click();
  assert.equal((await shift).status(),200);
  await page.waitForFunction(()=>document.querySelector('.brood-meta')?.textContent.includes('Хищник'));
  await page.waitForFunction(()=>document.querySelector('.raid-timeline-dot[data-actor^="brood:"]'));
  assert.match(await brood.locator('.brood-stance image').getAttribute('href'),/brood_predator\.png$/);
  const roots=page.locator('[data-raid="skill:cult_roots"]');
  const cast=raidPost('cult_roots');
  await roots.click();
  const result=await cast;
  assert.equal(result.status(),200);
  const castState=(await result.json()).data;
  assert(castState.log.some(e=>e.skill==='cult_roots'),JSON.stringify({log:castState.log.map(e=>[e.actor,e.target,e.skill,e.text]),summons:castState.summons}));
  await page.waitForFunction(()=>document.querySelector('.raid-log')?.textContent.includes('Корни Чёрного козла')&&
    document.querySelector('[data-raid="skill:cult_roots"]')?.disabled);
  assert.deepEqual(await page.evaluate(()=>{
    const watch=window.broodWatch;cancelAnimationFrame(watch.raf);
    return [watch.missing,watch.replaced];
  }),[0,0],'a living offspring remains the same image through the actual rendered frames');
  assert.deepEqual(errors,[]);
  await page.goto(host+test);
  const contact=page.locator('[data-raid="skill:cult_brood"]');
  await contact.waitFor();
  assert.equal(await brood.count(),0);
  await contact.click();
  await brood.waitFor();
  assert.match(await brood.innerText(),/Защитник/);
  assert.equal(await contact.isDisabled(),true);
  assert.deepEqual(errors,[]);
  // Keep the two real touch targets, but let Playwright wait for a stable
  // hitbox without the enemy sprite's continuous breathing animation.
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto(host+'/live-queue-review?mode=solo&summon=opponent&qte=0');
  const target=page.getByRole('button',{name:/Выбрать цель: Отпрыск/});
  await target.waitFor();
  await target.click();
  assert.equal(await target.getAttribute('aria-pressed'),'true');
  const owner=page.locator('img[data-battle-target="b"]');
  assert.equal(await owner.getAttribute('aria-pressed'),'false');
  await owner.tap();
  assert.equal(await owner.getAttribute('aria-pressed'),'true');
  assert.equal(await target.getAttribute('aria-pressed'),'false');
  await target.tap();
  assert.equal(await target.getAttribute('aria-pressed'),'true');
  const submitted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/battle/'));
  await page.locator('[data-skill="assassin_cut"]').click();
  const attack=await submitted;
  assert.equal(attack.status(),200);
  const body=attack.request().postDataJSON();
  assert.match(body.target,/^brood:b:/);
  assert((await attack.json()).state.log.some(e=>e.target===body.target&&e.skill_id==='assassin_cut'));
  assert.deepEqual(errors,[]);
  await page.goto(host+'/live-queue-review?mode=solo&patron=cultist_shub&summon=self&qte=0');
  const battleIntercept=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/battle/')
    &&r.request().postDataJSON().action==='intercept');
  await page.getByRole('button',{name:/Взять удар на себя/}).tap();
  const alternate=await battleIntercept;
  assert.equal(alternate.status(),200);
  assert((await alternate.json()).state.action_queue.entries.some(e=>e.actor==='b'&&e.targets[0]==='a'&&e.original_target.startsWith('brood:a:')));
  assert.deepEqual(errors,[]);
  await page.goto(host+'/live-queue-review?mode=party&patron=cultist_shub&summon=1&qte=0');
  const line=page.getByRole('button',{name:/Гоблин.*Отпрыск.*Взять на себя/});
  await line.waitFor();
  const partyCover=raidIntercept();
  await line.press('Enter');
  assert.deepEqual((await (await partyCover).json()).data.enemy_intents.e1.targets,['10']);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
 console.log('Summon: stable render, icons, tap targeting and intercept/undo verified.');
})().catch(e=>{console.error(e);process.exitCode=1;});
