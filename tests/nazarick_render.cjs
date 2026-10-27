// Exercise the same presentation functions used by the live battle and lab.
const fs=require('node:fs'),vm=require('node:vm');
const E=require('../webapp/qte-unique/engine'),B=require('../webapp/qte-block/engine'),N=require('../webapp/nazarick-qte.js');
const window={QTEUnique:E,QTEBlock:B,NazarickQTE:N};
const sandbox={window,QTEUnique:E,QTEBlock:B,Math};
vm.runInNewContext(fs.readFileSync('webapp/qte-view','utf8'),sandbox);
vm.runInNewContext(fs.readFileSync('webapp/qte-block-view','utf8'),sandbox);
let draws=0;
const ctx=new Proxy({}, {get(o,k){return o[k]??((...args)=>{for(const a of args)if(typeof a==='number'&&!Number.isFinite(a))throw Error('Non-finite '+k);});},set(o,k,v){o[k]=v;return true;}});
let raw='';process.stdin.on('data',b=>raw+=b);
process.stdin.on('end',()=>{
 for(const desc of JSON.parse(raw)){
  const p=E.profile(desc);
  const dodge=E.defense(p,{accuracy:100,evasion:0,enemyAccuracy:100,enemyEvasion:0},42,{hp:100000,endOnDeath:false});
  const block=B.create(desc,{physicalDefense:20,magicDefense:20,enemyAttack:20,enemyAccuracy:100},42,{hp:100000,endOnDeath:false});
  for(let i=0;i<Math.ceil(dodge.duration*120);i++){
   E.defenseStep(dodge,1/120,{x:Math.sin(i/120),y:Math.cos(i/120)});
   if(i%18===0){window.QTEView.draw(ctx,{clientWidth:360},dodge);draws++;}
  }
  for(let i=0;i<Math.ceil(block.duration*120);i++){
   B.step(block,1/120,{angle:Math.sin(i/70),active:i%120<50});
   if(i%18===0){window.QTEBlockView.draw(ctx,{clientWidth:360},block);draws++;}
  }
 }
 process.stdout.write(JSON.stringify({draws}));
});
