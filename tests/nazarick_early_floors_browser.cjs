const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8157';
(async()=>{
 const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 fs.mkdirSync('output/nzd-early-floors',{recursive:true});
 try{
  const p=await b.newPage({viewport:{width:1200,height:950}});
  p.on('pageerror',e=>errors.push(e.message));
  p.on('response',r=>{if(r.status()>=400&&/\/api\/|\/nzd-demo|\/static\/assets\//.test(r.url()))errors.push(r.status()+' '+r.url());});
  await p.goto(origin+'/nazarick-dungeon-review');
  await p.waitForFunction(()=>document.querySelector('#room').options.length>1);
  for(const [room,count] of [[0,2],[1,3]]){
   await p.locator(`[data-room="${room}"]`).click();
   const frame=p.frameLocator('iframe');try{await frame.locator('.raid-enemy').first().waitFor({timeout:15000});}catch(e){console.log('Frame content:',await frame.locator('body').innerText(),'Errors:',errors);await p.screenshot({path:'output/nzd-early-floors/error.png'});throw e;}
   await p.waitForTimeout(400);
   assert.equal(await frame.locator('.raid-enemy').count(),count);
   assert.match(await frame.locator('body').innerText(),/Рыцарь катакомб/);
   assert.match(await frame.locator('body').innerText(),/Костяной заклинатель/);
   assert.match(await frame.locator('.raid-enemy .raid-sprite').first().getAttribute('src'),/nazarick\/knight\.png/);
   assert.equal(await p.locator('#room').inputValue(),String(room));
   await p.screenshot({path:`output/nzd-early-floors/floor-${room+1}.png`,fullPage:true});
  }
  assert.deepEqual(errors,[]);console.log('PASS review shortcuts open floors I/II with two/three regular enemies, no API or JavaScript errors');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
