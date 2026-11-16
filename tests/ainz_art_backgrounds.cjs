const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),A=require('../webapp/ainz-qte.js');
const sources=[],labels=[];
class Image{constructor(){this.complete=true;this.naturalWidth=1881;this.naturalHeight=836;}set src(s){sources.push(s);}}
const ctx=new Proxy({globalAlpha:1,fillText:t=>labels.push(t)},{get:(o,k)=>o[k]??(()=>{}),set:(o,k,v)=>(o[k]=v,true)});
const scope={Image,AinzQTE:A,NazarickQTE:{STONE_COLORS:['red','blue','violet','green','gold','pink','gray']},QTEUnique:{geometry:()=>{throw Error('Warning revealed future path');}},Math};
vm.runInNewContext(fs.readFileSync('webapp/ainz-qte-art.js','utf8'),scope);
for(let phase=1;phase<=6;phase++)for(const move of [0,1]){
 const p={skill:{base_id:`nz_ainz6_p${phase}_${move}`}},s={kind:'defense',p,time:1,preparation:1};
 scope.AinzArt.field(ctx,s);assert.equal(scope.AinzArt.backgroundKey(p),phase===6&&move===1?'ritual':String(phase));
}
assert.equal(sources.length,7);assert(sources.every(s=>/ainz-qte-bg-(?:[1-6]|ritual)-v3\.png$/.test(s)));
assert(!labels.includes('АРТЕФАКТ'));
scope.AinzArt.hazard(ctx,{p:{skill:{base_id:'nz_ainz6_p2_0'}},time:1},{type:'bullet',x:30,y:60,vx:140,vy:0,r:7,motif:'dagger',color:'#dda'},null,{warning:true,spent:false});
console.log('PASS seven phase/special backgrounds, no boss/artifact decoration, no future projectile trail');
