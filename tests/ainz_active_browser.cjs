const assert=require('node:assert/strict'),fs=require('node:fs'),{chromium}=require('playwright');
const origin=process.env.AINZ_ORIGIN||'http://127.0.0.1:8161';
(async()=>{
 const b=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 fs.mkdirSync('output/ainz-six',{recursive:true});
 try{
  const catalog=await(await fetch(origin+'/nzd-catalog')).json(),room=catalog.rooms.find(r=>r.enemies.includes('ainz')).index;
  const p=await b.newPage({viewport:{width:1100,height:1000}});p.on('pageerror',e=>errors.push(e.message));
  for(let phase=1;phase<=6;phase++){
   const move=phase===3?1:phase===6?2:0;
   await p.goto(origin+`/nzd-demo?mode=pattern&who=ainz&room=${room}&phase=${phase}&move=${move}&defense=dodge`);
   await p.locator('.qte-cover').waitFor();await p.waitForTimeout(3300);
   assert(await p.evaluate(()=>!!window.AinzArt&&!!window.AinzQTE));
   await p.screenshot({path:`output/ainz-six/active-${phase}.png`});
  }
  const loaded=await p.evaluate(async()=>Promise.all(['mage','blades','bow','axe','warrior','death','qte-bg-1','qte-bg-2','qte-bg-3','qte-bg-4','qte-bg-5','qte-bg-6','qte-bg-ritual'].map(async key=>{const im=new Image();im.src='/static/assets/nazarick/ainz-'+key+'-v3.png';await im.decode();return im.naturalWidth>0;})));
  assert(loaded.every(Boolean));await p.close();
  const m=await b.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});m.on('pageerror',e=>errors.push(e.message));
  for(const defense of ['dodge','block']){
   await m.goto(origin+`/nzd-demo?mode=pattern&who=ainz&room=${room}&phase=5&move=2&defense=${defense}`);
   await m.locator('.qte-cover').waitFor();await m.waitForTimeout(2500);
   assert(await m.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   const canvas=m.locator('.qte-cover canvas');const bounds=await canvas.boundingBox();
   assert(bounds.width>200&&bounds.x>=0&&bounds.x+bounds.width<=390);
   await m.screenshot({path:`output/ainz-six/mobile-${defense}.png`});
   await m.locator('.qte-abort').click();
  }
  assert.deepEqual(errors,[]);console.log('PASS active art for six phases, all 13 v3 PNGs, mobile native dodge/block');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
