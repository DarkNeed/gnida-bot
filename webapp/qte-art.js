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
    assassin:['dagger','#a895c8','Кинжалы, дым и вскрытые раны'],
    cultist:['void','#b995eb','Печати и запретные обряды'],
    gambler:['card','#edc581','Карты, кости и рулетка'],
  };
  const CULT={
    cult_sign:['cult_eye','#d1a4ed','КОЩУНСТВЕННЫЙ ЗНАК','#100d19'],
    cult_voice:['cult_echo','#d0b8d8','ГОЛОС ИЗ-ЗА ГРАНИ','#131015'],
    cult_rite:['cult_wax','#ffc381','ЗАПРЕТНЫЙ ОБРЯД','#030303'],
    cult_depths:['cult_wraith','#92a89e','ШЁПОТ ЗАТОНУВШЕГО ГОРОДА','#07141b'],
    arch_cultist_cthulhu:['cult_tide','#91e3d8','ПРОБУЖДЕНИЕ Р’ЛЬЕХА','#061c26'],
    arch_cultist_yog:['cult_sphere','#b6a5ff','СХОДЯЩИЕСЯ СФЕРЫ','#0d102b'],
    cult_roots:['cult_root','#b5c997','КОРНИ ЧЁРНОГО КОЗЛА','#223026'],
    cult_yellow:['cult_mask','#efd076','ЖЁЛТЫЙ ЗНАК','#1b130c'],
    arch_cultist_hastur:['cult_actor','#dfb15d','ВТОРОЙ АКТ КАРКОЗЫ','#1c1017'],
  };
  function appearance(p){
    const sk=p.skill||{},cls=sk.class_id,base=THEMES[cls];
    if((sk.base_id||'').startsWith('guild_chest_'))return {cls:'chest_mimic',motif:sk.base_id.includes('coins')?'chest_coin':sk.base_id.endsWith('tongue')?'chest_tongue':sk.base_id.endsWith('devour')?'chest_mouth':'chest_teeth',color:'#daaab1',label:'НЕНАСЫТНАЯ СОКРОВИЩНИЦА'};
    if(sk.mimic)return {cls,motif:({slash:'claw',stars:'crystal',mirror:'crystal',gun:'bullet',mana:'orb',void:'orb'})[p.kind]||'crystal',color:'#f061a2',label:'ГОЛОДНОЕ ОТРАЖЕНИЕ'};
    // Bespoke boss/casino presentations remain in their own renderers. A borrowed
    // boss ability keeps its native appearance even in an RP character's loadout.
    if(!base||p.chaplain||p.kit||p.kind?.startsWith('casino_')||window.NazarickQTE?.identity(p))return null;
    const n=(sk.name+' '+(sk.base_id||'')).toLowerCase(),kind=p.kind;
    let [motif,color,label]=base;
    if(cls==='cultist'&&Object.hasOwn(CULT,sk.base_id)){
      const [motif,color,label,ground]=CULT[sk.base_id];
      return {cls,motif,color,label,ground};
    }
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
    else if(cls==='assassin'){
      motif=kind==='thrust'?'needle':/дым|уход/.test(n)?'smoke':/нить|рана/.test(n)?'bloodblade':'dagger';
      color=motif==='smoke'?'#aab1c8':motif==='needle'?'#b9c7e2':'#b75c79';
    }
    if(cls==='mage'||cls==='priest'){
      if(kind==='void'){motif='void';color='#bc9ae8';}
      else if(kind==='death'){motif='soul';color='#84bba0';}
      else if(kind==='fire'){motif='flame';color='#f1a06e';}
      else if(kind==='ice'){motif='crystal';color='#a0e0f1';}
      else if(kind==='lightning'){motif='spark';color='#c3b6ff';}
      else if(cls==='priest')motif=kind==='thrust'?'glaive':kind==='impact'?'hammer':'holy';
    }
    if(sk.base_id==='guild_net'){motif='web';color='#d5cddb';}
    if((sk.base_id||'').startsWith('guild_')){
      motif=({death:'soul',fire:'flame',ice:'crystal',lightning:'spark',beast:'claw',slash:'blade',impact:'shield',paint:'paint',mana:'mana'})[kind]||motif;
      if(sk.base_id==='guild_net')motif='web';
      color=kind==='paint'?'#a9bc75':color;
    }
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
      case 'cult_ink':case 'cult_eye':
        c.fillStyle='#1e102b';c.strokeStyle=color;c.lineWidth=1.4;c.beginPath();c.moveTo(-11,0);c.quadraticCurveTo(0,-13,11,0);c.quadraticCurveTo(0,13,-11,0);c.fill();c.stroke();
        disc(c,0,0,3.8,color);polygon(c,[[0,-4],[1.6,0],[0,4],[-1.6,0]],dark);
        break;
      case 'cult_echo':
        for(let k=-2;k<=2;k++){
          const y=k*3,A=Math.sin(time*3+k)*1.8;
          stroke(c,[[-11,y],[-5,y+A],[-2,y-4],[1,y+3],[4,y+A],[11,y]],k%2?'#81647e':color,k===0?1.55:.9);
        }
        break;
      case 'cult_wraith':
        c.beginPath();c.moveTo(-12,-9);c.bezierCurveTo(-2,-5,0,-12,5,-8);
        c.bezierCurveTo(12,-6,13,4,7,8);c.bezierCurveTo(1,12,-3,5,-11,10);
        c.quadraticCurveTo(-4,2,-10,1);c.quadraticCurveTo(-5,-3,-12,-9);c.closePath();
        c.fillStyle='#050c10';c.fill();
        c.beginPath();c.moveTo(-9,-8);c.bezierCurveTo(-2,-3,0,-10,5,-7);
        c.bezierCurveTo(11,-5,11,4,6,7);c.bezierCurveTo(1,10,-2,4,-7,8);
        c.strokeStyle=color;c.lineWidth=.92;c.stroke();
        stroke(c,[[3,-3],[5,-2],[2,-1]],'#c1c3a5',.8);stroke(c,[[2,2],[5,3],[3,4]],'#758e81',.8);
        break;
      case 'cult_wax':case 'cult_altar':{
        const lean=Math.sin(time*13+x*.17)*2;
        polygon(c,[[-5,10],[-5,-1],[-2,0],[0,-1],[4,-1],[5,10]],'#814934');
        polygon(c,[[-4,8],[-4,-1],[-2,0],[0,-1],[3,-.8],[2,7],[1,3],[-.5,8]],'#e7b885');
        stroke(c,[[0,0],[0,-2.6]],'#eddeab',.85);
        c.fillStyle='#e67d3b';c.beginPath();c.moveTo(-3,-5);c.quadraticCurveTo(-3,-8,lean,-12);c.quadraticCurveTo(6,-5,2,-3);c.quadraticCurveTo(0,-2,-3,-5);c.fill();
        c.fillStyle='#fff1b0';c.beginPath();c.ellipse(.3,-5,1.65,2.7,-lean*.12,0,TAU);c.fill();
        break;
      }
      case 'cult_limb':case 'cult_tide':
        c.strokeStyle=color;c.lineWidth=3;c.beginPath();c.moveTo(-10,5);c.bezierCurveTo(-4,-10,0,9,7,3);c.quadraticCurveTo(12,-1,8,-5);c.stroke();
        for(const [dx,dy] of [[-7,1],[-4,-1],[1,1],[5,4]])disc(c,dx,dy,1.45,light);
        break;
      case 'cult_root':
        polygon(c,[[-9,4],[-6,-4],[1,-7],[10,0],[1,7]],'#435138');
        stroke(c,[[-8,0],[2,1],[9,0]],color,1.8);
        for(const a of [-1,1])stroke(c,[[-1,0],[-3,a*4],[2,a*6]],light,1);
        break;
      case 'cult_sphere':
        disc(c,0,0,9,'#29214d');circle(c,0,0,9,color,1.2);
        for(let j=0;j<3;j++){const a=time*2+j*TAU/3;disc(c,Math.cos(a)*7,Math.sin(a)*7,2.2,light);}
        break;
      case 'cult_comet':
        stroke(c,[[-11,2],[-3,1],[8,0]],color,2.5);disc(c,5,0,4.6,'#f7d2ac');circle(c,5,0,5.5,color,1.1);
        break;
      case 'cult_actor':case 'cult_stage':case 'cult_reprise':
        c.beginPath();c.moveTo(0,-11);c.quadraticCurveTo(7,-11,8,-3);
        c.bezierCurveTo(9,2,8,7,12,11);c.quadraticCurveTo(5,7,0,10);
        c.quadraticCurveTo(-6,12,-11,10);c.quadraticCurveTo(-7,3,-8,-3);
        c.quadraticCurveTo(-8,-10,0,-11);c.fillStyle='#281b22';c.fill();
        c.strokeStyle=color;c.lineWidth=1.05;c.stroke();
        polygon(c,[[-5,-5],[4,-6],[5,-3],[3,3],[0,6],[-3,3]],'#e2c1a2');
        stroke(c,[[-3,-2],[-1,-1]],'#33232a',1.1);stroke(c,[[3,-3],[1,-1]],'#33232a',1.1);
        stroke(c,[[1,-5],[0,-1],[1,0],[0,2]],'#815958',.68);
        break;
      case 'cult_curtain':
        polygon(c,[[-10,-9],[10,-9],[8,9],[3,6],[-3,10],[-10,8]],'#682c40');
        for(const x of [-7,-2,3,7])stroke(c,[[x,-8],[x-1,1],[x,6]],color,1);
        stroke(c,[[-10,-9],[10,-9]],'#e8bb87',1.1);
        break;
      case 'cult_mask':case 'cult_hollow':{
        const ghost=motif==='cult_hollow',ink=ghost?'#88766a':color;
        c.beginPath();c.moveTo(-10,-7);c.quadraticCurveTo(-5,-12,-1,-9);c.quadraticCurveTo(5,-12,10,-6);
        c.bezierCurveTo(8,5,5,8,0,12);c.bezierCurveTo(-7,7,-8,4,-10,-7);c.closePath();
        c.fillStyle=ghost?'#201b19':'#906745';c.fill();c.strokeStyle=ink;c.lineWidth=1.1;c.stroke();
        polygon(c,[[-6,-4],[-2,-3],[-2,-1],[-5,-2]],ghost?'#191918':'#ffdf91');
        polygon(c,[[6,-4],[2,-3],[2,-1],[5,-2]],ghost?'#191918':'#ffdf91');
        stroke(c,[[5,-9],[3,-5],[5,-3],[4,1],[8,4]],'#51382b',.85);
        stroke(c,[[-3,6],[1,4],[3,6]],'#322319',1.3);
        break;
      }
      case 'chest_coin':
        c.save();c.scale(.55+.35*Math.abs(Math.sin(time*11)),1);disc(c,0,0,10,'#c8b480');circle(c,0,0,8,'#fff0b9',1.3);stroke(c,[[0,-5],[0,5]],'#6a583c',2);stroke(c,[[-3,-3],[3,-3],[-3,3],[3,3]],'#f3dda1',1);c.restore();break;
      case 'chest_teeth':
        polygon(c,[[-10,-8],[9,-8],[9,-4],[-10,-4]],'#773f51');polygon(c,[[-9,-4],[-3,5],[0,-4]],'#f1e7cb');polygon(c,[[0,-4],[6,7],[9,-4]],'#e3d5b5');break;
      case 'chest_tongue':
        stroke(c,[[-10,0],[-2,-3],[7,-2],[10,1]],'#a85270',8);stroke(c,[[-9,-1],[-1,-4],[6,-3]],'#e7a8b9',1.3);break;
      case 'chest_mouth':
        c.fillStyle='#1b0c18';c.beginPath();c.ellipse(0,0,11,8,0,0,TAU);c.fill();circle(c,0,0,10,'#b78089',1);for(let j=-1;j<=1;j++){polygon(c,[[j*6-3,-6],[j*6+2,-6],[j*6,0]],'#ede0c4');polygon(c,[[j*6-3,6],[j*6+2,6],[j*6,2]],'#ede0c4');}break;
      case 'chest_splinter':
        polygon(c,[[-10,-3],[2,-5],[11,0],[-3,4]],'#9d7758');stroke(c,[[-7,-1],[6,0]],'#dac2a1',1);break;
      case 'bullet':case 'silver_bullet':{
        const silver=motif==='silver_bullet',brass=silver?'#bdcbe0':'#c59b51',shine=silver?'#f5f2ed':'#f0d38b';
        polygon(c,[[-10,-5],[3,-5],[11,0],[3,5],[-10,5]],brass);
        polygon(c,[[3,-5],[11,0],[3,5]],silver?'#eee6dc':'#dce1e1');
        stroke(c,[[-8,-3],[3,-3],[8,0]],shine,1.6);stroke(c,[[-7,-5],[-7,5]],'#6b5943',1.5);
        if(silver){stroke(c,[[-3,-3],[-3,3]],'#68567b',1);stroke(c,[[-5,0],[-1,0]],'#68567b',1);}break;
      }
      case 'sword':case 'blade':case 'bloodblade':case 'saw':case 'bayonet':case 'starblade':case 'glaive':case 'dagger':{
        const serrated=motif==='saw',gold=motif==='glaive'?'#d1b876':'#8da8c0';
        polygon(c,[[-6,-3],[motif==='dagger'?1:5,-3],[12,0],[motif==='dagger'?1:5,3],[-6,3]],light);
        stroke(c,[[-5,0],[8,0]],color,1.4);stroke(c,[[-6,-6],[-6,6]],gold,2);
        stroke(c,[[-10,0],[-6,0]],'#795d4b',3);
        if(serrated)for(let i=-4;i<6;i+=3)polygon(c,[[i,3],[i+3,3],[i,6]],'#bfc9d2');
        if(motif==='starblade'){star(c,color);stroke(c,[[-5,0],[10,0]],light,1);}
        if(motif==='bloodblade')for(let i=0;i<3;i++)disc(c,-3+i*4,3,1.5,color);
        if(motif==='glaive')polygon(c,[[7,0],[-1,-10],[2,-1],[-1,8]],color);
        break;
      }
      case 'needle':{
        stroke(c,[[-11,0],[10,0]],'#dbe6f6',2);disc(c,10,0,2,color);stroke(c,[[-6,-2],[-6,2]],color,1.4);break;
      }
      case 'smoke':{
        for(const [x,y,r]of[[-7,2,4],[-1,-3,5],[6,1,4]]){c.globalAlpha=.35;disc(c,x,y,r,color);}c.globalAlpha=1;break;
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
    if(a.cls==='chest_mimic'&&h.motif)return h.motif;
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
      if(a.motif==='chest_teeth'){
        c.globalAlpha/= .16;
        for(let x=14;x<length;x+=30)glyph(c,'chest_teeth',x,0,Math.min(10,r),0,a.color,s.time);
        // The inward arrow explains the jaw's coming movement, not a hitbox.
        const vx=(h.chestMoveX||0)*Math.cos(angle)+(h.chestMoveY||0)*Math.sin(angle),vy=-(h.chestMoveX||0)*Math.sin(angle)+(h.chestMoveY||0)*Math.cos(angle),len=Math.hypot(vx,vy)||1;
        const dx=vx/len*22,dy=vy/len*22;
        stroke(c,[[length/2,0],[length/2+dx,dy]],a.color,1.5);
        const tip=Math.atan2(dy,dx);stroke(c,[[length/2+dx-7*Math.cos(tip-.5),dy-7*Math.sin(tip-.5)],[length/2+dx,dy],[length/2+dx-7*Math.cos(tip+.5),dy-7*Math.sin(tip+.5)]],a.color,1.5);
      }
    }else{
      // Every pixel in the authoritative collision strip remains visibly filled.
      c.globalAlpha*=.40;c.fillStyle=a.color;c.fillRect(0,-r,length,r*2);c.globalAlpha/= .40;
      const m=a.motif,steel=['sword','blade','bloodblade','bayonet','glaive','saw','starblade','dagger'].includes(m);
      if(steel){
        polygon(c,[[0,-r*.6],[length*.75,-r*.48],[length,0],[length*.75,r*.48],[0,r*.6]],'#d7e5ee');
        stroke(c,[[0,-r*.85],[length*.8,-r*.65]],a.color,2);stroke(c,[[0,0],[length,0]],a.color,1);
        if(m==='bloodblade')stroke(c,[[length*.08,r*.35],[length*.7,r*.3]],'#bb4c66',Math.max(2,r*.3));
        if(m==='saw')for(let x=12;x<length;x+=22)polygon(c,[[x,r*.35],[x+13,r*.35],[x+3,r*.85]],'#ccd8df');
      }else if(m==='cult_root'){
        const points=[];for(let x=0;x<=length;x+=12)points.push([x,Math.sin(x*.13)*r*.47]);
        stroke(c,points,'#4c5940',Math.max(3,r*.85));stroke(c,points,a.color,1.35);
        for(let x=12;x<length;x+=25){const y=Math.sin(x*.13)*r*.47;stroke(c,[[x,y],[x+8,y-r*.62]],a.color,1.3);}
      }else if(m==='chest_teeth'){
        for(let x=0;x<length;x+=30){polygon(c,[[x,-r*.9],[x+23,-r*.9],[x+12,r*.85]],'#eee0c5');stroke(c,[[x,-r],[x+23,-r]],'#8f4f61',2);}
      }else if(m==='chest_tongue'){
        stroke(c,[[0,0],[length,0]],'#9f4764',Math.max(3,r*1.5));stroke(c,[[0,-r*.3],[length,-r*.3]],'#e6a1b2',Math.max(1,r*.17));disc(c,length-r,0,r*.75,'#c66e87');
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
  function cultHazard(c,s,h,g,{warning,spent},a){
    if(a.cls!=='cultist'||!h.motif?.startsWith('cult_'))return false;
    const E=window.QTEUnique,t=s.time,color=a.color;
    c.save();c.shadowBlur=0;c.strokeStyle=color;c.fillStyle=color;
    const path=(coordinates,ink=color,width=1)=>stroke(c,coordinates,ink,width);
    if(h.type==='bullet'){
      if(h.motif==='cult_wax'){
        // Candles are tangible objects, never dots, rings, or trajectory previews.
        if(h.riteOut&&warning){c.restore();return true;}
        if(h.riteOut){
          const back=E.geometry(h,Math.max(h.start,t-.036));
          c.save();c.globalAlpha*=.22;glyph(c,'cult_wax',back.x,back.y,g.r*.9,0,'#d76c45',t);c.restore();
        }
        c.globalAlpha*=warning?.54+.22*Math.abs(Math.sin(t*9+h.x)):.98;
        glyph(c,'cult_wax',g.x,g.y,g.r*1.15,0,color,t);c.restore();return true;
      }
      if(h.motif==='cult_mask'||h.motif==='cult_wraith'){
        const mask=h.motif==='cult_mask',ghost=h.visualOnly;
        const angle=mask?Math.sin(t*4+h.x*.038)*.14:Math.atan2(g.vy,g.vx);
        c.setLineDash([]);
        if(warning){
          c.globalAlpha*=ghost?.32:.61;
          // A figure seen just beneath the surface, not a traced trajectory.
          glyph(c,mask?'cult_hollow':'cult_wraith',g.x,g.y,g.r*1.04,angle,mask?color:'#637a76',t);
          if(mask&&!ghost&&h.start-t<.24){
            c.globalAlpha*=1.45;glyph(c,'cult_mask',g.x,g.y,g.r*1.04,angle,color,t);
          }
        }else{
          c.save();c.globalAlpha*=ghost?.23:.24;
          const echo=E.geometry(h,Math.max(h.start,t-.079));
          glyph(c,mask?'cult_hollow':'cult_wraith',echo.x,echo.y+5,g.r*1.15,angle,mask?'#b3786a':'#477b72',t);
          c.restore();
          c.globalAlpha*=ghost?.43:1;
          glyph(c,mask?(ghost?'cult_hollow':'cult_mask'):'cult_wraith',g.x,g.y,g.r*1.08,angle,
            mask?(ghost?'#89736b':'#ffe1a4'):(ghost?'#3c635a':color),t);
        }
        c.restore();return true;
      }
      if(h.cultVine){
        const theta=Math.atan2(g.vy,g.vx),nx=-Math.sin(theta),ny=Math.cos(theta);
        if(warning){
          c.globalAlpha*=.57+.23*Math.sin(t*13);glyph(c,'cult_root',h.x+g.vx*.055,h.y+g.vy*.055,13,theta,color,t);
          path([[h.x-nx*15,h.y-ny*15],[h.x+nx*15,h.y+ny*15]],'#a29c6d',2.8);
        }else{
          const v=[[h.x,h.y],...(h.vineTrail||[]),[g.x,g.y]];
          c.lineJoin='round';c.lineCap='round';path(v,'#98a17b',h.vineBody*2);path(v,'#070908',h.vineBody*1.58);
          for(const [x,y,qx,qy] of h.vineBranches||[]){
            path([[x,y],[qx,qy]],'#899777',h.vineTwig*2);
            path([[x,y],[qx,qy]],'#070908',h.vineTwig*1.32);
          }
          // The rim encloses the actual trunk and branch colliders.
          c.translate(g.x,g.y);c.rotate(theta);
          polygon(c,[[-15,-8],[-12,0],[-16,8],[-6,4],[1,8],[8,0],[1,-8],[-6,-4]],'#c1ca9e');
          polygon(c,[[-11,-4],[-4,0],[-11,4],[2,4],[6,0],[2,-4]],'#101611');
        }
        c.restore();return true;
      }
      if(h.gate_show&&(!warning||h.start-t<.53)){
        c.save();c.globalAlpha*=warning?.92:.65;
        for(const [x,y,col] of [[h.gate_x,h.gate_y,'#e7b183'],[h.x,h.y,color]]){
          disc(c,x,y,16,'#0a0916');
          for(let k=0;k<3;k++){
            c.strokeStyle=k===2?'#e9d8ff':col;c.lineWidth=k===2?1:1.6;c.beginPath();
            c.ellipse(x,y,25-3*k,12+3*k,t*.6+k*TAU/3,0,TAU);c.stroke();
          }
          disc(c,x,y,2.4,'#fcebd6');
        }
        c.restore();
      }
      if(warning){
        if(h.motif==='cult_sphere'||h.motif==='cult_comet'){
          if(h.motif==='cult_comet'&&h.start-t<.28)glyph(c,h.motif,g.x,g.y,h.r,Math.atan2(h.vy,h.vx),color,t);
          c.restore();return true;
        }
        const points=[];
        for(let n=0;n<=9;n++){
          const v=E.geometry(h,h.start+n*Math.min(h.end-h.start,h.crossing??.44)/9);
          points.push([v.x,v.y]);
        }
        c.globalAlpha*=.62;c.setLineDash([2,9]);
        path(points,h.reprise?'#d29a9b':color,h.replay_x==null?1:1.65);c.globalAlpha/=.62;
        if(h.replay_x!=null){
          c.save();c.translate(h.replay_x,h.replay_y);path([[-10,-10],[10,10],[-10,10],[10,-10]],h.reprise?'#d29a9b':color,1.3);c.restore();
        }
        glyph(c,h.motif,h.x,h.y,h.r,Math.atan2(h.vy,h.vx),color,t);
      }else{
        trail(c,s.p,h,g,t,a);
        if(h.motif==='cult_actor'){
          const angle=Math.atan2(g.vy,g.vx),tail=[g.x-Math.cos(angle)*h.length,g.y-Math.sin(angle)*h.length];
          c.lineCap='round';path([tail,[g.x,g.y]],h.reprise?'#823b4b':'#6e4634',g.r*1.5);
          glyph(c,h.motif,g.x,g.y,g.r*1.22,0,h.reprise?'#eec3be':color,t);
        }else glyph(c,h.motif,g.x,g.y,g.r,Math.atan2(g.vy,g.vx),color,t);
      }
    }else if(h.drapeBank!==undefined){
      const side=h.drapeBank?-1:1;
      if(warning){
        const edge=h.drapeBank?720:0,halo=c.createLinearGradient(edge,0,edge+side*62,0);
        halo.addColorStop(0,'#a44d6aab');halo.addColorStop(1,'#44203400');
        c.fillStyle=halo;c.fillRect(Math.min(edge,edge+side*62),0,62,320);
        path([[h.drapeEdge,251],[h.drapeEdge,305]],'#dcab82',1.8);
        polygon(c,[[h.drapeEdge-6,304],[h.drapeEdge+6,304],[h.drapeEdge,312]],'#e3bb91');
      }else if(g.w>0){
        if(spent&&!h.disabled)c.globalAlpha=.44;
        const hem=h.drapeBank?g.x:g.x+g.w,ink=c.createLinearGradient(hem,0,hem-side*Math.max(g.w,1),0);
        ink.addColorStop(0,'#903b58');ink.addColorStop(.34,'#542333');ink.addColorStop(1,'#2b1728');
        c.save();c.beginPath();c.rect(g.x,0,g.w,320);c.clip();c.fillStyle=ink;c.fillRect(g.x,0,g.w,320);
        for(let n=10;n<g.w+30;n+=25){
          const x=hem-side*n,bend=5+7*Math.sin(t*7+n*.14);
          c.beginPath();c.moveTo(x,0);c.bezierCurveTo(x+side*bend,89,x-side*bend,222,x,320);
          c.lineWidth=6;c.strokeStyle='#251323';c.stroke();c.lineWidth=1;c.strokeStyle='#c0737c';c.stroke();
        }
        c.restore();path([[hem,0],[hem,320]],'#d8a57b',2.4);
      }
    }else if(h.type==='line'){
      if(h.motif==='cult_ink'){
        const dx=g.bx-g.ax,dy=g.by-g.ay,reach=Math.hypot(dx,dy);
        c.translate(h.ax,h.ay);c.rotate(warning?Math.atan2(h.by-h.ay,h.bx-h.ax):Math.atan2(dy,dx));
        if(warning){
          c.globalAlpha*=.51;c.setLineDash([4,6]);path([[8,0],[151,0]],color,1.3);
          c.setLineDash([]);const turn=h.clockTurn*.56;
          c.beginPath();c.arc(0,0,144,Math.min(0,turn),Math.max(0,turn));c.stroke();
        }else if(reach>1){
          const r=g.r;polygon(c,[[0,-r],[reach*.45,-r*.85],[reach*.77,-r],[reach,0],[reach*.77,r],[reach*.45,r*.85],[0,r]],'#5d3675');
          path([[0,0],[reach*.42,-r*.55],[reach*.63,r*.5],[reach*.86,-r*.38],[reach,0]],'#f3d7fe',1.7);
          for(let x=24;x<reach-5;x+=21)path([[x-4,-r*.65],[x+3,0],[x-4,r*.65]],'#d49ded',1.2);
        }
      }else{c.restore();return false;}
    }else if(h.type==='polyline'&&h.fold){
      const wave=warning?E.geometry(h,h.start+.13).points:g.points,shift=Math.sign(h.fold[3]);
      c.setLineDash([]);c.lineJoin='round';c.lineCap='round';
      if(!warning)path(wave,h.tone?'#64455d':'#493a4e',g.r*1.8);
      for(let j=-1;j<=1;j++){
        const fragment=wave.map(([x,y],n)=>[x,y+shift*(j*5+3*Math.sin(t*9+n*1.9+j))]);
        c.setLineDash(j===0?[]:[5+(j+1)*2,7]);
        path(fragment,j===0?color:'#a983a2',warning?1:1.55);
      }
      c.setLineDash([]);
      if(!warning)for(let n=1;n<wave.length;n++){
        const [x,y]=wave[n];stroke(c,[[x-7,y+shift*5],[x+3,y+shift*5],[x+10,y+shift*9]],'#d6bfd047',1.25);
      }
    }else if(h.tideBank!==undefined){
      if(warning){
        if(h.start-t<.64){
          const edge=h.cultSlide>0?0:720,inside=edge+Math.sign(h.cultSlide)*65;
          const mist=c.createLinearGradient(edge,0,inside,0);
          mist.addColorStop(0,'#a5dacc70');mist.addColorStop(1,'#07435000');
          c.fillStyle=mist;c.fillRect(Math.min(edge,inside),g.y,65,g.h);
        }
      }
      else{
        const direction=Math.sign(h.cultSlide), crest=g.points;
        c.setLineDash([]);c.lineJoin='round';c.lineCap='round';
        path(crest,'#183a4d',g.r*1.94);
        path(crest.map(([x,y])=>[x+direction*7,y]),'#2f6171',g.r*1.12);
        const foam=crest.flatMap(([x,y],i)=>{
          if(i===crest.length-1)return [[x+direction*14,y]];
          const [nx,ny]=crest[i+1];
          return [0,1,2,3].map(n=>[x+(nx-x)*n/4+direction*(12+4*Math.sin(y*.27+n*1.3-t*21)),y+(ny-y)*n/4]);
        });
        path(foam,h.tidePhase?'#9dcbc9':'#c4e6da',2.5);
        for(let n=0;n<foam.length;n+=2){
          const [x,y]=foam[n],drift=8+5*Math.sin(t*12+n);
          path([[x-direction*(drift+8),y+2],[x-direction*drift,y]],'#9aebd084',1.1);
        }
      }
    }else if(h.type==='well'&&h.motif==='cult_sink'){
      c.translate(g.x,g.y);c.setLineDash([]);
      const shade=c.createRadialGradient(0,0,1,0,0,g.r);
      shade.addColorStop(0,'#010509');shade.addColorStop(1,'#12434a00');disc(c,0,0,g.r,shade);
      for(let arm=0;arm<3;arm++){
        const points=Array.from({length:15},(_,n)=>{
          const angle=n*.20+arm*TAU/3-t*(warning?1.7:4.2),r=g.r*(1-n/16);
          return [Math.cos(angle)*r,Math.sin(angle)*r*.86];
        });
        path(points,warning?'#68928c':'#8cb8a8',warning?1.25:2);
      }
    }else if(h.type==='circle'){
      if(h.motif==='cult_stage'||h.motif==='cult_reprise'){
        const old=h.motif==='cult_reprise',ink=old?'#e3a0b1':'#ffd08b';
        const spotlight=c.createRadialGradient(g.x,g.y,2,g.x,g.y,g.r);
        spotlight.addColorStop(0,warning?'#9b581c22':'#a94419ab');
        spotlight.addColorStop(.81,old?'#85405e60':'#d17d3670');
        spotlight.addColorStop(1,'#71324a11');disc(c,g.x,g.y,g.r,spotlight);
        c.setLineDash([]);
        for(let i=0;i<7;i++){
          const b=i*TAU/7+Math.sin(t*2)*.06; c.strokeStyle=ink;c.lineWidth=warning?1.1:2;
          c.beginPath();c.arc(g.x,g.y,g.r,b,b+.34+(i%3)*.09);c.stroke();
        }
        glyph(c,h.motif,g.x,g.y,g.r*.35,0,ink,t);
      }else if(h.motif==='cult_altar'){
        if(!warning||h.start-t<.52){
          disc(c,g.x,g.y,g.r,warning?'#7e351337':'#6b2617a0');
          const fire=Array.from({length:38},(_,n)=>{const b=n*TAU/38,rr=g.r*(n%2?1:.87+.08*Math.sin(n*6+t*14));return [g.x+Math.cos(b)*rr,g.y+Math.sin(b)*rr];});
          stroke(c,fire,warning?'#b56f3b':'#ffba71',warning?1.2:2.3,true);
          for(const d of [-1,0,1])glyph(c,'cult_wax',g.x+d*16,g.y+Math.abs(d)*5,12,0,color,t);
        }
      }else if(h.motif==='cult_eye'){
        disc(c,g.x,g.y,g.r,warning?'#46245e77':'#74378799');
        const rim=Array.from({length:10},(_,n)=>{const b=n*TAU/10+t*.45;return [g.x+Math.cos(b)*g.r,g.y+Math.sin(b)*g.r];});
        stroke(c,rim,color,warning?1.3:2.8,true);circle(c,g.x,g.y,g.r,color,warning?.8:1.35);
        glyph(c,'cult_eye',g.x,g.y,g.r*.52+.9*Math.sin(t*12),0,color,t);
      }else{c.restore();return false;}
    }else{c.restore();return false;}
    c.restore();return true;
  }
  function hazard(c,s,h,g,flags){
    const a=appearance(s.p);if(!a)return false;
    if(cultHazard(c,s,h,g,flags,a))return true;
    if(h.uniform||h.visualOnly)return false;
    if(a.cls==='chest_mimic'&&h.motif)a.motif=h.motif;
    if((s.p.skill.base_id||'').startsWith('guild_')&&h.color)a.color=h.color;
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
        if(a.cls==='chest_mimic'){glyph(c,'chest_mouth',g.x,g.y,g.r*.85,0,a.color,t);}
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
    if((a.cls==='chest_mimic'||a.cls==='cultist')&&e.motif)a.motif=e.motif;
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
    const a=appearance(s.p);if(!a?.ground||s.layered)return;
    const art=a.motif,t=s.time;
    c.save();c.globalAlpha=1;c.fillStyle=a.ground;c.fillRect(0,0,720,height);
    if(art==='cult_wax'){
      // Pure black, with only the actual hazards illuminating the vault.
      c.restore();return;
    }
    const dusk=c.createRadialGradient(360,height*.53,40,360,height*.5,391);
    dusk.addColorStop(0,art==='cult_root'?'#48523b75':'#d6c3c110');dusk.addColorStop(1,'#020309d6');
    c.fillStyle=dusk;c.fillRect(0,0,720,height);
    c.globalAlpha=.14;c.strokeStyle=a.color;c.lineWidth=1;
    if(art==='cult_actor'){
      polygon(c,[[0,0],[225,0],[162,34],[93,47],[57,110],[41,height],[0,height]],'#a14452');
      polygon(c,[[720,0],[495,0],[558,34],[627,47],[663,110],[679,height],[720,height]],'#a14452');
      for(const side of [-1,1])for(let i=0;i<7;i++){
        const x=360+side*(218+i*16);c.beginPath();c.moveTo(x,0);c.quadraticCurveTo(x-side*41,67,x+side*6,height);c.stroke();
      }
      for(let x=-145;x<900;x+=90)stroke(c,[[360+(x-360)*.28,height*.63],[x,height]],'#ac7671',1);
      for(let y=height*.70;y<height;y+=12+(y-height*.70)*.55)stroke(c,[[0,y],[720,y]],'#ac7671',1);
      for(let i=0;i<7;i++){
        const x=105+i*85,y=height*.67+3*Math.sin(i*2.5);
        c.globalAlpha=.09;glyph(c,'cult_hollow',x,y,7+i%2*2,Math.sin(t*.51+i)*.17,'#87716c',t);
      }
      if(s.kind==='defense'&&t>=s.preparation){
        let scene=0;
        for(const e of s.events||[])if(e.ready)scene=e.index;
        const cue=['I · СВЕТ','II · ДВОЙНИКИ','III · ЗАНАВЕС'][Math.min(scene,2)];
        c.globalAlpha=.42;c.font='600 13px Georgia,serif';c.textAlign='center';c.fillStyle='#e5b78d';
        c.fillText(cue,360,25);
      }
    }else if(art==='cult_mask'){
      // Empty gilded frames of the King; static scenery, not false hazards.
      for(const x of [58,185,535,662]){
        c.strokeStyle='#ab8453';c.strokeRect(x-30,17,60,78);c.strokeRect(x-24,23,48,66);
        polygon(c,[[x-19,31],[x+19,31],[x+11,68],[x,81],[x-11,68]],'#6c5736');
      }
    }else if(art==='cult_tide'){
      for(let i=0;i<14;i++){
        const x=i*56,top=height-(25+(i*79)%71);
        polygon(c,[[x-5,height],[x+4,top+13],[x+9,top],[x+22,top+2],[x+31,top+17],[x+33,height]],'#679f9a');
        stroke(c,[[x+8,height],[x+15,top+21],[x+25,height]],'#173241',3);
      }
      for(let i=0;i<34;i++)disc(c,(i*199+Math.sin(t*.32+i)*7+720)%720,(i*79-t*(7+i%6)%height+height)%height,.8+(i%3)*.42,a.color);
    }else if(art==='cult_wraith'){
      // The submerged palette stays, but the scene has no floor decorations.
      // Slow ink currents and fragmentary reflections never overlap the HUD.
      for(let i=0;i<5;i++){
        const x=i*161-60,y=height*(.18+(i%4)*.20),dx=Math.sin(t*.87+i)*34;
        const fog=c.createLinearGradient(x,y-22,x,y+43);
        fog.addColorStop(0,'#24464300');fog.addColorStop(.50,'#38636191');fog.addColorStop(1,'#18323900');
        c.fillStyle=fog;c.beginPath();c.moveTo(x-64,y+18);c.bezierCurveTo(x-22,y-40,x+95+dx,y+30,x+205,y-9);
        c.bezierCurveTo(x+129,y+41,x+38+dx,y+17,x-64,y+18);c.fill();
      }
      c.globalAlpha=.07;
      for(let i=0;i<5;i++)glyph(c,'cult_wraith',(120+i*131)+Math.sin(t*.7+i)*35,40+i%3*93,13+i%3*8,Math.sin(t*.55+i)*.7,'#6f8f82',t);
      if(s.kind==='defense'&&s.player&&t>=s.preparation){
        const x=720-s.player.x,y=height-s.player.y;
        c.globalAlpha=.12;
        glyph(c,'cult_wraith',x+9*Math.sin(t*1.4),y,30,-.6,'#6b9987',t);
        c.globalAlpha=.06;glyph(c,'cult_wraith',x-12,y+8,33,-.55,'#7d737c',t);
      }
    }else if(art==='cult_root'){
      for(const side of [-1,1])for(let i=0;i<15;i++){
        const x=i*53-12,y=side>0?0:height,l=12+(i*11)%40;
        c.strokeStyle='#020603';c.lineWidth=9;c.lineCap='round';c.beginPath();c.moveTo(x,y);
        c.bezierCurveTo(x-18,y+l*.25*side,x+17,y+l*.63*side,x+9,y+l*side);c.stroke();
        stroke(c,[[x+5,y+l*.53*side],[x+23,y+l*.71*side],[x+27,y+l*.98*side]],'#172c20',3);
      }
      for(let i=0;i<67;i++){const x=(i*197)%720,y=(i*79+20)%height;disc(c,x,y,(i%3)*.35+.5,'#d1ceab');}
    }else if(art==='cult_sphere'){
      for(let i=0;i<55;i++){const x=(i*211+43)%720,y=(i*113+21)%height;disc(c,x,y,i%3?.9:1.65,a.color);}
      for(let i=0;i<6;i++){
        const x=i*145-80;c.beginPath();c.ellipse(x,height*.50,176,23,-.61,0,TAU);c.stroke();
      }
    }else if(art==='cult_echo'){
      for(let j=0;j<14;j++){
        const x=(j*137+93)%720,y=(j*53+37)%height,w=36+(j*41)%101,dx=Math.sin(t*.9+j*2)*14;
        c.globalAlpha=.07+.04*(1+Math.sin(t*1.9+j));
        for(let n=0;n<3;n++)stroke(c,[[x+dx+n*8,y+n*5],[x+dx+w*(.5+.16*n),y+n*5]],n===1?'#bf969f':'#62607d',1.1);
      }
    }else{
      for(let i=0;i<17;i++){
        const x=(i*107+13)%720,y=(i*69+34)%height;
        stroke(c,[[x-5,y+7],[x+4,y-8],[x+6,y+3],[x-5,y-3],[x+5,y+7]],'#ac85bd',1);
      }
    }
    c.restore();
  }
  window.QTEArt={appearance,glyph,hazard,block,attack,field,themes:THEMES};
})();
