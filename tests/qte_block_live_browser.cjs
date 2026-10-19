const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');const origin=process.env.QTE_LIVE_URL||'http://127.0.0.1:8117';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const out=path.join(__dirname,'../output/qte-block-live');fs.mkdirSync(out,{recursive:true});
  try{
    for(const viewport of [{width:1280,height:900},{width:900,height:700},{width:390,height:844},{width:320,height:568},{width:844,height:390}]){
      const mobile=viewport.width<600||viewport.height<500;
      const page=await browser.newPage({viewport,hasTouch:mobile,isMobile:mobile}),errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.goto(origin+'/preview?tgWebAppStartParam=menu_1&player=20');await page.locator('[data-combat-open]').waitFor();
      if(mobile)await page.evaluate(()=>{document.documentElement.style.setProperty('--app-system-top','24px');document.documentElement.style.setProperty('--app-content-top','48px');document.documentElement.style.setProperty('--app-system-bottom','20px');});
      await page.evaluate(()=>{
        window.__proof=null;const create=QTEBlock.create;QTEBlock.create=(...args)=>(window.__block=create(...args));
        ArenaMiniGames.play({version:3,defense_mode:'block',id:'block-layout',kind:'defense',name:'Совершенная поступь тигробоя',
          profile:{id:'tigerslayer_flurry:Совершенная поступь тигробоя:6:physical',base_id:'tigerslayer_flurry',name:'Совершенная поступь тигробоя',class_id:'middle',strikes:6,damage_type:'physical'},
          stats:{physicalDefense:35,magicDefense:20,enemyAttack:30,enemyAccuracy:95},seed:23,damage_base:40,target_hp:200,
          server_now:Date.now()/1000,expires:Date.now()/1000+20}).then(p=>window.__proof=p);
      });
      const win=page.locator('.qte-window'),r=await win.boundingBox(),field=await page.locator('canvas').boundingBox();
      assert(Math.abs(field.width/field.height-1.8)<.01,'undistorted blocking field');
      assert(r.y>=0&&r.y+r.height<=viewport.height+1,'modal within viewport');
      await page.screenshot({path:path.join(out,`block-${viewport.width}x${viewport.height}.png`)});
      assert(await win.evaluate(el=>el.scrollHeight<=el.clientHeight+1),'block controls visible without scroll '+JSON.stringify({viewport,sizes:await win.evaluate(el=>({height:el.clientHeight,scroll:el.scrollHeight,kids:[...el.children].map(c=>[c.className,c.getBoundingClientRect().height])}))}));
      if(mobile){
        await page.waitForFunction(()=>document.querySelector('.qte-cover').dataset.preparing==='false');
        const stick=await page.locator('.qte-stick').boundingBox(),x=stick.x+stick.width/2,y=stick.y+stick.height/2;
        const cdp=await page.context().newCDPSession(page);
        await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});
        await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+35,y:y-35,id:1}]});await page.waitForTimeout(250);
        assert(await page.evaluate(()=>__block.active&&__block.angle<-.3&&__block.player.x===360&&__block.player.y===200));
        await cdp.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});await page.waitForTimeout(80);
        assert.equal(await page.evaluate(()=>__block.active),false);await cdp.detach();
      }
      await page.locator('.qte-abort').click();await page.waitForFunction(()=>!!__proof);
      assert.deepEqual(errors,[]);console.log('PASS live block layout, input, cleanup',viewport);await page.close();
    }
    const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('response',async r=>{if(r.url().includes('/api/')&&r.status()>=400)errors.push(await r.text());});
    await page.goto(origin+'/preview?tgWebAppStartParam=menu_1');await page.locator('[data-combat-open]').click();
    await page.locator('[data-defense-mode=block]').click();await page.locator('[data-defense-mode=block][aria-pressed=true]').waitFor();
    await page.locator('[data-combat-close]').click();await page.reload();await page.locator('[data-combat-open]').click();
    await page.locator('[data-defense-mode=block][aria-pressed=true]').waitFor();await page.locator('[data-combat-close]').click();
    await page.locator('[data-do="waste:10"]').click();
    await page.evaluate(()=>{const attack=QTEUnique.attack;QTEUnique.attack=(...args)=>(window.__attack=attack(...args));});
    await page.locator('[data-skill=bum_punch]').click();await page.locator('.qte-attack').waitFor();
    await page.waitForFunction(()=>{const s=window.__attack;if(!s)return false;const f=QTEUnique.attackFrame(s);if(f.canHit&&Math.abs(f.cursor-f.center)<f.width/4){window.dispatchEvent(new KeyboardEvent('keydown',{code:'Space'}));return true;}return false;},null,{polling:'raf'});
    await page.locator('.qte-block').waitFor({timeout:15000});
    await page.keyboard.down('ArrowRight');await page.waitForTimeout(1500);await page.keyboard.up('ArrowRight');
    await page.locator('.qte-cover').waitFor({state:'detached',timeout:15000});
    await page.waitForFunction(()=>document.querySelector('#panel .skills')||document.querySelector('#turn')?.textContent==='Бой завершён',null,{timeout:15000});
    assert.deepEqual(errors,[]);console.log('PASS saved character block preference, live PvE input proof and server replay');
    await page.close();
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
