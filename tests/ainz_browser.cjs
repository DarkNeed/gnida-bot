const assert=require('node:assert/strict'),fs=require('node:fs');
const{chromium}=require('playwright');
const origin=process.env.AINZ_ORIGIN||'http://127.0.0.1:8161';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 fs.mkdirSync('output/ainz-six',{recursive:true});
 try{
  const catalog=await(await fetch(origin+'/nzd-catalog')).json(),room=catalog.rooms.find(r=>r.enemies.includes('ainz')).index;
  assert.equal(catalog.guardians.find(g=>g.id==='ainz').moves.length,6);
  for(const width of[1100,390]){
   const p=await browser.newPage({viewport:{width,height:width<500?844:1000},isMobile:width<500,hasTouch:width<500});
   let latestRaid;
   p.on('response',async r=>{if(r.url().includes('/api/raid/'))try{const body=await r.json(),raid=body.raid||body;if(raid.status)latestRaid=raid;}catch{}});
   p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.status()>=400&&new URL(r.url()).origin===origin)errors.push(r.status()+' '+r.url());});
   for(let phase=1;phase<=6;phase++){
    await p.goto(origin+`/nzd-demo?mode=fight&room=${room}&phase=${phase}`);
    await p.locator('.nazarick-field').waitFor();
    const sprite=p.locator('.enemy-0 .raid-sprite');await sprite.evaluate(n=>n.decode());
    assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    assert.equal(await p.locator('.nz-floating-staff').count(),phase===6?1:0);
    assert.equal(latestRaid?.phase_count,6);
    assert.match(await p.locator('body').innerText(),new RegExp(phase+'/6'));
    assert.equal(await p.locator('.ainz-strategy').count(),0);
    await p.screenshot({path:`output/ainz-six/phase-${phase}-${width}.png`,fullPage:true});
   }
   await p.close();
  }
  const p=await browser.newPage({viewport:{width:1100,height:1000}});p.on('pageerror',e=>errors.push(e.message));
  for(const defense of['dodge','block'])for(let phase=1;phase<=6;phase++){
   await p.goto(origin+`/nzd-demo?mode=pattern&who=ainz&room=${room}&phase=${phase}&move=${phase===1?1:0}&defense=${defense}`);
   await p.locator('.qte-cover').waitFor({timeout:10000});await p.waitForTimeout(1700);
   assert.match(await p.locator('.qte-cover h2').innerText(),/Аинз/);
   assert(!(await p.locator('.qte-cover .qte-help').innerText()).includes('Убийство слабого'));
   await p.screenshot({path:`output/ainz-six/pattern-${phase}-${defense}.png`});
   await p.locator('.qte-abort').click();await p.waitForTimeout(350);
   assert(!(await p.locator('body').innerText()).includes('Объявленный навык недоступен'));
  }
  await p.goto(origin+'/ainz-review');await p.waitForFunction(()=>document.querySelector('#phase')?.options.length===6);
  assert.equal(await p.locator('#guardian').inputValue(),'ainz');
  assert.deepEqual(errors,[]);console.log('PASS six phases, desktop/mobile, all sprites, floating staff, native dodge/block and review controls');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
