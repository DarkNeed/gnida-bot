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
    detach:'Отсоединить ветвь от Истока',link:'Добавить родство',marry:'Внести брак',unlink:'Убрать родство',appoint:'Назначить судью',revoke:'Снять судью'};
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
    if(!state.members.includes(selected)) selected=state.origin;
    if(before!==undefined && before!==state.revision) camera.k=0;
    scene=null;
  }
  function layout() {
    const origin=state.origin, ids=state.members, out=new Map(ids.map(id=>[id,[]])), ins=new Map(ids.map(id=>[id,[]]));
    const partners=new Map(state.marriages.flatMap(([a,b])=>[[a,b],[b,a]]));
    for(const [p,c] of [...state.parents,...(state.branches||[]).map(id=>[0,id])]){out.get(p).push(c);ins.get(c).push(p);}
    const rank=new Map(ids.map(id=>[id,id===origin?0:1]));
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
    for(const p of order)for(const c of out.get(p))rank.set(c,Math.max(rank.get(c),rank.get(p)+1));
    const rows=[];
    for(const id of ids)(rows[rank.get(id)]??=[]).push(id);
    const width=Math.max(510,...rows.map(row=>row.length*187+28)), height=rows.length*114+10, spots=new Map();
    rows.forEach((row,y)=>{
      const slot=new Set(row);
      function weight(id){
        const spouse=partners.get(id), anchors=[...ins.get(id),...(slot.has(spouse)?ins.get(spouse):[])]
          .map(p=>spots.get(p)?.[0]).filter(Number.isFinite);
        return anchors.length?anchors.reduce((a,b)=>a+b,0)/anchors.length:width/2;
      }
      const ranked=row.map(id=>[id,weight(id)]).sort(([a,x],[b,y])=>x-y||a-b);
      const placed=[];
      for(const [id] of ranked)if(slot.delete(id)){
        placed.push(id);
        const p=partners.get(id);if(slot.delete(p))placed.push(p);
      }
      placed.forEach((id,i)=>spots.set(id,[width*(i+.5)/placed.length,49+y*114]));
    });
    return {spots,width,height,partners,ins,out};
  }
  function graph() {
    const {spots,width,height,partners,ins}=scene, paths=[], rings=[], grouped=new Map();
    for(const [a,b] of state.marriages){
      const [x,y]=spots.get(a), [u,v]=spots.get(b), mid=(x+u)/2;
      if(y!==v){
        const end=v+(v>y?-32:32), start=y+(v>y?32:-32);
        paths.push('<path class="spouse" d="M'+x+' '+start+' C'+x+' '+((start+end)/2)+' '+u+' '+((start+end)/2)+' '+u+' '+end+'"/>');
        continue;
      }
      paths.push('<path class="spouse" d="M'+x+' '+y+' H'+u+'"/>');
      rings.push('<span class="ring" aria-hidden="true" style="left:'+mid+'px;top:'+y+'px">💍</span>');
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
  const avatars=new Map();
  function avatarJob(node) {
    const id=Number(node.dataset.avatar);
    if(!avatars.has(id)){
      const promise=fetch(base+'/avatar/'+id,{headers:headers()}).then(r=>r.ok?r.blob():null)
        .then(blob=>blob?URL.createObjectURL(blob):null).catch(()=>null);
      avatars.set(id,promise);
    }
    return avatars.get(id).then(url=>{
      if(url && node.isConnected){const img=new Image();img.alt='';img.src=url;node.replaceChildren(img);}
    });
  }
  function card(id) {
    const [x,y]=scene.spots.get(id), isRoot=id===state.origin, user=people.get(id);
    const handle=user?.username?'@'+user.username:'';
    const avatar=isRoot?'🌌':esc(name(id).trim().slice(0,2).toLocaleUpperCase('ru'));
    return '<button class="person'+(isRoot?' origin':'')+'" type="button" data-person="'+id+'" aria-pressed="'+(id===selected)+
      '" title="'+esc(name(id))+'" style="left:'+x+'px;top:'+y+'px"><span class="avatar" aria-hidden="true"'+(isRoot?'':' data-avatar="'+id+'"')+
      '>'+avatar+'</span><span class="caption"><strong>'+esc(name(id))+'</strong><small>'+esc(id===0?'Начало древа':isRoot?'Первородный':handle)+'</small></span></button>';
  }
  const picker=(field,label,value='')=>'<div class="search" data-field="'+field+'"><label><span>'+esc(label)+
    '</span><input type="search" value="'+esc(value)+'" placeholder="Имя или @ник" autocomplete="off"></label><div class="results" hidden></div></div>';
  function selectedInfo(){
    const party=scene.partners.get(selected), children=scene.out.get(selected)||[];
    if(selected===0)return '<strong>🌌 Исток</strong> · ветвей: '+children.length;
    return '<strong>'+esc(name(selected))+'</strong> · родители: '+(scene.ins.get(selected)?.filter(id=>id!==0).length||0)+' · дети: '+children.length+
      (party===undefined?'':' · в браке: '+esc(name(party)));
  }
  function tree() {
    if(state.origin==null) return '<section class="panel stack"><h2>Общее древо чата</h2><p class="muted">Владелец ещё не назначил Исток.</p>'+
      (state.owner?button('Создать пустой Исток','edit:blank','primary')+' '+button('Назначить участника','edit:origin'):'')+'</section>';
    scene??=layout();
    return '<section class="panel"><div class="heading"><div><h2>Общее древо чата</h2><p class="muted">Людей в древе: '+(state.members.length-(state.origin===0?1:0))+
      '</p></div>'+picker('tree','Найти в древе')+'</div><div class="map"><div class="pan" role="group" aria-label="Карта родства">'+
      '<div class="world" style="width:'+scene.width+'px;height:'+scene.height+'px">'+graph()+state.members.slice().sort((a,b)=>
        scene.spots.get(a)[1]-scene.spots.get(b)[1]||scene.spots.get(a)[0]-scene.spots.get(b)[0]).map(card).join('')+'</div></div></div>'+
      '<div class="map-controls"><div class="legend"><span>Родство</span><span class="married">Брак</span>'+
      (state.origin===0?'<span class="attached">Ветвь Истока</span>':'')+'</div><div class="actions">'+
      '<output aria-label="Масштаб" class="muted"></output>'+button('−','zoom:out')+button('+','zoom:in')+button('Всё древо','zoom:fit')+
      button('К Истоку','zoom:root')+'</div></div><p class="selected muted" aria-live="polite">'+selectedInfo()+'</p></section>';
  }
  function mountMap() {
    const pan=$('.pan',screen);if(!pan)return;
    const world=$('.world',pan), indicator=$('output',screen), {width,height,spots}=scene;
    const pointers=new Map(), rect=()=>pan.getBoundingClientRect(), mid=()=>[pan.clientWidth/2,pan.clientHeight/2];
    let dragged=false, stopped=false, running=0;
    const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
    const fitScale=()=>Math.min(1,(pan.clientWidth-12)/width,(pan.clientHeight-12)/height);
    function draw(){
      const [mx,my]=mid(), edgeX=Math.min(55,width*camera.k/2,mx),edgeY=Math.min(55,height*camera.k/2,my);
      camera.x=clamp(camera.x,edgeX-width*camera.k,mx*2-edgeX);
      camera.y=clamp(camera.y,edgeY-height*camera.k,my*2-edgeY);
      world.style.transform='translate('+camera.x+'px,'+camera.y+'px) scale('+camera.k+')';
      pan.style.backgroundPosition=(camera.x%21)+'px '+(camera.y%21)+'px';
      indicator.value=Math.round(camera.k*100)+'%';
    }
    function go(x,y,k){const [mx,my]=mid();camera={k,x:mx-x*k,y:my-y*k};draw();}
    const fit=()=>go(width/2,height/2,fitScale());
    center=id=>{const point=spots.get(id);if(point)go(...point,Math.max(.9,camera.k));};
    if(!camera.k){
      if(fitScale()>=.58) fit();
      else {center(state.origin);camera.y=15;draw();}
    }else draw();
    function zoom(k, ox,oy,nx=ox,ny=oy){
      const next=clamp(k,Math.min(.18,fitScale()),2.1), ratio=next/camera.k;
      camera={k:next,x:nx-(ox-camera.x)*ratio,y:ny-(oy-camera.y)*ratio};draw();
    }
    const tools=e=>{
      const action=e.target.closest('[data-action^="zoom:"]')?.dataset.action;
      if(action==='zoom:fit')fit();
      if(action==='zoom:root')select(state.origin,true);
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
    const queue=new Set();
    function pump(){
      while(!stopped&&running<3&&queue.size){
        const [node]=queue;queue.delete(node);observe.unobserve(node);running++;
        avatarJob(node).finally(()=>{running--;pump();});
      }
    }
    const observe=new IntersectionObserver(entries=>{
      for(const e of entries)if(e.isIntersecting)queue.add(e.target);else queue.delete(e.target);
      pump();
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
  const resultNames={open:'На рассмотрении',approved:'Брак расторгнут',rejected:'Заявление отклонено'};
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
    const wedding=activeEditor==='marry', two=wedding||['link','unlink'].includes(activeEditor);
    const selectedPerson=chosen.a, related=(state.editor?.parents||[]).filter(p=>p.includes(selectedPerson));
    const marriage=(state.editor?.marriages||[]).find(pair=>pair.includes(selectedPerson));
    const branchMode=activeEditor==='attach'||activeEditor==='detach';
    const fields=activeEditor==='blank'?'<p class="muted">Галактика без привязки к игроку. Существующее древо сохранится.</p>':
      branchMode?picker('b','Участник в начале ветви',chosen.b?name(chosen.b):''):
      picker('a',wedding?'Первый супруг':two?'Родитель':'Участник',chosen.a?name(chosen.a):'')+
      (two?picker('b',wedding?'Второй супруг':'Ребёнок',chosen.b?name(chosen.b):''):'');
    return '<section class="panel stack"><h2>Редактор связей</h2><form class="stack" id="edit"><label>Действие<select id="edit-kind">'+
      Object.entries(kinds).filter(([id])=>state.origin===0||id===activeEditor||!['attach','detach'].includes(id))
        .map(([id,label])=>'<option value="'+id+'"'+(id===activeEditor?' selected':'')+'>'+label+'</option>').join('')+
      '</select></label><div class="'+(two?'fields':'')+'">'+fields+'</div>'+
      (wedding?'<p class="muted">Запись вносится вручную, без отправки предложения в чат. Расторгнуть брак можно только через суд.</p>':'')+
      '<label>Заметка для журнала<textarea id="edit-reason" name="reason" rows="2" maxlength="500"></textarea></label>'+
      '<button class="primary">Проверить правку</button></form>'+
      (related.length?'<div class="stack"><h3>Родство выбранного участника</h3>'+related.map(([a,b])=>'<div class="row"><span>'+esc(name(a))+' → '+esc(name(b))+'</span>'+
        button('Убрать','unlink:'+a+':'+b,'danger')+'</div>').join('')+'</div>':'')+
      (marriage?'<p class="muted">💍 '+marriage.map(id=>esc(name(id))).join(' и ')+' · расторжение только через суд</p>':'')+'</section>'+
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
      (result.marriage_visible===false?'<p>Брак сохранится в архиве. Линия появится на карте, когда оба супруга будут в древе.</p>':'')+
      list(result.added,'Появятся в древе')+
      list(result.removed,'Вне древа после правки'),async()=>{
        await api('',{op:'apply',revision:result.revision,proof:result.proof,...payload});
        await load();render();status(payload.edit==='marry'?'Брак внесён в архив.':'Правка сохранена.');
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
      if(field==='a'&&activeEditor==='unlink')render();
      return;
    }
    const [action,a,c]=(b.dataset.action||'').split(':');
    if(action==='refresh'||action==='cases')run(async()=>{
      if(action==='cases'){caseID=null;casesOffset=Math.max(0,casesOffset+(a==='next'?20:-20));}
      await load();render();
    });
    if(action==='edit'){activeEditor=a;chosen={};tab='editor';render();}
    if(action==='unlink'||action==='revoke'){
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
      if(Object.hasOwn(kinds,view)&&state.owner){
        tab='editor';activeEditor=a==='0'?{origin:'blank',link:'attach',unlink:'detach'}[view]||view:view;
        chosen={a:Number(a),...(b?{b:Number(b)}:{})};
      }
      render();
      if(view==='find')select(Number(a),true);
      if(tab==='editor'&&a!==undefined)await run(()=>preview(editPayload(activeEditor,chosen)));
    }catch(error){screen.textContent=error.message;}
  })();
})();
