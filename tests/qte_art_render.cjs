/* All catalogue classes, real trajectories, strict read-only canvas smoke test. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const E=require('../webapp/qte-unique/engine'),B=require('../webapp/qte-block/engine'),N=require('../webapp/nazarick-qte.js');
const window={QTEUnique:E,QTEBlock:B,NazarickQTE:N},sandbox={window,QTEUnique:E,QTEBlock:B,Math};
for(const file of['qte-art.js','qte-casino-view','qte-view','qte-block-view'])vm.runInNewContext(fs.readFileSync('webapp/'+file,'utf8'),sandbox,{filename:file});
let calls=0,depth=0,draws=0;const stack=[];
const target={globalAlpha:1,save(){stack.push({...target});depth++;},restore(){assert(depth>0,'Unbalanced canvas restore');Object.assign(target,stack.pop());depth--;},createLinearGradient(){return {addColorStop(){}};},createRadialGradient(){return {addColorStop(){}};}};
const ctx=new Proxy(target,{get(o,k){return o[k]??((...args)=>{calls++;for(const a of args)if(typeof a==='number')assert(Number.isFinite(a),'Non-finite canvas '+k);if(k==='arc')assert(args[2]>=0);});},set(o,k,v){if(typeof v==='number')assert(Number.isFinite(v),'Non-finite canvas property '+k);o[k]=v;return true;}});
let raw='';process.stdin.on('data',b=>raw+=b);
process.stdin.on('end',()=>{
 const catalog=JSON.parse(raw),classes=new Set(),motifs=new Set(),handled=new Set();
 const stats={accuracy:85,evasion:15,enemyAccuracy:100,enemyEvasion:0};
 function render(view,s){
  const before=JSON.stringify(s);window[view].draw(ctx,{clientWidth:360},s);
  assert.equal(depth,0,'Canvas stack leaked');assert.equal(JSON.stringify(s),before,'Renderer mutated combat state');draws++;
 }
 for(const sk of catalog){
  const p=E.profile(sk),a=window.QTEArt.appearance(p);
  if(a){classes.add(a.cls);motifs.add(a.motif);}
  const dodge=E.defense(p,stats,17,{hp:100000,endOnDeath:false});
  const block=B.create(sk,{physicalDefense:30,magicDefense:30,enemyAttack:30,enemyAccuracy:100},17,{hp:100000,endOnDeath:false});
  const attack=E.attack(p,stats,17,{hp:100000,endOnDeath:false});
  for(let i=0;i<Math.ceil(dodge.duration*120);i++){
   E.defenseStep(dodge,1/120,{x:Math.sin(i/150),y:Math.cos(i/180)});
   if(i%20===0){render('QTEView',dodge);for(const h of dodge.hazards){if(dodge.time>=h.start&&dodge.time<h.end){const g=E.geometry(h,dodge.time);if(window.QTEArt.hazard(ctx,dodge,h,g,{warning:false,spent:false}))handled.add(sk.class_id+':'+h.type);}}}
  }
  for(let i=0;i<Math.ceil(block.duration*120);i++){
   B.step(block,1/120,{angle:i/150,active:i%120<60});if(i%30===0)render('QTEBlockView',block);
  }
  for(let i=0;i<Math.ceil(attack.duration*120);i++){
   E.attackStep(attack,1/120);if(i%30===0)render('QTEView',attack);
  }
 }
 assert.equal(classes.size,13); // Gambler keeps its existing bespoke casino art.
 assert(motifs.size>=25,`Only ${motifs.size} visual motifs`);
 for(const cls of Object.keys(window.QTEArt.themes).filter(c=>c!=='gambler'))assert([...handled].some(k=>k.startsWith(cls+':')),'Unstyled '+cls);
 const find=id=>E.profile(catalog.find(s=>s.base_id===id));
 assert.equal(window.QTEArt.appearance(find('warning_shot')).motif,'bullet');
 assert.equal(window.QTEArt.appearance(find('hunter_shot')).motif,'silver_bullet');
 assert.equal(window.QTEArt.appearance(find('first_line')).motif,'paper');
 assert.equal(window.QTEArt.appearance(find('red_etude')).motif,'paint');
 for(const sk of catalog.filter(s=>s.class_id==='raid'))assert.equal(window.QTEArt.appearance(E.profile(sk)),null,'Boss art overwritten');
 // Flipping art on/off must not change deterministic outcomes.
 for(const id of['warning_shot','hunter_shot','red_etude','whole_family','mana_shot']){
  const p=find(id),first=E.defense(p,stats,24,{hp:10000,endOnDeath:false}),second=E.defense(p,stats,24,{hp:10000,endOnDeath:false});
  for(let i=0;i<1000;i++){const input={x:Math.sin(i/130),y:Math.cos(i/90)};E.defenseStep(first,1/120,input);E.defenseStep(second,1/120,input);if(i%10===0)render('QTEView',first);}
  assert.equal(JSON.stringify(first),JSON.stringify(second),'Rendering changed outcomes '+id);
 }
 process.stdout.write(JSON.stringify({profiles:catalog.length,classes:classes.size,existingCasino:1,motifs:motifs.size,draws,calls,handled:[...handled]}));
});
