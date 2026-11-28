window.MirrorDungeon=(()=>{
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rooms={fight:'Отражение',elite:'Элита',rest:'Передышка',cache:'Тайник',shop:'Торговец отражениями'};
  const rarities={common:'обычных',uncommon:'необычных',rare:'редких'};
  const stats={max_hp:'HP',physical_attack:'Физ. атака',magic_attack:'Маг. атака',physical_defense:'Физ. защита',magic_defense:'Маг. защита',speed:'Скорость',evasion:'Уклонение'};
  const roomIcons={fight:'battle',elite:'elite',rest:'rest',cache:'treasure',shop:'shop',boss:'boss'};
  const tile=kind=>`<span class="mirror-node-tile" aria-hidden="true">${window.GuildApp?.roomIcon?.(roomIcons[kind])||'◆'}</span>`;
  const sprite=mob=>mob?.sprite?.startsWith('/static/assets/')?`<img class="mirror-map-sprite" src="${esc(mob.sprite)}" alt="" draggable="false">`:'';
  const pages=items=>Object.entries(items||{}).map(([k,n])=>`${n} ${rarities[k]||''}`).join(' · ');
  const rowHeight=108, lanes=[50,150,250];

  function rewardChoices(data,button,rarityBadge){
    const offer=it=>{
      const info=it.kind==='gear'?[
        it.slot_name+' · уровень 20+',
        Object.entries(it.stats).map(([key,value])=>`${stats[key]||key} +${value}`).join(' · '),
        it.effect_text
      ].filter(Boolean):[it.kind==='pages'?pages(it.pages):it.kind==='skill'?'Активный трактат':'Пассивный трактат'];
      return button(esc(it.name)+(it.rarity?rarityBadge(it.rarity):'')+info.map(line=>'<small>'+esc(line)+'</small>').join(''),
                    'mirrorchoice:claim:'+it.id,'mirror-offer');
    };
    const gear=data.rewards.filter(it=>it.kind==='gear');
    const rest=data.rewards.filter(it=>it.kind!=='gear');
    const choices=items=>'<div class="mirror-offers">'+items.map(offer).join('')+'</div>';
    return (gear.length?'<h3>Снаряжение S · выбери слот</h3>'+choices(gear)+'<h3>Трактаты и страницы</h3>':'')+choices(rest);
  }

  function trail(data){
    const end=data.route.length, height=(end+1)*rowHeight, y=f=>(end+1-f)*rowHeight+76;
    const edge=(x1,y1,x2,y2,lit)=>`<path class="${lit?'passed mirror-link-lit':''}" d="M${x1},${y1} C${x1},${y1-52} ${x2},${y2+52} ${x2},${y2}"/>`;
    const edges=data.route.flatMap(({floor,links})=>links.map(([src,dst])=>{
      const from=`f${floor-1}-${src}`, to=`f${floor}-${dst}`;
      const lit=data.path[floor-2]===from&&(data.available.includes(to)||data.path[floor-1]===to);
      return edge(lanes[src],y(floor-1),lanes[dst],y(floor),lit);
    })).join('');
    const rows=[...data.route].reverse().map(({floor,nodes})=>`<div class="mirror-map-row" data-mirror-floor="${floor}"><span class="mirror-depth">${String(floor).padStart(2,'0')}</span>${nodes.map(node=>{
      const reachable=data.available.includes(node.id),visited=data.path.includes(node.id),last=data.path.at(-1)===node.id;
      const name=node.mob?.name||rooms[node.kind], label=node.mob?`${name} · ур. ${node.mob.level}`:name;
      return `<button type="button" class="mirror-node ${node.kind}${visited?' visited':''}${reachable?' reachable':''}${last?' current':''}" data-lane="${node.lane}" data-do="mirrorchoice:visit:${esc(node.id)}" ${reachable?'':'disabled'} title="${esc(label)}" aria-label="${esc('Этаж '+floor+' · '+label+(node.kind==='elite'?' · элита':'')+(reachable?' · доступно':''))}">${tile(node.kind)}${sprite(node.mob)}${node.kind==='shop'?'<span class="mirror-node-caption">Магазин</span>':''}</button>`;
    }).join('')}</div>`).join('');
    const bossReady=data.phase==='merchant'&&data.step===end&&!data.boss_active;
    const finalEdges=data.route.at(-1).nodes.map(n=>edge(lanes[n.lane],y(end),lanes[1],y(end+1),(bossReady||data.boss_active)&&data.path.at(-1)===n.id)).join('');
    const bossName=data.route_version===2?`Босс этажа ${data.floor} · ${data.boss.name} · ур. ${data.boss.level}`:`Босс: Последнее отражение · ${data.boss.name}`;
    const boss=`<div class="mirror-map-row mirror-final-row"><button type="button" class="mirror-node boss${bossReady?' reachable':data.boss_active?' current':''}" data-lane="1" ${bossReady?'data-do="mirroraction:next"':'disabled'} title="${esc(bossName)}" aria-label="${esc(bossName)}">${tile('boss')}${sprite(data.boss)}<span class="mirror-node-caption">Босс</span></button></div>`;
    return `<div class="mirror-map-scroll guild-map-panel" data-biome="crypt" role="region" aria-label="Маршрут Зеркальной Пустоши" tabindex="0"><div class="mirror-map-grid"><svg class="guild-map-lines" aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 300 ${height}">${edges}${finalEdges}</svg>${boss}${rows}</div></div>`;
  }

  function render(data,{button,confirm,petRewards,rarityBadge,chrome}){
    const chapter=data.route_version===2;
    const bar=(label,value,max,kind)=>`<div class="mirror-meter ${kind}"><div><span>${label}</span><strong>${value} / ${max}</strong></div><span><i style="width:${max?Math.max(0,Math.min(100,value/max*100)):0}%"></i></span></div>`;
    const gearShards=Object.entries(data.gear_shards||{}).map(([rank,n])=>`${n} ${rank}`).join(' · ');
    const ownedValue=`<span>${data.francs} ₣</span><span>${data.xp} XP</span>${pages(data.pages)?`<span>Страницы: ${esc(pages(data.pages))}</span>`:''}${gearShards?`<span>Осколки: ${esc(gearShards)}</span>`:''}`;
    const header=`<div class="mirror-dashboard"><div><small>ЭТАЖ</small><strong>${data.floor}<small> / ${data.total_floors}</small></strong>${chapter?`<small class="mirror-stage-number">Путь ${data.boss_active?data.floor_length:data.step}/${data.floor_length}</small>`:''}</div><div>${bar('HP',data.hp,data.max_hp,'hp')}${bar('Энергия',data.resource,data.resource_max,'energy')}</div><div><small>ПЫЛЬ</small><strong>${data.dust}</strong></div></div>`;
    let actions='';
    if(confirm)actions='<section class="card mirror-phase"><h2>Оставить забег?</h2><p>Пыль и артефакты исчезнут. Опыт, франки и страницы с пройденных рубежей сохранены.</p>'+button('Оставить забег','mirroraction:abandon','danger')+button('Продолжить','mirrorback')+'</section>';
    else if(data.phase==='reward')actions=petRewards(data.pet_rewards)+'<section class="card mirror-phase"><h2>Последнее отражение разбито</h2><p>Награды рубежей уже получены. Выбери <strong>один</strong> трофей.'+(data.weekly_bonus?' За первое прохождение на этой неделе снаряжение эпическое.':'')+'</p>'+rewardChoices(data,button,rarityBadge)+'</section>';
    else if(data.status!=='active')actions=petRewards(data.pet_rewards)+'<section class="card mirror-phase"><h2>'+esc(data.result)+'</h2><p>Пройдено этажей: '+data.cleared+' / '+data.total_floors+'</p>'+data.item_rewards.map(it=>'<p>'+esc(it.name)+' '+rarityBadge(it.rarity)+'</p>').join('')+button('В меню','menu','primary')+'</section>';
    else if(data.phase==='map'){
      const label=chapter&&data.step===data.route.length?'К лавке перед боссом':data.floor===1&&data.step===1?'Вход в Пустошь':'Выбери путь · этаж '+data.floor;
      actions=`<div class="mirror-route-caption"><h2 class="mirror-route-hint">${label}</h2>${data.result?`<small>${esc(data.result)}</small>`:''}</div>`;
    }
    else if(data.phase==='combat')actions='<section class="card mirror-phase"><h2>'+(data.boss_active?(chapter?'Босс этажа '+data.floor:'Последнее отражение'):'Бой на этаже '+data.floor)+'</h2>'+button('Открыть бой','battle:'+data.battle_token,'primary')+'</section>';
    else if(data.phase==='merchant')actions=`<section class="card mirror-phase mirror-shop"><small>ЭТАЖ ${data.floor}</small><h2>Торговец отражениями</h2><p>${esc(data.result)}</p><div class="mirror-offers">${data.offers.map(it=>button(esc(it.name)+'<b>'+it.price+' ◇</b><small>'+esc(it.bought?'Уже куплено':it.full?'Уже полный запас':it.description)+'</small>','mirrorchoice:buy:'+it.id,'mirror-offer '+it.kind,it.bought||it.full||data.dust<it.price)).join('')}</div>${button(chapter?'К боссу этажа':data.floor===data.total_floors?'К Последнему отражению':'↑ Этаж '+(data.floor+1),'mirroraction:next','primary')}</section>`;
    else if(data.phase==='landing')actions=`<section class="card mirror-phase"><h2>Этаж ${data.floor} пройден</h2><p>${esc(data.result)}</p>${button('↑ Этаж '+(data.floor+1),'mirroraction:next','primary')}</section>`;
    const gifts=data.gifts.length?`<section class="mirror-stash"><h3>Артефакты забега · ${data.gifts.length}</h3>${data.gifts.map(g=>`<p><b>${esc(g.name)}</b><br>${esc(g.description)}</p>`).join('')}</section>`:'';
    const info=`<details class="mirror-info"><summary>О забеге</summary><div class="card mirror-info-panel"><section class="mirror-receipts"><small>УЖЕ СОХРАНЕНО</small><div>${ownedValue}</div>${data.mirror_title?`<p>Титул: <strong>${esc(data.mirror_title)}</strong></p>`:''}<p>Рубежи 3, 6 и 9 дают франки и страницы. За финал — франки и один трофей. Пыль и артефакты действуют только в этом забеге.</p></section>${gifts}${data.status==='active'&&!confirm?button('Оставить забег','mirrorabandon','small danger'):''}</div></details>`;
    const controls=`<div class="mirror-dock-controls"><button type="button" data-mirror-jump="current" aria-label="К текущему этажу" title="К текущему этажу">◎</button>${info}</div>`;
    const hint=data.status==='active'&&data.phase==='map'&&!confirm;
    return `${trail(data)}<div class="mirror-hud">${chrome}${header}</div><div class="mirror-dock${hint?' map-phase':''}">${hint?`<div class="mirror-dock-row">${actions}${controls}</div>`:`<div class="mirror-action-sheet">${actions}</div><div class="mirror-dock-row">${controls}</div>`}</div>`;
  }

  function spacing(screen){
    const hud=screen.querySelector('.mirror-hud'), dock=screen.querySelector('.mirror-dock');
    const bottom=screen.clientHeight-dock.offsetTop+12;
    screen.style.setProperty('--mirror-map-top',`${hud.offsetTop+hud.offsetHeight+10}px`);
    screen.style.setProperty('--mirror-map-bottom',`${bottom}px`);
    return bottom;
  }

  function focus(root,data){
    const screen=root.querySelector('.mirror-v2'), map=screen.querySelector('.mirror-map-scroll');
    const row=screen.querySelector(`[data-mirror-floor="${data.step}"]`), grid=map.querySelector('.mirror-map-grid');
    const current=()=>{
      const bottom=spacing(screen);
      map.scrollTop=data.step===data.route.length?0:grid.offsetTop+row.offsetTop+row.offsetHeight+bottom-map.clientHeight;
    };
    current();
    screen.querySelector('[data-mirror-jump="current"]').addEventListener('click',current);
  }
  window.addEventListener('resize',()=>{const screen=document.querySelector('.mirror-v2');if(screen)spacing(screen);});
  return {render,focus};
})();
