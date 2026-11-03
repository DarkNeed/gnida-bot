const assert=require('node:assert/strict'),C=require('../webapp/qte-combined.js'),drawn=[];
const proxy=C.layerContext({fillText:(...a)=>drawn.push(a)});
proxy.fillText('НАЗАРИК · Костяной залп',18,23);
proxy.fillText('Клинок рыцаря смерти · ФАЗА 1',360,25);
proxy.fillText('КАМЕНЬ 3 / 7 · БЕЗДНА',360,52);
proxy.fillText('СМЕРТЬ',100,100);
assert.deepEqual(drawn.map(a=>a[0]),['КАМЕНЬ 3 / 7 · БЕЗДНА','СМЕРТЬ']);
console.log('PASS duplicate source headings hidden, mechanic instructions preserved');
