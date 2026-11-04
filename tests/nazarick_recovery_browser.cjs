const assert=require('node:assert/strict'),fs=require('node:fs');
const{chromium}=require('playwright');
const origin='http://127.0.0.1:8157',out='output/nzd-recovery-review';
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const p=await browser.newPage({viewport:{width:1100,height:1000}});let latestStatus=null;
  p.on('pageerror',e=>errors.push(e.message));
  p.on('response',async r=>{if(!r.url().includes('/api/'))return;try{const body=await r.json(),view=body.raid||body;if(view?.status)latestStatus=view.status;}catch{}});
  for(const[who,room]of[['gargantua',3],['victim',7]]){
   await p.goto(origin+`/nzd-demo?mode=fight&who=${who}&room=${room}&phase=2&energy=0`);
   await p.locator('[data-raid="skill:defend"]').waitFor();
   if(who==='gargantua'){
    assert(await p.locator('.raid-enemy .raid-sprite').evaluate(n=>getComputedStyle(n).scale.startsWith('-1')));
    await p.screenshot({path:out+'/gargantua-facing.png'});
   }else{
    assert.equal(await p.locator('[data-raid="skill:mana_shot"]').isDisabled(),true);
    assert.match(await p.locator('[data-raid="skill:mana_shot"]').innerText(),/печать нельзя атаковать/);
    await p.screenshot({path:out+'/ritual-no-attack-reset.png'});
   }
   for(let i=0;i<12;i++){
    if(await p.locator('.qte-cover').count())break;
    await p.locator('[data-raid="skill:defend"]').click();await p.waitForTimeout(200);
   }
   await p.locator('.qte-cover').waitFor();
   assert.match(await p.locator('.qte-cover h2').innerText(),who==='gargantua'?/Гаргантюа/:/Последняя печать/);
   if(who==='victim')await p.waitForFunction(()=>parseFloat(document.querySelector('.qte-count')?.textContent)>10,{timeout:3000});
   await p.waitForTimeout(1700);await p.screenshot({path:out+'/'+who+'-real-defense.png'});
   await p.locator('.qte-abort').click();await p.waitForTimeout(600);
   const text=await p.locator('body').innerText();assert(!text.includes('Объявленный навык недоступен'));
   if(who==='victim'){for(let i=0;i<20&&latestStatus!=='finished';i++)await p.waitForTimeout(100);assert.equal(latestStatus,'finished','Trial must end the encounter, not just redraw the seal');console.log('Ritual after defense: encounter status',latestStatus);}
  }
  assert.deepEqual(errors,[]);console.log('PASS zero-energy Gargantua resumes; ritual publishes and finishes; hostile spam disabled; actual facing reversed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
