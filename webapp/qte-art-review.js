/* Read-only art gallery. Uses actual simulators/renderers, never gameplay APIs. */
(()=>{
  'use strict';
  const E=window.QTEUnique,B=window.QTEBlock,A=window.QTEArt,$=id=>document.getElementById(id);
  const catalog=JSON.parse($('catalog').textContent),classes=Object.keys(A.themes),params=new URLSearchParams(location.search);
  let mode=['attack','block'].includes(params.get('mode'))?params.get('mode'):'defense',paused=false,last=0;
  const defaults={ragamuffin:'bum_punch',cutie:'air_kiss',jock:'arch_mge_bro',nerd:'humiliate',thumb:'warning_shot',index:'first_line',middle:'whole_family',ring:'red_etude',pinky:'falling_star',warrior:'armor_split',mage:'mana_shot',priest:'holy_judgment',hunter:'hunter_shot',gambler:'casino_all_in'};
  const entries=[],stats={accuracy:85,evasion:15,enemyAccuracy:90,enemyEvasion:15};
  for(const cls of classes){
    const skills=catalog.filter(sk=>sk.class_id===cls);if(!skills.length)continue;
    const card=document.createElement('article');card.className='card';card.dataset.class=cls;
    const caption=document.createElement('div');caption.className='caption';
    const title=document.createElement('h2');title.textContent=skills[0].class_name;caption.append(title);
    const badge=document.createElement('span');badge.textContent=String(skills.length)+' приёмов';badge.style.cssText='font-size:12px;color:#9aadc1';caption.append(badge);card.append(caption);
    const sel=document.createElement('select');sel.setAttribute('aria-label','Атака: '+skills[0].class_name);
    for(const sk of skills){const opt=document.createElement('option');opt.value=sk.id;opt.textContent=sk.name+' · '+sk.origin;sel.append(opt);}
    sel.value=(skills.find(sk=>sk.id===params.get('skill'))||skills.find(sk=>sk.base_id===defaults[cls]&&sk.origin==='Базовый навык')||skills.find(sk=>sk.base_id===defaults[cls])||skills[0]).id;
    card.append(sel);const canvas=document.createElement('canvas');canvas.width=720;canvas.height=320;canvas.setAttribute('aria-label',skills[0].class_name+' — демонстрация');card.append(canvas);
    const meta=document.createElement('div');meta.className='meta';const label=document.createElement('span'),link=document.createElement('a');link.textContent='Попробовать ↗';meta.append(label,link);card.append(meta);
    const entry={cls,card,canvas,ctx:canvas.getContext('2d'),select:sel,label,link,skills,sim:null,elapsed:0,wait:0,visible:true};
    sel.addEventListener('change',()=>refresh(entry));entries.push(entry);$('grid').append(card);
    const opt=document.createElement('option');opt.value=cls;opt.textContent=skills[0].class_name;$('class').append(opt);
  }
  function reset(e){
    const sk=e.skills.find(sk=>sk.id===e.select.value),p=E.profile(sk);
    e.elapsed=0;e.wait=0;e.canvas.height=mode==='block'?400:320;e.card.classList.toggle('block',mode==='block');
    e.sim=mode==='block'?B.create(sk,{physicalDefense:30,magicDefense:30,enemyAttack:30,enemyAccuracy:90},17,{hp:100000,endOnDeath:false}):mode==='attack'?E.attack(p,stats,17):E.defense(p,stats,17,{hp:100000,endOnDeath:false});
    e.label.textContent=A.appearance(p)?.label||A.themes[e.cls][2];
    e.link.href=(mode==='block'?'/qte-lab/block/':'/qte-lab/unique/?mode='+mode+'&')+(mode==='block'?'?':'')+'skill='+encodeURIComponent(sk.id);
    paint(e);
  }
  function paint(e){if(mode==='block')window.QTEBlockView.draw(e.ctx,e.canvas,e.sim);else window.QTEView.draw(e.ctx,e.canvas,e.sim);}
  function filter(){const cls=$('class').value;for(const e of entries)e.card.hidden=!!cls&&cls!==e.cls;$('grid').style.gridTemplateColumns=cls?'minmax(0,1fr)':'';$('grid').style.maxWidth=cls?'900px':'';}
  $('class').value=classes.includes(params.get('class'))?params.get('class'):'';$('class').addEventListener('change',filter);filter();
  function buttons(){document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));}
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.mode;buttons();entries.forEach(refresh);}));
  function pauseLabel(){$('pause').textContent=paused?'Продолжить':'Пауза';$('pause').setAttribute('aria-pressed',String(paused));}
  $('pause').addEventListener('click',()=>{paused=!paused;if(!paused)$('frame').value='';pauseLabel();});
  function advance(e,dt){
    const s=e.sim;e.elapsed+=dt;
    if(mode==='block')B.step(s,dt,{angle:e.elapsed*.8,active:Math.sin(e.elapsed*3)>-.3});
    else if(mode==='attack'){E.attackStep(s,dt);const f=E.attackFrame(s);if(f.canHit&&Math.abs(f.cursor-f.center)<f.width*.35)E.hit(s);}
    else E.defenseStep(s,dt,{x:Math.sin(e.elapsed*1.1),y:Math.cos(e.elapsed*.8)});
  }
  function refresh(e){
    reset(e);const seconds=Number($('frame').value);
    if(seconds){for(let i=0;i<seconds*120;i++)advance(e,1/120);paint(e);}
  }
  $('frame').addEventListener('change',()=>{
    const seconds=Number($('frame').value);paused=!!seconds;pauseLabel();
    if(seconds)entries.forEach(refresh);
  });
  const observer=new IntersectionObserver(rows=>{for(const row of rows){const e=entries.find(e=>e.card===row.target);if(e)e.visible=row.isIntersecting;}},{rootMargin:'120px'});entries.forEach(e=>observer.observe(e.card));
  $('count').textContent=entries.length+' классов · '+entries.reduce((sum,e)=>sum+e.skills.length,0)+' профилей';
  buttons();entries.forEach(reset);
  function frame(now){
    const dt=last?Math.min(.05,(now-last)/1000):0;last=now;
    if(!paused&&!document.hidden)for(const e of entries){
      if(e.card.hidden||!e.visible)continue;
      const s=e.sim;
      if(s.ended){e.wait+=dt;if(e.wait>.8)reset(e);continue;}
      for(let i=0;i<Math.ceil(dt*120);i++)advance(e,dt/Math.max(1,Math.ceil(dt*120)));
      paint(e);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
