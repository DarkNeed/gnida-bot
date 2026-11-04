const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.WHALER_URL||'http://127.0.0.1:8119';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  fs.mkdirSync('output/whaler-review',{recursive:true});
  try{
    for(const width of [1280,390]){
      const page=await browser.newPage({viewport:{width,height:width===390?844:1000},hasTouch:width===390,isMobile:width===390});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      for(const mode of ['', 'miasma','rot']){
        await page.goto(origin+'/whaler-demo'+(mode?'?mode='+mode:''));
        await page.locator('.whaler-field').waitFor();
        assert.equal(await page.locator('.raid-enemy img.raid-sprite').evaluate(img=>img.complete&&img.naturalWidth>0),true);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
        await page.screenshot({path:`output/whaler-review/${mode||'harpoon'}-${width}.png`,fullPage:true});
      }
      assert.deepEqual(errors,[]);await page.close();
    }
    const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('response',async r=>{if(r.url().includes('/api/')&&r.status()>=400)errors.push(await r.text());});
    await page.goto(origin+'/whaler-demo');
    await page.locator('[data-raid="skill:mana_focus"]').click();
    await page.locator('.qte-defense').waitFor();
    await page.locator('.qte-abort').click();
    await page.locator('.qte-window h2').filter({hasText:'Кара болот'}).waitFor({timeout:20000});
    await page.screenshot({path:'output/whaler-review/reaction-live.png'});
    await page.locator('.qte-abort').click();
    await page.locator('.qte-cover').waitFor({state:'detached'});
    await page.waitForTimeout(5000);
    assert.deepEqual(errors,[]);
    console.log('PASS Whaler desktop/mobile, sprite, three intents, actual live restoration -> extra reaction -> resolved raid');
    await page.close();
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
