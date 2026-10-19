// Touch/browser regression with a mocked Telegram bridge; not a real iPhone test.
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin=process.env.QTE_LIVE_URL||'http://127.0.0.1:8115';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:390,height:844},hasTouch:true,isMobile:true,
      userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin+'/preview?tgWebAppStartParam=menu_1&player=20');
    await page.locator('[data-combat-open]').waitFor();
    await page.evaluate(()=>{
      const spacer=document.createElement('div');spacer.style.height='2400px';document.body.append(spacer);
      document.documentElement.style.scrollBehavior='auto';window.scrollTo(0,500);
      window.__swipes=[];Object.assign(Telegram.WebApp,{isVerticalSwipesEnabled:true,
        isVersionAtLeast:()=>true,
        disableVerticalSwipes(){this.isVerticalSwipesEnabled=false;__swipes.push('disable');},
        enableVerticalSwipes(){this.isVerticalSwipesEnabled=true;__swipes.push('enable');}});
      window.__styles=()=>[...['position','top','left','width','overflow'].map(k=>[k,document.body.style.getPropertyValue(k)]),
        ...['overflow','overscroll-behavior','scroll-behavior'].map(k=>['root:'+k,document.documentElement.style.getPropertyValue(k)])];
      window.__before={scroll:scrollY,styles:__styles()};
    });
    const cdp=await page.context().newCDPSession(page);
    const touch=(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:['touchEnd','touchCancel'].includes(type)?[]:[{x,y,radiusX:5,radiusY:5,id:1}]});
    const start=async(version=2)=>page.evaluate(version=>{
      window.__proof=null;
      ArenaMiniGames.play({version,defense_mode:version===3?'block':undefined,defense_preparation:1,id:'scroll-'+version,kind:'defense',name:'Проверка джойстика',
        strikes:1,pattern:'cross',seed:23,profile:{id:'mana_shot:Мановый выстрел:1:magic',base_id:'mana_shot',
          name:'Мановый выстрел',class_id:'mage',strikes:1,damage_type:'magic'},damage_base:40,target_hp:200,
        stats:{accuracy:75,enemyEvasion:25,enemyAccuracy:95,evasion:10,physicalDefense:35,magicDefense:35,enemyAttack:30},
        server_now:Date.now()/1000,expires:Date.now()/1000+20}).then(p=>window.__proof=p);
    },version);
    for(const version of [1,2,3]){
      await start(version);await page.locator('.qte-stick').waitFor();
      assert.equal(await page.evaluate(()=>document.body.style.position),'fixed');
      assert.equal(await page.evaluate(()=>Telegram.WebApp.isVerticalSwipesEnabled),false);
      const before=await page.locator('.qte-window').boundingBox();
      const stick=await page.locator('.qte-stick').boundingBox(),x=stick.x+stick.width/2,y=stick.y+stick.height/2;
      await touch('touchStart',x,y);
      for(let i=1;i<=8;i++){await touch('touchMove',x-10*i,y-25*i);await page.waitForTimeout(25);}
      assert(await page.locator('.qte-stick').evaluate(el=>{
        const event=new TouchEvent('touchmove',{bubbles:true,cancelable:true});el.dispatchEvent(event);return event.defaultPrevented;
      }),'non-passive touch handler cancels iOS scrolling');
      await touch('touchCancel');
      const after=await page.locator('.qte-window').boundingBox();
      assert(Math.abs(after.y-before.y)<1&&Math.abs(after.x-before.x)<1,'joystick must not drag the window');
      assert.equal(await page.locator('.qte-stick.held').count(),0,'cancel releases captured input');
      assert.equal(await page.evaluate(()=>Telegram.WebApp.isVerticalSwipesEnabled),false,'gesture release must not unlock open modal');
      await page.locator('.qte-abort').click();await page.waitForFunction(()=>!!__proof);
      assert(await page.evaluate(()=>Math.abs(scrollY-__before.scroll)<1),'closing restores original scroll');
      assert.deepEqual(await page.evaluate(()=>__styles()),await page.evaluate(()=>__before.styles));
      assert.equal(await page.evaluate(()=>Telegram.WebApp.isVerticalSwipesEnabled),true);
    }
    assert.deepEqual(await page.evaluate(()=>__swipes),['disable','enable','disable','enable','disable','enable']);
    console.log('PASS live v1/v2/v3: no touch scroll, fixed viewport, cancel, styles/scroll/swipes restored');
    // Preserve an already-disabled preference; skip unsupported/throwing bridges.
    for(const mode of ['disabled','old','throwing']){
      await page.evaluate(mode=>{
        window.__swipes=[];Telegram.WebApp.isVerticalSwipesEnabled=mode!=='disabled';
        Telegram.WebApp.isVersionAtLeast=()=>mode!=='old';
        Telegram.WebApp.disableVerticalSwipes=mode==='throwing'?()=>{throw Error('unsupported');}:
          function(){this.isVerticalSwipesEnabled=false;__swipes.push('disable');};
      },mode);
      await start();await page.keyboard.press('Escape');await page.waitForFunction(()=>!!__proof);
      assert.deepEqual(await page.evaluate(()=>__swipes),[]);
      assert.equal(await page.evaluate(()=>Telegram.WebApp.isVerticalSwipesEnabled),mode!=='disabled');
    }
    await page.evaluate(()=>{
      Object.assign(Telegram.WebApp,{isVerticalSwipesEnabled:true,isVersionAtLeast:()=>true,
        disableVerticalSwipes(){this.isVerticalSwipesEnabled=false;__swipes.push('disable');}});
      window.__swipes=[];
      const container=document.createElement('div');document.body.append(container);
      const first=QTETouch.lockViewport(container),second=QTETouch.lockViewport(container);
      first();if(document.body.style.position!=='fixed'||Telegram.WebApp.isVerticalSwipesEnabled)throw Error('early unlock');
      first();second();second();container.remove();
    });
    assert.deepEqual(await page.evaluate(()=>__swipes),['disable','enable']);
    assert.deepEqual(await page.evaluate(()=>__styles()),await page.evaluate(()=>__before.styles));
    console.log('PASS nested/idempotent cleanup, existing preference, unsupported SDK fallbacks');
    await cdp.detach();
    // The atlas shares touch suppression without freezing its ordinary page scroll.
    await page.goto(origin+'/qte-lab/unique/');await page.locator('#start').click();
    const atlasStick=page.locator('#stick');await atlasStick.scrollIntoViewIfNeeded();
    const r=await atlasStick.boundingBox(),scroll=await page.evaluate(()=>scrollY);
    const atlasCdp=await page.context().newCDPSession(page);
    await atlasCdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:r.x+r.width/2,y:r.y+r.height/2,id:1}]});
    await atlasCdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:r.x+r.width/2,y:r.y+r.height/2-90,id:1}]});
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(()=>scrollY),scroll);
    assert(await atlasStick.evaluate(el=>{const e=new TouchEvent('touchmove',{bubbles:true,cancelable:true});el.dispatchEvent(e);return e.defaultPrevented;}));
    await atlasCdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await page.locator('#stop').click();
    assert.notEqual(await page.evaluate(()=>document.body.style.position),'fixed');
    assert.deepEqual(errors,[]);
    console.log('PASS atlas touch suppression and no browser errors');
    await atlasCdp.detach();await page.close();
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
