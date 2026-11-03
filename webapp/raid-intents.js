/* Intent is drawn on the battlefield, never in a second action panel. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.RaidIntentLines=api;})(globalThis,function(){'use strict';const NS='http://www.w3.org/2000/svg',colors=['#79c8df','#a8d5ad','#d8ae73','#dc9279','#b39ce5','#db9fc7','#8ebdc6','#c8be87'];let observer=null;
function showLines(data){const d=data.data||data,players=Object.values(d.players||{}).filter(p=>!p.withdrawn&&p.fighter?.hp>0).length,enemies=Object.values(d.enemies||(d.boss?{boss:d.boss}:{})).filter(f=>f.hp>0).length;return players>0&&enemies>0&&(players>1||enemies>1);}
function mount(field,data,onIntercept){
 observer?.disconnect();if(!field||data.status!=='active')return;
 const d=data.data,ids=[...Object.keys(d.players),...Object.keys(d.enemies||{boss:d.boss})],palette=d.action_queue?.colors||Object.fromEntries(ids.map((k,i)=>[k,colors[i%colors.length]]));
 field.classList.toggle('queue-encounter',!!d.action_queue);
 const svg=showLines(data)?document.createElementNS(NS,'svg'):null;if(svg){svg.classList.add('raid-intent-lines');svg.setAttribute('aria-label','Намерения противников. Нажми на линию к союзнику, чтобы перехватить одиночную атаку.');field.append(svg);}
 function element(name,attrs,parent=svg){const e=document.createElementNS(NS,name);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e;}
 function draw(){if(!svg)return;svg.replaceChildren();const rect=field.getBoundingClientRect(),w=rect.width,h=rect.height;svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
  const center=k=>{const node=document.getElementById('raid-fighter-'+k),el=node?.querySelector('.raid-sprite')||node;if(!el)return null;const r=el.getBoundingClientRect();return{x:r.x-rect.x+r.width/2,y:r.y-rect.y+r.height*.55};};
  for(const [key,intent]of Object.entries(d.enemy_intents||{boss:d.intent})){if((d.enemies?.[key]||d.boss)?.hp<=0)continue;const a=center(key);if(!a)continue;const list=[...new Set(intent.targets||[])],source=d.enemies?.[key]?.name||d.boss.name,me=d.players[String(data.actor_id)];
   for(const target of list){const b=center(target);if(!b||d.players[target]?.fighter.hp<=0)continue;const cover=!!(d.action_queue&&!me?.ready&&!data.qte?.waiting&&!['defense','resolve'].includes(d.action_queue.phase)&&me?.fighter.hp>0&&list.length===1&&(intent.interceptor===String(data.actor_id)||target!==String(data.actor_id)&&!d.players[target]?.ready&&!intent.interceptor));
    const label=source+': '+intent.text+' · '+list.length+' '+(list.length===1?'цель':'цели')+' → '+(d.players[target]?.fighter.name||target)+(cover?' · '+(intent.interceptor?'Отменить перехват':'Взять на себя · 8 энергии'):'');
    const g=element('g',{class:'raid-intent-link'+(cover?' interceptable':''),tabindex:'0',role:cover?'button':'img','aria-label':label});element('title',{},g).textContent=label;const mid={x:(a.x+b.x)/2,y:Math.max(15,Math.min(a.y,b.y)-h*.12)};
    const path=`M${a.x},${a.y} Q${mid.x},${mid.y} ${b.x},${b.y}`;element('path',{d:path,fill:'none',stroke:palette[key]||'#e3be93','stroke-width':2,'stroke-dasharray':intent.interceptor?'3 4':'6 7'},g);element('path',{d:path,fill:'none',stroke:'transparent','stroke-width':18},g);element('circle',{cx:b.x,cy:b.y,r:4,fill:palette[key]||'#e3be93'},g);
    if(cover){const x=(a.x+2*mid.x+b.x)/4,y=(a.y+2*mid.y+b.y)/4;element('circle',{cx:x,cy:y,r:13,fill:'#15243b',stroke:'#8ed8ec'},g);element('text',{x,y:y+4,'text-anchor':'middle',fill:'#c3eff7','font-size':13},g).textContent=intent.interceptor?'×':'⛨';g.onclick=()=>onIntercept(key);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onIntercept(key);}};}
   }
  }
 }
 ids.forEach(k=>{const name=document.getElementById('raid-fighter-'+k)?.querySelector('.raid-hud strong');if(name){const dot=document.createElement('i');dot.className='raid-order-dot';dot.style.background=palette[k];name.prepend(dot);}});
 window.RaidTimeline?.mount(field,data);
 draw();observer=new ResizeObserver(draw);observer.observe(field);
}
return {mount,showLines};});
