/* Rendering adapter: reuse the production views without editing any skill/view. */
(()=>{'use strict';
function layerContext(ctx){let skipStroke=false;
 return new Proxy(ctx,{get(target,key){
  if(key==='clearRect')return ()=>{};
  if(key==='fillRect')return (x,y,w,h)=>{if(x===0&&y===0&&w===720&&(h===320||h===400))return;if(x===-5&&y===-5&&w===10&&h===10&&target.fillStyle==='#92e2ce')return;if(x===-9&&y===-9&&w===18&&h===18&&target.fillStyle==='#9cd9c9')return;target.fillRect(x,y,w,h);};
  if(key==='fillText')return (text,...args)=>{if(/^(КАСАНИЯ |−\d|ПРИГОТОВЬСЯ|ЗАТЕМ —|ПАЛЕЦ \/|ЩИТ ПОДНЯТ|ОПУСТИ ЩИТ —)/.test(String(text)))return;target.fillText(text,...args);};
  if(key==='beginPath')return ()=>{skipStroke=false;target.beginPath();};
  if(key==='arc')return (x,y,r,...args)=>{if(x===360&&y===200&&[48,92,145].includes(r))skipStroke=true;target.arc(x,y,r,...args);};
  if(key==='stroke')return (...args)=>{if(skipStroke||['#1b3040','#162b3b'].includes(target.strokeStyle))return;target.stroke(...args);};
  const v=Reflect.get(target,key,target);return typeof v==='function'?v.bind(target):v;
 },set(target,key,value){Reflect.set(target,key,value,target);return true;}});
}
function draw(ctx,canvas,s){const Q=QueueExisting,jobs=Q.activeJobs(s.existing,s.time),exclusive=!s.config.strictOverlap&&jobs.find(j=>j.policy.exclusive);ctx.save();
 const height=s.config.mode==='block'?400:320;ctx.scale(1,360/height);const proxy=layerContext(ctx),viewCanvas={clientWidth:canvas.clientWidth};
 for(const job of jobs){const state=job.state;if(state.time<state.preparation)continue;ctx.save();
  const rendered={...state,contacts:[],player:s.config.mode==='block'?state.player:{...state.player,x:s.player.x,y:s.player.y*height/360}};
  const nativeBackground=job.policy.exclusive&&!s.config.strictOverlap;
  if(s.config.mode==='block'){QTEBlockView.draw(nativeBackground?ctx:proxy,viewCanvas,rendered);}else QTEView.draw(nativeBackground?ctx:proxy,viewCanvas,rendered);ctx.restore();
 }
 ctx.restore();return {jobs,ownsPlayer:!!exclusive&&exclusive.state.time>=exclusive.state.preparation};
}
window.QueueExistingView={draw,layerContext};
})();
