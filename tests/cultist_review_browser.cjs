const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8168';
const branches={
 'Ктулху':['cult_depths','arch_cultist_cthulhu','Звёздное отродье Р’льеха'],
 'Йог-Сотот':['cult_gate','arch_cultist_yog','Дитя Врат'],
 'Шуб-Нигуррат':['cult_brood','arch_cultist_shub','Тёмное дитя Чёрного Козла'],
 'Хастур':['cult_yellow','arch_cultist_hastur','Живая маска Каркозы'],
};

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const context=await browser.newContext({viewport:{width:390,height:840},isMobile:true,hasTouch:true});
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/'))errors.push(r.status()+' '+r.url());});
  await page.goto(origin+'/cultist-review');
  const trials=await page.locator('a[href^="/qte-lab/unique/"]').evaluateAll(links=>links.map(link=>link.href));
  assert.equal(trials.length,9,'all damaging skills have a dedicated training link');
  const lab=await context.newPage();
  lab.on('pageerror',e=>errors.push(e.message));
  await lab.bringToFront();
  for(const link of trials){
   const id=new URL(link).searchParams.get('skill');
   await lab.goto(link);
   assert.equal(await lab.locator('[data-mode=defense]').getAttribute('aria-pressed'),'true');
   assert.equal((await lab.locator('#skill').inputValue()).split(':')[0],id);
   await lab.locator('#start').click();
   await lab.locator('#game[data-phase=defense]').waitFor();
   const time=lab.locator('#phase-time'), resume=lab.locator('#resume');
   for(let pulse=0;pulse<4;pulse++){
    await lab.waitForFunction(()=>!document.querySelector('#resume').hidden||
      parseFloat(document.querySelector('#phase-time').textContent)<=6.2,null,{timeout:6000});
    if(await resume.isVisible())await resume.click();
    else break;
   }
   const remaining=await time.textContent();
   assert(parseFloat(remaining)<=6.2,id+' reaches the active attack: '+remaining);
   assert.equal(await lab.locator('canvas:visible').count(),1,id+' displays a battle field');
   if(id==='arch_cultist_hastur'){
    // A dropped frame in a visible WebView must not leave the game paused.
    await lab.evaluate(()=>{window.dispatchEvent(new Event('blur'));const until=performance.now()+420;while(performance.now()<until){}});
    await lab.waitForFunction(()=>!document.querySelector('#resume').hidden||
      document.querySelector('#phase-time').textContent==='ИТОГ',null,{timeout:12000});
    assert.equal(await resume.isVisible(),false,'Carcosa keeps running after a slow foreground frame');
    assert.equal(await time.textContent(),'ИТОГ','Carcosa closes with a result');
   }
   if(id==='cult_rite'){
    await lab.evaluate(()=>{window.requestAnimationFrame=()=>0;});
    await lab.waitForFunction(()=>document.querySelector('#phase-time').textContent==='ИТОГ',
      null,{timeout:17000,polling:100});
    assert.equal(await resume.isVisible(),false,'Ritual ends even if the WebView stops sending animation frames');
    assert.equal(await lab.locator('#qte-outcome').isVisible(),true,'result is visible over the arena instead of a frozen final frame');
    assert.equal(await lab.locator('#start').isEnabled(),true,'Ritual can be restarted after the result');
   }
   assert.deepEqual(errors,[],id);
  }
  await lab.close();
  const skill=id=>page.locator('[data-raid="skill:'+id+'"]');
  for(const [name,[starter,finisher,form]] of Object.entries(branches)){
   await page.goto(origin+'/cultist-review');
   const card=page.locator('article').filter({has:page.getByRole('heading',{name,exact:true})});
   assert.match(await card.innerText(),/ур\. 10[\s\S]*ур\. 15/);
   assert((await card.getByRole('link',{name:'Уклонение',exact:true}).count())>0,name+' доступен в лаборатории');
   assert.equal(await card.getByRole('heading',{name:form,exact:true}).count(),1);
   const avatar=await card.locator('.final-form img').getAttribute('src');
   assert.match(avatar,/^\/static\/assets\/archclasses\/cultist_[a-z]+_final\.png$/);
   const human=await card.locator('.human-form img').getAttribute('src');
   assert.equal(human,'/static/assets/archclasses/'+finisher.slice(5)+'.png');
   await card.getByRole('link',{name:'Бой на 10 уровне',exact:true}).click();
   await skill(starter).waitFor();
   const untransformed=page.locator('#raid-fighter-10');
   assert((await untransformed.innerText()).includes('Культист Бездны · '+name+' · Lv.10'));
   assert.equal(await untransformed.locator('.raid-sprite').getAttribute('src'),human);
   await untransformed.locator('.raid-sprite').evaluate(el=>el.decode());
   assert.equal(await page.locator('[data-status-id="cult:form"]').count(),0);
   assert.equal(await skill(finisher).count(),0);
   await page.goto(origin+'/cultist-review');
   await card.getByRole('link',{name:'Быстрый бой'}).click();
   await skill(starter).waitFor();
   assert(await skill(starter).isEnabled(),name);
   assert(!(await skill(finisher).isEnabled()),name+' требует подготовки');
   const fighter=page.locator('#raid-fighter-10');
   assert.match(await fighter.innerText(),new RegExp(form));
   const sprite=fighter.locator('.raid-sprite');
   assert.equal(await sprite.getAttribute('src'),avatar);
   await sprite.evaluate(el=>el.decode());
   assert.equal(await page.locator('[data-status-id="cult:form"]').count(),1);
   assert.equal(await page.locator('.raid-timeline-v3').count(),1);
   const colors=await page.evaluate(()=>[...document.querySelectorAll('.raid-timeline-dot')].map(marker=>{
    const dot=document.querySelector('.raid-order-dot[data-order-actor="'+marker.dataset.actor+'"]');
    return !!dot&&getComputedStyle(dot).backgroundColor===getComputedStyle(marker).backgroundColor;
   }));
   assert(colors.length>=2&&colors.every(Boolean),'same colors on compact enemy HUD and timeline');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await skill(starter).click();
   await page.waitForFunction(id=>!!document.querySelector('[data-raid="skill:'+id+'"] small')?.textContent.includes('ещё'),starter);
   if(starter==='cult_gate'){
    assert.equal(await page.locator('[data-status-id="cult:fanaticism"]').innerText(),'2/3');
    assert.equal(await page.locator('[data-status-id="effect:cult_gate_open:cult_gate_open"]').count(),1);
   }
   if(starter==='cult_brood'){
    const brood=page.locator('[data-status-id="cult:brood"]');
    await brood.waitFor();
    assert.match(await brood.innerText(),/\d+\/30/);
    await brood.click();
    await page.getByText('Стадия 1 / 3.',{exact:false}).waitFor();
   }
  }
  await page.goto(origin+'/cultist-review');
  const base=page.locator('.base-cultist');
  assert.equal(await base.locator('img').getAttribute('src'),'/static/assets/cultist.png');
  await base.getByRole('link',{name:'Бой базовым культистом',exact:true}).click();
  await skill('cult_sign').waitFor();
  assert.match(await page.locator('#raid-fighter-10').innerText(),/Культист Бездны · Lv.8/);
  assert.equal(await page.locator('#raid-fighter-10 .raid-sprite').getAttribute('src'),'/static/assets/cultist.png');
  await page.locator('#raid-fighter-10 .raid-sprite').evaluate(el=>el.decode());
  assert.equal(await page.locator('[data-status-id="cult:form"]').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS nine dodge demos, four patron sprites at both stages and the base cultist sprite in mobile battles');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
