const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.GEAR_MARKET_URL||'http://127.0.0.1:8159';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/gear-market-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:1000},isMobile:width===390,hasTouch:width===390});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   page.on('response',r=>{if(r.status()>=500)errors.push(r.status()+' '+r.url());});
   await page.goto(origin+'/guild-preview?actor=10&tgWebAppStartParam=shop_-100');
   await page.locator('[data-do="guildgear"]').waitFor();
   assert.equal(await page.locator('[data-do="merchanttab:gear"]').count(),0);
   const shopWait=page.waitForResponse(r=>r.url().includes('/api/guild/equipment?'));
   await page.locator('[data-do="guildgear"]').click();
   const shop=await (await shopWait).json();
   const first=page.locator('[data-guild^="gearselect:"]').first();await first.waitFor();
   const offer=(await first.getAttribute('data-guild')).slice('gearselect:'.length);
   await first.click();assert.equal(await page.locator('[data-guild^="gearselect:"]').count(),0);
   await page.screenshot({path:`output/gear-market-review/guild-detail-${width}.png`,fullPage:true});
   await page.locator('[data-guild="gearask"]').click();
   const buyWait=page.waitForResponse(r=>r.url().includes('/api/guild/equipment')&&r.request().method()==='POST');
   await page.locator('[data-guild="gearconfirm"]').click();
   const buy=await buyWait;assert.equal(buy.status(),200);const bought=await buy.json();
   assert.equal(bought.shop.balance,shop.balance-shop.offers.find(i=>i.id===offer).price);
   await page.locator('[data-guild^="gearselect:"]').first().waitFor();
   await page.locator('#guild-gear-rarity').selectOption('epic');
   assert.equal(await page.locator('[data-guild^="gearselect:"]').count(),4);
   const prices=await page.locator('[data-guild^="gearselect:"]').allTextContents();
   assert(new Set(prices).size>1,'different epic properties must produce different prices');
   await page.screenshot({path:`output/gear-market-review/guild-epics-${width}.png`,fullPage:true});
   const menuWait=page.waitForResponse(r=>r.url().includes('/api/menu/-100')&&r.request().method()==='GET');
   await page.goto(origin+'/guild-preview?actor=10&tgWebAppStartParam=shop_-100');
   const menu=await (await menuWait).json(),owned=menu.merchant.gear.items[0];
   assert.equal(owned.key,shop.offers.find(i=>i.id===offer).key);
   await page.locator('[data-do="merchanttab:sell"]').click();
   await page.locator('[data-do="merchantitem:'+owned.id+'"]').click();
   await page.locator('[data-do^="merchantask:"]').click();
   const saleWait=page.waitForResponse(r=>r.url().includes('/api/menu/')&&r.request().method()==='POST');
   await page.locator('[data-do="merchantconfirm"]').click();
   const sale=await saleWait;assert.equal(sale.status(),200);const sold=await sale.json();
   assert.equal(sold.menu.balance,bought.shop.balance+owned.sell_price);
   assert(!sold.menu.merchant.gear.items.some(i=>i.id===owned.id));
   await page.goto(origin+'/guild-shop-review?newbie=1');
   await page.locator('#guild-gear-rank').waitFor();
   assert.equal(await page.locator('#guild-gear-rank').inputValue(),'F');
   await page.locator('#guild-gear-rank').selectOption('E');
   await page.locator('[data-guild^="gearselect:"]').first().click();
   assert(await page.locator('[data-guild="gearask"]').isDisabled(),'rank F cannot buy E despite level 7');
   await page.screenshot({path:`output/gear-market-review/guild-rank-lock-${width}.png`,fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow');
   assert.deepEqual(errors,[]);console.log('PASS guild stock, purchase, merchant sale, filters and strict rank lock',width);
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
