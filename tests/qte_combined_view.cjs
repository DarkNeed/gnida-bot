const assert=require('node:assert/strict'),C=require('../webapp/qte-combined.js'),drawn=[];
const proxy=C.layerContext({fillText:(...a)=>drawn.push(a)});
proxy.fillText('НАЗАРИК · Костяной залп',18,23);
proxy.fillText('Клинок рыцаря смерти · ФАЗА 1',360,25);
proxy.fillText('КАМЕНЬ 3 / 7 · БЕЗДНА',360,52);
proxy.fillText('СМЕРТЬ',100,100);
assert.deepEqual(drawn.map(a=>a[0]),['КАМЕНЬ 3 / 7 · БЕЗДНА','СМЕРТЬ']);
// Several simultaneous sources share one shield. The shared renderer must retain
// the normal block arena and the bright exact-block cue rather than reducing it
// to a thin line.
global.QTEBlockView={draw(){}};
const arcs=[],strokes=[],texts=[];
const ctx={
  save(){},restore(){},clearRect(){},fillRect(){},beginPath(){},moveTo(){},lineTo(){},
  arc(x,y,r){arcs.push(r);},translate(){},rotate(){},setLineDash(){},
  stroke(){strokes.push([this.strokeStyle,this.lineWidth]);},fillText(value){texts.push(value);},
};
C.draw(ctx,{}, {block:true,time:2,states:[{time:2}],contacts:[{time:1.8,outcome:'perfect',damage:0}],carrier:{active:true,time:2,perfectUntil:2.2,angle:0,params:{arc:1.8}}});
assert(arcs.includes(145)&&arcs.includes(92)&&arcs.includes(48),'full block rings are drawn once');
assert(strokes.some(([color,width])=>color==='#fff1bd'&&width===10),'exact block has its original wide gold cue');
assert(texts.includes('ТОЧНЫЙ БЛОК'),'exact block result remains visible');
console.log('PASS duplicate source headings hidden; shared block keeps rings and exact-block cue');
