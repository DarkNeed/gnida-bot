const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const origin=process.env.AINZ_ORIGIN||'http://127.0.0.1:8161';
(async()=>{const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const cat=await(await fetch(origin+'/nzd-catalog')).json(),room=cat.rooms.find(r=>r.enemies.includes('ainz')).index;
 fs.mkdirSync('output/ainz-pressure',{recursive:true});
 const p=await b.newPage({viewport:{width:1100,height:1000}});p.on('pageerror',e=>errors.push(e.message));
 for(const[phase,move]of[[4,0],[4,1],[4,2],[4,3],[6,0]]){
  await p.goto(origin+`/nzd-demo?mode=pattern&who=ainz&room=${room}&phase=${phase}&move=${move}&defense=dodge`);
  await p.locator('.qte-cover').waitFor();assert(!(await p.locator('.qte-help').innerText()).includes('Убийство'));
  await p.waitForTimeout(phase===6?4600:3300);
  await p.screenshot({path:`output/ainz-pressure/p${phase}-${move}.png`});
  await p.locator('.qte-abort').click();
 }
 await p.close();const m=await b.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});m.on('pageerror',e=>errors.push(e.message));
 await m.goto(origin+`/nzd-demo?mode=pattern&who=ainz&room=${room}&phase=6&move=0&defense=dodge`);
 await m.locator('.qte-cover').waitFor();await m.waitForTimeout(4000);
 assert(await m.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await m.screenshot({path:'output/ainz-pressure/time-mobile.png'});
 assert.deepEqual(errors,[]);console.log('PASS all four heavy attacks, crossed time curtains, no tactical hints, mobile layout');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
