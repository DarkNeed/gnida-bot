const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const origin=process.env.QTE_LIVE_URL||'http://127.0.0.1:8108';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const output=path.join(__dirname,'../output/qte-controls');fs.mkdirSync(output,{recursive:true});
  try{
    for(const viewport of [{width:900,height:700},{width:1280,height:900},{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
      const mobile=viewport.width<=400||viewport.height<500;
      const page=await browser.newPage({viewport,hasTouch:mobile,isMobile:mobile});const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.goto(origin+'/preview?tgWebAppStartParam=menu_1&player=20');await page.locator('[data-combat-open]').waitFor();
      if(mobile)await page.evaluate(()=>{
        document.documentElement.style.setProperty('--app-system-top','24px');document.documentElement.style.setProperty('--app-content-top','48px');document.documentElement.style.setProperty('--app-system-bottom','20px');
      });
      for(const version of [1,2])for(const kind of ['attack','defense']){
        await page.evaluate(({kind,version})=>{
          window.__proof=null;window.__steps=[];const E=version===2?QTEUnique:QTELab;
          if(!E.__testDefense){E.__testDefense=E.defense;E.defense=(...args)=>(window.__sim=E.__testDefense(...args));}
          if(!E.__testStep){E.__testStep=E.defenseStep;E.defenseStep=(s,dt,cmd)=>{const old={...s.player};E.__testStep(s,dt,cmd);window.__steps.push({cmd,d:Math.hypot(s.player.x-old.x,s.player.y-old.y)});};}
          ArenaMiniGames.play({version,defense_preparation:1,id:'test-'+kind,kind,name:'Совершенная поступь тигробоя',strikes:6,pattern:'cross',seed:23,
            profile:{id:'tigerslayer_flurry:Совершенная поступь тигробоя:6:physical',base_id:'tigerslayer_flurry',name:'Совершенная поступь тигробоя',class_id:'middle',strikes:6,damage_type:'physical'},damage_base:40,target_hp:200,
            stats:{accuracy:75,enemyEvasion:25,enemyAccuracy:95,evasion:10},server_now:Date.now()/1000,expires:Date.now()/1000+20}).then(p=>window.__proof=p);
        },{kind,version});
        const canvas=page.locator('.qte-live-canvas'),r=await canvas.boundingBox(),win=await page.locator('.qte-window').boundingBox();
        assert(Math.abs(r.width/r.height-2.25)<.005,'undistorted '+JSON.stringify(viewport));
        assert(win.y>=0&&win.y+win.height<=viewport.height,'modal inside viewport');
        await page.screenshot({path:path.join(output,`${kind}-v${version}-${viewport.width}x${viewport.height}.png`)});
        assert(await page.locator('.qte-window').evaluate(el=>el.scrollHeight<=el.clientHeight+1),'controls fit without scrolling '+JSON.stringify({kind,version,viewport,win,canvas:r}));
        if(version===2&&kind==='defense'){
          assert.equal(await page.locator('.qte-cover').getAttribute('data-preparing'),'true');
          await page.keyboard.down('ArrowRight');await page.waitForTimeout(180);await page.keyboard.up('ArrowRight');
          assert(await page.evaluate(()=>__sim.player.x===720*.32&&!__sim.hazards.length&&!__sim.contacts.length),'defense countdown is non-interactive and harmless');
          await page.screenshot({path:path.join(output,`defense-preparation-${viewport.width}.png`)});
        }
        if(mobile&&kind==='defense'){
          if(version===2)await page.waitForFunction(()=>document.querySelector('.qte-cover')?.dataset.preparing==='false');
          assert(await page.locator('.qte-stick').isVisible());assert(!(await page.locator('.qte-live-pad').isVisible()));
          const cdp=await page.context().newCDPSession(page);
          const touch=async(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'||type==='touchCancel'?[]:[{x,y,radiusX:5,radiusY:5,id:1}]});
          const x=r.x+r.width*.85,y=r.y+r.height*.8;
          const before=await page.evaluate(()=>({...window.__sim.player}));
          await touch('touchStart',x,y);await page.waitForTimeout(90);
          const after=await page.evaluate(()=>({...window.__sim.player}));assert(Math.hypot(after.x-before.x,after.y-before.y)<.01,'touch anywhere does not move towards finger');
          await touch('touchMove',x-25,y-10);await page.waitForTimeout(180);await touch('touchEnd');
          const moved=await page.evaluate(()=>({...window.__sim.player}));assert(moved.x<after.x-5&&moved.y<after.y,'relative drag moves correctly');
          await page.waitForTimeout(90);const stopped=await page.evaluate(()=>({...window.__sim.player}));assert(Math.hypot(stopped.x-moved.x,stopped.y-moved.y)<.01,'release stops motion');
          const stick=await page.locator('.qte-stick').boundingBox(),sx=stick.x+stick.width/2,sy=stick.y+stick.height/2;
          await touch('touchStart',sx,sy);await touch('touchMove',sx+40,sy-40);await page.waitForTimeout(160);await touch('touchCancel');
          assert(await page.evaluate(()=>window.__steps.every(s=>s.d<=2.000001)),'touch cannot exceed keyboard speed');
          assert(await page.evaluate(()=>window.__steps.some(s=>s.cmd.x>0&&s.cmd.y<0)),'joystick allows diagonals');
          assert.equal(await page.locator('.qte-stick.held').count(),0);
          await cdp.detach();
        }
        await page.screenshot({path:path.join(output,`${kind}-v${version}-${viewport.width}x${viewport.height}.png`)});
        await page.locator('.qte-abort').click();
        await page.waitForFunction(()=>!!window.__proof);
      }
      assert.deepEqual(errors,[]);console.log('PASS aspect ratio, fit and input',viewport);await page.close();
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
