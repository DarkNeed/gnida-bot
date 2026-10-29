/* Class-specific canvas art. Presentation only: no random numbers, state writes,
   hit tests, extra hazards or changes to the authoritative projectile geometry. */
(()=>{
  'use strict';
  const TAU=Math.PI*2,light='#eef4ef',dark='#0a111c';
  const THEMES={
    ragamuffin:['fist','#c2a47c','Ржавчина и уличная пыль'],
    cutie:['heart','#f29cc6','Сердца, поцелуи и кошачьи когти'],
    jock:['fist','#daaa8a','Кулаки, захваты и клубный экспресс'],
    nerd:['code','#76e4c4','Код, вирусы и ошибки исполнения'],
    thumb:['bullet','#e1be7b','Латунь, сталь и порох'],
    index:['paper','#ded1ae','Предписания и печати Указа'],
    middle:['chain','#cc9fa6','Цепи и кулаки семьи'],
    ring:['paint','#df83b1','Краска, кисти и холст'],
    pinky:['blade','#bbd2ff','Звёздные клинки и созвездия'],
    warrior:['sword','#b7c9db','Сталь, кровь и огонь Феникса'],
    mage:['mana','#80ceef','Мана, стихии, души и пустота'],
    priest:['holy','#dfd3a4','Свет, руны и священное оружие'],
    hunter:['claw','#c5bccf','Серебро, кровь и бледная луна'],
    gambler:['card','#edc581','Карты, кости и рулетка'],
  };
  function appearance(p){
    const sk=p.skill||{},cls=sk.class_id,base=THEMES[cls];
    // Bespoke boss/casino presentations remain in their own renderers. A borrowed
    // boss ability keeps its native appearance even in an RP character's loadout.
    if(!base||p.chaplain||p.kit||p.kind?.startsWith('casino_')||window.NazarickQTE?.identity(p))return null;
    const n=(sk.name+' '+(sk.base_id||'')).toLowerCase(),kind=p.kind;
    let [motif,color,label]=base;
    if(cls==='cutie'&&/мяу|милот|лап/.test(n))motif='paw';
    else if(cls==='cutie'&&/поцелуй/.test(n))motif='kiss';
    if(cls==='ragamuffin'&&kind==='dust')motif='dust';
    else if(cls==='ragamuffin'&&/клинок/.test(n))motif='saw';
    if(cls==='middle'&&/цеп/.test(n))motif='chain';
    if(kind==='train'){motif='train';color='#de956f';}
    else if(kind==='rocket'){motif='rocket';color='#ed936e';}
    else if(kind==='tiger'){motif='claw';color='#e8ae77';}
    else if(cls==='thumb'&&kind==='thrust')motif='bayonet';
    else if(cls==='middle'&&kind==='impact')motif='fist';
    else if(cls==='hunter'&&kind==='gun'){motif='silver_bullet';color='#cfdaed';}
    else if(cls==='hunter'&&kind==='stars'){motif='moon';color='#ddd6f5';}
    else if(cls==='hunter'&&kind==='thrust')motif='saw';
    else if(cls==='hunter'&&kind==='slash')motif='saw';
    else if(cls==='ring'&&kind==='beast')motif='paint_claw';
    else if(cls==='pinky'&&kind==='stars')motif='starblade';
    else if(cls==='nerd'&&kind==='script'){motif='terminal';color='#9ebff1';}
    else if(cls==='warrior'&&/пепел|пыла|феникс|жар/.test(n)){motif='flame';color='#eb956e';}
    else if(cls==='warrior'&&/кров|берсерк/.test(n)){motif='bloodblade';color='#d46e7f';}
    else if(cls==='warrior'&&kind==='impact'){motif='shield';color='#99bada';}
    if(cls==='mage'||cls==='priest'){
      if(kind==='void'){motif='void';color='#bc9ae8';}
      else if(kind==='death'){motif='soul';color='#84bba0';}
      else if(kind==='fire'){motif='flame';color='#f1a06e';}
      else if(kind==='ice'){motif='crystal';color='#a0e0f1';}
      else if(kind==='lightning'){motif='spark';color='#c3b6ff';}
      else if(cls==='priest')motif=kind==='thrust'?'glaive':kind==='impact'?'hammer':'holy';
    }
    if(sk.base_id==='guild_net'){motif='web';color='#d5cddb';}
    return {cls,motif,color,label};
  }
  function stroke(c,points,color,width=1,close=false,fill=false){
    c.strokeStyle=color;c.lineWidth=width;c.beginPath();points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));
    if(close)c.closePath();if(fill){c.fillStyle=color;c.fill();}else c.stroke();
  }
  function disc(c,x,y,r,color){c.fillStyle=color;c.beginPath();c.arc(x,y,Math.max(0,r),0,TAU);c.fill();}
  function circle(c,x,y,r,color,width=1){c.strokeStyle=color;c.lineWidth=width;c.beginPath();c.arc(x,y,Math.max(0,r),0,TAU);c.stroke();}
  function polygon(c,points,color){stroke(c,points,color,1,true,true);}
  function heart(c,color){c.fillStyle=color;c.beginPath();c.moveTo(10,0);c.bezierCurveTo(2,-15,-13,-12,-3,0);c.bezierCurveTo(-13,12,2,15,10,0);c.fill();}
  function star(c,color){const points=[];for(let i=0;i<8;i++){const a=i*Math.PI/4,r=i%2?3:11;points.push([Math.cos(a)*r,Math.sin(a)*r]);}polygon(c,points,color);}
  function claw(c,color){for(let k=-1;k<=1;k++){c.strokeStyle=color;c.lineWidth=2.4;c.beginPath();c.moveTo(-8,k*5+2);c.quadraticCurveTo(0,k*5-4,10,k*4-1);c.stroke();}}
  function skull(c,color){
    c.fillStyle=color;c.beginPath();c.ellipse(0,-1,8,9,0,0,TAU);c.fill();c.fillRect(-5,3,10,7);
    disc(c,-3,-2,2.4,dark);disc(c,3,-2,2.4,dark);polygon(c,[[0,1],[-2,4],[2,4]],dark);
    for(let i=-1;i<=1;i++)stroke(c,[[i*3,7],[i*3,10]],dark,1);
  }
  // Native glyphs face +X. Normal-size silhouettes fit inside the collision disk;
  // only subdued trails/glows may extend outside it. No invisible large hitboxes.
  function glyph(c,motif,x,y,r,angle,color,time=0){
    c.save();c.translate(x,y);c.rotate(angle);c.scale(Math.max(1,r)/12,Math.max(1,r)/12);
    c.setLineDash([]);c.lineJoin='round';c.lineCap='round';c.shadowBlur=0;
    switch(motif){
      case 'bullet':case 'silver_bullet':{
        const silver=motif==='silver_bullet',brass=silver?'#bdcbe0':'#c59b51',shine=silver?'#f5f2ed':'#f0d38b';
        polygon(c,[[-10,-5],[3,-5],[11,0],[3,5],[-10,5]],brass);
        polygon(c,[[3,-5],[11,0],[3,5]],silver?'#eee6dc':'#dce1e1');
        stroke(c,[[-8,-3],[3,-3],[8,0]],shine,1.6);stroke(c,[[-7,-5],[-7,5]],'#6b5943',1.5);
        if(silver){stroke(c,[[-3,-3],[-3,3]],'#68567b',1);stroke(c,[[-5,0],[-1,0]],'#68567b',1);}break;
      }
      case 'sword':case 'blade':case 'bloodblade':case 'saw':case 'bayonet':case 'starblade':case 'glaive':{
        const serrated=motif==='saw',gold=motif==='glaive'?'#d1b876':'#8da8c0';
        polygon(c,[[-6,-3],[5,-3],[12,0],[5,3],[-6,3]],light);
        stroke(c,[[-5,0],[8,0]],color,1.4);stroke(c,[[-6,-6],[-6,6]],gold,2);
        stroke(c,[[-10,0],[-6,0]],'#795d4b',3);
        if(serrated)for(let i=-4;i<6;i+=3)polygon(c,[[i,3],[i+3,3],[i,6]],'#bfc9d2');
        if(motif==='starblade'){star(c,color);stroke(c,[[-5,0],[10,0]],light,1);}
        if(motif==='bloodblade')for(let i=0;i<3;i++)disc(c,-3+i*4,3,1.5,color);
        if(motif==='glaive')polygon(c,[[7,0],[-1,-10],[2,-1],[-1,8]],color);
        break;
      }
      case 'heart':heart(c,color);stroke(c,[[-3,-5],[1,-7]],'#ffdeee',1.5);break;
      case 'kiss':
        polygon(c,[[-11,0],[-4,-5],[0,-3],[4,-5],[11,0],[4,5],[-4,5]],color);
        stroke(c,[[-9,0],[8,0]],'#742c51',1.5);break;
      case 'paw':
        c.fillStyle=color;c.beginPath();c.ellipse(-2,1,7,6,0,0,TAU);c.fill();
        for(const [x,y]of[[6,-6],[9,0],[6,6],[-1,-8]])disc(c,x,y,2.7,color);break;
      case 'fist':
        polygon(c,[[-11,-5],[-5,-5],[-5,-9],[5,-9],[9,-5],[9,5],[3,9],[-5,6],[-11,6]],color);
        for(let y=-6;y<=3;y+=3)stroke(c,[[3,y],[8,y]],'#6c4d47',1.2);
        stroke(c,[[-3,-3],[2,-3],[3,4],[-2,5]],'#6c4d47',1.5);
        stroke(c,[[-10,-4],[-10,5]],'#d4dae5',2.5);break;
      case 'chain':
        for(let i=-1;i<=1;i++){c.save();c.translate(i*7,0);c.rotate(i%2?-.5:.5);c.strokeStyle=color;c.lineWidth=2.2;c.beginPath();c.ellipse(0,0,6,3.5,0,0,TAU);c.stroke();c.restore();}break;
      case 'paper':
        polygon(c,[[-10,-7],[8,-7],[10,-3],[8,8],[-9,7]],'#d8cdb0');
        for(let y=-3;y<5;y+=3)stroke(c,[[-6,y],[4,y]],'#73654e',1);
        disc(c,5,4,3,'#b75d56');stroke(c,[[4,3],[6,5]],'#e5baa1',1);break;
      case 'code':case 'terminal':
        c.fillStyle='#0c2829';c.fillRect(-11,-8,22,16);c.strokeStyle=color;c.lineWidth=1.5;c.strokeRect(-11,-8,22,16);
        if(motif==='terminal'){stroke(c,[[-7,-3],[-3,0],[-7,3]],color,2);stroke(c,[[0,4],[6,4]],color,2);}
        else{stroke(c,[[-3,-4],[-7,0],[-3,4]],color,1.6);stroke(c,[[3,-4],[7,0],[3,4]],color,1.6);stroke(c,[[1,-5],[-1,5]],light,1.2);}break;
      case 'paint':
        c.fillStyle=color;c.beginPath();c.moveTo(11,0);c.bezierCurveTo(-2,-1,-2,-10,-9,-6);c.bezierCurveTo(-15,4,-3,9,11,0);c.fill();
        disc(c,-5,-3,1.6,'#f9cee2');disc(c,-10,5,1.2,color);break;
      case 'paint_claw':case 'claw':claw(c,color);break;
      case 'web':
        for(let j=0;j<6;j++){const b=j*TAU/6;stroke(c,[[0,0],[Math.cos(b)*11,Math.sin(b)*11]],color,1);}
        for(const r of[4,8,11]){const pts=[];for(let j=0;j<=6;j++){const b=j*TAU/6;pts.push([Math.cos(b)*r,Math.sin(b)*r]);}stroke(c,pts,color,.8);}break;
      case 'dust':
        for(const [x,y,r]of[[-7,-4,2],[-3,5,2.8],[5,-3,3],[8,4,1.5]]){
          polygon(c,[[x-r,y],[x,y-r],[x+r,y],[x+r*.5,y+r]],color);
          stroke(c,[[x-r*.5,y],[x,y-r*.6]],'#e3d1a8',.7);
        }break;
      case 'mana':case 'void':
        c.shadowColor=color;c.shadowBlur=7;disc(c,0,0,8,motif==='void'?'#080613':color);circle(c,0,0,10,color,1.4);
        if(motif==='mana'){polygon(c,[[0,-5],[4,0],[0,5],[-4,0]],'#e9fbff');}
        else{c.strokeStyle=color;c.lineWidth=1;c.beginPath();c.ellipse(0,0,11,4,-.5,0,TAU);c.stroke();}break;
      case 'soul':
        c.shadowColor=color;c.shadowBlur=5;c.fillStyle=color;c.beginPath();c.moveTo(-11,0);c.bezierCurveTo(-2,-1,-5,-10,3,-9);c.bezierCurveTo(13,-9,12,8,3,7);c.quadraticCurveTo(-2,3,-11,0);c.fill();disc(c,5,-2,1.7,dark);disc(c,8,1,1.4,dark);break;
      case 'skull':skull(c,'#e3e6d8');break;
      case 'bone':stroke(c,[[-8,0],[8,0]],'#dce4d6',4);for(const x of[-8,8])for(const y of[-2,2])disc(c,x,y,3,'#dce4d6');break;
      case 'holy':
        c.shadowColor=color;c.shadowBlur=6;star(c,color);stroke(c,[[-7,0],[7,0]],light,2);stroke(c,[[0,-9],[0,9]],light,2);circle(c,0,0,6,color,1);break;
      case 'hammer':
        stroke(c,[[-10,0],[7,0]],'#a48456',3);polygon(c,[[1,-9],[10,-7],[10,7],[1,9]],'#ced4cf');
        stroke(c,[[5,-5],[5,5]],color,2);stroke(c,[[3,0],[8,0]],color,2);break;
      case 'shield':polygon(c,[[-8,-10],[8,-10],[9,2],[0,11],[-9,2]],'#6c8ca8');stroke(c,[[-8,-10],[8,-10],[9,2],[0,11],[-9,2]],'#c3d6e6',1.5,true);stroke(c,[[0,-7],[0,6]],light,1);break;
      case 'moon':
        c.fillStyle=color;c.beginPath();c.arc(0,0,10,Math.PI*.15,Math.PI*1.85);c.quadraticCurveTo(-4,0,9,4);c.fill();circle(c,0,0,11,color,.7);break;
      case 'flame':
        c.shadowColor='#f47743';c.shadowBlur=6;c.fillStyle=color;c.beginPath();c.moveTo(11,0);c.bezierCurveTo(1,-9,-2,-2,-11,-9);c.quadraticCurveTo(-4,-1,-10,5);c.quadraticCurveTo(1,11,11,0);c.fill();polygon(c,[[8,0],[-3,-3],[-2,3]],'#ffe1a0');break;
      case 'crystal':polygon(c,[[11,0],[0,-7],[-10,-3],[-5,5],[1,7]],color);stroke(c,[[11,0],[-5,0],[0,-7],[1,7]],'#efffff',1);break;
      case 'spark':polygon(c,[[10,-7],[0,-2],[2,-8],[-10,5],[-1,1],[-2,8]],color);stroke(c,[[-8,5],[0,0],[9,-6]],light,1);break;
      case 'rocket':
        polygon(c,[[-8,-5],[4,-5],[11,0],[4,5],[-8,5]],'#c9d2d6');polygon(c,[[4,-5],[11,0],[4,5]],'#ae635a');
        polygon(c,[[-8,-5],[-11,-9],[-3,-5]],color);polygon(c,[[-8,5],[-11,9],[-3,5]],color);
        polygon(c,[[-8,-3],[-12,0],[-8,3]],'#ffbf69');break;
      case 'train':
        c.fillStyle='#814e3b';c.fillRect(-10,-7,18,12);c.fillStyle='#e8c999';c.fillRect(-6,-5,5,4);c.fillRect(1,-5,4,4);
        polygon(c,[[8,-4],[12,5],[8,5]],'#b9aba1');stroke(c,[[-10,-7],[8,-7]],color,2);
        for(const x of[-6,5]){disc(c,x,7,3,'#233345');circle(c,x,7,2,'#c4b6aa',1);}break;
      case 'card':c.fillStyle='#e4d3b5';c.fillRect(-8,-10,16,20);heart(c,'#a34b63');break;
      default:star(c,color);
    }
    c.restore();
  }
  function forHazard(a,h){
    if(a.cls==='mage'&&a.motif==='soul')return h.motif==='bone'?'bone':h.motif==='skull'?'skull':'soul';
    if(h.motif==='star'&&a.cls==='hunter'&&a.motif==='silver_bullet')return 'silver_bullet';
    return a.motif;
  }
  function trail(c,p,h,g,t,a){
    // A short fading trace, never another projectile or a replacement hit area.
    const E=window.QTEUnique,back=E.geometry(h,Math.max(h.start,t-.045));
    c.save();c.globalAlpha*=.25;c.strokeStyle=a.color;c.lineWidth=Math.max(1,g.r*.6);c.lineCap='round';
    c.beginPath();c.moveTo(back.x,back.y);c.lineTo(g.x,g.y);c.stroke();c.restore();
  }
  function lineArt(c,s,h,g,a,warning){
    const dx=g.bx-g.ax,dy=g.by-g.ay,length=Math.hypot(dx,dy)||1,angle=Math.atan2(dy,dx),r=g.r;
    c.save();c.translate(g.ax,g.ay);c.rotate(angle);c.lineCap='butt';c.setLineDash(warning?[7,6]:[]);
    if(warning){
      stroke(c,[[0,-r],[length,-r]],a.color,1);stroke(c,[[0,r],[length,r]],a.color,1);
      c.globalAlpha*=.16;c.fillStyle=a.color;c.fillRect(0,-r,length,r*2);
    }else{
      // Every pixel in the authoritative collision strip remains visibly filled.
      c.globalAlpha*=.40;c.fillStyle=a.color;c.fillRect(0,-r,length,r*2);c.globalAlpha/= .40;
      const m=a.motif,steel=['sword','blade','bloodblade','bayonet','glaive','saw','starblade'].includes(m);
      if(steel){
        polygon(c,[[0,-r*.6],[length*.75,-r*.48],[length,0],[length*.75,r*.48],[0,r*.6]],'#d7e5ee');
        stroke(c,[[0,-r*.85],[length*.8,-r*.65]],a.color,2);stroke(c,[[0,0],[length,0]],a.color,1);
        if(m==='bloodblade')stroke(c,[[length*.08,r*.35],[length*.7,r*.3]],'#bb4c66',Math.max(2,r*.3));
        if(m==='saw')for(let x=12;x<length;x+=22)polygon(c,[[x,r*.35],[x+13,r*.35],[x+3,r*.85]],'#ccd8df');
      }else if(['claw','paw','paint_claw'].includes(m)){
        for(let j=-1;j<=1;j++){
          c.strokeStyle=j===0?'#ffe0db':a.color;c.lineWidth=Math.max(1,r*.25);c.beginPath();c.moveTo(0,j*r*.6);c.quadraticCurveTo(length*.5,j*r*.6-r*.2,length,j*r*.6);c.stroke();
        }
      }else if(m==='paper'){
        stroke(c,[[0,0],[length,0]],a.color,Math.max(2,r*.7));
        for(let x=30;x<length;x+=75)glyph(c,'paper',x,0,r*.82,0,a.color,s.time);
      }else if(m==='code'||m==='terminal'){
        c.font=`600 ${Math.max(10,r*1.4)}px monospace`;c.fillStyle=a.color;c.textAlign='left';
        for(let x=10;x<length;x+=70)c.fillText(m==='terminal'?'>_ exec':'0xFF',x,r*.45);
        stroke(c,[[0,-r*.7],[length,-r*.7]],a.color,1);
      }else if(m==='paint'){
        for(let j=0;j<4;j++)stroke(c,[[0,(j-1.5)*r*.4],[length,(j-1.5)*r*.38]],j%2?a.color:'#a8517d',Math.max(1,r*.28));
      }else if(m==='spark'){
        // Jagged light is clipped to the existing collision strip, not a new bolt.
        const pts=[];for(let i=0;i<=24;i++)pts.push([length*i/24,Math.sin(i*2.91+s.time*13)*r*.72]);
        stroke(c,pts,a.color,Math.max(3,r*.35));stroke(c,pts,'#f2f7ff',1.3);
      }else if(m==='holy'){
        stroke(c,[[0,0],[length,0]],'#f6efd7',Math.max(2,r*.38));
        for(let x=35;x<length;x+=95){stroke(c,[[x,-r*.7],[x,r*.7]],a.color,2);circle(c,x,0,r*.8,a.color,1);}
      }else if(m==='chain'){
        for(let x=10;x<length;x+=Math.max(16,r*1.4))glyph(c,'chain',x,0,r,0,a.color,s.time);
      }else if(m==='flame'){
        for(let x=10;x<length;x+=28){
          const lean=Math.sin(x*.09+s.time*7)*r*.2;
          c.fillStyle=a.color;c.beginPath();c.moveTo(x-12,r*.7);c.quadraticCurveTo(x+lean,-r*.2,x+8,-r*.85);c.quadraticCurveTo(x+5,r*.2,x+14,r*.7);c.fill();
          stroke(c,[[x-6,r*.5],[x+4,-r*.3]],'#ffe1a0',Math.max(1,r*.12));
        }
      }else{
        stroke(c,[[0,0],[length,0]],a.color,Math.max(2,r*.4));
        // Dark/mana beam filaments; stays within the solid attack footprint.
        for(let j=-1;j<=1;j++){const pts=[];for(let i=0;i<=20;i++)pts.push([length*i/20,Math.sin(i*.8+s.time*6+j)*r*.6]);stroke(c,pts,j===0?light:a.color,1);}
      }
    }
    c.restore();
  }
  function hazard(c,s,h,g,flags){
    const a=appearance(s.p);if(!a||h.uniform||h.visualOnly)return false;
    const {warning}=flags,t=s.time;c.save();c.strokeStyle=a.color;c.fillStyle=a.color;c.shadowBlur=0;
    if(h.type==='bullet'){
      if(warning){
        // Keep the engine's exact direction/orbit preview and add art only at spawn.
        c.restore();return false;
      }
      trail(c,s.p,h,g,t,a);
      glyph(c,forHazard(a,h),g.x,g.y,g.r,Math.atan2(g.vy,g.vx),a.color,t);
      // Don't enclose physical objects in a bright circle: that turns a cartridge
      // back into the very same "dot" the art is meant to replace. The object is
      // inscribed in its original collision disk; faint trails do not deal damage.
      if(['mana','void','soul','holy'].includes(a.motif))circle(c,g.x,g.y,g.r,a.color,.7);
      if(['heavy','critical'].includes(h.tier)){
        c.save();c.translate(g.x,g.y);c.rotate(Math.atan2(g.vy,g.vx));
        stroke(c,[[-g.r*.75,-g.r*.65],[g.r*.4,-g.r*.65]],'#efca8c',1.3);c.restore();
      }
    }else if(h.type==='line')lineArt(c,s,h,g,a,warning);
    else if(h.type==='ring'){
      c.setLineDash(warning?[5,5]:[]);c.lineWidth=warning?2:g.thickness*2;
      c.beginPath();c.arc(g.x,g.y,warning?h.r:g.r,g.gap+g.gapWidth/2,g.gap+TAU-g.gapWidth/2);c.stroke();
      if(!warning){c.lineWidth=1;c.strokeStyle=light;c.stroke();}
    }else if(h.type==='circle'||h.type==='well'){
      c.setLineDash(warning?[5,5]:[]);circle(c,g.x,g.y,g.r,a.color,warning?1.5:2);
      c.save();c.globalAlpha*=warning?.07:.18;disc(c,g.x,g.y,g.r,a.color);c.restore();c.setLineDash([]);
      if(h.type==='well'){
        disc(c,g.x,g.y,g.r*.72,'#080713');
        for(let j=0;j<3;j++){c.save();c.translate(g.x,g.y);c.rotate(t*.8+j*TAU/3);c.strokeStyle=a.color;c.lineWidth=1.5;c.beginPath();c.ellipse(0,0,g.r*.94,g.r*.35,0,0,TAU);c.stroke();c.restore();}
      }else if(!warning){
        if(a.motif==='paint'){
          for(let j=0;j<9;j++){const b=j*2.4,rr=g.r*(.25+(j%3)*.21);disc(c,g.x+Math.cos(b)*rr,g.y+Math.sin(b)*rr,g.r*(.06+(j%2)*.025),j%3?a.color:'#f4b0a6');}
        }else if(['flame','rocket'].includes(a.motif)){
          // A burning floor, not a single "fire icon" in a generic circular zone.
          for(let j=0;j<7;j++){
            const b=j*2.4,rr=g.r*(j? .46:0),size=g.r*(.25+.035*Math.sin(t*9+j*1.7));
            glyph(c,'flame',g.x+Math.cos(b)*rr,g.y+Math.sin(b)*rr,size,-Math.PI/2,a.color,t);
          }
        }else if(['fist','shield','claw','paint_claw'].includes(a.motif)){
          for(let j=0;j<7;j++){
            const b=j*TAU/7,rr=g.r*.86;
            stroke(c,[[g.x+Math.cos(b)*g.r*.2,g.y+Math.sin(b)*g.r*.2],[g.x+Math.cos(b+.15)*rr*.64,g.y+Math.sin(b+.15)*rr*.64],[g.x+Math.cos(b)*rr,g.y+Math.sin(b)*rr]],a.color,1.2);
          }
          glyph(c,a.motif,g.x,g.y,Math.min(23,g.r*.5),-Math.PI/2,a.color,t);
        }else{
          glyph(c,a.motif,g.x,g.y,Math.min(23,g.r*.5),-Math.PI/2,a.color,t);
          for(let j=0;j<8;j++){const b=j*TAU/8+t*.25;stroke(c,[[g.x+Math.cos(b)*g.r*.88,g.y+Math.sin(b)*g.r*.88],[g.x+Math.cos(b)*g.r*.97,g.y+Math.sin(b)*g.r*.97]],a.color,1);}
        }
      }
    }else if(h.type==='rect'){
      c.setLineDash(warning?[5,5]:[]);c.lineWidth=1.5;c.strokeRect(g.x,g.y,g.w,g.h);
      c.save();c.globalAlpha*=warning?.07:.23;c.fillRect(g.x,g.y,g.w,g.h);c.restore();
      if(!warning){
        c.save();c.beginPath();c.rect(g.x,g.y,g.w,g.h);c.clip();
        for(let y=g.y+22;y<g.y+g.h;y+=45)for(let x=g.x+23;x<g.x+g.w;x+=60)glyph(c,a.motif,x,y,10,0,a.color,t);
        c.restore();
      }
      if(h.label){c.font='12px sans-serif';c.textAlign='left';c.fillText(h.label,g.x+5,g.y+17);}
    }else{c.restore();return false;}
    c.restore();return true;
  }
  function block(c,s,e,v){
    const a=appearance(s.p);if(!a)return false;
    const cx=360,cy=200,r=162-v*113,angle=e.angle,t=s.time;
    c.save();c.setLineDash([]);c.strokeStyle=a.color;c.fillStyle=a.color;
    if(e.kind==='wave'){
      circle(c,cx,cy,155-v*107,a.color,4);
      for(let i=0;i<8;i++){const b=i*TAU/8;glyph(c,a.motif,cx+Math.cos(b)*r,cy+Math.sin(b)*r,10,b+Math.PI,a.color,t);}
      c.font='500 14px sans-serif';c.textAlign='center';c.fillText('ВОЛНА · ПОДНИМИ БЛОК',cx,309);
    }else{
      c.save();c.globalAlpha*=.3;c.setLineDash([4,6]);stroke(c,[[cx+Math.cos(angle)*162,cy+Math.sin(angle)*162],[cx+Math.cos(angle)*52,cy+Math.sin(angle)*52]],a.color,1);c.restore();
      // Preserve the gold direction marker regardless of class palette.
      c.lineWidth=4;c.strokeStyle=e.tier==='minor'?'#a4bfd0':'#f2cb87';c.beginPath();c.arc(cx,cy,54,angle-.09,angle+.09);c.stroke();
      glyph(c,a.motif,cx+Math.cos(angle)*r,cy+Math.sin(angle)*r,e.tier==='minor'?10:15,angle+Math.PI,a.color,t);
    }
    c.restore();return true;
  }
  function attack(c,s,frame){
    const a=appearance(s.p);if(!a||frame.phase==='ready')return;
    // Weapon medallions outside all timing zones; gold hit and pink crit remain
    // authoritative. Do not put decorative moving projectiles on the timing bar.
    c.save();c.globalAlpha=.85;
    for(const x of[112,608]){
      circle(c,x,63,20,a.color,1);glyph(c,a.motif,x,63,13,x<360?0:Math.PI,a.color,s.time);
    }
    // Replace programmer text in other classes with their own vocabulary.
    c.restore();
  }
  function field(c,s,height=320){
    const a=appearance(s.p);if(!a)return;
    c.save();c.globalAlpha=.6;c.fillStyle=a.color;c.fillRect(0,0,4,28);c.fillRect(716,height-28,4,28);c.restore();
  }
  window.QTEArt={appearance,glyph,hazard,block,attack,field,themes:THEMES};
})();
