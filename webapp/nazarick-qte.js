/* Mirrored by arena_nazarick_patterns.py. No client-trusted outcomes. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.NazarickQTE=api;})(globalThis,function(){
'use strict';
const colors={shalltear:'#ff244c',demiurge:'#e74620',albedo:'#8145cf',pandora:'#b48bd8',ainz:'#a58aff',knight:'#8d8fb6',lich:'#75c89e',hellguard:'#ef4723',pyromancer:'#ff642b'};
function identity(p){const a=(p.skill.base_id||'').split('_');return a.length===4&&a[0]==='nz'?{who:a[1],phase:Number(a[2].slice(1)),move:Number(a[3])}:null;}
const STONE_COLORS=['#ff593c','#70c6ff','#b69bff','#86e478','#f4db75','#ee86da','#e4edff'];
const STONE_STATUSES=['burn','shock','curse','venom','exposed','sealed','frailty'];
function activeDuration(p){const n=identity(p);return n?.who==='ainz'&&n.phase===1&&n.move===0?18.8:n?.who==='ainz'&&n.phase===2&&n.move===0?10.4:6.8;}
function blockDuration(p){return activeDuration(p)===6.8?9.5:1+activeDuration(p);}
function schedule(p,count,span){const n=identity(p);if(!n)return[count,span];if(n.who==='ainz'&&n.phase===1&&n.move===0)return[7,15.3];if(n.who==='ainz'&&n.phase===2&&n.move===0)return[2,5.2];if(n.who==='demiurge'&&(n.phase===1&&n.move===2||n.phase===2&&n.move===1)||n.who==='ainz'&&n.phase===2&&n.move===1)return[3,4.0];if(n.who==='ainz'&&n.phase===2&&n.move===2)return[3,4.4];return[count,span];}
function shapes(s,e){
 const {who,phase,move}=identity(s.p),x=s.player.x,y=s.player.y,d=s.d,i=e.index,sign=i%2?1:-1,color=colors[who]||'#9ba9de',out=[];
 const add=(h,delay=0,duration=.24,extra={})=>out.push({color,...h,delay,duration,...extra});
 const line=(ax,ay,bx,by,width=7,delay=0,extra={})=>add({type:'line',ax,ay,bx,by,r:width*d.beamScale},delay,.24,extra);
 function bolt(bx,by,motif='needle',delay=0,n=3,tracking=0,speed=.65){
  const a=Math.atan2(y-by,x-bx);
  for(let j=0;j<n;j++){const angle=a+(j-(n-1)/2)*.23,core=j===Math.floor(n/2);
   add({type:'bullet',x:bx,y:by,vx:Math.cos(angle)*d.speed*speed,vy:Math.sin(angle)*d.speed*speed,r:core?7:4,motif,length:motif==='spear'?35:['needle','feather'].includes(motif)?14:0,homing:tracking,turnRate:motif==='bat'?1.45:.90,tier:core?'heavy':'minor',weight:core?.48:.10},delay,2.65);}
 }
 function lightning(ax,ay,bx,by,delay=0,weak=false){
  const dx=bx-ax,dy=by-ay,length=Math.hypot(dx,dy)||1,points=[];
  for(let j=0;j<13;j++){const f=j/12,zig=Math.sin(j*2.7+i*.8)*Math.sin(f*Math.PI)*(weak?13:23);points.push([ax+dx*f-dy/length*zig,ay+dy*f+dx/length*zig]);}
  add({type:'polyline',points,r:(weak?4:7)*d.beamScale,motif:'lightning',color:weak?'#a3bfff':'#b5dcff'},delay,.20);
 }
 function corridor(vertical=false,delay=0){
  const half=Math.max(52,d.gap*.55-4*(phase-1)),axis=vertical?720:320,center=Math.max(half+12,Math.min(axis-half-12,(vertical?x:y)+sign*40));
  for(const[lo,length]of[[0,center-half],[center+half,axis-center-half]])add({type:'rect',x:vertical?lo:0,y:vertical?0:lo,w:vertical?length:720,h:vertical?320:length,label:'ПРЕКЛОНИСЬ',status:'curse'},delay,.18);
 }
 function hole(cx,cy,r=55,delay=0,weak=false){add({type:'well',x:Math.max(r+12,Math.min(708-r,cx)),y:Math.max(r+12,Math.min(308-r,cy)),r,pull:weak?45:75,motif:'blackhole',color:'#9864e8',tier:'heavy',weight:.55},delay,weak?.80:1.05);}
 function safeSeal(delay=1.0,radius=70){const cx=Math.max(78,Math.min(642,x+sign*100)),cy=Math.max(75,Math.min(245,y-sign*35));add({type:'safe_zone',x:cx,y:cy,r:radius,motif:'sigil',label:'СЮДА',color:'#7fe5ac',status:'curse',tier:'heavy',weight:.55},delay,.16);return[cx,cy];}
 function orbit(stone,angle,delay=0,radius=112,spiral=55){const omega=sign*1.9,cx=360,cy=160;add({type:'bullet',x:cx+Math.cos(angle)*radius,y:cy+Math.sin(angle)*radius,vx:Math.cos(angle)*spiral-Math.sin(angle)*radius*omega,vy:Math.sin(angle)*spiral+Math.cos(angle)*radius*omega,r:8,motif:'staff_orb',orbit:true,cx,cy,orbitRadius:radius,orbitAngle:angle,orbitSpeed:omega,spiral,staff:true,color:STONE_COLORS[stone],stone,status:STONE_STATUSES[stone],tier:'normal',weight:.23},delay,1.85);}
 if(who==='shalltear'){
  if(phase===1&&move===0)bolt(sign>0?30:690,35+e.jitter*250,'needle',0,3,.70);
  else if(phase===1&&move===1){bolt(25,40+e.jitter*220,'bat',0,3,.85,.47);bolt(695,280-e.jitter*220,'bat',.45,1,.65,.47);}
  else if(phase===1){for(const bx of[220,500])line(bx,20,bx+(x-bx)*4,20+(y-20)*4,6,.30,{motif:'eye',clockTurn:sign*(bx===220?.18:-.18),duration:.42,tier:'heavy',weight:.5});}
  else if(move===0){bolt(sign>0?30:690,y,'spear',0,3,0,.92);bolt(x,sign>0?12:308,'spear',.65,3,0,.85);}
  else if(move===1){bolt(25,y,'spear',0,1,0,.86);bolt(25,y,'spear',.70,1,0,.86);bolt(695,320-y,'bat',.95,1,.7,.48);}
  else{bolt(30,30+e.jitter*260,'needle',0,3,.7,.72);bolt(690,290-e.jitter*260,'bat',.50,1,.9,.52);}
 }else if(who==='demiurge'){
  if(phase===1&&move===0){const angle=.40+sign*.8;for(let j=0;j<2;j++){const a=angle+j*1.15;line(x-Math.cos(a)*850,y-Math.sin(a)*850,x+Math.cos(a)*850,y+Math.sin(a)*850,6,j*.60,{motif:'cut',status:'curse'});}}
  else if(phase===1&&move===1){corridor();corridor(true,.70);}
  else if(phase===1){const[cx,cy]=safeSeal(1.0,44+e.jitter*26);Object.assign(out.at(-1),{uniform:true,label:'ПУТЬ',color:'#e47562'});add({type:'circle',x:cx+(cx<360?200:-200),y:cy,r:44+((e.jitter+.47)%1)*26,motif:'sigil',label:'ЛОВУШКА',uniform:true,color:'#e47562',status:'curse'},1.0,.16);}
  else if(move===0){add({type:'rect',x:0,y:0,w:720,h:32,motif:'fire',status:'burn',label:'ОГОНЬ'},0,.60);add({type:'rect',x:0,y:288,w:720,h:32,motif:'fire',status:'burn',label:'ОГОНЬ'},0,.60);bolt(690,40+e.jitter*240,'fire',.35,3,0,.66);bolt(30,280-e.jitter*240,'fire',.65,3,0,.64);bolt(130+i%4*150,i%2?22:298,'fire',.85,1,0,.62);for(const h of out.slice(5))h.weight=Math.min(h.weight??.2,.22);}
  else if(move===1){const tx=Math.max(55,Math.min(665,x+(s.player.vx||0)*.28)),ty=Math.max(50,Math.min(270,y+(s.player.vy||0)*.28));const[cx,cy]=safeSeal(1.0,48);line(tx-650,ty-sign*350,tx+650,ty+sign*350,7,1.65,{motif:'cut',status:'curse'});}
  else{bolt(40,25,'fire',0,3,0,.65);bolt(680,295,'fire',.50,3,0,.65);}
 }else if(who==='albedo'){
  if(move===0&&phase===1||move===1&&phase===2){bolt(25,35+e.jitter*240,'feather',0,5,0,.65);if(phase===2)bolt(695,285-e.jitter*240,'feather',.55,3,0,.65);}
  else if(move===1||move===0){const angle=sign*.55,points=Array.from({length:23},(_,j)=>[x+Math.cos(angle+j*.15)*110,y+Math.sin(angle+j*.15)*110]);add({type:'polyline',points,r:10*d.beamScale,motif:'halberd',tier:'heavy',weight:.6},.12,.24);line(x-650,y-sign*300,x+650,y+sign*300,7,.75,{motif:'purple_ray'});}
  else{bolt(690,y,'spear',0,1,0,.88);line(0,y+sign*42,720,y+sign*42,10,.65,{motif:'purple_ray',tier:'heavy',weight:.6});}
 }else if(who==='pandora'){
  if(phase===1&&move===0)lightning(x-50,0,x+25,320,.30,true);
  else if(phase===1&&move===1)hole(x+sign*95,y,37,.35,true);
  else if(phase===1)line(0,y,720,y,7,.65,{motif:'death',color:'#a79acc'});
  else if(move===0){bolt(sign>0?690:30,y,'spear',0,3,0,.74);bolt(sign>0?25:695,320-y,'needle',.55,5,.25,.64);}
  else if(move===1){if(s.p.skill.copy_skill?.base_id==='mana_shot'){bolt(i%2?-20:740,60+e.jitter*200,'orb',.20,3,0,.50);bolt(i%2?740:-20,260-e.jitter*200,'orb',.95,3,0,.48);}else if(i%3===0)lightning(x-70,0,x+40,320,.45,true);else if(i%3===1)bolt(690,45+e.jitter*220,'mask',0,3,.45,.52);else line(0,y,720,y,6,.40,{motif:'copied_cut',color:'#dca2ff'});}
  else{for(const side of[-1,1])bolt(360+side*320,160+side*100,'mask',side<0?.20:.65,5,.35,.65);bolt(170+i%3*180,i%2?12:308,'mask',.90,3,0,.58);}
 }else if(who==='ainz'){
  if(phase===1&&move===0){
   const j=i%7,c=STONE_COLORS[j];
   if(j===0){bolt(30,45+e.jitter*230,'fire',0,5,0,.86);bolt(690,275-e.jitter*230,'fire',.55,3,0,.80);}
   else if(j===1){lightning(x-90,0,x+80,320,.10);lightning(x+110,0,x-70,320,.85);[100,260,460,620].forEach((bx,k)=>lightning(bx,0,bx+sign*45,320,.35+k*.30,true));}
   else if(j===2){hole(x+sign*85,y,64,.20);bolt(sign>0?690:30,160,'staff_orb',.65,3,0,.72);}
   else if(j===3){add({type:'ring',x:360+sign*150,y:160,r:18,speed:175,gap:Math.atan2(y-160,x-360-sign*150),gapWidth:1.65,thickness:7,status:'curse',motif:'venom',weight:.28,tier:'normal'},.12,1.7);bolt(30,40,'venom',.65,3,0,.76);}
   else if(j===4){line(x-650,y-270,x+650,y+270,6,.15,{motif:'holy_ray'});line(x-650,y+270,x+650,y-270,6,.90,{motif:'holy_ray'});}
   else if(j===5){for(const jx of[-1,0,1])add({type:'circle',x:Math.max(35,Math.min(685,x+jx*95)),y:Math.max(40,Math.min(280,y-jx*45)),r:32,motif:'sigil',status:'curse',weight:.22,tier:'normal'},.15+Math.abs(jx)*.5,.25);}
   else{bolt(690,30+e.jitter*260,'skull',0,3,0,.78);bolt(30,290-e.jitter*260,'bone',.55,5,0,.80);}
   for(const h of out){h.color=c;h.stone=i%7;h.status=STONE_STATUSES[i%7];h.duration=Math.min(h.duration,Math.max(.1,2.10-h.delay));h.weight=Math.min(h.weight??.35,.35);}
  }
  else if(phase===1&&move===1){hole(x+sign*95,y,58,.35);if(i%2)hole(x-sign*145,320-y,48,.95);}
  else if(phase===1)bolt(690,40+e.jitter*240,'bone',0,5,0,.75);
  else if(move===0){
   const cycle=i%2,base=cycle*5.2,release=(s.preparation||0)+base+3.15;
   for(let j=0;j<14;j++){const bx=j%2?30:690,by=22+(j%7)*46,a=Math.atan2(y-by,x-bx),delay=.10+j*.12,stone=(j+cycle*3)%7,start=(e.at||0)+d.warning+delay;
    add({type:'bullet',x:bx,y:by,vx:Math.cos(a)*d.speed*.88,vy:Math.sin(a)*d.speed*.88,r:6,motif:j%2?'staff_orb':'frozen_blade',color:STONE_COLORS[stone],stone,status:STONE_STATUSES[stone],freezeAt:0,freezeFor:Math.max(0,release-start),pendingLaunch:true,staff:true,cycle,tier:'normal',weight:.18},delay,Math.max(.1,release-start+1.9));}
  }else if(move===1){
   const[cx,cy]=safeSeal(1.35);Object.assign(out.at(-1),{color:'#cfb2f0',label:'СМЕРТЬ',staff:true,uniform:true,status:'curse',tier:'heavy',weight:.55,r:44+e.jitter*12});
   for(const[j,side]of[-1,1].entries())add({type:'decoy',x:Math.max(80,Math.min(640,cx+(cx<360?1:-1)*(190+j*190))),y:Math.max(76,Math.min(244,cy-side*48)),r:44+((e.jitter+j*.37+.23)%1)*12,motif:'sigil',color:'#cfb2f0',label:'ЖИЗНЬ',uniform:true,staff:true,visualOnly:true},1.35,.16);
  }else{
   const j=i%3;
   for(let k=0;k<7;k++)orbit(k,k*Math.PI*2/7+i*.37,.12+k*.035,95,48);
   if(j===0)line(0,y-45,720,y-45,5,.75,{motif:'staff_laser',color:STONE_COLORS[0],status:'burn'});
   else if(j===1){lightning(x-80,0,x+90,320,.20);Object.assign(out.at(-1),{stone:1,status:'shock',color:STONE_COLORS[1]});}
   else{hole(x+sign*100,y,48,.20);Object.assign(out.at(-1),{stone:2,status:'curse'});line(x-650,y+200,x+650,y-200,5,1.05,{motif:'staff_laser',color:STONE_COLORS[5],status:'sealed'});}
   for(const h of out){h.staff=true;h.duration=Math.min(h.duration,Math.max(.1,2.05-h.delay));h.weight=Math.min(h.weight??.35,.35);}
  }
 }else if(who==='knight'||who==='hellguard'){line(x-600,y-sign*240,x+600,y+sign*240,8,.20,{motif:'halberd',...(who==='hellguard'?{status:'burn'}:{})});bolt(690,y,'spear',.7,1,0,.70);}
 else if(who==='pyromancer'){bolt(690,40+e.jitter*240,'fire',0,5,0,.65);bolt(30,280-e.jitter*240,'fire',.40,3,0,.62);add({type:'circle',x,y,r:26,motif:'sigil',status:'curse'},.65,.24);}
 else{bolt(690,40+e.jitter*240,'skull',0,3,0,.65);bolt(30,280-e.jitter*240,'bone',.45,3,0,.62);line(x,0,x,320,5,.85,{motif:'bone',color:'#e4dfda'});}
 for(const h of out){if(h.motif==='fire')h.status='burn';if(['bone','skull'].includes(h.motif))h.color='#e4dfda';}
 return out;
}
function timeStopped(s){const id=identity(s.p),elapsed=s.time-(s.preparation||0);return id?.who==='ainz'&&id.phase===2&&id.move===0&&elapsed>=0&&elapsed<10.4&&elapsed%5.2>=.5&&elapsed%5.2<2.5;}
function advanceHoming(h,p,t,dt){
 if(!h.homing||t<h.start)return;
 h.lastX=h.px??h.x;h.lastY=h.py??h.y;
 let a=Math.atan2(h.vy,h.vx);
 if(t-h.start<h.homing){const target=Math.atan2(p.y-h.lastY,p.x-h.lastX),turn=Math.atan2(Math.sin(target-a),Math.cos(target-a)),speed=Math.hypot(h.vx,h.vy);a+=Math.max(-h.turnRate*dt,Math.min(h.turnRate*dt,turn));h.vx=Math.cos(a)*speed;h.vy=Math.sin(a)*speed;}
 h.px=h.lastX+h.vx*dt;h.py=h.lastY+h.vy*dt;
}
function blockThreats(p,seed,params,rng){
 const which=identity(p);if(!which)return null;const{who,phase,move}=which,r=rng((seed^p.seed)>>>0),offset=Math.floor(r()*8)*Math.PI/4,out=[];
 if(who==='ainz'&&(phase===1&&move===0||phase===2&&move===0)){
  if(phase===1){for(let stone=0;stone<7;stone++)for(let j=0;j<3;j++){const angle=offset+stone*Math.PI*2/7+j*.55;out.push({id:'',at:2.05+stone*2.55+j*.62,warning:Math.max(.85,params.warning),angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:[2,5].includes(stone)&&j===2?'wave':'bolt',motif:['fire','lightning','blackhole','venom','holy','sigil','skull'][stone],color:STONE_COLORS[stone],stone,tier:'normal',weight:.24,strike:0,resolved:false});}}
  else for(let cycle=0;cycle<2;cycle++)for(let j=0;j<5;j++){const angle=offset+(j+cycle)*Math.PI*2/3,at=4.2+cycle*5.2+j*.32;out.push({id:'',at,warning:at-(1.05+cycle*5.2+j*.10),freezeStart:1.5+cycle*5.2,freezeEnd:3.5+cycle*5.2,angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:'bolt',motif:'staff_orb',color:STONE_COLORS[j],stone:j,status:STONE_STATUSES[j],tier:'normal',weight:.24,strike:0,resolved:false});}
  out.forEach((event,index)=>{event.id='block:'+index;if(event.stone!==undefined)event.status=STONE_STATUSES[event.stone];});return out;
 }
 const motifs={shalltear:phase===1?['thread','bat','eye']:['lance','echo','blood'],demiurge:phase===1?['sigil','order','trap']:['fire','plan','demon'],albedo:phase===1?['wing','shaft','shield']:['crack','wing','axe'],pandora:['false_light','mask','mask'],ainz:phase===1?['staff_orb','blackhole','bone']:['freeze','death','meteor']};
 for(let i=0;i<(who==='ainz'&&phase===2&&move===1?3:phase===1?4:5);i++){
  const at=who==='ainz'&&phase===2&&move===0?3.85+i*1.10:2.1+i*(phase===1?1.65:1.35),motif=(motifs[who]||['bone','bone','bone'])[Math.min(move,2)];let angle=offset+p.polarity*i*Math.PI/2;
  if(who==='shalltear')angle=offset+p.polarity*(move===0?i%2*Math.PI:move===1?i*Math.PI/4:i*Math.PI/2);
  else if(who==='demiurge')angle=offset+((i*3+move)%8)*Math.PI/4;
  else if(who==='albedo')angle=offset+i%2*Math.PI/2;
  else if(who==='pandora')angle=offset+((i+move*2)%4)*Math.PI/2;
  else if(who==='ainz')angle=offset+i*Math.PI*(move===0?2/7:move===1?2/3:.5);
  const add=(t,a,weight=.3,kind='slash')=>out.push({id:'',at:t,warning:Math.max(.72,params.warning)+(motif==='freeze'?.30:0),angle:Math.atan2(Math.sin(a),Math.cos(a)),kind,motif,tier:weight>=1?'critical':weight>=.6?'heavy':weight>=.3?'normal':'minor',weight,strike:0,resolved:false});
  add(at,angle,move===2?.6:.3,who==='demiurge'&&phase===2||who==='ainz'&&move===1?'wave':'slash');
  if(who==='shalltear'&&phase===2&&move===1)add(at+.62,angle,.3);
  else if(who==='albedo')add(at+.65,angle+(move===1?Math.PI/2:0),.6,phase===2?'wave':'slash');
  else if(who==='pandora'&&phase===2)add(at+.65,angle+Math.PI/2,.3);
  else if(who==='ainz'&&move===0)add(at+.55,angle+Math.PI/4,.1,'bolt');
  else if(who==='demiurge'&&move===1)add(at+.65,angle+Math.PI/2,.3);
  else if(who==='shalltear'&&move===0)add(at+.55,angle+Math.PI,.1,'bolt');
  else if(who==='shalltear'&&move===2)add(at+.60,angle,.6,'wave');
  else if(who==='demiurge'&&move===2)add(at+.62,angle,.1,'bolt');
  else if(who==='pandora'&&move===1)add(at+.65,angle,.6,'wave');
 }
 out.sort((a,b)=>a.at-b.at);out.forEach((event,index)=>{if(who==='lich')Object.assign(event,{color:'#e4dfda',motif:index%2?'skull':'bone'});if(who==='ainz'&&phase===2&&move===2){const stone=index%7;Object.assign(event,{motif:'staff_orb',stone,color:STONE_COLORS[stone],status:STONE_STATUSES[stone]});}if(['demiurge','hellguard','pyromancer'].includes(who))event.status=phase===2&&move===0||['hellguard','pyromancer'].includes(who)?'burn':'curse';});const delay=Math.max(0,1.02-Math.min(...out.map(e=>e.at-e.warning)));
 out.forEach((e,i)=>Object.assign(e,{id:'block:'+i,at:e.at+delay,strike:Math.min(p.strikes-1,Math.floor(i*p.strikes/out.length))}));return out;
}
function blockFlight(e,t){const elapsed=t-(e.at-e.warning);if(e.freezeStart===undefined)return Math.max(0,Math.min(1,elapsed/e.warning));const pause=e.freezeEnd-e.freezeStart,paused=Math.max(0,Math.min(pause,t-e.freezeStart));return Math.max(0,Math.min(1,(elapsed-paused)/(e.warning-pause)));}
return{identity,colors,shapes,blockThreats,blockFlight,timeStopped,advanceHoming,activeDuration,blockDuration,schedule,STONE_COLORS,STONE_STATUSES};
});
