/* Presentation only. Image bounds and trails never change collision outcomes. */
(()=>{
 'use strict';
 const TAU=Math.PI*2,images=new Map();
 function image(key){if(typeof Image!=='function')return null;if(!images.has(key)){const im=new Image();im.src='/static/assets/nazarick/'+(key.startsWith('bg-')?'ainz-qte-'+key+'-v3.png':'ainz-'+key+'-v2.png');images.set(key,im);}return images.get(key);}
 function art(c,key,x,y,w,h,angle=0,alpha=1){const im=image(key);if(!im?.complete||!im.naturalWidth)return false;const scale=Math.min(w/im.naturalWidth,h/im.naturalHeight);c.save();c.translate(x,y);c.rotate(angle);c.globalAlpha*=alpha;c.drawImage(im,-im.naturalWidth*scale/2,-im.naturalHeight*scale/2,im.naturalWidth*scale,im.naturalHeight*scale);c.restore();return true;}
 function stroke(c,points,color,width=1){c.strokeStyle=color;c.lineWidth=width;c.beginPath();points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.stroke();}
 function disc(c,x,y,r,color){c.fillStyle=color;c.beginPath();c.arc(x,y,Math.max(.1,r),0,TAU);c.fill();}
 function text(c,value,x,y,color,size=11){c.font=`600 ${size}px Segoe UI,sans-serif`;c.textAlign='center';c.fillStyle=color;c.fillText(value,x,y);}
 function glyph(c,h,x,y,r,angle,t){
  const color=h.color||'#d2c0ea',m=h.motif||'staff_orb';c.save();c.translate(x,y);c.rotate(angle);c.strokeStyle=color;c.fillStyle=color;c.lineWidth=1.5;
  if(h.ainzSprite==='axe'||h.ainzSprite==='sword'){
   if(art(c,'prop-'+h.ainzSprite,-(h.length||14)/2,0,(h.length||14)+r*2,r*2)){
    c.restore();return;
   }
  }
  if(m==='spear'||m==='holy_ray'){
   const len=h.length||24;stroke(c,[[-len,0],[r,0]],'#f1dc9c',2);
   c.beginPath();c.moveTo(r,0);c.lineTo(-r*.5,-r*.65);c.lineTo(-r*.15,0);c.lineTo(-r*.5,r*.65);c.closePath();c.fill();
   stroke(c,[[-len,-r*.65],[-len+r,0],[-len,r*.65]],color,1.4);
  }else if(['dagger','blade','bloodblade'].includes(m)){
   const len=h.length||18;c.fillStyle=m==='bloodblade'?'#b93d59':'#d3dce3';
   c.beginPath();c.moveTo(r,0);c.lineTo(-len*.55,-r*.65);c.lineTo(-len*.65,0);c.lineTo(-len*.55,r*.65);c.closePath();c.fill();
   stroke(c,[[-len*.65,0],[-len,0]],'#8d7764',3);stroke(c,[[-len*.6,-r],[-len*.6,r]],color,2);stroke(c,[[r,0],[-len*.5,-r*.45]],color,1);
  }else if(m==='skull'){
   c.fillStyle='#e0dfd7';c.beginPath();c.ellipse(0,-1,r*.9,r,0,0,TAU);c.fill();c.fillRect(-r*.6,r*.1,r*1.2,r*.8);
   disc(c,-r*.35,-r*.15,r*.22,'#19131e');disc(c,r*.35,-r*.15,r*.22,'#19131e');stroke(c,[[-r*.4,r*.55],[r*.4,r*.55]],'#5e5265',1);
   for(let j=-1;j<=1;j++)stroke(c,[[j*r*.25,r*.35],[j*r*.25,r*.9]],'#5e5265',.8);
  }else if(m==='bone'){
   stroke(c,[[-r,0],[r,0]],'#dddcd4',r*.55);for(const side of[-1,1])for(const yy of[-1,1])disc(c,side*r*.85,yy*r*.24,r*.28,'#dddcd4');
  }else if(m==='rubble'||m==='crystal'){
   c.fillStyle=m==='rubble'?'#6b5153':'#c54563';c.strokeStyle=m==='rubble'?'#b6a095':'#f294ae';c.lineWidth=1;
   c.beginPath();for(let j=0;j<7;j++){const a=j*TAU/7,rr=r*(j%2?.82:1);c.lineTo(Math.cos(a)*rr,Math.sin(a)*rr);}c.closePath();c.fill();c.stroke();
   stroke(c,[[-r*.5,r*.2],[0,-r*.65],[r*.4,r*.3]],m==='rubble'?'#342c35':'#f9b1bd',1);
  }else if(m==='fire'){
   c.fillStyle='#d8543d';c.beginPath();c.moveTo(r,0);c.quadraticCurveTo(-r,-r,-r*1.6,0);c.quadraticCurveTo(-r,r,r,0);c.fill();disc(c,0,0,r*.48,'#efb766');
  }else if(m==='lightning'){
   stroke(c,[[-r*1.3,-r*.5],[-r*.2,r*.2],[-r*.5,-r*.7],[r,0]],'#a6d5f1',2.2);stroke(c,[[-r,0],[r,0]],'#f2f4e9',.8);
  }else if(m==='void'){
   disc(c,0,0,r,'#090614');c.strokeStyle=color;c.beginPath();c.ellipse(0,0,r,r*.55,t,0,TAU);c.stroke();
  }else{
   c.beginPath();for(let j=0;j<6;j++){const a=j*TAU/6;c.lineTo(Math.cos(a)*r,Math.sin(a)*r);}c.closePath();c.fill();
   stroke(c,[[-r*.5,-r*.3],[0,-r*.6],[r*.4,-r*.2]],'#e8e1df',1);disc(c,-r*.2,-r*.1,r*.2,'#ece5e2');
  }c.restore();
 }
 function backgroundKey(p){const n=globalThis.AinzQTE?.identity(p);return n?(n.phase===6&&n.move===1?'ritual':String(n.phase)):null;}
 function field(c,s,H=320){
  const n=globalThis.AinzQTE?.identity(s.p);if(!n||s.kind==='attack')return;
  const {phase,move}=n,t=s.time,key=backgroundKey(s.p),im=image('bg-'+key);c.save();
  if(im?.complete&&im.naturalWidth){const scale=Math.max(720/im.naturalWidth,H/im.naturalHeight);c.globalAlpha=.72;c.drawImage(im,(720-im.naturalWidth*scale)/2,(H-im.naturalHeight*scale)/2,im.naturalWidth*scale,im.naturalHeight*scale);}
  c.globalAlpha=1;c.fillStyle='#05081380';c.fillRect(0,0,720,H);
  if(phase===1&&move===0&&t>=(s.preparation||0)){
   const stone=Math.max(0,Math.min(6,Math.floor((t-(s.preparation||0)-.18)/2.55))),names=['ОГОНЬ','ГРОЗА','БЕЗДНА','ЯД','СВЕТ','ПЕЧАТЬ','КОСТИ'],color=globalThis.NazarickQTE.STONE_COLORS[stone];
   c.globalAlpha=.08;c.fillStyle=color;c.fillRect(0,0,720,H);c.globalAlpha=1;text(c,'КАМЕНЬ '+(stone+1)+'/7 · '+names[stone],360,40,color,13);
  }
  if(phase===6&&move===0){
   c.globalAlpha=.13;c.strokeStyle='#b9c7d7';c.lineWidth=1;c.beginPath();c.arc(360,H/2,137,0,TAU);c.stroke();
   for(let j=0;j<12;j++){const a=j*TAU/12;stroke(c,[[360+Math.cos(a)*129,H/2+Math.sin(a)*129],[360+Math.cos(a)*137,H/2+Math.sin(a)*137]],'#b9c7d7',1);}
   c.globalAlpha=.8;text(c,'ЦИКЛ '+Math.max(1,Math.min(2,1+Math.floor((t-(s.preparation||0))/5.2)))+'/2 · ГРАНИЦЫ ВРЕМЕНИ',360,H-14,'#c1bad8',11);
  }
  c.restore();
 }
 function hazard(c,s,h,g,{warning,spent}){
  if(!globalThis.AinzQTE?.identity(s.p)||h.uniform||h.visualOnly)return false;
  const E=globalThis.QTEUnique,t=s.time,color=h.color||s.p.color;c.save();
  if(h.type==='bullet'){
   if(warning){
    // Warn about the source, not the exact future dodge solution.
    c.setLineDash([]);c.globalAlpha*=.8;c.strokeStyle=color;c.lineWidth=1.5;
    const pulse=1+.15*Math.sin(t*12);c.beginPath();c.arc(h.x,h.y,(h.r+6)*pulse,0,TAU);c.stroke();
    glyph(c,h,h.x,h.y,h.r,Math.atan2(h.vy,h.vx),t);
   }else{
    c.setLineDash([]);c.globalAlpha*=spent?.25:1;
    if(!spent){const pts=[];for(let j=5;j>=0;j--){const v=E.geometry(h,Math.max(h.start,t-j*.025));pts.push([v.x,v.y]);}c.save();c.globalAlpha*=.24;stroke(c,pts,color,Math.max(1,g.r*.5));c.restore();}
    // A quiet footprint remains visible even through transparent PNG margins.
    // It is exactly the swept capsule used by touches(), not a larger glow.
    if(!spent){const len=Math.hypot(g.vx,g.vy)||1;c.save();c.globalAlpha*=.18;c.lineCap='round';stroke(c,[[g.x-g.vx/len*(h.length||0),g.y-g.vy/len*(h.length||0)],[g.x,g.y]],color,g.r*2);c.restore();}
    glyph(c,h,g.x,g.y,g.r,Math.atan2(g.vy,g.vx),t);
   }
  }else if(h.type==='rect'&&h.terrain){
   c.globalAlpha*=warning?.16:spent?.07:.24;c.fillStyle=color;c.fillRect(g.x,g.y,g.w,g.h);
   c.globalAlpha=warning?.75:.9;c.strokeStyle=color;c.lineWidth=warning?1.5:2.5;c.setLineDash(warning?[6,5]:[]);
   c.strokeRect(g.x,g.y,g.w,g.h);
  }else if(h.type==='circle'&&h.motif==='conductor'){
   c.globalAlpha*=warning?.45:spent?.15:1;c.strokeStyle=color;c.lineWidth=2;c.beginPath();c.arc(g.x,g.y,g.r,0,TAU);c.stroke();
   if(!warning&&!spent){c.shadowColor=color;c.shadowBlur=12;disc(c,g.x,g.y,g.r*.6,'#e1f0ff');}
  }else if(h.type==='ring'&&h.motif==='shockwave'){
   const from=g.gap+g.gapWidth/2,to=g.gap+TAU-g.gapWidth/2;c.setLineDash(warning?[6,5]:[]);
   c.globalAlpha*=warning?.35:spent?.12:.8;c.strokeStyle='#a96f70';c.lineWidth=g.thickness*2;c.beginPath();c.arc(g.x,g.y,Math.max(.1,g.r),from,to);c.stroke();
   c.setLineDash([]);c.lineWidth=2;c.strokeStyle='#e3b5a3';c.beginPath();
   for(let j=0;j<=90;j++){const a=from+(to-from)*j/90,rr=g.r+Math.sin(j*1.9)*g.thickness*.55;j?c.lineTo(g.x+Math.cos(a)*rr,g.y+Math.sin(a)*rr):c.moveTo(g.x+Math.cos(a)*rr,g.y+Math.sin(a)*rr);}c.stroke();
   c.strokeStyle='#2b1820';c.lineWidth=2;for(let j=0;j<22;j++){const a=from+(to-from)*j/22;stroke(c,[[g.x+Math.cos(a)*(g.r-g.thickness),g.y+Math.sin(a)*(g.r-g.thickness)],[g.x+Math.cos(a)*(g.r+g.thickness),g.y+Math.sin(a)*(g.r+g.thickness)]],'#2b1820',2);}
  }else if(h.type==='line'||h.type==='polyline'){
   const pts=h.type==='line'?[[g.ax,g.ay],[g.bx,g.by]]:g.points;
   if(warning&&h.ainzPath==='sweepLine'){
    const life=h.end-h.start;c.save();c.globalAlpha*=.14;c.fillStyle=color;c.beginPath();
    c.moveTo(h.ax,h.ay);c.lineTo(h.bx,h.by);c.lineTo(h.bx+h.dx*life,h.by+h.dy*life);c.lineTo(h.ax+h.dx*life,h.ay+h.dy*life);c.closePath();c.fill();c.restore();
   }
   if(warning&&h.clockTurn){const a=Math.atan2(h.by-h.ay,h.bx-h.ax),r=Math.hypot(h.bx-h.ax,h.by-h.ay);c.save();c.globalAlpha*=.13;c.fillStyle=color;c.beginPath();c.moveTo(h.ax,h.ay);c.arc(h.ax,h.ay,r,Math.min(a,a+h.clockTurn*(h.end-h.start)),Math.max(a,a+h.clockTurn*(h.end-h.start)));c.closePath();c.fill();c.restore();}
   c.setLineDash(warning?[7,5]:[]);c.globalAlpha*=warning?.42:spent?.15:1;
   stroke(c,pts,color,warning?1.5:g.r*2);
   if(!warning&&!spent){
    const stone=['fracture','ground_shear','bloodblade'].includes(h.motif);c.shadowColor=color;c.shadowBlur=stone?3:10;
    stroke(c,pts,stone?'#1a0f16':'#f1f5ff',Math.max(1,g.r*(stone?.7:.34)));
    if(!stone&&h.motif==='lightning'&&h.type==='line'){
     const dx=g.bx-g.ax,dy=g.by-g.ay,len=Math.hypot(dx,dy)||1,zz=[];
     for(let j=0;j<=24;j++){const u=j/24,k=Math.sin(j*2.7+t*25)*g.r*.6;zz.push([g.ax+dx*u-dy/len*k,g.ay+dy*u+dx/len*k]);}
     stroke(c,zz,'#d8efff',1.4);
    }
   }
  }else if(h.type==='well'){
   c.setLineDash(warning?[6,5]:[]);c.strokeStyle=color;c.lineWidth=1.5;c.beginPath();c.arc(g.x,g.y,g.r,0,TAU);c.stroke();
   c.setLineDash([]);disc(c,g.x,g.y,g.r*.83,'#070613');
   for(let j=0;j<4;j++){const r=g.r*(.25+((t*.35+j*.23)%1)*.7);c.save();c.translate(g.x,g.y);c.rotate(t*.8+j);c.strokeStyle=color;c.globalAlpha*=.65;c.beginPath();c.ellipse(0,0,r,r*.38,0,0,TAU);c.stroke();c.restore();}
  }else{c.restore();return false;}
  c.restore();return true;
 }
 function blockGlyph(c,s,h,x,y,r,t){if(!globalThis.AinzQTE?.identity(s.p))return false;glyph(c,h,x,y,r,0,t);return true;}
 globalThis.AinzArt={field,hazard,blockGlyph,backgroundKey};
})();
