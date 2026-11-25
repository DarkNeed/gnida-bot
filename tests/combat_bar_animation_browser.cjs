const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin=process.env.QUEUE_ORIGIN||'http://127.0.0.1:8165';

async function track(page){
 await page.addInitScript(()=>{
  const animate=Element.prototype.animate;
  window.barAnimations=[];
  window.vitalFrames=[];
  Element.prototype.animate=function(frames,options){
   const key=this.dataset.vital||(this.matches('.raid-timeline-dot')&&'cast:'+this.dataset.actor);
   if(key)window.barAnimations.push({key,frames});
   return animate.call(this,frames,options);
  };
  const sample=()=>{
   const vitals=Object.fromEntries([...document.querySelectorAll('[data-vital]')].map(n=>[n.dataset.vital,n.style.width]));
   const last=window.vitalFrames.at(-1);
   if(Object.keys(vitals).length&&JSON.stringify(last)!==JSON.stringify(vitals))window.vitalFrames.push(vitals);
   requestAnimationFrame(sample);
  };
  requestAnimationFrame(sample);
 });
}
async function inspect(page){
 return page.evaluate(()=>({frames:window.vitalFrames,animations:window.barAnimations}));
}
async function checkVitals(page,{manaKey}={}){
 const {frames,animations}=await inspect(page),before=frames[0],after=frames.at(-1);
 if(manaKey)assert.notEqual(before[manaKey],after[manaKey],'expense not entirely refunded');
 for(const [key,old] of Object.entries(before)){
  const result=after[key];
  assert(frames.every(frame=>frame[key]===old||frame[key]===result),JSON.stringify({key,old,result,frames}));
  assert.equal(animations.filter(record=>record.key===key).length,Number(old!==result),key);
 }
 return animations;
}

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const p=await browser.newPage({viewport:{width:1100,height:900}});
  await track(p);
  await p.goto(origin+'/live-queue-review?mode=bars&qte=0');
  const cut=p.locator('[data-raid="skill:assassin_cut"]');
  await cut.waitFor();
  await p.waitForFunction(()=>window.vitalFrames.length>0);
  await cut.click();
  await p.waitForFunction(()=>document.querySelector('.raid-timeline').dataset.now!=='Сейчас · 0.00'
    && document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])'));
  await p.waitForTimeout(450);
  let animations=await checkVitals(p);
  assert.deepEqual(animations.filter(a=>a.key.startsWith('cast:')).map(a=>a.key).sort(),['cast:e1','cast:e2']);

  const first=await p.locator('.raid-timeline').getAttribute('data-now');
  await p.evaluate(()=>{window.barAnimations=[];window.vitalFrames=window.vitalFrames.slice(-1);});
  await cut.click();
  await p.waitForFunction(before=>document.querySelector('.raid-timeline')?.dataset.now!==before
    && document.querySelector('[data-raid="skill:assassin_cut"]:not([disabled])'),first);
  await p.waitForTimeout(450);
  animations=await checkVitals(p);
  assert.deepEqual(animations.filter(a=>a.key.startsWith('cast:')).map(a=>a.key).sort(),['cast:e1','cast:e2']);
  assert(animations.filter(a=>a.key.startsWith('cast:')).every(a=>a.frames.at(0).left!==a.frames.at(-1).left));
  await p.close();

  const raid=await browser.newPage();
  await track(raid);
  await raid.goto(origin+'/live-queue-review?mode=bars&qte=0');
  const needle=raid.locator('[data-raid="skill:assassin_needle"]');
  await needle.waitFor();
  await raid.waitForFunction(()=>window.vitalFrames.length>0);
  await needle.click();
  await raid.waitForFunction(()=>document.querySelector('[data-vital-label=mp-10]')?.textContent==='94 / 100');
  await raid.waitForTimeout(450);
  await checkVitals(raid,{manaKey:'mp-10'});
  await raid.close();

  const solo=await browser.newPage();
  await track(solo);
  await solo.goto(origin+'/live-queue-review?mode=solo&qte=0');
  const soloNeedle=solo.locator('[data-skill="assassin_needle"]');
  await soloNeedle.waitFor();
  await solo.waitForFunction(()=>window.vitalFrames.length>0);
  await soloNeedle.click();
  await solo.waitForFunction(()=>document.querySelector('[data-vital=mp-a]')?.style.width!==window.vitalFrames[0]['mp-a']);
  await solo.waitForTimeout(450);
  await checkVitals(solo,{manaKey:'mp-a'});
  await solo.close();
  console.log('PASS one visual update each for HP, resource and shared timeline markers');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
