(() => {
  'use strict';
  const $ = (q, root=document) => root.querySelector(q);
  const screen=$('#screen'), nav=$('#nav'), note=$('#notice'), dialog=$('#verify');
  const tg=window.Telegram?.WebApp;
  tg?.ready?.(); tg?.expand?.();
  for(const name of ['safeAreaInset','contentSafeAreaInset']){
    const update=()=>{
      const stem=name==='safeAreaInset'?'safe-area':'content-safe-area';
      for(const edge of ['top','bottom']) document.documentElement.style.setProperty('--tg-'+stem+'-inset-'+edge, (tg?.[name]?.[edge]||0)+'px');
    };
    update();tg?.onEvent?.(name==='safeAreaInset'?'safeAreaChanged':'contentSafeAreaChanged',update);
  }
  const query=new URLSearchParams(location.search);
  const entry=(query.get('entry') || query.get('tgWebAppStartParam') || tg?.initDataUnsafe?.start_param || '')
    .match(/^family_(-[1-9]\d{0,15})(?:_([a-z]+)(?:_(\d{1,16}))?(?:_(\d{1,16}))?)?$/);
  const base=entry ? '/api/family/'+entry[1] : '';
  const kinds={blank:'Создать пустой Исток',origin:'Назначить участника Истоком',attach:'Прикрепить ветвь к Истоку',
    detach:'Отсоединить ветвь от Истока',link:'Добавить родство',sibling:'Добавить брата или сестру',
    unsibling:'Убрать связь брата или сестры',marry:'Внести брак',unmarry:'Расторгнуть брак без суда',unlink:'Убрать родство',appoint:'Назначить судью',revoke:'Снять судью'};
  const editPayload=(kind,fields)=>kind==='blank'?{edit:'origin',a:0}:
    kind==='attach'||kind==='detach'?{edit:kind==='attach'?'link':'unlink',a:0,b:fields.b}:{edit:kind,...fields};
  let state, people=new Map(), tab=entry?.[2]==='file'?'file':'tree', selected, scene, activeEditor='origin', chosen={}, pending, busy=false;
  let casesOffset=0, caseID=entry?.[2]==='court' ? Number(entry[3])||null : null;
  let teardown=()=>{}, center=()=>{}, camera={x:0,y:0,k:0};
  const headers=()=>({'X-Telegram-Init-Data':tg?.initData||''});
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const name=id=>id===0?'Исток':people.get(id)?.name || 'Участник '+id;
  const when=n=>new Intl.DateTimeFormat('ru',{dateStyle:'short',timeStyle:'short',timeZone:'Europe/Moscow'}).format(n*1000);
  const button=(label,action,css='')=>'<button type="button" class="'+css+'" data-action="'+action+'">'+label+'</button>';
  const status=(message,error=false)=>{
    note.textContent=message; note.hidden=!message; note.toggleAttribute('data-error',error);
  };
  function explain(error){status(error.message||'Не удалось выполнить действие.',true);}
  async function api(path='', body, signal) {
    const response=await fetch(base+path,{method:body?'POST':'GET',headers:{...headers(),...(body?{'Content-Type':'application/json'}:{})},
      body:body?JSON.stringify(body):undefined,signal,cache:'no-store'});
    const data=await response.json();
    if(!response.ok) throw Error(data.error||'Семейный архив недоступен.');
    return data;
  }
  async function load() {
    const args=new URLSearchParams();
    if(caseID)args.set('case',caseID);
    if(casesOffset)args.set('offset',casesOffset);
    if(tab==='file')args.set('mine','1');
    const before=state?.revision;
    state=await api(args.size?'?'+args:'');
    people=new Map(state.people.map(p=>[p.id,p]));
    const ids=[...state.members,...(state.detached||[]).flat()];
    if(!ids.includes(selected)) selected=state.origin??ids[0];
    if(before!==undefined && before!==state.revision) camera.k=0;
    scene=null;
  }
  function layout() {
    const detached=state.detached||[], ids=[...state.members,...detached.flat()];
    const out=new Map(ids.map(id=>[id,[]])), ins=new Map(ids.map(id=>[id,[]]));
    const partners=new Map(state.marriages.flatMap(([a,b])=>[[a,b],[b,a]]));
    const siblings=new Map(ids.map(id=>[id,[]]));
    for(const [a,b] of state.siblings||[]){siblings.get(a).push(b);siblings.get(b).push(a);}
    for(const [p,c] of [...state.parents,...(state.branches||[]).map(id=>[0,id])]){out.get(p).push(c);ins.get(c).push(p);}
    const main=state.members.length?layoutPart(state.members,state.origin,out,ins,partners,siblings):null;
    const parts=detached.map(ids=>layoutPart(ids,null,out,ins,partners,siblings));
    const width=Math.max(main?.width||300,...parts.map(part=>part.width),parts.length>1?600:300);
    const spots=new Map();
    const place=(part,x,y)=>{for(const [id,[u,v]] of part.spots)spots.set(id,[x+u,y+v]);};
    if(main)place(main,(width-main.width)/2,0);
    const start=main?main.height+38:9;
    let x=0,y=start+43,rowHeight=0;
    for(const part of parts){
      if(x && x+part.width>width){x=0;y+=rowHeight+24;rowHeight=0;}
      place(part,x,y);
      x+=part.width;rowHeight=Math.max(rowHeight,part.height);
    }
    const height=parts.length?y+rowHeight+12:main.height;
    return {spots,width,height,partners,ins,out,siblings,detachedStart:parts.length?start:null};
  }
  function alignSiblings(ids,rank,out,siblings) {
    const groupOf=new Map(), groups=[];
    for(const id of ids){
      if(groupOf.has(id))continue;
      const group={ids:[id],rank:0,next:new Set(),incoming:0};
      groups.push(group);
      groupOf.set(id,group);
      for(const person of group.ids){
        group.rank=Math.max(group.rank,rank.get(person));
        for(const other of siblings.get(person))if(!groupOf.has(other)){
          groupOf.set(other,group);
          group.ids.push(other);
        }
      }
    }
    for(const id of ids)for(const child of out.get(id)){
      const a=groupOf.get(id), b=groupOf.get(child);
      if(!a.next.has(b)){a.next.add(b);b.incoming++;}
    }
    const ready=groups.filter(group=>!group.incoming);
    for(const group of ready)for(const child of group.next){
      child.rank=Math.max(child.rank,group.rank+1);
      if(--child.incoming===0)ready.push(child);
    }
    for(const group of ready)for(const id of group.ids)rank.set(id,group.rank);
    return groupOf;
  }
  function layoutPart(ids,origin,out,ins,partners,siblings) {
    const rank=new Map(ids.map(id=>[id,origin===null||id===origin?0:1]));
    const remaining=new Map(ids.map(id=>[id,ins.get(id).length]));
    const order=ids.filter(id=>!remaining.get(id)), direct=new Set([origin]);
    for(const p of order) for(const c of out.get(p)){
      if(direct.has(p))direct.add(c);
      remaining.set(c,remaining.get(c)-1);
      if(!remaining.get(c)) order.push(c);
      rank.set(c,Math.max(rank.get(c),rank.get(p)+1));
    }
    // A co-parent without a line descending from the root belongs near their children.
    for(const p of order.slice().reverse())if(!direct.has(p) && out.get(p).length){
      rank.set(p,Math.max(rank.get(p),Math.min(...out.get(p).map(c=>rank.get(c)))-1));
    }
    // A spouse linked through marriage alone belongs next to their partner.
    for(const id of ids)if(id!==origin&&!ins.get(id).length){
      const partner=partners.get(id);
      if(rank.has(partner))rank.set(id,Math.max(rank.get(id),rank.get(partner)));
    }
    for(const p of order)for(const c of out.get(p))rank.set(c,Math.max(rank.get(c),rank.get(p)+1));
    const groupOf=alignSiblings(ids,rank,out,siblings);
    const ranks=[];
    for(const id of ids)(ranks[rank.get(id)]??=[]).push(id);
    const rows=ranks.filter(Boolean);
    const width=Math.max(origin===null?215:510,...rows.map(row=>row.length*187+28));
    const height=rows.length*114+10, spots=new Map();
    rows.forEach((row,y)=>{
      const slot=new Set(row);
      function weight(id){
        const spouse=partners.get(id), anchors=[...ins.get(id),...(slot.has(spouse)?ins.get(spouse):[])]
          .map(p=>spots.get(p)?.[0]).filter(Number.isFinite);
        return anchors.length?anchors.reduce((a,b)=>a+b,0)/anchors.length:width/2;
      }
      const ranked=row.map(id=>[id,weight(id)]).sort(([a,x],[b,y])=>x-y||a-b);
      const placed=[];
      for(const [id] of ranked)if(slot.has(id)){
        const groups=[groupOf.get(id)], queued=new Set(groups);
        for(const group of groups)for(const person of group.ids){
          if(!slot.delete(person))continue;
          placed.push(person);
          // Keep a same-row marriage as two adjacent cards even when either
          // spouse belongs to a larger sibling group.
          const partner=partners.get(person);
          if(!slot.delete(partner))continue;
          placed.push(partner);
          const partnerGroup=groupOf.get(partner);
          if(!queued.has(partnerGroup)){queued.add(partnerGroup);groups.push(partnerGroup);}
        }
      }
      placed.forEach((id,i)=>spots.set(id,[width*(i+.5)/placed.length,49+y*114]));
    });
    return {spots,width,height};
  }
  function graph() {
    const {spots,width,height,partners,ins}=scene, paths=[], rings=[], grouped=new Map();
    for(const [a,b] of state.marriages){
      const [x,y]=spots.get(a), [u,v]=spots.get(b), mid=(x+u)/2;
      if(y!==v){
        const end=v+(v>y?-32:32), start=y+(v>y?32:-32);
        paths.push('<path class="spouse" d="M'+x+' '+start+' C'+x+' '+((start+end)/2)+' '+u+' '+((start+end)/2)+' '+u+' '+end+'"/>');
      }else{
        paths.push('<path class="spouse" d="M'+x+' '+y+' H'+u+'"/>');
      }
      rings.push('<span class="ring" aria-hidden="true" style="left:'+mid+'px;top:'+((y+v)/2)+'px">💍</span>');
    }
    for(const [a,b] of state.siblings||[]){
      const [x,y]=spots.get(a), [u,v]=spots.get(b);
      paths.push('<path class="sibling" d="M'+x+' '+(y+29)+' V'+(y+41)+' H'+u+' V'+(v+29)+'"/>');
    }
    for(const [id,from] of ins){
      const [x,y]=spots.get(id),end=y-32;
      if(from.length===2 && partners.get(from[0])===from[1] && spots.get(from[0])[1]===spots.get(from[1])[1]){
        const key=from.slice().sort((a,b)=>a-b).join(',');
        if(!grouped.has(key))grouped.set(key,{from,to:[]});
        grouped.get(key).to.push([x,end]);
        continue;
      }
      for(const p of from){
        const [u,v]=spots.get(p),start=v+32,rail=(start+end)/2;
        paths.push('<path'+(p===0?' class="branch"':'')+' d="M'+u+' '+start+' C'+u+' '+rail+' '+x+' '+rail+' '+x+' '+end+'"/>');
      }
    }
    for(const {from,to} of grouped.values()){
      const [[a,y],[b]]=from.map(id=>spots.get(id)), mid=(a+b)/2;
      const rail=(y+32+Math.min(...to.map(p=>p[1])))/2;
      paths.push('<path d="M'+mid+' '+(y+12)+' V'+rail+' M'+Math.min(mid,...to.map(p=>p[0]))+' '+rail+' H'+Math.max(mid,...to.map(p=>p[0]))+'"/>');
      for(const [x,end] of to)paths.push('<path d="M'+x+' '+rail+' V'+end+'"/>');
    }
    return '<svg class="wires" viewBox="0 0 '+width+' '+height+'" aria-hidden="true">'+paths.join('')+'</svg>'+rings.join('');
  }
  const avatars=new Map(), avatarTTL=300000;
  let avatarVersion=0;
  function resetAvatars(){
    avatarVersion++;
    for(const {promise} of avatars.values())promise.then(url=>{if(url)URL.revokeObjectURL(url);});
    avatars.clear();
  }
  function avatarJob(node) {
    const id=Number(node.dataset.avatar), version=avatarVersion, now=Date.now();
    const previous=avatars.get(id);
    if(!previous||now-previous.at>=avatarTTL){
      previous?.promise.then(url=>{if(url)URL.revokeObjectURL(url);});
      const promise=fetch(base+'/avatar/'+id+(version?'?refresh=1':''),{headers:headers(),cache:'no-store'})
        .then(r=>r.ok?r.blob():r.status===404?null:undefined)
        .then(blob=>blob?URL.createObjectURL(blob):blob).catch(()=>undefined);
      avatars.set(id,{at:now,promise});
    }
    node.dataset.loadedPhoto=version;
    node.dataset.photoAt=now;
    return avatars.get(id).promise.then(url=>{
      if(!node.isConnected||version!==avatarVersion)return;
      if(url){const img=new Image();img.alt='';img.src=url;node.replaceChildren(img);}
      else if(url===null)node.textContent=node.dataset.initials;
    });
  }
  function card(id) {
    const [x,y]=scene.spots.get(id), isRoot=id===state.origin, user=people.get(id);
    const handle=user?.username?'@'+user.username:'';
    const avatar=isRoot?'🌌':esc(name(id).trim().slice(0,2).toLocaleUpperCase('ru'));
    return '<button class="person'+(isRoot?' origin':'')+'" type="button" data-person="'+id+'" aria-pressed="'+(id===selected)+
      '" title="'+esc(name(id))+'" style="left:'+x+'px;top:'+y+'px"><span class="avatar" aria-hidden="true"'+
      (id===0?'':' data-avatar="'+id+'" data-initials="'+avatar+'"')+'>'+avatar+
      '</span><span class="caption"><strong>'+esc(name(id))+'</strong><small>'+esc(id===0?'Начало древа':isRoot?'🌌 Первородный':handle)+'</small></span></button>';
  }
  const picker=(field,label,value='')=>'<div class="search" data-field="'+field+'"><label><span>'+esc(label)+
    '</span><input type="search" value="'+esc(value)+'" placeholder="Имя или @ник" autocomplete="off"></label><div class="results" hidden></div></div>';
  function selectedInfo(){
    const party=scene.partners.get(selected), children=scene.out.get(selected)||[];
    if(selected===0)return '<strong>🌌 Исток</strong> · ветвей: '+children.length;
    const siblings=scene.siblings.get(selected)||[];
    return '<strong>'+esc(name(selected))+'</strong> · родители: '+(scene.ins.get(selected)?.filter(id=>id!==0).length||0)+' · дети: '+children.length+
      (party===undefined?'':' · в браке: '+esc(name(party)))+
      (siblings.length?' · братья и сёстры: '+siblings.map(id=>esc(name(id))).join(', '):'')+
      (state.owner?' '+button('Добавить брата или сестру','edit:sibling:'+selected):'');
  }
  function tree() {
    const noOrigin=state.origin==null?'<div class="row"><p class="muted">Владелец ещё не назначил Исток.</p>'+
      (state.owner?'<div class="actions">'+button('Создать пустой Исток','edit:blank','primary')+' '+button('Назначить участника','edit:origin')+'</div>':'')+'</div>':'';
    if(!state.members.length&&!state.detached?.length) return '<section class="panel stack"><h2>Общее древо чата</h2>'+noOrigin+'</section>';
    scene??=layout();
    return '<section class="panel"><div class="heading"><div><h2>Общее древо чата</h2><p class="muted">Людей на карте: '+(scene.spots.size-(state.origin===0?1:0))+
      '</p></div>'+picker('tree','Найти на карте')+'</div>'+noOrigin+'<div class="map"><div class="pan" role="group" aria-label="Карта родства">'+
      '<div class="world" style="width:'+scene.width+'px;height:'+scene.height+'px">'+
      (scene.detachedStart!==null?'<div class="detached-label" style="top:'+scene.detachedStart+'px">Семьи вне Истока</div>':'')+
      graph()+[...scene.spots.keys()].sort((a,b)=>
        scene.spots.get(a)[1]-scene.spots.get(b)[1]||scene.spots.get(a)[0]-scene.spots.get(b)[0]).map(card).join('')+'</div></div></div>'+
      '<div class="map-controls"><div class="legend"><span>Родство</span><span class="married">Брак</span>'+
      (state.siblings?.length?'<span class="siblings">Братья и сёстры</span>':'')+
      (state.origin===0?'<span class="attached">Ветвь Истока</span>':'')+'</div><div class="actions">'+
      '<output aria-label="Масштаб" class="muted"></output>'+button('−','zoom:out')+button('+','zoom:in')+button('Всё древо','zoom:fit')+
      (state.origin==null?'':button('К Истоку','zoom:root'))+
      (state.detached?.length?button('К отдельным семьям','zoom:detached'):'')+
      button('Обновить аватарки','photos')+'</div></div><p class="selected muted" aria-live="polite">'+selectedInfo()+'</p></section>';
  }
  function mountMap() {
    const pan=$('.pan',screen);if(!pan)return;
    const world=$('.world',pan), indicator=$('output',screen), {width,height,spots}=scene;
    const pointers=new Map(), rect=()=>pan.getBoundingClientRect(), mid=()=>[pan.clientWidth/2,pan.clientHeight/2];
    let dragged=false, stopped=false, running=0, pumpPhotos=()=>{};
    const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
    const fitScale=()=>Math.min(1,(pan.clientWidth-12)/width,(pan.clientHeight-12)/height);
    function draw(){
      const [mx,my]=mid(), edgeX=Math.min(55,width*camera.k/2,mx),edgeY=Math.min(55,height*camera.k/2,my);
      camera.x=clamp(camera.x,edgeX-width*camera.k,mx*2-edgeX);
      camera.y=clamp(camera.y,edgeY-height*camera.k,my*2-edgeY);
      world.style.transform='translate('+camera.x+'px,'+camera.y+'px) scale('+camera.k+')';
      pan.style.backgroundPosition=(camera.x%21)+'px '+(camera.y%21)+'px';
      indicator.value=Math.round(camera.k*100)+'%';
      pumpPhotos();
    }
    function go(x,y,k){const [mx,my]=mid();camera={k,x:mx-x*k,y:my-y*k};draw();}
    const fit=()=>go(width/2,height/2,fitScale());
    center=id=>{const point=spots.get(id);if(point)go(...point,Math.max(.9,camera.k));};
    if(!camera.k){
      if(fitScale()>=.58) fit();
      else {
        const target=state.origin??selected;
        center(target);camera.y=60-spots.get(target)[1]*camera.k;draw();
      }
    }else draw();
    function zoom(k, ox,oy,nx=ox,ny=oy){
      const next=clamp(k,Math.min(.18,fitScale()),2.1), ratio=next/camera.k;
      camera={k:next,x:nx-(ox-camera.x)*ratio,y:ny-(oy-camera.y)*ratio};draw();
    }
    const tools=e=>{
      if(e.target.closest('[data-action="photos"]')){
        resetAvatars();
        for(const node of visible)queue.add(node);
        pumpPhotos();
        status('Аватарки обновляются по мере появления карточек на экране.');
        return;
      }
      const action=e.target.closest('[data-action^="zoom:"]')?.dataset.action;
      if(action==='zoom:fit')fit();
      if(action==='zoom:root')select(state.origin,true);
      if(action==='zoom:detached')select(state.detached[0][0],true);
      if(action==='zoom:out'||action==='zoom:in')zoom(camera.k*(action==='zoom:in'?1.24:1/1.24),...mid());
    };
    screen.addEventListener('click',tools);
    pan.addEventListener('wheel',e=>{
      e.preventDefault();const r=rect();zoom(camera.k*Math.exp(-clamp(e.deltaY*(e.deltaMode?16:1),-130,130)*.0025),e.clientX-r.left,e.clientY-r.top);
    },{passive:false});
    const xy=e=>[e.clientX-rect().left,e.clientY-rect().top];
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    pan.addEventListener('pointerdown',e=>{
      if(e.button!==0||pointers.size===2)return;
      if(!pointers.size)dragged=false;
      pointers.set(e.pointerId,xy(e));e.target.setPointerCapture?.(e.pointerId);
      if(pointers.size===2)dragged=true;
    });
    pan.addEventListener('pointermove',e=>{
      const start=pointers.get(e.pointerId);if(!start)return;
      const end=xy(e);if(!dragged&&distance(start,end)<6)return;
      dragged=true;pan.dataset.dragging='';pointers.set(e.pointerId,end);
      const other=[...pointers].find(([id])=>id!==e.pointerId)?.[1];
      if(other)zoom(camera.k*distance(end,other)/Math.max(1,distance(start,other)),
        (start[0]+other[0])/2,(start[1]+other[1])/2,(end[0]+other[0])/2,(end[1]+other[1])/2);
      else {camera.x+=end[0]-start[0];camera.y+=end[1]-start[1];draw();}
    });
    for(const ev of ['pointerup','pointercancel','lostpointercapture'])pan.addEventListener(ev,e=>{
      pointers.delete(e.pointerId);if(!pointers.size)delete pan.dataset.dragging;
    });
    pan.addEventListener('click',e=>{if(dragged&&e.detail){e.preventDefault();e.stopImmediatePropagation();}},true);
    const resize=new ResizeObserver(draw);resize.observe(pan);
    const visible=new Set(), queue=new Set();
    pumpPhotos=()=>{
      while(!stopped&&camera.k>=.32&&running<3&&queue.size){
        const [node]=queue;queue.delete(node);
        if(node.dataset.loadedPhoto===String(avatarVersion)&&Date.now()-Number(node.dataset.photoAt)<avatarTTL)continue;
        running++;
        avatarJob(node).finally(()=>{running--;pumpPhotos();});
      }
    };
    const observe=new IntersectionObserver(entries=>{
      for(const e of entries){
        if(e.isIntersecting){visible.add(e.target);queue.add(e.target);}
        else{visible.delete(e.target);queue.delete(e.target);}
      }
      pumpPhotos();
    },{root:pan});
    for(const node of pan.querySelectorAll('[data-avatar]'))observe.observe(node);
    teardown=()=>{stopped=true;observe.disconnect();resize.disconnect();screen.removeEventListener('click',tools);};
  }
  function select(id, move) {
    if(!scene?.spots.has(id))return;
    selected=id;
    for(const node of screen.querySelectorAll('[data-person]'))node.setAttribute('aria-pressed',String(Number(node.dataset.person)===id));
    $('.selected',screen).innerHTML=selectedInfo();
    if(move){center(id);$('[data-person="'+id+'"]',screen)?.focus({preventScroll:true});}
  }
  const resultNames={open:'На рассмотрении',approved:'Брак расторгнут',rejected:'Заявление отклонено',editor_closed:'Закрыто: брак расторгнут без суда'};
  function caseRows(judge) {
    return state.cases.map(c=>{
      const own=state.actor===c.a||state.actor===c.b;
      return '<article class="row"><div><h3>Дело №'+c.id+' · '+esc(name(c.a))+' и '+esc(name(c.b))+'</h3><p>'+resultNames[c.status]+
        '</p><small>'+when(c.created_at)+' · заявление: '+esc(name(c.requester))+'</small>'+
        (c.reason?'<p>'+esc(c.reason)+'</p>':'')+(c.decided_by?'<small>Решение: '+esc(name(c.decided_by))+'</small>':'')+'</div>'+
        (judge&&c.status==='open'&&!own?'<div class="actions">'+button('Расторгнуть','approve:'+c.id,'danger')+button('Отклонить','reject:'+c.id)+'</div>':
          judge&&c.status==='open'&&own?'<small>Свой развод рассматривает другой судья.</small>':'')+'</article>';
    }).join('')||'<p class="muted">Дел не найдено.</p>';
  }
  function court(){
    return '<section class="panel stack"><div class="heading"><h2>Суд по разводам</h2>'+button('Обновить','refresh')+'</div>'+
      caseRows(true)+'<div class="actions">'+(caseID||casesOffset?button(caseID?'Все дела':'Назад','cases:back'):'')+
      (state.more_cases?button('Следующие дела','cases:next'):'')+'</div></section>';
  }
  function file() {
    const own=state.cases.filter(c=>c.a===state.actor||c.b===state.actor),open=own.some(c=>c.status==='open');
    const canSubmit=state.spouse&&!open;
    return '<section class="panel stack"><h2>Мой брак</h2><p class="muted">'+(state.spouse?'Супруг(а): '+esc(name(state.spouse)):'Нет действующего брака в этом чате.')+
      '</p>'+(canSubmit?'<form class="stack" id="file"><label>Причина (необязательно)<textarea maxlength="500" name="reason" rows="3"></textarea></label>'+
        '<p class="muted">Причину увидят только стороны и судьи. Брак действует до решения суда.</p><button class="primary">Подать заявление</button></form>':'')+
      '</section><section class="panel stack"><div class="heading"><h2>Мои дела</h2>'+button('Обновить','refresh')+'</div>'+
      (own.length?own.map(c=>'<div class="row"><strong>№'+c.id+' · '+resultNames[c.status]+'</strong><small>'+when(c.created_at)+'</small></div>').join(''):'<p class="muted">Заявлений пока нет.</p>')+
      '</section>';
  }
  function editor() {
    const wedding=activeEditor==='marry', divorce=activeEditor==='unmarry', sibling=['sibling','unsibling'].includes(activeEditor);
    const privileged=state.editor?.marriage_override, marriageAction=wedding||divorce;
    const two=marriageAction||sibling||['link','unlink'].includes(activeEditor);
    const selectedPerson=chosen.a, related=(state.editor?.parents||[]).filter(p=>p.includes(selectedPerson));
    const siblings=(state.editor?.siblings||[]).filter(p=>p.includes(selectedPerson));
    const marriage=(state.editor?.marriages||[]).find(pair=>pair.includes(selectedPerson));
    const branchMode=activeEditor==='attach'||activeEditor==='detach';
    const fields=activeEditor==='blank'?'<p class="muted">Галактика без привязки к игроку. Существующее древо сохранится.</p>':
      branchMode?picker('b','Участник в начале ветви',chosen.b?name(chosen.b):''):
      picker('a',marriageAction?'Первый супруг':sibling?'Участник':two?'Родитель':'Участник',chosen.a?name(chosen.a):'')+
      (two?picker('b',marriageAction?'Второй супруг':sibling?'Брат или сестра':'Ребёнок',chosen.b?name(chosen.b):''):'');
    return '<section class="panel stack"><h2>Редактор связей</h2><form class="stack" id="edit"><label>Действие<select id="edit-kind">'+
      Object.entries(kinds).filter(([id])=>(id!=='unmarry'||privileged)&&
        (state.origin===0||id===activeEditor||!['attach','detach'].includes(id)))
        .map(([id,label])=>'<option value="'+id+'"'+(id===activeEditor?' selected':'')+'>'+label+'</option>').join('')+
      '</select></label><div class="'+(two?'fields':'')+'">'+fields+'</div>'+
      (wedding?'<p class="muted">Запись вносится без предложения в чат. '+(privileged
        ?'В редакторе можно внести брак между братьями и сёстрами.':'Расторжение — через суд.')+'</p>':'')+
      (divorce?'<p class="muted">Родство и дети сохранятся. Открытое заявление по этому браку будет закрыто.</p>':'')+
      '<label>Заметка для журнала<textarea id="edit-reason" name="reason" rows="2" maxlength="500"></textarea></label>'+
      '<button class="primary">Проверить правку</button></form>'+
      (related.length?'<div class="stack"><h3>Родство выбранного участника</h3>'+related.map(([a,b])=>'<div class="row"><span>'+esc(name(a))+' → '+esc(name(b))+'</span>'+
        button('Убрать','unlink:'+a+':'+b,'danger')+'</div>').join('')+'</div>':'')+
      (siblings.length?'<div class="stack"><h3>Братья и сёстры</h3>'+siblings.map(([a,b])=>'<div class="row"><span>'+esc(name(a===selectedPerson?b:a))+'</span>'+
        button('Убрать','unsibling:'+a+':'+b,'danger')+'</div>').join('')+'</div>':'')+
      (marriage?'<div class="row"><span>💍 '+marriage.map(id=>esc(name(id))).join(' и ')+'</span>'+
        (privileged?button('Расторгнуть без суда','unmarry:'+marriage.join(':'),'danger'):'<small>Расторжение через суд</small>')+'</div>':'')+'</section>'+
      (state.origin===0?'<section class="panel stack"><h2>Ветви Истока</h2>'+
        ((state.branches||[]).map(id=>'<div class="row"><strong>'+esc(name(id))+'</strong>'+button('Отсоединить','unlink:0:'+id,'danger')+'</div>').join('')
          ||'<p class="muted">Пока нет ветвей.</p>')+button('Прикрепить ветвь','edit:attach')+'</section>':'')+
      '<section class="panel stack"><h2>Судьи</h2><p class="muted">Владелец чата и создатель бота — судьи по должности.</p>'+
      state.judges.map(id=>'<div class="row"><strong>'+esc(name(id))+'</strong>'+button('Снять','revoke:'+id,'danger')+'</div>').join('')+'</section>'+
      '<section class="panel stack"><h2>Журнал изменений</h2>'+state.log.map(row=>'<div class="row"><div>'+esc(name(row.actor))+' · '+esc(row.description)+'</div><small>'+
        when(row.at)+'</small></div>').join('')+'</section>';
  }
  function render() {
    teardown();teardown=()=>{};center=()=>{};
    if(tab==='court'&&!state.judge||tab==='editor'&&!state.owner)tab='tree';
    for(const tabButton of nav.querySelectorAll('button')){
      const value=tabButton.dataset.tab;
      tabButton.hidden=value==='court'&&!state.judge||value==='editor'&&!state.owner||
        value==='file'&&(!state.spouse&&!state.cases.some(c=>c.a===state.actor||c.b===state.actor))&&tab!=='file';
      if(value===tab)tabButton.setAttribute('aria-current','page');else tabButton.removeAttribute('aria-current');
    }
    nav.hidden=false;
    $('#chat-title').textContent=state.title+' / Семейный архив';
    screen.innerHTML=({tree,file,court,editor})[tab]();
    if(tab==='tree') mountMap();
  }
  function ask(markup, action) {
    pending=action;$('#verify-body').innerHTML=markup;dialog.showModal();
  }
  async function preview(payload){
    const result=await api('',{op:'preview',...payload});
    const list=(people,label)=>people.length?'<p><strong>'+label+' ('+people.length+'):</strong> '+
      people.slice(0,15).map(p=>esc(p.name)).join(', ')+(people.length>15?' и ещё '+(people.length-15):'')+'</p>':'';
    ask('<p>'+esc(result.summary)+'</p>'+
      (result.marriage_rooted===false?'<p>Брак будет виден на карте в разделе «Семьи вне Истока».</p>':'')+
      list(result.added,'Свяжутся с Истоком')+
      list(result.removed,'Потеряют связь с Истоком'),async()=>{
        await api('',{op:'apply',revision:result.revision,proof:result.proof,...payload});
        await load();render();status(payload.edit==='marry'?'Брак внесён в архив.':
          payload.edit==='unmarry'?'Брак расторгнут без суда.':'Правка сохранена.');
    });
  }
  async function run(action) {
    if(busy)return;
    busy=true;status('');
    try{await action();}catch(error){explain(error);}finally{busy=false;}
  }
  nav.addEventListener('click',event=>{
    const next=event.target.closest('[data-tab]')?.dataset.tab;
    if(!next||next===tab)return;
    run(async()=>{tab=next;casesOffset=0;caseID=null;await load();render();});
  });
  $('#cancel').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{pending=null;});
  $('#confirm').addEventListener('click',()=>{
    const apply=pending;pending=null;dialog.close();if(apply)run(apply);
  });
  screen.addEventListener('change',event=>{
    if(event.target.id==='edit-kind'){activeEditor=event.target.value;chosen={};render();}
  });
  screen.addEventListener('submit',event=>{
    const form=event.target;
    if(!['edit','file'].includes(form.id))return;
    event.preventDefault();
    const reason=new FormData(form).get('reason')||'';
    if(form.id==='edit')run(()=>preview({...editPayload(activeEditor,chosen),reason}));
    else if(!busy)ask('<p>Отправить заявление в суд?</p>',async()=>{
      const result=await api('',{op:'file',reason});
      await load();render();status('Заявление зарегистрировано: дело №'+result.case+'.');
    });
  });
  screen.addEventListener('click',event=>{
    const b=event.target.closest('button');if(!b||b.disabled)return;
    if(b.dataset.person){select(Number(b.dataset.person),false);return;}
    if(b.dataset.pick){
      const id=Number(b.dataset.pick), host=b.closest('.search'), field=host.dataset.field;
      $('.results',host).hidden=true;
      if(field==='tree'){select(id,true);return;}
      chosen[field]=id;const input=$('input',host);input.value=name(id);input.focus();
      if(field==='a'&&['unlink','unsibling','sibling','marry','unmarry'].includes(activeEditor)){
        const reason=$('#edit-reason')?.value||'';
        if(activeEditor==='unmarry'){
          const pair=state.editor?.marriages.find(pair=>pair.includes(id));
          chosen.b=pair?.find(other=>other!==id);
        }
        render();$('#edit-reason').value=reason;
      }
      return;
    }
    const [action,a,c]=(b.dataset.action||'').split(':');
    if(action==='refresh'||action==='cases')run(async()=>{
      if(action==='cases'){caseID=null;casesOffset=Math.max(0,casesOffset+(a==='next'?20:-20));}
      await load();render();
    });
    if(action==='edit'){activeEditor=a;chosen=c?{a:Number(c)}:{};tab='editor';render();}
    if(['unlink','unsibling','revoke','unmarry'].includes(action)){
      activeEditor=action==='unlink'&&a==='0'?'detach':action;chosen={a:Number(a),...(c?{b:Number(c)}:{})};
      run(()=>preview({edit:action,...chosen}));
    }
    if((action==='approve'||action==='reject')&&!busy){
      ask('<p>'+(action==='approve'?'Расторгнуть брак? Родительские связи останутся.':'Отклонить заявление? Брак останется действующим.')+'</p>',async()=>{
        await api('',{op:action,case:Number(a)});await load();render();status('Решение сохранено.');
      });
    }
  });
  const searches=new WeakMap();
  screen.addEventListener('input',event=>{
    const input=event.target;if(!input.matches('.search input'))return;
    const host=input.closest('.search'),field=host.dataset.field,out=$('.results',host);
    if(field!=='tree')delete chosen[field];
    const previous=searches.get(input);if(previous){clearTimeout(previous.timer);previous.control.abort();}
    const q=input.value.trim(), control=new AbortController();
    out.hidden=true;if(q.replace(/^@/,'').length<2)return;
    const timer=setTimeout(async()=>{
      try{
        const hits=await api('/search?q='+encodeURIComponent(q)+(field==='tree'?'':'&directory=1'),null,control.signal);
        if(!input.isConnected||!host.contains(document.activeElement)||control.signal.aborted)return;
        out.innerHTML=hits.map(p=>{
          people.set(p.id,p);
          return '<button type="button" data-pick="'+p.id+'"><strong>'+esc(p.name)+'</strong><small>'+
            esc(p.username?'@'+p.username:'')+(p.in_tree===false?' · вне древа':'')+'</small></button>';
        }).join('')||'<p class="muted" role="status">Никого не найдено</p>';
        out.hidden=false;
      }catch(error){if(error.name!=='AbortError'&&input.isConnected)explain(error);}
    },220);
    searches.set(input,{timer,control});
  });
  screen.addEventListener('focusout',e=>{
    const host=e.target.closest('.search');if(host&&!host.contains(e.relatedTarget))$('.results',host).hidden=true;
  });
  screen.addEventListener('keydown',e=>{
    const host=e.target.closest('.search'),out=host&&$('.results',host);
    if(!out||out.hidden||e.isComposing)return;
    if(e.key==='Escape'){e.preventDefault();out.hidden=true;$('input',host).focus();}
    if(e.target.matches('input')&&(e.key==='Enter'||e.key==='ArrowDown')){
      e.preventDefault();const first=$('button',out);if(e.key==='Enter')first?.click();else first?.focus();
    }
  });
  (async()=>{
    if(!entry||!tg?.initData){screen.textContent='Открой семейный архив из Telegram командой !древо.';return;}
    try{
      await load();
      const [, ,view,a,b]=entry;
      if(view==='file'||view==='court')tab=view;
      if(Object.hasOwn(kinds,view)&&state.owner&&(view!=='unmarry'||state.editor?.marriage_override)){
        tab='editor';activeEditor=a==='0'?{origin:'blank',link:'attach',unlink:'detach'}[view]||view:view;
        chosen={a:Number(a),...(b?{b:Number(b)}:{})};
      }
      render();
      if(view==='find')select(Number(a),true);
      if(tab==='editor'&&a!==undefined)await run(()=>preview(editPayload(activeEditor,chosen)));
    }catch(error){screen.textContent=error.message;}
  })();
})();
