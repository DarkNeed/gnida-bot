// Real local API for settings; mocked Telegram insets, never production data.
const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium}=require('playwright');
const origin=process.env.QTE_LIVE_URL||'http://127.0.0.1:8105';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  try{
    for(const viewport of [{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
      const page=await browser.newPage({viewport,hasTouch:true,isMobile:true});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/preview?**',async route=>{
        const response=await route.fetch();
        const body=(await response.text()).replace('ready(){}',
          'safeAreaInset:{top:24,bottom:20,left:0,right:0},contentSafeAreaInset:{top:48,bottom:0,left:0,right:0},isFullscreen:true,platform:"android",_events:{},onEvent(name,fn){this._events[name]=fn},ready(){}');
        await route.fulfill({response,body});
      });
      await page.goto(origin+'/preview?tgWebAppStartParam=menu_1&player=20');
      const gear=page.locator('[data-combat-open]'),sound=page.locator('[data-audio-open]');
      await gear.waitFor();
      assert.equal(await page.locator('[data-do="tab:settings"]').count(),0);
      const a=await gear.boundingBox(),b=await sound.boundingBox();
      assert(a.y>=72&&b.y>=72,'header buttons clear system and Telegram controls');
      assert.equal(a.width,b.width);assert.equal(a.height,b.height);
      assert(Math.abs(a.y-b.y)<1,'icon buttons in one row');
      assert(a.x+a.width<=b.x,'settings beside sound');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no page overflow');
      await page.screenshot({path:path.join(__dirname,`../output/qte-lab/mobile-menu-${viewport.width}.png`)});
      await gear.click();
      const settings=page.locator('#combat-settings');
      await settings.locator('[data-combat-enabled]').waitFor();
      const modal=await settings.boundingBox();
      assert(modal.y>=72&&modal.y+modal.height<=viewport.height-20,'settings inside safe viewport');
      const toggle=settings.locator('[data-combat-enabled]'),initial=await toggle.getAttribute('data-combat-enabled');
      await toggle.click();await settings.locator(`[data-combat-enabled="${initial==='true'?'false':'true'}"]`).waitFor();
      await page.locator('[data-combat-close]').click();
      await gear.click();await settings.locator(`[data-combat-enabled="${initial==='true'?'false':'true'}"]`).waitFor();
      await settings.locator('[data-combat-enabled]').click(); // Restore account setting.
      await settings.locator(`[data-combat-enabled="${initial}"]`).waitFor();
      await page.screenshot({path:path.join(__dirname,`../output/qte-lab/mobile-settings-${viewport.width}.png`)});
      await page.locator('[data-combat-close]').click();
      await sound.click();
      const audio=await page.locator('.audio-dialog').boundingBox();
      assert(audio.y>=72&&audio.y+audio.height<=viewport.height-20,'audio dialog safe');
      await page.locator('[data-audio-close]').click();
      // Native safe-area change (rotation or switching fullscreen), without reload.
      await page.evaluate(()=>{
        const tg=Telegram.WebApp;tg.safeAreaInset={top:30,bottom:24,left:16,right:18};
        tg.contentSafeAreaInset.top=56;tg._events.safeAreaChanged();tg._events.contentSafeAreaChanged();
      });
      assert((await gear.boundingBox()).y>=86,'live safe-area events applied');
      await page.evaluate(()=>{
        ArenaMiniGames.play({id:'layout-only',kind:'defense',name:'Тигриное рассечение',strikes:6,pattern:'slashes',seed:23,
          stats:{accuracy:75,enemyEvasion:25,enemyAccuracy:95,evasion:10},server_now:Date.now()/1000,expires:Date.now()/1000+20});
      });
      const qte=await page.locator('.qte-window').boundingBox();
      assert(qte.y>=86&&qte.y+qte.height<=viewport.height-24,'QTE window safe');
      assert(qte.x>=16&&qte.x+qte.width<=viewport.width-18,'landscape side insets respected');
      const controls=await page.locator('[data-direction="down"]').boundingBox();
      assert(controls.y>=qte.y&&controls.y+controls.height<=qte.y+qte.height,'all dodge arrows visible without scrolling');
      await page.screenshot({path:path.join(__dirname,`../output/qte-lab/mobile-qte-${viewport.width}.png`)});
      await page.locator('.qte-abort').click();
      await page.evaluate(()=>{
        const tg=Telegram.WebApp;tg.safeAreaInset={top:0,bottom:0,left:0,right:0};
        tg.contentSafeAreaInset={top:0,bottom:0,left:0,right:0};tg.isFullscreen=false;tg._events.fullscreenChanged();
      });
      assert((await gear.boundingBox()).y<50,'normal browser has no fullscreen header gap');
      await page.evaluate(()=>{Telegram.WebApp.isFullscreen=true;Telegram.WebApp._events.fullscreenChanged();});
      assert((await gear.boundingBox()).y>=44,'fallback protects fullscreen while waiting for insets');
      assert.deepEqual(errors,[]);
      console.log('PASS mobile settings, sound, QTE and dynamic safe areas',viewport);
      await page.close();
    }
    // Combat gear opens and saves settings without replacing the active arena.
    const page=await browser.newPage({viewport:{width:390,height:844}});
    await page.goto(origin+'/preview?tgWebAppStartParam=menu_1');
    await page.locator('[data-do="waste:10"]').click();
    await page.locator('.battle .field').waitFor();
    await page.locator('[data-combat-open]').click();
    const toggle=page.locator('#combat-settings [data-combat-enabled]');await toggle.waitFor();
    const initial=await toggle.getAttribute('data-combat-enabled');
    await toggle.click();await page.locator(`#combat-settings [data-combat-enabled="${initial==='true'?'false':'true'}"]`).waitFor();
    assert.equal(await page.locator('.battle .field').count(),1);
    await page.locator('#combat-settings [data-combat-enabled]').click();
    await page.locator(`#combat-settings [data-combat-enabled="${initial}"]`).waitFor();
    await page.locator('[data-combat-close]').click();
    await page.locator('[data-do=surrender]').click();
    console.log('PASS settings can be saved from combat without navigating away');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
