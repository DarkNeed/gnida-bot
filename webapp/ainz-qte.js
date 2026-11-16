/* Ainz's animated weapons and analytic paths. Python is the authority. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AinzQTE=api;})(globalThis,function(){
'use strict';
const colors=['#b69bff','#d6c7ff','#ffe59a','#e95c83','#a7ddff','#cb8eff'];
const stoneColors=['#ef4545','#81bdff','#a882e8','#75b985','#f3d48b','#d78db6','#dfe8ee'];
const stoneStatuses=['burn','shock','curse','venom','exposed','sealed','frailty'];
const families=[['mana','void','death','death'],['slash','slash','thrust','slash'],['holy','holy','holy','holy'],['impact','impact','slash','impact'],['lightning','lightning','slash','impact'],['coins','eclipse','holy','void']];
const statuses=[[null,'curse',null,'frailty'],['bleed','bleed','bleed','bleed'],['exposed','exposed','exposed','exposed'],['frailty','bleed','frailty','bleed'],['shock','shock','shock','shock'],[null,null,null,'curse']];
function identity(p){const a=(p.skill.base_id||'').split('_');return a.length===4&&a[1]==='ainz6'?{phase:Number(a[2].slice(1)),move:Number(a[3])}:null;}
function activeDuration(phase,move){return phase===1&&move===0?18.8:phase===6&&move===0?10.4:[4,5,6].includes(phase)?9.2:8.8;}
function schedule(phase,move){return phase===1&&move===0?[7,15.3]:phase===6&&move===0?[2,5.2]:phase===4||phase===6&&move===1?[3,4.8]:[4,4.8];}
function motion(h,age){
 const path=h.ainzPath;let x,y,vx,vy;
 if(path==='slidePolyline')return{...h,points:h.points.map(([x,y])=>[x+age*h.dx,y+age*h.dy])};
 if(path==='driftRect'){const offset=Math.sin(age*h.frequency+h.offset)-Math.sin(h.offset);return{...h,x:h.x+offset*h.driftX,y:h.y+offset*h.driftY};}
 if(path==='sweepLine')return{...h,ax:h.ax+age*h.dx,ay:h.ay+age*h.dy,bx:h.bx+age*h.dx,by:h.by+age*h.dy};
 if(path==='ricochet'){
  const reflect=(p,v,lo,hi)=>{const width=hi-lo,u=((p-lo+v*age)%(2*width)+2*width)%(2*width);return u<width?[lo+u,v]:[hi-(u-width),-v];};
  [x,vx]=reflect(h.x,h.vx,h.minX,h.maxX);[y,vy]=reflect(h.y,h.vy,h.minY,h.maxY);return{...h,x,y,vx,vy};
 }
 if(path==='sealDrift')return{...h,x:h.x+Math.sin(age*h.frequency)*h.driftX,y:h.y+Math.sin(age*h.frequency*.7)*h.driftY};
 if(path==='bezier'){
  const u=Math.min(1,age/h.pathTime),v=1-u;
  x=v**3*h.x+3*v*v*u*h.c1x+3*v*u*u*h.c2x+u**3*h.tx;
  y=v**3*h.y+3*v*v*u*h.c1y+3*v*u*u*h.c2y+u**3*h.ty;
  vx=3*(v*v*(h.c1x-h.x)+2*v*u*(h.c2x-h.c1x)+u*u*(h.tx-h.c2x))/h.pathTime;
  vy=3*(v*v*(h.c1y-h.y)+2*v*u*(h.c2y-h.c1y)+u*u*(h.ty-h.c2y))/h.pathTime;
 }else if(path==='wave'){
  const length=Math.hypot(h.vx,h.vy)||1,nx=-h.vy/length,ny=h.vx/length,envelope=1-Math.exp(-age*3);
  const offset=h.amplitude*Math.sin(age*h.frequency)*envelope;
  const derivative=h.amplitude*(h.frequency*Math.cos(age*h.frequency)*envelope+3*Math.sin(age*h.frequency)*Math.exp(-age*3));
  x=h.x+h.vx*age+nx*offset;y=h.y+h.vy*age+ny*offset;vx=h.vx+nx*derivative;vy=h.vy+ny*derivative;
 }else if(path==='orbitLaunch'){
  const t=Math.min(age,h.releaseAt),a=h.orbitAngle+h.orbitSpeed*t,r=h.orbitRadius+h.spiral*t;
  x=h.cx+Math.cos(a)*r;y=h.cy+Math.sin(a)*r;vx=Math.cos(a)*h.spiral-Math.sin(a)*r*h.orbitSpeed;vy=Math.sin(a)*h.spiral+Math.cos(a)*r*h.orbitSpeed;
  if(age>h.releaseAt){const length=Math.hypot(vx,vy)||1;vx=vx/length*h.launchSpeed;vy=vy/length*h.launchSpeed;x+=vx*(age-h.releaseAt);y+=vy*(age-h.releaseAt);}
 }else throw Error('Unknown Ainz trajectory');
 return{...h,x,y,vx,vy};
}
function timeCurtains(s,e){
 const cycle=e.index%2,base=cycle*5.2,prep=s.preparation??1,out=[],gaps=[cycle===0?270:450,cycle===0?200:120,360];
 for(let wall=0;wall<3;wall++)for(let j=0;j<(wall!==1?15:12);j++){
  const lane=wall!==1?150+j*30:28+j*24;if(Math.abs(lane-gaps[wall])<(wall!==1?44:38))continue;
  const[bx,by,vx,vy]=wall===0?[lane,-45,0,245]:wall===1?[765,lane,-330,0]:[lane,365,0,-235],delay=wall*.1-s.d.warning-.18;
  const start=(e.at??prep+base+.18)+s.d.warning+delay,freezeBegin=prep+base+.5,release=prep+base+3.15+wall*.38;
  out.push({type:'bullet',x:bx,y:by,vx,vy,r:6.5,motif:'staff_orb',stone:j%7,color:stoneColors[j%7],status:stoneStatuses[j%7],tier:'normal',weight:.26,staff:true,ainzPath:'wave',amplitude:9,frequency:4.2,freezeAt:Math.max(0,freezeBegin-start),freezeFor:Math.max(0,release-Math.max(freezeBegin,start)),delay,duration:release-start+1.5,timeWall:wall});
 }
 return out;
}
function pressure(s,e){
 const{phase,move}=identity(s.p),i=e.index,sign=i%2?1:-1,{x,y}=s.player,out=[],d=s.d;
 const color=phase===1&&move===0?stoneColors[i%7]:['#b69bff','#dac9ae','#f3d48b','#cb435e','#92cfff','#bb8bdd'][phase-1],status=phase===1&&move===0?stoneStatuses[i%7]:{1:'curse',2:'bleed',3:'exposed',4:'frailty',5:'shock',6:'sealed'}[phase];
 const add=(h,delay=.4,duration=.25,extra={})=>out.push({color,status,tier:'minor',weight:.14,...h,delay,duration,...extra});
 const bolt=(bx,by,vx,vy,delay=.4,motif='lightning',duration=3,extra={})=>add({type:'bullet',x:bx,y:by,vx,vy,r:7,motif,...extra},delay,duration);
 const line=(ax,ay,bx,by,delay=.75,duration=.26,r=6,motif='lightning',extra={})=>add({type:'line',ax,ay,bx,by,r,motif,...extra},delay,duration);
 function corridor(width,amplitude=0,duration=2.7,delay=.15){for(const bx of[360-width/2-900,360+width/2])add({type:'rect',x:bx,y:0,w:900,h:320,motif:'territory',ainzPath:'driftRect',driftX:amplitude,driftY:0,frequency:.85,offset:i*.8,terrain:true},delay,duration,{weight:.18});}
 const ricochet=(bx,by,a,delay=.5,speed=150)=>bolt(bx,by,Math.cos(a)*speed,Math.sin(a)*speed,delay,'lightning',3,{ainzPath:'ricochet',minX:105,maxX:615,minY:38,maxY:282,r:7});
 function fracture(bx,delay=.6){const points=Array.from({length:13},(_,j)=>[bx+Math.sin(j*1.7+i)*18,j*320/12]);add({type:'polyline',points,r:8,motif:'fracture',ainzPath:'slidePolyline',dx:sign*75,dy:0},delay,.55,{weight:.24});}
 if(phase===1&&move===2||phase===6&&move===1)return[];
 corridor(phase===6&&move===0?360:[2,5].includes(phase)?440:480,phase===6&&move===0?0:35,phase===6&&move===0?2:phase===1&&move===0?1.9:2.7,phase===6&&move===0?2.97-d.warning:.15);
 if(phase===6&&move===0){for(const yy of[-858,278])add({type:'rect',x:0,y:yy,w:720,h:900,motif:'time_wall',terrain:true},2.97-d.warning,2,{weight:.18,status:'curse'});return out;}
 for(const yy of[-876,296])add({type:'rect',x:0,y:yy,w:720,h:900,motif:'territory',terrain:true},.15,phase===1&&move===0?1.9:2.7,{weight:.18});
 if(![4,5].includes(phase)){
  const lanes=[65+((i*67+move*31)%190),255-((i*53+move*41)%190)];
  lanes.forEach((yy,j)=>bolt(sign>0?35:685,yy,sign*(125+j*15),j?-18:18,.5+j*.5,phase===3?'spear':phase===1&&move===0?['fire','lightning','void','venom','holy_ray','sigil','bone'][i%7]:phase===1?'bone':phase===2?'dagger':'staff_orb',phase===1&&move===0?1.1:3.6,{ainzPath:'wave',amplitude:22,frequency:3.1,weight:.12}));return out;
 }
 if(phase===4){
  if(move===0){
   const yy=65+i%3*80;line(0,yy,720,yy,.65,.72,11,'ground_shear',{ainzPath:'sweepLine',dx:0,dy:sign*90,weight:.3});
   add({type:'ring',x:Math.max(150,Math.min(570,x)),y:Math.max(85,Math.min(235,y)),r:18,speed:155,gap:e.angle??i*.7,gapWidth:1.45,thickness:9,motif:'shockwave'},1,1.5,{weight:.28});
   for(let j=0;j<5;j++){const a=j*Math.PI*2/5+i*.4;bolt(360,160,Math.cos(a)*140,Math.sin(a)*140,1.5,'crystal',2,{returnAt:.85,r:6});}
  }else if(move===1){
   for(let j=0;j<3;j++)fracture(155+j*170,.25+j*.3);
   for(let row=0;row<2;row++){const gap=(i*2+row*3+1)%11;for(let j=0;j<12;j++){if(j===gap||j===gap+1)continue;bolt(100+j*48,-24,sign*(25+row*20),255+row*30,.35+row*.62+j%3*.065,'rubble',1.65,{r:7,weight:.08});}}
   for(let j=0;j<4;j++){const a=Math.atan2(y-160,x-(sign>0?35:685))+(j-1.5)*.24;bolt(sign>0?35:685,160,Math.cos(a)*240,Math.sin(a)*240,1.05,'crystal',1.8,{r:6,weight:.1});}
  }else if(move===2){
   for(let row=0;row<3;row++){const gap=(i*3+row*2+2)%11;for(let j=0;j<12;j++){if(j===gap||j===gap+1)continue;bolt(100+j*48,-24,sign*(18+row*15),265,.25+row*.46+j%2*.09,'rubble',1.65,{r:7,weight:.08});}}
   const gapx=220+i%3*130;for(const[ax,bx]of[[0,gapx-48],[gapx+48,720]])line(ax,310,bx,310,.8,.9,7,'ground_shear',{ainzPath:'sweepLine',dx:0,dy:-300,weight:.25});
   bolt(x,-24,0,285,1.1,'rubble',1.5,{r:10,weight:.12});
  }else{
   for(let j=0;j<2;j++){const a=i*.7+j*Math.PI;line(360,160,360+Math.cos(a)*300,160+Math.sin(a)*300,.4,.6,9,'bloodblade',{clockTurn:sign*2.6,weight:.3});}
   for(let row=0;row<2;row++)for(let j=0;j<10;j++){const a=i*.5+j*Math.PI*2/10+row*.31;bolt(360,160,Math.cos(a)*225,Math.sin(a)*225,.85+row*.5,'crystal',1.65,{returnAt:.65,r:5.5,weight:.08});}
  }
  return out;
 }
 if(move===0){const nodes=[[150,75],[360,175],[570,75]];nodes.forEach(([bx,by],j)=>{add({type:'circle',x:bx,y:by,r:17,motif:'conductor'},.45+j*.35,.35,{weight:.18});if(j<2)line(bx,by,...nodes[j+1],.8+j*.45,.28,7);});ricochet(160,90,.5+sign*.3,.6);ricochet(560,240,Math.PI+.5-sign*.3,1.2);}
 else if(move===1){for(let j=0;j<3;j++){line(170+j*185,0,170+j*185,320,.5+j*.45,.26,6);line(90,65+j*95,630,65+j*95,1.1+j*.4,.25,6);}ricochet(360,50,1.1+i*.3,.8);}
 else if(move===2){for(let j=0;j<3;j++){const yy=65+j*95;line(90,yy,630,320-yy,.45+j*.38,.18,7,'blade',{weight:.22});line(90,yy,630,320-yy,1.35+j*.38,.18,5,'lightning',{weight:.18});}ricochet(150,160,.65*sign,.8);}
 else{for(let j=0;j<2;j++){const cx=230+j*260,cy=160,r=74,points=[[cx-r,cy-r],[cx+r,cy-r],[cx+r,cy+r],[cx-r,cy+r],[cx-r,cy-r]];add({type:'polyline',points,r:6,motif:'lightning'},.65+j*.6,.3,{weight:.2});}ricochet(160,60,.7,.45);ricochet(560,260,Math.PI+.7,1.05);line(0,160,720,160,1.7,.25,7);}
 return out;
}
function shapes(s,e){
 const{phase,move}=identity(s.p),{x,y}=s.player,d=s.d,i=e.index,sign=i%2?1:-1,color=colors[phase-1],status=statuses[phase-1][move],out=[],clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 const add=(h,delay=.25,duration=.26)=>out.push({color,status,tier:'normal',weight:.22,...h,delay,duration});
 const shot=(bx,by,angle,delay=.25,motif='dagger',speed=.62,extra={})=>add({type:'bullet',x:bx,y:by,vx:Math.cos(angle)*d.speed*speed,vy:Math.sin(angle)*d.speed*speed,r:6,motif,...extra},delay,2.6);
 function fan(bx,by,n=5,delay=.25,motif='dagger',spread=.28,homing=0,tint=null){const a=Math.atan2(y-by,x-bx);for(let j=0;j<n;j++){shot(bx,by,a+(j-(n-1)/2)*spread,delay,motif,.60,homing?{homing,turnRate:.95}:{});if(tint)out.at(-1).color=tint;}}
 function curve(bx,by,bend=85,delay=.25,motif='dagger',time=2.3,tint=null){const dx=2*(x-bx),dy=2*(y-by),length=Math.hypot(dx,dy)||1,nx=-dy/length,ny=dx/length;
  add({type:'bullet',x:bx,y:by,vx:dx/time,vy:dy/time,r:7,length:18,motif,ainzPath:'bezier',c1x:bx+dx/3+nx*bend,c1y:by+dy/3+ny*bend,c2x:bx+dx*2/3-nx*bend,c2y:by+dy*2/3-ny*bend,tx:bx+dx,ty:by+dy,pathTime:time},delay,time);if(tint)out.at(-1).color=tint;
 }
 const wave=(bx,by,angle,delay=.25,motif='spear',amplitude=22,frequency=3.4,extra={})=>shot(bx,by,angle,delay,motif,.67,{ainzPath:'wave',amplitude,frequency,...extra});
 const orbit=(angle,delay=.25,motif='staff_orb',radius=128,spiral=-18,omega=1.4,release=1.1,extra={})=>add({type:'bullet',x:360+Math.cos(angle)*radius,y:160+Math.sin(angle)*radius,vx:0,vy:0,cx:360,cy:160,r:8,motif,ainzPath:'orbitLaunch',orbitAngle:angle,orbitRadius:radius,orbitSpeed:omega,spiral,releaseAt:release,launchSpeed:d.speed*.72,...extra},delay,2.7);
 const cut=(ax,ay,bx,by,delay=.6,r=7,motif='blade',duration=.26,extra={})=>add({type:'line',ax,ay,bx,by,r:r*d.beamScale,motif,...extra},delay,duration);
 function ribbon(cx,cy,delay=.7,motif='lightning',width=6,vertical=false){const points=[];for(let j=0;j<19;j++){const u=j/18;points.push([vertical?cx+Math.sin(u*Math.PI*4+i*.7)*26:720*u,vertical?320*u:cy+Math.sin(u*Math.PI*4+i*.7)*26]);}add({type:'polyline',points,r:width*d.beamScale,motif},delay,.32);}
 const well=(cx,cy,delay=.4,r=48)=>add({type:'well',x:clamp(cx,r+10,710-r),y:clamp(cy,r+10,310-r),r,pull:40,motif:'blackhole'},delay,1.6);
 if(phase===1){
  if(move===0){const stone=i%7;
   if(stone===0){for(const side of[-1,1])curve(360+side*335,45+e.jitter*230,side*95,.12,'fire',1.85);}
   else if(stone===1){for(let j=0;j<3;j++)ribbon(110+j*250,160,.15+j*.38,'lightning',6,true);wave(20,50,Math.atan2(y-50,x-20),.65,'lightning',35);}
   else if(stone===2){well(x+sign*90,y,.2,46);curve(sign>0?690:30,160,sign*120,.7,'void',1.3);}
   else if(stone===3){fan(25,50,5,.15,'venom',.3,.65);fan(695,270,3,.65,'venom',.35,.45);}
   else if(stone===4){for(let j=0;j<3;j++)wave(20,60+j*100,0,.15+j*.18,'holy_ray',22,4.2);}
   else if(stone===5){for(let j=0;j<5;j++)orbit(j*Math.PI*2/5+i*.2,.1,'sigil',104,-12,sign*1.6,.65);}
   else{curve(25,60,120,.1,'skull',1.8);curve(695,260,-120,.5,'bone',1.6);}
   for(const h of out){Object.assign(h,{color:stoneColors[stone],status:stoneStatuses[stone],stone});h.duration=Math.min(h.duration,Math.max(.1,2.15-h.delay));}
  }else if(move===1){well(x+sign*90,y,.3,50);for(let j=0;j<4;j++)orbit(i*.4+j*Math.PI/2,.35,'void',135,-22,sign*1.7,1.2);curve(i%2?25:695,45+e.jitter*230,sign*110,1,'skull',1.7);}
  else if(move===2){for(let j=0;j<3;j++)curve(25,60+j*100,sign*100,.2+j*.22,'bone',2);}
  else{for(let j=0;j<3;j++){curve(22,35+j*125,80+j*25,.15+j*.22,'bone',2.2);curve(698,285-j*125,-80-j*25,.7+j*.16,'skull',2);}}
 }else if(phase===2){
  if(move===0){orbit(i*.6,.15,'dagger',126,-12,1.7,.95,{length:24,ainzSprite:'blades',color:'#ecd7a0'});orbit(i*.6+Math.PI,.45,'dagger',126,-12,-1.7,.95,{length:24,ainzSprite:'blades',color:'#bfcced'});curve(i%2?22:698,55+e.jitter*210,sign*115,1,'dagger',1.7);}
  else if(move===1){fan(22,70,3,.15,'dagger',.45,.65,'#ecd7a0');fan(698,250,3,.7,'dagger',.45,.65,'#bfcced');curve(360,12,sign*130,1.1,'dagger',1.65);}
  else if(move===2){curve(22,50,130,.15,'dagger',2.1,'#ecd7a0');curve(698,270,-130,.7,'dagger',1.8,'#bfcced');for(let j=0;j<3;j++)shot(360,18,Math.PI/2+(j-1)*.42,1.1,'dagger',.57,{turn:sign*.65});}
  else{const bx=i%2?30:690,fy=80+i%3*80;cut(bx,fy,bx+sign*580,fy+sign*85,.75,6,'blade',.55,{clockTurn:sign*.45});curve(360,308,-sign*140,.85,'dagger',1.9);curve(360,12,sign*140,1.2,'dagger',1.8);}
 }else if(phase===3){
  if(move===0){curve(22,70+e.jitter*180,sign*110,.45,'spear',2.2);Object.assign(out.at(-1),{r:8,length:30,ainzSprite:'bow'});for(const side of[-1,1])wave(22,160+side*85,Math.atan2(y-160-side*85,x-22),.85,'spear',28);}
  else if(move===1){const gap=clamp(y+sign*72,75,245);for(const by of[25,70,115,160,205,250,295])if(Math.abs(by-gap)>47)wave(22,by,0,.45,'spear',16,3.6,{ainzLane:gap});curve(698,160,sign*130,1.2,'spear',1.8);}
  else if(move===2){for(let j=0;j<5;j++)orbit(j*Math.PI*2/5+i*.4,.25,'spear',112,6,sign*1.5,.85,{length:22});curve(i%2?30:690,25,sign*120,1.15,'spear',1.9);}
  else{ribbon(360,y,.95,'holy_ray',11);for(let j=0;j<3;j++)curve(22,45+j*115,(j-1)*110,.3+j*.3,'spear',2);}
 }else if([4,5].includes(phase)){
  return pressure(s,e);
 }else{
  if(move===0){out.push(...timeCurtains(s,e));
  }else if(move===1){
   const cx=clamp(x+sign*85,90,630),cy=clamp(y-sign*35,75,245);add({type:'safe_zone',x:cx,y:cy,r:44,motif:'sigil',label:'СМЕРТЬ',uniform:true,ainzPath:'sealDrift',driftX:18,driftY:10,frequency:1.2},1.35,.22);
   for(let j=0;j<2;j++)add({type:'decoy',x:clamp(cx+(cx<360?1:-1)*(185+j*175),80,640),y:clamp(cy+(j*2-1)*70,75,245),r:44,motif:'sigil',label:'ЖИЗНЬ',uniform:true,visualOnly:true,ainzPath:'sealDrift',driftX:18,driftY:10,frequency:1.2},1.35,.22);
   for(const h of out)Object.assign(h,{color:'#b7a0cf',status:'curse',weight:.5});
  }else if(move===2){for(let j=0;j<7;j++){orbit(j*Math.PI*2/7+i*.35,.15+j*.035,'staff_orb',138,-22,sign*(1.1+j*.05),1.15);Object.assign(out.at(-1),{color:stoneColors[j],status:stoneStatuses[j],stone:j,staff:true});}curve(360,18,sign*150,1.25,'staff_orb',1.8);Object.assign(out.at(-1),{status:'sealed',color:stoneColors[5],stone:5,staff:true});}
  else{well(x+sign*100,y,.35,45);ribbon(360,y,.6,'void',8);for(let j=0;j<3;j++)curve(j%2?22:698,35+j*125,sign*(100+j*40),.4+j*.35,'void',2.1);}
 }
 return out.concat(pressure(s,e));
}
function blocks(p,seed,params,rng){
 const{phase,move}=identity(p),offset=Math.floor(rng((seed^p.seed)>>>0)()*8)*Math.PI/4,out=[];
 if(phase===6&&move===0){for(let cycle=0;cycle<2;cycle++)for(let j=0;j<7;j++){const angle=offset+(j+cycle)*Math.PI*2/7,at=3.9+cycle*5.2+j*.32;out.push({id:'',at,warning:at-(1.05+cycle*5.2+j*.1),freezeStart:1.5+cycle*5.2,freezeEnd:3.5+cycle*5.2,angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:'bolt',motif:'staff_orb',color:stoneColors[j],status:stoneStatuses[j],stone:j,tier:'normal',weight:.22,strike:0,resolved:false});}}
 else if(phase===1&&move===0){for(let stone=0;stone<7;stone++)for(let j=0;j<3;j++){const angle=offset+stone*Math.PI*2/7+j*.55;out.push({id:'',at:2.05+stone*2.55+j*.62,warning:Math.max(.85,params.warning),angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:j===2&&[2,5].includes(stone)?'wave':'bolt',motif:['fire','lightning','blackhole','venom','holy','sigil','skull'][stone],color:stoneColors[stone],status:stoneStatuses[stone],stone,tier:'normal',weight:.22,strike:0,resolved:false});}}
 else if([4,5].includes(phase)){for(let wave=0;wave<3;wave++)for(let j=0;j<(phase===4?2:3);j++){const angle=offset+wave*Math.PI*2/3+j*(phase===4?Math.PI/2:Math.PI*2/7)+move*.35,heavy=phase===4&&j===0;out.push({id:'',at:2.1+wave*2.05+j*(phase===4?.7:.42),warning:Math.max(heavy?1.15:.85,params.warning),angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:heavy?'wave':'bolt',motif:phase===4&&j?'rubble':phase===4?'bloodblade':'lightning',color:colors[phase-1],status:statuses[phase-1][move],tier:heavy?'heavy':'normal',weight:heavy?.42:.2,strike:0,resolved:false});}}
 else for(let wave=0;wave<3;wave++)for(let j=0;j<([2,3].includes(phase)?3:2);j++){const count=[2,3].includes(phase)?3:2,heavy=[4,5,6].includes(phase)&&j===count-1,angle=offset+wave*(move%2?Math.PI/2:Math.PI*2/3)+j*(phase===2?Math.PI:Math.PI/3)+move*.25,at=2.1+wave*2.05+j*(phase===2?.46:.62);out.push({id:'',at,warning:Math.max(heavy?1.05:.85,params.warning),angle:Math.atan2(Math.sin(angle),Math.cos(angle)),kind:heavy?'wave':[1,3].includes(phase)?'bolt':'slash',motif:{1:'skull',2:'dagger',3:'spear',4:'bloodblade',5:'lightning',6:'void'}[phase],color:colors[phase-1],status:statuses[phase-1][move],tier:heavy?'heavy':'normal',weight:heavy?.45:.22,strike:0,resolved:false,ainzSprite:({2:'blades',3:'bow',4:'axe',5:'sword'})[phase]||''});}
 out.forEach((h,i)=>h.id='block:'+i);return out;
}
return{identity,legacy:()=>null,shapes,blocks,motion,pressure,colors,families,activeDuration,schedule};
});
