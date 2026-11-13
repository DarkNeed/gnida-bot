/* CSS layout regression with synthetic Telegram insets, no live user data. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 try{
  for(const viewport of [{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
   const page=await browser.newPage({viewport,isMobile:true,hasTouch:true});
   await page.setContent('<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}'+fs.readFileSync('webapp/equipment.css','utf8')+'</style><main><section class="gear"><header class="gear-header"><div><p class="gear-kicker">ГНИДА / ПЕРСОНАЖ</p><h1>Снаряжение</h1><p>Сила складывается из деталей.</p></div><button data-gear="back">← Назад</button></header><div style="height:900px"></div><section class="gear-right"><button class="gear-back-inventory">← Инвентарь</button></section><div style="height:1000px"></div></section></main>');
   await page.evaluate(()=>{for(const [side,value] of Object.entries({top:72,bottom:20,left:16,right:18}))document.documentElement.style.setProperty('--app-inset-'+side,value+'px');});
   const back=page.locator('[data-gear="back"]');let box=await back.boundingBox();
   assert(box.y>=72&&box.x>=16&&box.x+box.width<=viewport.width-18,'back clears Telegram and screen edges');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow');
   await page.evaluate(()=>document.documentElement.style.setProperty('--app-inset-top','100px'));
   assert((await back.boundingBox()).y>=100,'safe area updates without reopening equipment');
   await page.locator('.gear-right').evaluate(node=>node.scrollIntoView({block:'start'}));
   assert((await page.locator('.gear-back-inventory').boundingBox()).y>=100,'item details back clears controls after scroll');
   await page.evaluate(()=>{scrollTo(0,0);document.documentElement.style.setProperty('--app-inset-top','0px');});
   assert((await back.boundingBox()).y<90,'normal browser has no extra fullscreen gap');
   console.log('PASS equipment safe area',viewport.width,viewport.height);
   await page.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
