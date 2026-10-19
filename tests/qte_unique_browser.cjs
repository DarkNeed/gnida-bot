const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
const {chromium}=require('playwright');const origin=process.env.QTE_UNIQUE_URL||'http://127.0.0.1:8107';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const output=path.join(__dirname,'../output/qte-unique');fs.mkdirSync(output,{recursive:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET'||r.url().includes('/api/'))writes.push(r.url());});
    await page.goto(origin+'/qte-lab/unique/');await page.locator('#skill option').first().waitFor({state:'attached'});
    assert((await page.locator('#skill option').count())>=200);
    await page.screenshot({path:path.join(output,'desktop-catalog.png'),fullPage:true});
    const families=await page.locator('#family-filter option').evaluateAll(nodes=>nodes.map(n=>n.value).filter(Boolean));
    for(const family of families){
      await page.selectOption('#family-filter',family);await page.locator('#start').click();
      await page.waitForTimeout(1050);
      assert.equal(await page.locator('#game').getAttribute('data-phase'),'defense');
      if(['tiger','train','charm','void','eclipse','paint'].includes(family))await page.screenshot({path:path.join(output,family+'.png')});
      await page.locator('#stop').click();
    }
    console.log('PASS rendered every defense family',families.length);
    await page.selectOption('#family-filter','');
    await page.evaluate(()=>{for(const [id,value] of [['enemy-accuracy','100'],['evasion','0']]){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}});
    for(const [cls,name] of [['thumb','Предупредительный выстрел'],['index','Первая строка'],['pinky','Лунная дуга'],['ragamuffin','Удар бомжа']]){
      await page.selectOption('#class-filter',cls);await page.locator('#search').fill(name);
      await page.locator('#start').click();await page.waitForTimeout(900);
      assert.equal(await page.locator('#game').getAttribute('data-phase'),'defense');
      await page.screenshot({path:path.join(output,cls+'-accuracy100-evasion0.png')});await page.locator('#stop').click();
    }
    await page.selectOption('#class-filter','');await page.locator('#search').fill('');await page.locator('[data-preset="equal"]').click();
    console.log('PASS target class patterns at accuracy 100 / evasion 0');
    await page.selectOption('#family-filter','');await page.locator('[data-mode="attack"]').click();
    // Real keyboard timing on the actual UI, not a forged outcome.
    await page.evaluate(()=>{const attack=QTEUnique.attack;QTEUnique.attack=(...args)=>(window.__trial=attack(...args));});
    await page.selectOption('#family-filter','charm');await page.locator('#start').click();
    assert.equal(await page.locator('#hit').isDisabled(),true);
    await page.keyboard.press('Space');assert.equal(await page.evaluate(()=>window.__trial.attempts[0]),0);
    assert((await page.locator('#chance-status').textContent()).includes('Подготовка'));
    await page.screenshot({path:path.join(output,'attack-preparation.png')});
    // Deliberately miss on the first pass, then take the remaining chance.
    await page.waitForFunction(()=>{const s=window.__trial,f=QTEUnique.attackFrame(s);return f.canHit&&Math.abs(f.cursor-f.center)>f.width;},null,{polling:'raf'});
    await page.keyboard.press('Space');assert.equal(await page.evaluate(()=>window.__trial.attempts[0]),1);
    assert.equal(await page.evaluate(()=>window.__trial.results[0]),null);assert((await page.locator('#feedback').textContent()).includes('ещё одна'));
    await page.screenshot({path:path.join(output,'attack-second-chance.png')});
    await page.waitForFunction(()=>{
      const s=window.__trial;if(!s||s.ended)return false;const f=QTEUnique.attackFrame(s);
      if(f.canHit&&Math.abs(f.cursor-f.center)<f.width/3)window.dispatchEvent(new KeyboardEvent('keydown',{code:'Space'}));
      return s.ended;
    },null,{polling:'raf'});
    await page.waitForFunction(()=>document.querySelector('#game').dataset.phase==='idle');
    assert((await page.locator('#feedback').textContent()).includes('1/1'));
    assert.equal(await page.evaluate(()=>window.__trial.attempts[0]),2);assert((await page.locator('#hp-value').textContent()).includes('188 / 200'));
    await page.locator('[data-rate="В самый раз"]').click();assert((await page.locator('#log').textContent()).includes('Оценка: В самый раз'));
    await page.selectOption('#family-filter','tiger');await page.locator('#start').click();
    await page.waitForTimeout(400);await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    assert.equal(await page.locator('#game').getAttribute('data-phase'),'paused');
    await page.locator('#resume').click();await page.locator('#stop').click();
    await page.locator('[data-mode="defense"]').click();await page.selectOption('#family-filter','tiger');
    await page.evaluate(()=>{const defense=QTEUnique.defense;QTEUnique.defense=(...args)=>(window.__defense=defense(...args));});
    await page.locator('#start').click();await page.waitForFunction(()=>window.__defense.contacts.length>0,null,{polling:'raf'});
    const hp=await page.evaluate(()=>window.__defense.hp);assert(hp<200);assert((await page.locator('#hp-value').textContent()).startsWith(hp+' /'));
    assert.equal(await page.locator('#game').getAttribute('data-phase'),'defense');
    await page.screenshot({path:path.join(output,'immediate-projectile-damage.png')});await page.locator('#stop').click();
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
    console.log('PASS actual attack input, pause/resume, session rating and no gameplay requests');
    for(const viewport of [{width:390,height:844},{width:320,height:568},{width:844,height:390}]){
      const mobile=await browser.newPage({viewport,hasTouch:true,isMobile:true});
      await mobile.goto(origin+'/qte-lab/unique/?skill=tigerslayer_flurry');await mobile.locator('#start').click();
      await mobile.waitForTimeout(500);
      assert(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow');
      const canvas=await mobile.locator('#game').boundingBox();assert(canvas.width<=viewport.width);
      await mobile.screenshot({path:path.join(output,'mobile-'+viewport.width+'.png')});
      await mobile.locator('#game').tap();await mobile.locator('#stop').click();await mobile.close();
    }
    console.log('PASS mobile portrait and landscape layouts');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
