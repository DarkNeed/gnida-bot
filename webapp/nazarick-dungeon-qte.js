/* Deterministic guardian patterns, mirrored by arena_nazarick_dungeon_patterns.py. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.NazarickDungeonQTE=api;})(globalThis,function(){
'use strict';
const colors={gargantua:'#c8ad76',cocytus:'#8edcff',aura:'#b0da79',mare:'#73bd83',victim:'#edacd0',sebas:'#d7e2e7',yuri:'#b0b8de',narberal:'#8ccfff',lupusregina:'#e9b187',solution:'#91cfb4',entoma:'#dc8ba8',cz:'#c5be94'};
const motifs={gargantua:'stone',cocytus:'ice',aura:'arrow',mare:'root',victim:'sigil',sebas:'fist',yuri:'fist',narberal:'orb',lupusregina:'claw',solution:'venom',entoma:'beetle',cz:'bullet'};
const families={gargantua:['impact','impact','impact','impact','impact'],cocytus:['slash','slash','ice','ice','slash'],aura:['thrust','slash','beast','edict','beast'],mare:['paint','thrust','impact','holy','fire'],victim:['mana','edict','script','holy','script'],sebas:['thrust','impact','slash','holy','impact'],yuri:['impact','impact','slash','holy','impact'],narberal:Array(5).fill('lightning'),lupusregina:['beast','beast','impact','holy','beast'],solution:['paint','paint','paint','holy','paint'],entoma:['thrust','paint','beast','holy','beast'],cz:Array(5).fill('thrust')};
function shapes(s,e){
 const revision=revisionShapes(s,e);if(revision!==null)return revision;
 const parts=s.p.skill.base_id.split('_'),who=parts[1],phase=Number(parts[2].slice(1)),move=Number(parts[3]);if(!colors[who])return null;
 const x=s.player.x,y=s.player.y,i=e.index,sign=i%2?1:-1,d=s.d,out=[],color=colors[who],motif=motifs[who];
 function add(h,delay=0,duration=.25){out.push({color,motif,...h,delay,duration});}
 function line(angle,delay=0,width=6){const dx=Math.cos(angle)*850,dy=Math.sin(angle)*850;add({type:'line',ax:x-dx,ay:y-dy,bx:x+dx,by:y+dy,r:width*d.beamScale,motif:'cut',tier:'heavy',weight:.45},delay,.23);}
 function volley(bx,by,delay=0,n=3,speed=.70){const a=Math.atan2(y-by,x-bx);for(let j=0;j<n;j++){const angle=a+(j-(n-1)/2)*.25;add({type:'bullet',x:bx,y:by,vx:Math.cos(angle)*d.speed*speed,vy:Math.sin(angle)*d.speed*speed,r:j===Math.floor(n/2)?7:5,tier:'normal',weight:.20,length:22},delay,2.4);}}
 function circle(cx,cy,delay=0,r=35){add({type:'circle',x:Math.max(r+10,Math.min(710-r,cx)),y:Math.max(r+10,Math.min(310-r,cy)),r,motif:who==='mare'?'root':'sigil',tier:'normal',weight:.28},delay,.28);}
 function corridor(delay=0){const center=Math.max(62,Math.min(258,y+sign*36)),half=Math.max(49,d.gap*.52);for(const [a,b]of[[0,Math.max(0,center-half)],[Math.min(320,center+half),320]])if(b>a)add({type:'rect',x:0,y:a,w:720,h:b-a,label:who==='cocytus'?'МОРОЗ':'РАЗЛОМ',tier:'heavy',weight:.45},delay,.25);}
 if(move===3){if(who==='aura'&&phase===2){for(let j=0;j<3;j++)volley(j%2?20:700,45+j*110,j*.65,3,.48);}return out;}
 if(move===4){
  if(who==='gargantua'){
   for(let j=0;j<3;j++){const cx=Math.max(55,Math.min(665,x+(j-1)*145));add({type:'rect',x:cx-42,y:0,w:84,h:320,label:'ВАЛУН',motif:'stone',tier:'heavy',weight:.42},.30+j*.65,.28);volley(j%2?20:700,50+j*100,.65+j*.65,1,.50);}
  }else if(who==='cocytus'){
   for(let j=0;j<5;j++){const angle=sign*(.20+j*.57),dx=Math.cos(angle)*850,dy=Math.sin(angle)*850;add({type:'line',ax:x-dx,ay:y-dy,bx:x+dx,by:y+dy,r:(j===4?8:5)*d.beamScale,motif:j===4?'lightning':'ice',color:j===4?'#c4edff':colors[who],tier:j===4?'heavy':'normal',weight:j===4?.40:.22},.10+j*.48,.18);}
  }else if(who==='aura'){
   for(let j=0;j<3;j++){const bx=j%2?20:700,by=45+((i+j)%3)*110,a=Math.atan2(y-by,x-bx);add({type:'bullet',x:bx,y:by,vx:Math.cos(a)*d.speed*.65,vy:Math.sin(a)*d.speed*.65,r:9,motif:'wolf',length:27,homing:.22,turnRate:.75,tier:'heavy',weight:.35},j*.64,2.4);volley(360,20,.30+j*.64,2,.61);}
  }else if(who==='mare'){
   for(let j=0;j<3;j++){if(phase===1){const cy=30+((i+j)%3)*125;add({type:'rect',x:0,y:cy,w:720,h:28,label:'ЛАВА',motif:'flame',color:'#ed7847',tier:'heavy',weight:.4},.25+j*.65,.24);}else{circle(x+(j-1)*115,y,.30+j*.60,38);line(sign*(.35+j*.70),.62+j*.60,6);}}
  }else if(who==='victim'){
   for(let j=0;j<4;j++){line(sign*(j*.65+.2),.20+j*.52,5);if(j%2===0)volley(360,20,.48+j*.52,2,.45);}
  }else if(who==='sebas'||who==='yuri'){
   for(let j=0;j<3;j++){const a=sign*(.25+j*1.0),dx=Math.cos(a)*850,dy=Math.sin(a)*850;add({type:'line',ax:x-dx,ay:y-dy,bx:x+dx,by:y+dy,r:j===2?10:6,motif:'fist',tier:j===2?'heavy':'normal',weight:j===2?.45:.25},.16+j*.65,.20);}if(who==='sebas'&&phase===2)circle(x+sign*100,y,1.85,38);
  }else if(who==='narberal'){
   for(let j=0;j<(phase===1?3:4);j++){const bx=j%2?0:720,by=30+((i+j)%3)*125,tx=x+(j-1)*90,ty=y,dx=tx-bx,dy=ty-by,length=Math.hypot(dx,dy)||1,points=[];for(let k=0;k<15;k++){const f=k/14,zig=Math.sin(k*2.6+j)*Math.sin(f*Math.PI)*24;points.push([bx+dx*f-dy/length*zig,by+dy*f+dx/length*zig]);}add({type:'polyline',points,r:5*d.beamScale,motif:'lightning',color:'#9bdcff',tier:'heavy',weight:.33},.15+j*.58,.20);}
  }else if(who==='lupusregina'){
   for(let j=0;j<3;j++){circle(x+(j-1)*85,y,.22+j*.64,32);line(sign*(.55+j*.6),.54+j*.64,6);}
  }else if(who==='solution'){
   for(let j=0;j<3;j++){circle(x+(j-1)*120,y+sign*25,.35+j*.60,43);volley(j%2?20:700,50+j*100,.60+j*.60,3,.43);}
  }else if(who==='entoma'){
   for(let j=0;j<3;j++){const bx=j%2?20:700,by=45+j*110,a=Math.atan2(y-by,x-bx);for(let k=0;k<4;k++){const angle=a+(k-1.5)*.30;add({type:'bullet',x:bx,y:by,vx:Math.cos(angle)*d.speed*.62,vy:Math.sin(angle)*d.speed*.62,r:4,motif:'fly',tier:'minor',weight:.08},j*.64,2.4);}if(j===1)line(sign*.65,1.25,4);}
  }else if(who==='cz'){for(let j=0;j<3;j++)volley(j%2?20:700,40+j*115,.12+j*.70,3,.76);}
  const total=Math.max(0,...out.map(h=>h.delay))||1;out.forEach((h,j)=>{h.strike=Math.min(s.p.strikes-1,who==='cocytus'?j:Math.floor(h.delay/total*s.p.strikes));});
  return out;
 }
 if(who==='gargantua'){
  if(move===0){line(sign*.5,.20,10);if(phase===2)volley(sign>0?20:700,40+e.jitter*240,.90,3,.63);}
  else if(move===1){volley(700,35+e.jitter*250,0,phase===2?5:3,.62);circle(x+sign*95,y,.85,40);}
  else{corridor(.35);if(phase===2)line(sign*1.15,1.1,7);}
 }else if(who==='cocytus'){
  if(move===0){line(sign*.65,.10);line(-sign*.65,.90);}
  else if(move===1){for(let j=0;j<(phase===2?4:3);j++)line(sign*(.25+j*.65),j*.50,5);}
  else{corridor(.30);volley(690,160,1.0,3,.66);}
 }else if(who==='aura'){
  if(move===0){volley(20,40+e.jitter*240,0,3,.78);volley(700,280-e.jitter*240,.80,phase===2?3:1,.75);}
  else if(move===1){const a=sign*.45;add({type:'polyline',points:Array.from({length:19},(_,j)=>[x+Math.cos(a+j*.19)*105,y+Math.sin(a+j*.19)*105]),r:7,motif:'halberd',tier:'heavy',weight:.45},.35,.30);if(phase===2)volley(20,160,1.05,1,.73);}
  else{for(let j=0;j<(phase===2?3:2);j++)volley(j%2?700:20,35+((i+j)%3)*120,j*.60,1,.64);}
 }else if(who==='mare'){
  if(move===0){circle(x,y,.45,34);circle(x+sign*110,y-sign*30,1.1,34);}
  else if(move===1){volley(30,40+e.jitter*240,.15,phase===2?5:3,.63);volley(690,280-e.jitter*240,.95,1,.66);}
  else{corridor(.40);if(phase===2)circle(x+sign*90,y,1.15,40);}
 }else if(who==='victim'){
  if(move===0){volley(360,20,.10,phase===2?5:3,.48);volley(360,300,.95,3,.48);}
  else if(move===1){circle(x,y,.50,phase===2?48:38);if(phase===2)circle(x-sign*130,y+sign*30,1.15,38);}
  else{line(sign*.70,.35,5);if(phase===2){line(-sign*.70,1.0,5);volley(700,160,1.3,1,.52);}}
 }else if(who==='sebas'||who==='yuri'){
  if(move===0){volley(700,y,.15,1,who==='sebas'?.91:.78);volley(20,320-y,.95,1,.78);}
  else if(move===1){line(sign*.25,.20,7);line(-sign*.25,.95,7);if(phase===2)volley(700,y,1.5,1,.80);}
  else{add({type:'polyline',points:Array.from({length:23},(_,j)=>[x+Math.cos(j*.22)*100,y+Math.sin(j*.22)*100]),r:7,motif:'halberd',tier:'heavy',weight:.5},.40,.27);if(phase===2)line(sign*.85,1.2);}
 }else if(who==='narberal'){
  if(move===0)volley(700,35+e.jitter*250,.05,phase===2?5:3,.65);
  else if(move===2){for(let j=0;j<4;j++){const cx=90+j*180+sign*18;add({type:'polyline',points:Array.from({length:13},(_,k)=>[cx+Math.sin(k*2.7+j)*Math.sin(k*Math.PI/12)*18,k*320/12]),r:5*d.beamScale,motif:'lightning',tier:'normal',weight:.3},.20+j*.28,.20);}if(phase===2)volley(700,160,1.35,3,.57);}
  else{for(let j=0;j<(phase===2?3:2);j++){const cx=Math.max(24,Math.min(696,x+(j-1)*110)),points=Array.from({length:13},(_,k)=>[cx+Math.sin(k*2.1+i)*Math.sin(k*Math.PI/12)*22,k*320/12]);add({type:'polyline',points,r:5*d.beamScale,motif:'lightning',tier:'normal',weight:.3},.25+j*.65,.20);}}
 }else if(who==='lupusregina'){
  if(move===0){line(sign*.55,.20);line(-sign*.55,1.0);}
  else if(move===1){circle(x,y,.45,36);volley(20,160,1.1,phase===2?3:1,.76);}
  else{line(sign*1.05,.35,9);if(phase===2)circle(x+sign*110,y,1.1,40);}
 }else if(who==='solution'){
  if(move===0){volley(700,160,.15,phase===2?5:3,.50);volley(20,40+e.jitter*240,.95,3,.52);}
  else if(move===1){line(sign*.8,.35,6);line(Math.PI/2,1.10,5);}
  else{circle(x,y,.45,42);circle(x+sign*120,y-sign*35,1.25,35);}
 }else if(who==='entoma'){
  if(move===0){volley(700,30+e.jitter*260,.10,3,.68);volley(20,290-e.jitter*260,.9,phase===2?3:1,.65);}
  else if(move===1){line(sign*.7,.35,4);line(-sign*.7,1.1,4);}
  else{volley(360,20,.10,phase===2?5:3,.58);volley(700,280,1.0,3,.56);}
 }else if(who==='cz'){
  if(move===0){volley(sign>0?20:700,y,.15,1,.90);if(phase===2)volley(sign>0?700:20,320-y,.90,1,.87);}
  else if(move===1){for(let j=0;j<3;j++)volley(700,35+((i+j)%3)*120,j*.55,1,.79);}
  else{volley(20,60,.10,phase===2?3:1,.75);volley(700,260,.95,3,.75);}
 }
 return out;
}
function blocks(p,seed,params,rng){const a=p.skill.base_id.split('_'),who=a[1],phase=Number(a[2].slice(1)),move=Number(a[3]);if(!colors[who])return null;if(move===3&&(who!=='aura'||phase!==2))return [];
 if(['gargantua','sebas'].includes(who)){const out=[],random=rng((seed^p.seed)>>>0),offset=random()*Math.PI*2;for(let wave=0;wave<3;wave++){const count=[1,2].includes(move)?3:2;for(let j=0;j<count;j++){const angle=offset+(wave*2+j)*Math.PI/3,heavy=j===0&&who==='gargantua'||j===count-1&&move===4,kind=heavy&&(who==='gargantua'||phase===2)?'wave':who==='gargantua'?'bolt':'slash';out.push({id:'block:'+out.length,at:2.1+wave*2.1+j*(who==='gargantua'?.52:.37),warning:Math.max(.85,params.warning),angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind,motif:who==='gargantua'?'stone':phase===2?'claw':'fist',color:colors[who],tier:heavy?'heavy':'minor',weight:heavy?.3:.1,strike:Math.min(p.strikes-1,wave),resolved:false});}}return out;}
 if(who==='victim'&&phase===2&&move===4){const out=[];for(let part=0;part<6;part++){const count=[1,4].includes(part)?8:6;for(let j=0;j<count;j++){const a=(part+j*(part===4?.5:1))*Math.PI/3,feint=[2,5].includes(part)&&j===0,wave=j===count-1||part===3&&j===2,kind=feint?'feint':wave?'wave':[1,4].includes(part)?'bolt':'slash';out.push({id:'block:'+out.length,at:2.2+part*7+j*(count===8?.64:.85),warning:Math.max(.76,params.warning),angle:Math.atan2(Math.sin(a),Math.cos(a)),kind,motif:kind==='bolt'?'sigil':'chain',color:colors[who],tier:wave?'heavy':'minor',weight:feint?0:wave?.22:.075,strike:0,resolved:false});}}return out;}
 const r=rng((seed^p.seed)>>>0),offset=Math.floor(r()*8)*Math.PI/4,out=[];let count=phase===2?5:4;if(move===4)count=['gargantua','sebas','yuri'].includes(who)?3:who==='cocytus'?5:6;
 for(let i=0;i<count;i++){
  let angle=offset+p.polarity*(who==='cocytus'?i*Math.PI/2:who==='cz'?i%2*Math.PI:who==='sebas'||who==='yuri'?i%2*Math.PI/2:who==='mare'||who==='gargantua'?i*Math.PI/3:(i+move)*Math.PI/4);
  if(move===1)angle+=i%2*Math.PI/2;if(move===2)angle-=i*Math.PI/6;
  let kind=move===2&&['mare','gargantua','victim'].includes(who)?'wave':['aura','cz','entoma','narberal','solution'].includes(who)?'bolt':'slash';
  if(move===4){kind=['gargantua','mare','victim'].includes(who)?'wave':['cocytus','sebas','yuri','lupusregina'].includes(who)?'slash':'bolt';angle=offset+p.polarity*(who==='cz'?i%2*Math.PI:who==='cocytus'?i*Math.PI/2:i*Math.PI/3);}
  const at=2.2+i*(move===4?(count===3?2.0:1.05):(phase===2?1.3:1.65)),warning=Math.max(move===4?.88:.82,params.warning),weight=kind==='wave'?.5:.3;
  out.push({id:'block:'+out.length,at,warning,angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind,motif:motifs[who],color:colors[who],tier:kind==='wave'?'heavy':'normal',weight,strike:0,resolved:false});
  if(phase===2&&move===1)out.push({id:'block:'+out.length,at:at+.65,warning,angle:Math.atan2(Math.sin(angle+Math.PI/2),Math.cos(angle+Math.PI/2)),kind:'bolt',motif:motifs[who],color:colors[who],tier:'minor',weight:.1,strike:0,resolved:false});
 }
 out.sort((a,b)=>a.at-b.at);out.forEach((e,i)=>{e.id='block:'+i;e.strike=Math.min(p.strikes-1,Math.floor(i*p.strikes/out.length));});return out;
}
function glyph(ctx,motif,x,y,r,angle,color,t=0){
 if(!Object.values(motifs).includes(motif)&&!['fly','wolf','chain','whip','flame'].includes(motif))return false;
 ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.fillStyle=color;ctx.strokeStyle=color;ctx.lineWidth=1.7;ctx.shadowColor=color;ctx.shadowBlur=8;
 if(motif==='bullet'||motif==='arrow'){
  ctx.fillStyle=motif==='bullet'?'#d9b57a':color;ctx.beginPath();ctx.moveTo(r*2.3,0);ctx.lineTo(r*.3,-r*.55);ctx.lineTo(-r*1.9,-r*.55);ctx.lineTo(-r*1.9,r*.55);ctx.lineTo(r*.3,r*.55);ctx.closePath();ctx.fill();ctx.stroke();
  if(motif==='arrow'){for(const side of[-1,1]){ctx.beginPath();ctx.moveTo(-r*1.8,0);ctx.lineTo(-r*2.5,side*r);ctx.lineTo(-r*.9,side*r*.4);ctx.fill();}}
 }else if(motif==='ice'||motif==='stone'){
  ctx.beginPath();for(let j=0;j<6;j++){const a=j*Math.PI/3,rr=r*(j%2?1.1:1.7);ctx.lineTo(Math.cos(a)*rr,Math.sin(a)*rr);}ctx.closePath();ctx.fill();ctx.strokeStyle='#ffffff90';ctx.moveTo(-r,0);ctx.lineTo(r*.2,-r*.5);ctx.lineTo(r,r);ctx.stroke();
 }else if(motif==='wolf'){
  ctx.beginPath();ctx.moveTo(r*2,0);ctx.lineTo(r,-r*.7);ctx.lineTo(r*.1,-r*1.7);ctx.lineTo(-r*.3,-r*.7);ctx.lineTo(-r*1.7,-r*.5);ctx.lineTo(-r*1.8,r*.7);ctx.lineTo(r,r*.7);ctx.closePath();ctx.fill();ctx.fillStyle='#ff5b69';ctx.fillRect(r*.4,-r*.4,r*.5,r*.3);
 }else if(motif==='fly'){
  ctx.fillStyle='#cfb9d0bb';for(const side of[-1,1]){ctx.beginPath();ctx.ellipse(-r*.5,side*r,r*1.2,r*.5,side*.4,0,Math.PI*2);ctx.fill();}ctx.fillStyle='#3b263f';ctx.beginPath();ctx.ellipse(0,0,r*1.6,r*.7,0,0,Math.PI*2);ctx.fill();ctx.fillStyle='#e6788e';ctx.fillRect(r*.7,-r*.4,r*.5,r*.8);
 }else if(motif==='fist'){
  ctx.fillStyle='#dce4e9';ctx.fillRect(-r,-r*.7,r*2,r*1.4);ctx.fillStyle='#253249';for(let j=-1;j<2;j++)ctx.fillRect(j*r*.5,-r*.7,1,r*.75);ctx.fillStyle=color;ctx.fillRect(-r*1.8,-r*.45,r,r*.9);
 }else if(motif==='beetle'){
  ctx.beginPath();ctx.ellipse(0,0,r*1.6,r,0,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#401e39';ctx.beginPath();ctx.moveTo(-r*1.3,0);ctx.lineTo(r,0);ctx.stroke();ctx.strokeStyle=color;for(const side of[-1,1])for(let j=-1;j<=1;j++){ctx.beginPath();ctx.moveTo(j*r*.6,side*r*.7);ctx.lineTo((j-.5)*r,side*r*1.7);ctx.stroke();}
 }else if(motif==='claw'){
  for(let j=-1;j<=1;j++){ctx.beginPath();ctx.moveTo(-r*1.6,j*r);ctx.quadraticCurveTo(r*.5,j*r*.5,r*1.8,j*r*.6-r*.5);ctx.stroke();}
 }else if(motif==='root'){
  for(let j=0;j<4;j++){ctx.rotate(Math.PI/2);ctx.beginPath();ctx.moveTo(0,0);ctx.bezierCurveTo(r,0,-r,-r*2,0,-r*2);ctx.stroke();}
 }else if(motif==='chain'||motif==='whip'){
  for(let j=-2;j<=2;j++){ctx.beginPath();ctx.ellipse(j*r*.8,Math.sin(j+t*4)*r*.25,r*.65,r*.35,j%2?.5:-.5,0,Math.PI*2);ctx.stroke();}
 }else if(motif==='flame'){
  ctx.fillStyle='#f5a04a';ctx.beginPath();ctx.moveTo(r*2,0);ctx.quadraticCurveTo(-r,-r*2,-r*2.5,0);ctx.quadraticCurveTo(-r,r*2,r*2,0);ctx.fill();
 }else if(motif==='sigil'){
  ctx.beginPath();for(let j=0;j<6;j++){const a=(j*2%5)*Math.PI*2/5;ctx.lineTo(Math.cos(a)*r*1.7,Math.sin(a)*r*1.7);}ctx.stroke();
 }else{ctx.beginPath();ctx.moveTo(r*1.5,0);ctx.bezierCurveTo(0,-r*2,-r*1.5,-r,-r,0);ctx.bezierCurveTo(-r*1.5,r,0,r*2,r*1.5,0);ctx.fill();}
 ctx.restore();return true;
}
function revisionSchedule(who,phase,move){
 if(who==='victim'&&phase===2)return move===4?[12,37.4]:[3,3.4];
 if(who==='cocytus'&&move===4)return phase===2?[5,3.4]:[3,3];
 if(who==='sebas')return move===3?[1,0]:[4,3.8];
 if(who==='gargantua')return move===3?[1,0]:[3,3];
 if(who==='cocytus'&&move===2)return[2,3];
 if(who==='aura'&&move===1)return[3,3];
 if(who==='mare'&&[0,2,4].includes(move))return[2,3];return null;
}
function revisionShapes(s,e){
 const a=s.p.skill.base_id.split('_'),who=a[1],phase=Number(a[2].slice(1)),move=Number(a[3]),i=e.index;if(!revisionSchedule(who,phase,move))return null;
 const x=s.player.x,y=s.player.y,sign=i%2?1:-1,d=s.d,out=[],color={gargantua:'#c9b195',cocytus:'#88ceff',aura:'#b8db7b',mare:'#82c581',sebas:'#dbe9ee',victim:'#e9abd7'}[who],motif={gargantua:'stone',cocytus:'ice',aura:'whip',mare:'root',sebas:'fist',victim:'sigil'}[who];
 const add=(h,delay=0,duration=.24)=>out.push({color,motif,...h,delay,duration});
 function rect(x,y,w,h,delay=0,label='',extra={}){add({type:'rect',x,y,w,h,label,...extra},delay,.32);}
 function cut(ax,ay,bx,by,delay=0,r=8,extra={}){add({type:'line',ax,ay,bx,by,r,weight:.28,tier:'heavy',...extra},delay,.22);}
 function circle(x,y,r,delay=0,extra={}){add({type:'circle',x,y,r,weight:.22,tier:'normal',...extra},delay,.28);}
 function shots(bx,by,n=3,delay=0,speed=.65,spread=.26,kind=null){const aim=Math.atan2(y-by,x-bx);for(let j=0;j<n;j++){const ang=aim+(j-(n-1)/2)*spread;add({type:'bullet',x:bx,y:by,vx:Math.cos(ang)*d.speed*speed,vy:Math.sin(ang)*d.speed*speed,r:6,motif:kind||motif,length:17,weight:.09,tier:'minor'},delay,2);}}
 function ring(x,y,delay=0,kind=null){add({type:'ring',x,y,r:18,speed:145,thickness:8,gap:sign*.65,gapWidth:1.1,motif:kind||motif,weight:.24,tier:'heavy'},delay,1.8);}
 function passage(center,half,delay,label){center=Math.max(half+12,Math.min(308-half,center));for(const[lo,hi]of[[0,center-half],[center+half,320]])if(hi>lo)rect(0,lo,720,hi-lo,delay,label,{weight:.27,tier:'heavy'});rect(0,center-half,720,half*2,delay,'ПРОХОД →',{visualOnly:true,color:'#83edba',motif:'passage'});}
 if(move===3)return out;
 if(who==='gargantua'){
  if([0,4].includes(move)){const rx=Math.max(12,Math.min(608,x-50+sign*(move===4?20:0)));rect(rx,0,100,320,.3,move===0?'КАМЕННАЯ ЛАДОНЬ':'ОБВАЛ',{weight:.35,tier:'heavy',motif:'stone'});shots(i%2?20:700,40+(i%3)*120,phase===2?5:3,.65,.63);if(move===4)ring(x,y,1);}
  else if(move===1){shots(i%2?20:700,35+(i%3)*125,5,.1,.75,.18);circle(x,y,36,.85,{motif:'stone'});if(phase===2)shots(360,12,3,1.05,.62,.45);}
  else{circle(x,y,42,.15,{motif:'stone'});ring(x,y,.6);if(phase===2)cut(0,Math.max(25,Math.min(295,y+sign*48)),720,Math.max(25,Math.min(295,y+sign*48)),1.1,10,{motif:'stone'});}
 }else if(who==='cocytus'){
  if(move===2){if(phase===1){passage(y+sign*30,51,1,'МОРОЗ — ОПАСНО');shots(i%2?700:20,40+(i%3)*120,3,1.35,.45,.33);}else for(let j=0;j<4;j++){const cx=Math.max(22,Math.min(698,x+(j-1)*100));rect(cx-17,0,34,320,.35+j*.35,'ЛЕДЯНОЙ ПИК',{weight:.18,tier:'normal'});}}
  else if(move===4){if(phase===1){cut(0,y,720,y,.65,22,{motif:'ice'});ring(x,y,1,'ice');shots(i%2?700:20,20,3,1.15,.68,.34);}else{const k=i%5;if(k===0)cut(0,y,720,y,.4,14);else if(k===1)cut(x,0,x,320,.4,14);else if(k===2){circle(x,y,45,.3);ring(x,y,.8);}else if(k===3)shots(i%2?700:20,40+i*35,5,.3,.78,.22);else{cut(x-220,0,x+220,320,.45,12,{motif:'lightning'});cut(x+220,0,x-220,320,.95,12,{motif:'lightning'});}for(const h of out)h.strike=Math.min(s.p.strikes-1,k);}}
 }else if(who==='aura'){
  const points=Array.from({length:17},(_,k)=>[k*45,Math.max(8,Math.min(312,y+sign*90*Math.sin((k/16-x/720)*Math.PI*1.2)))]);add({type:'polyline',points,r:9,motif:'whip',weight:.28,tier:'heavy'},.25,.26);cut(x-sign*150,0,x+sign*150,320,.9,8,{motif:'whip'});shots(i%2?20:700,160,3,1.2,.63,.27,'arrow');
 }else if(who==='mare'){
  if(move===0){circle(x,y,37,.35);circle(Math.max(40,Math.min(680,x+sign*95)),Math.max(40,Math.min(280,y-sign*40)),32,1.15);}
  else if(move===2){passage(y+sign*26,58,1.15,'РАЗЛОМ — ОПАСНО');circle(x,y,28,.35);}
  else if(phase===1){cut(0,y,720,y,.4,15,{motif:'flame'});shots(i%2?20:700,40+i*130,5,.95,.57,.32,'stone');}
  else{circle(x,y,42,.4);cut(x-sign*160,0,x+sign*160,320,1.1,12,{motif:'stone'});shots(i%2?20:700,160,5,1.35,.62,.31,'stone');}
  rect(0,i%2===0?292:0,720,28,1.6,'КОРНИ',{weight:.15,tier:'normal',motif:'root'});
 }else if(who==='sebas'){
  if(phase===2&&move===0){cut(0,y,720,y,.2,12,{motif:'claw'});shots(360,20,5,.7,.82,.20,'claw');shots(360,300,3,1.2,.73,.30,'flame');}
  else if(phase===2&&move===1){for(let j=0;j<3;j++)cut(x-150+(j-1)*60,0,x+150+(j-1)*60,320,.2+j*.34,9,{motif:'claw'});ring(x,y,1.25,'claw');}
  else if(phase===2&&move===2){circle(x,y,37,.2,{motif:'claw'});for(let j=0;j<6;j++){const angle=j*Math.PI/3;add({type:'bullet',x:x+Math.cos(angle)*85,y:y+Math.sin(angle)*85,vx:0,vy:0,r:6,orbit:true,cx:x,cy:y,orbitAngle:angle,orbitRadius:85,spiral:20,orbitSpeed:sign*1.8,motif:'claw',weight:.09,tier:'minor'},.55,1.7);}}
  else if(move===0){shots(i%2?700:20,y,5,.15,.88,.18);cut(x-180,0,x+180,320,.85,8,{motif:phase===2?'claw':'fist'});}
  else if(move===1){cut(0,y,720,y,.2,10);shots(i%2?20:700,320-y,5,.85,.83,.24);if(phase===2)ring(x,y,1.2,'claw');}
  else if(move===2){circle(x,y,32,.2,{motif:phase===2?'claw':'fist'});for(let j=0;j<3;j++){const ang=j*Math.PI*2/3+i*.5;shots(360+Math.cos(ang)*340,160+Math.sin(ang)*145,2,.55+j*.32,.76,.20,phase===2?'claw':'fist');}}
  else{cut(0,y,720,y,.25,17,{motif:phase===2?'claw':'fist'});cut(x,0,x,320,.8,11,{motif:phase===2?'claw':'fist'});if(phase===2){ring(x,y,1.1,'claw');shots(i%2?700:20,160,5,1.35,.74,.26,'flame');}else shots(i%2?700:20,160,5,1.15,.86,.20);}
  rect(i%2===0?0:678,0,42,320,.85,'ДАВЛЕНИЕ',{weight:.12,tier:'normal',motif:phase===2?'claw':'fist'});if([0,1].includes(move))circle(x,y,29,1.2,{motif:phase===2?'claw':'fist'});
  for(const h of out){if(h.type==='bullet'){h.vx*=1.22;h.vy*=1.22;h.r+=1;}if(h.orbit)h.orbitSpeed*=1.2;}
  for(const h of out)h.strike=Math.min(s.p.strikes-1,i);
 }else if(who==='victim'){
  const section=Math.floor(i/2)%6;
  if(section===0){cut(0,y,720,y,.2,8,{motif:'chain'});cut(x,0,x,320,1.15,7,{motif:'chain'});shots(i%2?20:700,40+(i%3)*120,5,1.8,.58,.26,'sigil');}
  else if(section===1){shots(20,40,7,.15,.61,.24,'sigil');shots(700,280,7,1.05,.62,.24,'sigil');ring(x,y,1.6,'chain');}
  else if(section===2){for(let j=0;j<3;j++){const angle=sign*(.35+j*.9),dx=Math.cos(angle)*850,dy=Math.sin(angle)*850;cut(x-dx,y-dy,x+dx,y+dy,.2+j*.72,7,{motif:'chain'});}circle(x,y,31,2.3,{motif:'sigil'});}
  else if(section===3){passage(y+sign*22,51,.7,'СТЕНА ПЕЧАТИ');shots(i%2?20:700,160,7,1.45,.57,.22,'sigil');cut(x,0,x,320,2.4,8,{motif:'chain'});}
  else if(section===4){for(let j=0;j<8;j++){const angle=j*Math.PI/4;add({type:'bullet',x:x+Math.cos(angle)*95,y:y+Math.sin(angle)*95,vx:0,vy:0,r:6,orbit:true,cx:x,cy:y,orbitAngle:angle,orbitRadius:95,spiral:18,orbitSpeed:sign*1.5,motif:'sigil',weight:.055,tier:'minor'},.35,2.6);}circle(x,y,34,.9,{motif:'sigil'});ring(x,y,1.8,'chain');}
  else{passage(y+sign*24,48,.65,'ПОСЛЕДНЯЯ ПЕЧАТЬ');for(let j=0;j<2;j++)shots((i+j)%2?20:700,40+j*240,7,.9+j*.85,.65,.20,'sigil');ring(x,y,1.65,'chain');}
  for(const h of out)if(!h.visualOnly)h.weight=h.type==='bullet'?.085:h.type==='ring'?.22:.18;
 }
 return out;
}
function field(ctx,s,height=320){
 const parts=(s.p?.skill?.base_id||'').split('_'),who=parts[1],move=Number(parts[3]);if(!colors[who])return;
 if(who==='victim'&&parts[2]==='p2'&&move===4){const names=['ЦЕПИ','РОЙ ПЕЧАТЕЙ','РАЗРЫВ ПРОСТРАНСТВА','СТЕНЫ РИТУАЛА','КОЛЕСО ПРОКЛЯТИЙ','ПОСЛЕДНЯЯ ПЕЧАТЬ'],section=Math.max(0,Math.min(5,Math.floor((s.time-1.18)/6.8)));ctx.save();ctx.fillStyle='#f0c3e2';ctx.textAlign='center';ctx.font='bold 12px Segoe UI';ctx.fillText('ИСПЫТАНИЕ '+(section+1)+'/6 · '+names[section],360,21);for(let i=0;i<6;i++){ctx.fillStyle=i<=section?'#dd9bce':'#463449';ctx.fillRect(250+i*37,30,30,3);}ctx.restore();}
 ctx.save();ctx.strokeStyle=colors[who];ctx.fillStyle=colors[who];ctx.lineWidth=1.4;ctx.globalAlpha=.16;
 if(who==='cocytus'){
  for(let i=0;i<10;i++){const x=36+i*72;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x+10,18);ctx.lineTo(x+6,4);ctx.lineTo(x+22,12);ctx.stroke();ctx.beginPath();ctx.moveTo(x,height);ctx.lineTo(x-9,height-21);ctx.stroke();}
  if(move===4){const names=['МЕЧ','КОПЬЁ','ПАЛИЦА','ЗМЕЙ','ВАДЖРА'];for(let i=0;i<5;i++){const x=225+i*66,active=Math.floor(Math.max(0,s.time-(s.preparation||1))/.48)%5===i;ctx.globalAlpha=active?.7:.2;ctx.beginPath();ctx.arc(x,38,8,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(x,46);ctx.lineTo(x,63);ctx.moveTo(x-10,54);ctx.lineTo(x+10,54);ctx.stroke();ctx.font='9px Segoe UI';ctx.textAlign='center';ctx.fillText(names[i],x,76);}}
 }else if(who==='gargantua'){
  for(const side of[0,1]){ctx.save();ctx.translate(side?720:0,height/2);ctx.scale(side?-1:1,1);ctx.beginPath();ctx.moveTo(0,-76);ctx.lineTo(24,-62);ctx.lineTo(43,-35);ctx.lineTo(42,28);ctx.lineTo(15,62);ctx.lineTo(0,78);ctx.closePath();ctx.fill();ctx.restore();}
 }else if(who==='solution'){
  for(let i=0;i<8;i++){const x=45+i*90;ctx.beginPath();ctx.moveTo(x,height);ctx.bezierCurveTo(x-20,height-25,x+20,height-50,x,height-65);ctx.stroke();}
 }else if(who==='victim'){
  for(const x of[28,692])for(let y=65;y<height;y+=46){ctx.beginPath();ctx.arc(x,y,15,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y+15);ctx.lineTo(x,y+31);ctx.stroke();}
 }
 ctx.restore();
}
function hazard(ctx,s,h,g,{warning,spent}){
 if(!(s.p?.skill?.base_id||'').startsWith('nz_'))return false;
 if(!['passage','stone','ice','root','whip','fist','claw','chain'].includes(g.motif))return false;
 if(!['rect','line','circle','polyline'].includes(h.type))return false;
 const color=g.color||'#b3d9e7';ctx.save();ctx.setLineDash(warning?[8,5]:[]);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.globalAlpha=spent?.1:warning?.8:.95;
 if(h.type==='rect'){
  ctx.lineWidth=g.visualOnly?3:2;ctx.strokeRect(g.x,g.y,g.w,g.h);ctx.save();ctx.globalAlpha*=g.visualOnly?.12:warning?.12:.42;ctx.fillRect(g.x,g.y,g.w,g.h);ctx.restore();
  if(g.label){ctx.font=g.visualOnly?'bold 13px Segoe UI':'11px Segoe UI';ctx.textAlign='left';ctx.fillText(g.label,g.x+7,g.y+Math.min(20,g.h-5));}
  if(!warning&&!g.visualOnly){ctx.save();ctx.beginPath();ctx.rect(g.x,g.y,g.w,g.h);ctx.clip();for(let x=g.x+20;x<g.x+g.w;x+=54)for(let y=g.y+25;y<g.y+g.h;y+=55)glyph(ctx,g.motif,x,y,10,-Math.PI/2,color,s.time);ctx.restore();}
 }else if(h.type==='polyline'){
  ctx.lineWidth=warning?2:g.r*2;ctx.lineJoin='round';ctx.beginPath();g.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();if(!warning){ctx.setLineDash([]);ctx.lineWidth=2;ctx.strokeStyle='#f1e9b8';ctx.stroke();for(let k=1;k<g.points.length;k+=2){const[x,y]=g.points[k],prior=g.points[k-1];glyph(ctx,'whip',x,y,6,Math.atan2(y-prior[1],x-prior[0]),color,s.time);}}
 }else if(h.type==='line'){
  ctx.lineWidth=warning?2:g.r*2;ctx.beginPath();ctx.moveTo(g.ax,g.ay);ctx.lineTo(g.bx,g.by);ctx.stroke();
  if(warning){ctx.globalAlpha=.13;ctx.lineWidth=g.r*2;ctx.setLineDash([]);ctx.stroke();}
  else{ctx.setLineDash([]);ctx.shadowColor=color;ctx.shadowBlur=14;ctx.lineWidth=2;ctx.strokeStyle='#f0f7ff';ctx.stroke();
   const f=Math.max(0,Math.min(1,(s.time-h.start)/(h.end-h.start))),x=Math.max(14,Math.min(706,g.ax+(g.bx-g.ax)*f)),y=Math.max(14,Math.min(306,g.ay+(g.by-g.ay)*f));glyph(ctx,g.motif,x,y,Math.min(16,g.r+2),Math.atan2(g.by-g.ay,g.bx-g.ax),color,s.time);}
 }else{
  ctx.beginPath();ctx.arc(g.x,g.y,g.r,0,Math.PI*2);ctx.lineWidth=2;ctx.stroke();ctx.globalAlpha=warning?.12:.35;ctx.fill();if(!warning){ctx.globalAlpha=.95;glyph(ctx,g.motif,g.x,g.y,g.r*.65,-Math.PI/2,color,s.time);}
 }
 ctx.restore();return true;
}
return {colors,motifs,families,shapes,blocks,glyph,field,revisionSchedule,hazard};
});
