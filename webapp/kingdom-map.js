/* Code-native fantasy atlas. All geometry is decorative; legal land is server-owned. */
(()=>{
 'use strict';
 const center=t=>[45+t.q*60+(t.r%2)*30,46+t.r*52];
 const defs=`<defs>
 <radialGradient id="k-earth"><stop stop-color="#49624d"/><stop offset="1" stop-color="#243a35"/></radialGradient>
 <linearGradient id="k-basalt" x2=".8" y2="1"><stop stop-color="#746f70"/><stop offset="1" stop-color="#353940"/></linearGradient>
 <linearGradient id="k-snow" x2="1" y2="1"><stop stop-color="#bbc6bb"/><stop offset="1" stop-color="#697e79"/></linearGradient>
 <pattern id="k-ink" width="17" height="23" patternUnits="userSpaceOnUse"><path d="M1 3h3m8 10 2-1M5 20h1" stroke="#b2b18b" opacity=".09"/></pattern>
 <g id="k-tree1"><path d="M0 5v11" stroke="#786c46" stroke-width="2"/><path d="m0-23-10 15h5l-10 12h7l-10 11q18 7 36 0L8 4h7L5-8h5Z" fill="#203f35" stroke="#617659" stroke-width=".7"/><path d="M0-19 1 10M-8 3 0 6 8 3m-5-9L0-3-4-6" fill="none" stroke="#7d8e66" opacity=".45"/></g>
 <g id="k-tree2"><path d="M0 0v15m0-7-7-8m7 3L8-7" stroke="#756f4a" stroke-width="2"/><path d="M-13 1q-8-10 1-17-2-14 11-13 13-6 17 7 15 3 9 16-1 12-15 11Z" fill="#3c5741" stroke="#7d8c60" stroke-width=".6"/><path d="M-8-16q5-10 13-4m-17 17 8-2" fill="none" stroke="#8a986a" opacity=".5"/></g>
 <g id="k-peak"><path d="m-29 20 11-15 7-23 9-16 9 13 6 23 20 18Z" fill="url(#k-basalt)" stroke="#263832" stroke-width="1.2"/><path d="M-2-34 7-21 13 2 3-4 0 3-6-9-15 0-11-18Z" fill="url(#k-snow)"/><path d="m-2-29 0 18 9 23m-18-25-6 25M13 3l8 12" fill="none" stroke="#c2c9b4" opacity=".3"/></g>
 <g id="k-cottage"><path d="M0 2 9-6l12 8v15H0Z" fill="#b1a084" stroke="#343e36"/><path d="m-3 3 12-12 15 12-13-3Z" fill="#685346" stroke="#312f2a"/><path d="M10 8v9M4 7h3m8 1h3" stroke="#564c3d" stroke-width="2"/></g>
 <g id="k-tower"><path d="M0-6h13v28H0Z" fill="#929883" stroke="#313e35"/><path d="M-2-6 6-18 15-6Z" fill="#505d55" stroke="#313e35"/><path d="M6 0v6m0 5v7" stroke="#293a32" stroke-width="3"/><path d="M0 10h3m7 0h3M0 18h3" stroke="#c0b797"/></g>
 <g id="k-keep"><path d="M-7 0H19V28H-7Z" fill="#9d9f87" stroke="#2b3d35"/><path d="M-10 0 6-18 22 0Z" fill="#52615b" stroke="#293e36"/><path d="M2 28V16q4-5 8 0v12M1 4v6m10-6v6" stroke="#2c4037" fill="#3a4a3d"/><path d="M-7 11h5m16 0h5M-7 23h4" stroke="#c5bea3"/></g>
 <g id="k-ruin"><path d="M0 30V0l10 3 4-7 8 10 11-2v26M4 8h6m12 2h7M0 18h10m12 1h11" fill="#7a8873" stroke="#2a3b34"/><path d="m-4 30 10-5 6 5m12 0 8-5 8 5" fill="#5e755b"/></g>
 </defs>`;
 function background(view){
  const river=view.tiles.filter(t=>t.terrain==='river').sort((a,b)=>a.r-b.r).map(center);
  const path=river.length?'M'+river[0][0]+' -20 '+river.map(([x,y],i)=>i?'Q'+river[i-1][0]+' '+(y-26)+' '+x+' '+y:'L'+x+' '+y).join(' ')+' l18 90':'';
  return defs+`<rect width="964" height="652" fill="url(#k-earth)"/>
   <g fill="none" stroke="#98aa7e" stroke-width="1" opacity=".10"><path d="M-20 175Q130 90 210 170T470 85 740 135 990 50M-30 195Q130 115 220 190T480 110 750 160 980 75M30 485Q160 345 300 470T590 470 970 360M20 510Q170 365 310 495T600 495 990 380"/></g>
   <rect width="964" height="652" fill="url(#k-ink)"/>
   <path d="${path}" fill="none" stroke="#718573" stroke-width="41" opacity=".4"/>
   <path d="${path}" fill="none" stroke="#284e60" stroke-width="31"/>
   <path d="${path}" fill="none" stroke="#80b3bb" stroke-width="1.8" opacity=".5"/>
   <path d="M-10 306Q250 300 390 308T680 305 980 309" fill="none" stroke="#332f26" stroke-width="12"/>
   <path d="M-10 306Q250 300 390 308T680 305 980 309" fill="none" stroke="#b6a582" stroke-width="5" opacity=".7"/>`;
 }
 function art(tile,towns){
  const owner=towns.find(t=>t.id===tile.town),e=owner?.estate,land=e?.tiles?.[tile.q+':'+tile.r];
  if(tile.camp){const c=tile.camp,ruin=c.status==='ruins';return '<g class="k-live-camp '+(ruin?'ruin':'')+'"><ellipse cy="17" rx="28" ry="10" fill="#09121b" opacity=".8"/>'+(ruin?'<use href="#k-ruin" x="-18" y="-15"/>':'<path d="M-27 16V-5l4-6 4 6v22m4 0V-9l4-5 4 5v27m7 0V-9l4-5 4 5v26m5 0V-5l4-6 4 6v21M-28 5h56" fill="#655449" stroke="#2a252a" stroke-width="2"/><path d="M-16 12 0-20 17 12Z" fill="'+c.color+'" stroke="#24272b"/><path d="M-3 12V2h6v10M0-22v-17l19 5-19 6" fill="#202631" stroke="'+c.color+'"/><circle cx="10" cy="-34" r="2" fill="#f1dfb5"/>')+'<rect x="-25" y="23" width="50" height="4" rx="2" fill="#13212c"/><rect x="-25" y="23" width="'+(50*c.hp/c.max_hp)+'" height="4" rx="2" fill="'+c.color+'"/>'+(c.busy?'<circle cx="23" cy="-15" r="5" fill="#e7b56a"/>':'')+'</g>';}
  if(land?.decoration&&land.decoration!=='none'&&!towns.some(t=>t.q===tile.q&&t.r===tile.r))return decor(land.decoration,e.color);
  if(tile.site?.kind==='war')return '<g class="k-mini-war"><ellipse cy="16" rx="28" ry="10" fill="#152021" opacity=".7"/><path d="M-23 15V-4l5-7 5 7v20m5 1V-8l5-7 5 7v25m5-1V-4l5-7 5 7v19M-24 6h48" fill="#776b54" stroke="#29362e" stroke-width="1.5"/><path d="M0-18v-25l23 5-23 7" fill="#9b6967" stroke="#343b32"/><path d="m5-36 8 7m-8 0 8-7" stroke="#d8c2a2" stroke-width="2"/></g>';
  const capital=towns.find(t=>t.q===tile.q&&t.r===tile.r);
  if(capital)return '<g class="k-mini-town k-estate-'+(e?.style||'frontier')+' '+(capital.own?'own':'')+'" style="--estate-color:'+(e?.color||'#91b9bc')+'"><ellipse cy="16" rx="30" ry="11" fill="#101d1e" opacity=".6"/>'+(capital.stage>1?'<use href="#k-tower" x="-23" y="-8"/><use href="#k-tower" x="12" y="-8"/><path d="M-20 14V2H20V14" fill="#7b7c69" stroke="#252c29" stroke-width="2"/><use href="#k-keep" x="-6" y="-9"/>':'<use href="#k-cottage" x="-23" y="-5"/><use href="#k-cottage" x="5" y="0"/><use href="#k-tower" x="-6" y="-10"/><path d="M-30 15Q0 27 30 15M-25 14v7m10-4v7m10-3v6m10-6v6m10-10v7m10-10v7" fill="none" stroke="#9c8360" stroke-width="2"/>')+(capital.stage===3?'<path d="M0-40 3-31 10-36 7-26H-7L-10-36-3-31Z" fill="#e2c078"/>':'')+townAccents(e)+'<path d="M6-31v-15l18 4-18 5" class="k-town-flag" style="fill:var(--estate-color)"/><text x="12" y="-38" font-size="7" fill="#12202b">'+({crown:'♛',moon:'☾',sun:'☀',skull:'☠',rose:'✿',tower:'♜'}[e?.emblem]||'♛')+'</text></g>';
  if(tile.site){const s=tile.site;return '<g class="k-mini-site"><ellipse cy="15" rx="27" ry="11" fill="#101b20" opacity=".6"/>'+(s.kind==='faction'?'<use href="#k-keep" x="-7" y="-9"/><path d="M9-32v-16l17 5-17 5" fill="'+({velvet:'#c388b4',heating:'#ba8c58',light:'#d2ca91',grave:'#7caa9c'}[s.target]||'#b8a3cf')+'" stroke="#292a29"/>':s.kind==='boss'?'<path d="M-21 15-15-10-5-4 0-32 10-8 17-17 23 15Z" fill="url(#k-basalt)" stroke="#25272e"/><ellipse cy="-1" rx="10" ry="13" fill="#15121d"/><circle cy="-1" r="5" fill="#b67099" opacity=".8"/><path d="M-8-25 0-38 9-24" fill="none" stroke="#d8c189" stroke-width="1.3"/>':'<use href="#k-ruin" x="-18" y="-17"/><path d="M-10 12v-13q10-14 20 0v13" fill="#0e1a1e"/><path d="M-3 6h6" stroke="#e2bb75"/>')+'</g>';}
  const variant=(tile.q*31+tile.r*17)%7;
  if(tile.terrain==='forest')return '<g opacity=".8">'+Array.from({length:3},(_,i)=>{const x=((i*19+variant*7)%43)-21,y=((i*13+variant*5)%23)-7,scale=.6+(i%3)*.1;return '<use href="#k-tree'+((i+variant)%3===0?'2':'1')+'" transform="translate('+x+' '+y+') scale('+scale+')"/>';}).join('')+'</g>';
  if(tile.terrain==='hills')return '<g opacity=".85"><use href="#k-peak" transform="translate(-12 6) scale(.6)"/><use href="#k-peak" transform="translate(9 0) scale(.78)"/></g>';
  if(tile.terrain==='river')return '';
  return '<g class="k-meadow"><path d="m-20 9 2-4 2 4m17-12 2-3 2 3m14 12 2-4 2 4" fill="none" stroke="#819474" opacity=".5"/>'+(variant===0&&tile.terrain!=='road'?'<path d="M-12 13V2m-4 6h8" stroke="#b0ae84"/><ellipse cx="-12" cy="15" rx="6" ry="2" fill="#253f35"/>':'')+'</g>';
 }
 function decor(kind,color){
  const shapes={lanterns:'<path d="M-19 16v-35h8m25 35v-35h8" stroke="#8a9b9c"/><circle cx="-11" cy="-15" r="4" fill="#f2d289"/><circle cx="22" cy="-15" r="4" fill="#f2d289"/>',garden:'<ellipse cy="12" rx="26" ry="12" fill="#385546"/><path d="M-20 12Q0-12 21 12M0 18V-6" fill="none" stroke="#acc391"/><circle cy="-6" r="6" fill="'+color+'"/>',statue:'<path d="M-13 18h26v-5H-13ZM-5 13V-7h10v20m-10-16-10 8m20-8 10 8" fill="#aeb8af" stroke="#758991"/><circle cy="-13" r="6" fill="#bac1b4"/>',cemetery:'<path d="M-20 17v-20m-6 6h12M0 20V-10m-7 8H7m14 17V-1m-5 6h10" stroke="#a8b3a8" stroke-width="3"/>',road:'<path d="M-28 15 25-15" stroke="#9a9b8c" stroke-width="15"/><path d="M-23 10 24-17M-15 15 29-10m-38 0 7 10m5-18 7 9m5-16 7 10" stroke="#50605e" fill="none"/>'};
  return '<g class="k-land-decoration">'+(shapes[kind]||'')+'</g>';
 }
 function townAccents(e){
  if(!e)return '';
  const styles={gothic:'<path d="m-25-11 3-18 3 18m20-13 5-17 5 17" fill="#353748" stroke="#a2a1b7"/>',holy:'<circle cy="-29" r="11" fill="none" stroke="#ded4a0"/><path d="M0-43v20m-6-13h12" stroke="#ded4a0"/>',grave:'<path d="M-28 17V5m-5 4h10m42 8V1m-5 5h10" stroke="#91bbb2" stroke-width="3"/><ellipse cy="14" rx="27" ry="8" fill="#77ae9f" opacity=".2"/>',velvet:'<path d="M-22-18Q0-6 21-18v8Q0 2-22-10Z" fill="#995782"/>',scrap:'<path d="m-30 15 2-22 7 3 2 19m34 0 2-24 7 4 4 20" fill="#77644c" stroke="#ad936b"/>'};
  return (styles[e.style]||'')+(e.specials?.includes('wonder')?'<path d="M0-48v-20m-12 10 12-10 12 10-12 10Z" fill="#ddc184" stroke="#fff0bd"/>':'')+(e.specials?.includes('temple')?'<path d="M-31 15V-9l5-8 5 8v24" fill="#b8b593" stroke="#65736d"/>':'');
 }
 const foreground=`<g class="k-atlas-ink"><text x="125" y="74" transform="rotate(-8 125 74)">ШЕПЧУЩИЙ ЛЕС</text><text x="685" y="584" transform="rotate(-4 685 584)">ПУСТОШИ ПЕПЛА</text><text x="320" y="446" transform="rotate(66 320 446)">ТИХАЯ</text></g><g class="k-compass" transform="translate(908 590)"><circle r="31"/><circle r="26"/><path d="M0-43 7-7 40 0 7 7 0 43-7 7-40 0-7-7Z"/><path d="M-20-20 0-7 20-20 7 0 20 20 0 7-20 20-7 0Z"/><text y="-48">С</text></g><rect x="10" y="10" width="944" height="632" rx="7" fill="none" stroke="#c4b98b" stroke-opacity=".28" pointer-events="none"/>`;
 function marker(e){
  const symbol={moon:'<path d="M-3-8a8 8 0 1 0 9 10A9 9 0 0 1-3-8Z"/>',star:'<path d="m0-10 3 7 8 1-6 5 2 8-7-4-7 4 2-8-6-5 8-1Z"/>',sun:'<circle r="5"/><path d="M0-12v3m0 18v3M-12 0h3m18 0h3M-8-8l2 2M6 6l2 2M-8 8l2-2M6-6l2-2"/>',cart:'<path d="M-10 3h17V-5H-7l-3 8Zm1 2-2 4m17-4 2 4M-3-9h4"/><circle cx="-6" cy="9" r="2"/><circle cx="5" cy="9" r="2"/>'}[e.icon];
  return '<g class="k-timed-marker '+(e.claimed?'claimed':'')+'" transform="translate(18 -22)" pointer-events="none"><circle r="16"/>'+symbol+'</g>';
 }
 function lights(view){return view.towns.map(t=>{const[x,y]=center(t);return '<g class="k-night-lights" pointer-events="none"><circle cx="'+x+'" cy="'+(y+3)+'" r="13" fill="#f8c76f" opacity=".14"/><circle cx="'+x+'" cy="'+(y+3)+'" r="2" fill="#ffe2a0"/></g>';}).join('');}
 window.KingdomAtlas={background,art,foreground,marker,lights,decor};
})();
