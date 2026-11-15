const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const origin=process.env.CHEST_MIMIC_URL||'http://127.0.0.1:8160';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 fs.mkdirSync('output/chest-mimic-review',{recursive:true});
 try{
  for(const width of [1280,390]){
   const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(origin+'/chest-mimic-demo?mode=battle');
   await page.locator('.encounter-enemy .raid-sprite[src*="chest_mimic"]').waitFor();
   const lone=await page.locator('.encounter-field').evaluate(field=>{
    const f=field.getBoundingClientRect(),r=field.querySelector('.enemy-0').getBoundingClientRect();
    return {center:(r.left+r.width/2-f.left)/f.width,inset:(f.right-r.right)/f.width};
   });
   assert(lone.center>.78&&lone.center<.85,'Lone enemy must stay on the right without hugging the edge');
   assert(lone.inset>=.07&&lone.inset<=.10,'Enemy must have a visible inset from the right edge');
   await page.screenshot({path:`output/chest-mimic-review/formation-single-${width}.png`,fullPage:true});
   // Local DOM-only fixture: exercise the real CSS with one, two and three
   // enemies, without altering the encounter or inventing server participants.
   await page.locator('.encounter-field').evaluate(field=>{
    const first=field.querySelector('.enemy-0');
    for(let i=1;i<3;i++){const e=first.cloneNode(true);e.classList.remove('enemy-0');e.classList.add('enemy-'+i);field.append(e);}
   });
   for(const enterprise of [false,true]){
    await page.locator('.encounter-field').evaluate((f,on)=>f.classList.toggle('enterprise-defense-field',on),enterprise);
    const positions=await page.locator('.encounter-field').evaluate(field=>{
     const f=field.getBoundingClientRect();
     return [0,1,2].map(i=>{const r=field.querySelector('.enemy-'+i).getBoundingClientRect();return {x:r.left,y:r.top,right:r.right,bottom:r.bottom,left:f.left,edge:f.right};});
    });
    for(const p of positions){assert(p.x>=p.left-1);assert(p.right<=p.edge+1);}
    for(let i=1;i<positions.length;i++){assert(positions[i].x<positions[i-1].x);assert(positions[i].y>positions[i-1].y);}
   }
   await page.locator('.encounter-field').evaluate(f=>f.classList.remove('enterprise-defense-field'));
   await page.locator('.encounter-field').evaluate(field=>{
    const first=field.querySelector('.raid-ally.slot-0');
    for(let i=1;i<3;i++){const ally=first.cloneNode(true);ally.classList.remove('slot-0','raid-own');ally.classList.add('slot-'+i);ally.id='layout-only-ally-'+i;field.append(ally);}
    field.classList.add('guild-party-field');
   });
   const onField=await page.locator('.encounter-field').evaluate(field=>{
    const f=field.getBoundingClientRect();return [...field.querySelectorAll('.raid-ally .raid-hud')].every(e=>{const r=e.getBoundingClientRect();return r.top>=f.top&&r.bottom<f.bottom&&r.left>=f.left-1&&r.right<=f.right+1;});
   });
   assert(onField,'All three ally HUDs stay inside the natural-proportion scene');
   const clearHealth=await page.locator('.encounter-field').evaluate(field=>{
    const allies=[...field.querySelectorAll('.raid-ally .raid-sprite')].map(e=>e.getBoundingClientRect());
    return [...field.querySelectorAll('.encounter-compact-hud')].every(e=>{const r=e.getBoundingClientRect();return allies.every(a=>r.right<=a.left||r.left>=a.right||r.bottom<=a.top||r.top>=a.bottom);});
   });
   assert(clearHealth,'Enemy HP does not overlap full-size heroes in a three-unit party');
   await page.screenshot({path:`output/chest-mimic-review/formation-three-${width}.png`,fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   assert.deepEqual(errors,[]);console.log('PASS right-to-left enemy formation, solo and groups',width);await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
