const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('playwright');
const origin=process.env.QTE_LIVE_URL||'http://127.0.0.1:8104';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||undefined});
  const errors=[],apiErrors=[];
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('response',async r=>{if(r.url().includes('/api/')&&r.status()>=400)apiErrors.push([r.status(),await r.text()]);});
    await page.goto(origin+'/preview?tgWebAppStartParam=menu_1');
    await page.locator('[data-combat-open]').click();
    await page.locator('[data-combat-enabled="false"]').waitFor();
    await page.screenshot({path:path.join(__dirname,'../output/qte-lab/live-settings.png'),fullPage:true});
    await page.locator('[data-combat-enabled="false"]').click();
    await page.locator('[data-combat-enabled="true"]').waitFor();
    await page.reload();await page.locator('[data-combat-open]').click();
    await page.locator('[data-combat-enabled="true"]').waitFor();
    console.log('PASS live setting defaults on, switches off and persists after reload');
    await page.locator('[data-combat-enabled="true"]').click();
    await page.locator('[data-combat-enabled="false"]').waitFor();
    await page.locator('[data-combat-close]').click();
    await page.locator('[data-do="waste:10"]').click();
    await page.evaluate(()=>{
      const attack=QTEUnique.attack;
      QTEUnique.attack=(...args)=>(window.__liveState=attack(...args));
    });
    await page.locator('[data-skill=bum_punch]').click();
    await page.locator('.qte-cover').waitFor();
    await page.screenshot({path:path.join(__dirname,'../output/qte-lab/live-attack.png'),fullPage:true});
    await page.waitForFunction(()=>{
      const s=window.__liveState;if(!s)return false;
      const f=QTEUnique.attackFrame(s);
      if(f.canHit&&Math.abs(f.cursor-f.center)<f.width/4){window.dispatchEvent(new KeyboardEvent('keydown',{code:'Space'}));return true;}
      return false;
    },null,{polling:'raf'});
    await page.locator('.qte-eyebrow').filter({hasText:'ЗАЩИТА'}).waitFor({timeout:15000});
    await page.waitForFunction(()=>document.querySelector('.qte-cover')?.dataset.preparing==='true');
    await page.waitForTimeout(900);
    await page.screenshot({path:path.join(__dirname,'../output/qte-lab/live-defense.png'),fullPage:true});
    await page.waitForTimeout(6200);
    await page.locator('.qte-cover').waitFor({state:'detached'});
    await page.waitForFunction(()=>document.querySelector('#panel .skills')||document.querySelector('#turn')?.textContent==='Бой завершён',null,{timeout:15000});
    console.log('PASS live PvE: actual QTE proof, server replay, bot defense, return to actions');
    if(await page.locator('[data-do=surrender]').count())await page.locator('[data-do=surrender]').click();
    await page.locator('[data-do=menu]').click();
    await page.locator('[data-combat-open]').click();
    await page.locator('[data-combat-enabled="false"]').click();
    await page.locator('[data-combat-enabled="true"]').waitFor();
    await page.locator('[data-combat-close]').click();
    // Use PvE again so this setting check does not depend on random PvP initiative.
    await page.locator('[data-do="waste:10"]').click();
    await page.locator('[data-skill=bum_punch]').click();
    await page.waitForTimeout(2500);
    assert.equal(await page.locator('.qte-cover').count(),0);
    console.log('PASS disabled mode keeps one-click combat without overlays');
    if(await page.locator('[data-do=surrender]').count())await page.locator('[data-do=surrender]').click();
    await page.locator('[data-do=menu]').click();
    await page.locator('[data-combat-open]').click();
    await page.locator('[data-combat-enabled="true"]').click();
    await page.locator('[data-combat-enabled="false"]').waitFor();
    assert.deepEqual(errors,[]);assert.deepEqual(apiErrors,[]);
    console.log('PASS no browser or API errors');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
