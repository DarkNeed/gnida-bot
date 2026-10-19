const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const origin=process.env.QTE_BLOCK_URL||'http://127.0.0.1:8116';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const output=path.join(__dirname,'../output/qte-block');fs.mkdirSync(output,{recursive:true});
  try{
    for(const width of [1280,390,320]){
      const mobile=width<600,page=await browser.newPage({viewport:{width,height:mobile?844:1000},hasTouch:mobile,isMobile:mobile});
      const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/')||r.method()!=='GET')writes.push(r.url());});
      await page.goto(origin+'/qte-lab/block/');await page.locator('#start').waitFor();
      assert(await page.locator('#skill option').count()>200);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow');
      const box=await page.locator('canvas').boundingBox();assert(Math.abs(box.width/box.height-1.8)<.01,'undistorted block field');
      await page.screenshot({path:path.join(output,`idle-${width}.png`),fullPage:true});
      await page.evaluate(()=>{const create=QTEBlock.create;QTEBlock.create=(...args)=>(window.__block=create(...args));});
      await page.locator('#start').click();assert(await page.locator('#skill').isDisabled());
      await page.waitForFunction(()=>__block.time>1.05);
      if(!mobile){
        const angle=await page.evaluate(()=>__block.events[0].angle);
        const keys=[];if(Math.cos(angle)>.3)keys.push('ArrowRight');else if(Math.cos(angle)<-.3)keys.push('ArrowLeft');
        if(Math.sin(angle)>.3)keys.push('ArrowDown');else if(Math.sin(angle)<-.3)keys.push('ArrowUp');
        for(const k of keys)await page.keyboard.down(k);await page.waitForTimeout(350);for(const k of keys)await page.keyboard.up(k);
        await page.waitForFunction(()=>__block.time>=__block.events[0].at-.10,null,{polling:'raf'});
        await page.keyboard.down('Space');await page.waitForFunction(()=>__block.events[0].resolved);await page.keyboard.up('Space');
        assert(await page.evaluate(()=>__block.perfects>0),'real keyboard input can perform perfect block');
      }else{
        const stick=await page.locator('#stick').boundingBox();
        await page.locator('#stick').scrollIntoViewIfNeeded();const r=await page.locator('#stick').boundingBox();
        const cdp=await page.context().newCDPSession(page),x=r.x+r.width/2,y=r.y+r.height/2;
        const touch=(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:['touchEnd','touchCancel'].includes(type)?[]:[{x,y,id:1}]});
        const scroll=await page.evaluate(()=>scrollY);
        await touch('touchStart',x,y);await touch('touchMove',x+35,y-35);await page.waitForTimeout(260);
        assert(await page.evaluate(()=>__block.active&&__block.angle<-.3),'joystick rotates and raises the shield');
        assert(await page.evaluate(()=>__block.player.x===360&&__block.player.y===200),'marker remains stationary');
        assert.equal(await page.evaluate(()=>scrollY),scroll,'joystick does not scroll page');
        await touch('touchCancel');await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>__block.active),false);
        await cdp.detach();
      }
      await page.screenshot({path:path.join(output,`active-${width}.png`),fullPage:true});
      await page.evaluate(()=>window.dispatchEvent(new Event('blur')));assert(await page.locator('#resume').isVisible());
      const t=await page.evaluate(()=>__block.time);await page.waitForTimeout(220);assert.equal(await page.evaluate(()=>__block.time),t,'background is paused');
      await page.locator('#resume').click();await page.waitForTimeout(120);assert(await page.evaluate(t=>__block.time>t,t));
      await page.locator('#stop').click();assert(await page.locator('#summary').isVisible());assert(!(await page.locator('#skill').isDisabled()));
      await page.locator('[data-rate="В самый раз"]').click();assert.equal(await page.locator('#journal li').count(),1);
      await page.locator('[data-example=kit_eclipse]').click();assert((await page.locator('#skill-name').textContent()).length>0);
      await page.locator('[data-preset=fortress]').click();assert.equal(await page.locator('#physical').inputValue(),'75');
      assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);console.log('PASS block lab keyboard/touch, fit, pause, results, isolation',width);await page.close();
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
