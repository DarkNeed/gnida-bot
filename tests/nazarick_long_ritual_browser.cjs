const assert=require('node:assert/strict'),fs=require('node:fs');
const{chromium}=require('playwright');
const origin='http://127.0.0.1:8157',out='output/nzd-long-ritual-review';
(async()=>{
 fs.mkdirSync(out,{recursive:true});const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  for(const width of [1100,390]){
   const p=await b.newPage({viewport:{width,height:width<500?844:1000},isMobile:width<500,hasTouch:width<500});p.on('pageerror',e=>errors.push(e.message));let firstHeight;
   for(const phase of [1,2]){
    await p.goto(origin+`/nzd-demo?mode=fight&room=3&phase=${phase}`);const sprite=p.locator('.raid-enemy .raid-sprite');await sprite.waitFor();
    await sprite.evaluate(n=>n.decode());assert.match(await sprite.getAttribute('src'),phase===1?/gargantua-v2/:/gargantua-phase2-v1/);
    const h=await p.locator('.raid-enemy .raid-art').evaluate(n=>n.getBoundingClientRect().height);if(phase===1)firstHeight=h;else assert(h>firstHeight*1.3);
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await p.screenshot({path:out+`/gargantua-${phase}-${width}.png`,fullPage:true});
   }await p.close();
  }
  const p=await b.newPage({viewport:{width:1100,height:950}});p.on('pageerror',e=>errors.push(e.message));let latestStatus='active',calls=[];
  p.on('response',async r=>{if(!r.url().includes('/api/'))return;try{const data=await r.json(),view=data.raid||data;if(view?.status)latestStatus=view.status;}catch{}});
  await p.goto(origin+'/nzd-demo?mode=pattern&room=7&who=victim&phase=2&move=4');await p.locator('.qte-cover').waitFor();
  await p.evaluate(()=>{window.__qteSounds=[];const old=ArenaAudio.effect;ArenaAudio.effect=name=>{window.__qteSounds.push(name);return old(name);};});
  await p.waitForTimeout(1700);assert(parseFloat(await p.locator('.qte-count').innerText())>40);
  console.log('Native 45-second ritual started');const start=Date.now();
  for(let part=0;part<6;part++){
   if(part)await p.waitForTimeout(6800);await p.screenshot({path:out+`/ritual-${part+1}.png`});
   console.log('Ritual stage',part+1);
  }
  calls=await p.evaluate(()=>window.__qteSounds);assert(calls.includes('qte_hurt'),'real defense contacts must produce feedback');
  await p.waitForFunction(()=>!document.querySelector('.qte-cover'),null,{timeout:15000});
  assert(Date.now()-start>41000);for(let i=0;i<80&&latestStatus!=='finished';i++)await p.waitForTimeout(100);assert.equal(latestStatus,'finished');
  assert.deepEqual(errors,[]);console.log('PASS larger distinct phase 2, native long ritual accepted by server, in-game damage SFX, no browser errors');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
