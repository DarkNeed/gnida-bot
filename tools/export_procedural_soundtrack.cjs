// Offline render of the actual game synthesizer. Does not modify game source.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output','soundtrack-20261104');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 let code=fs.readFileSync(path.join(root,'webapp','arena-audio'),'utf8');
 assert(code.includes("while(next < ctx.currentTime+.18)"));
 code=code.replace("ctx.state !== 'running' || document.hidden || prefs.muted) return;","(!window.__renderLimit && ctx.state !== 'running') || document.hidden || prefs.muted) return;");
 code=code.replace('while(next < ctx.currentTime+.18)','while(next < (window.__renderLimit ?? ctx.currentTime+.18))');
 const expose=`
 window.__soundtrack={themes:Object.entries(THEMES).map(([id,t])=>({id,name:THEME_LABELS[id]||id,bpm:t.bpm})),async render(id){
 const theme=THEMES[id],bars=theme.style==='chaplain'?32:16,rate=24000;
 const length=bars*(theme.beats||4)*60/theme.bpm,seconds=length+7;
 const offline=new OfflineAudioContext(1,Math.ceil(seconds*rate),rate),Original=window.AudioContext;
 ctx=null;voices.clear();roomNodes=[];prefs={muted:false,music:100,effects:0};
 window.AudioContext=function(){return offline;};createContext();window.AudioContext=Original;
 musicBus=ctx.createGain();musicBus.gain.value=1;musicBus.connect(master);createRoom(theme);
 playing=id;step=0;next=.03;window.__renderLimit=length;schedule();delete window.__renderLimit;
 master.gain.setValueAtTime(.65,length);master.gain.linearRampToValueAtTime(0,seconds-.05);
 const rendered=await offline.startRendering(),samples=rendered.getChannelData(0),bytes=new Uint8Array(44+samples.length*2),v=new DataView(bytes.buffer);
 const ascii=(o,s)=>{for(let i=0;i<s.length;i++)bytes[o+i]=s.charCodeAt(i);};
 ascii(0,'RIFF');v.setUint32(4,bytes.length-8,true);ascii(8,'WAVE');ascii(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);ascii(36,'data');v.setUint32(40,samples.length*2,true);
 let peak=0;for(let i=0;i<samples.length;i++){const s=Math.max(-1,Math.min(1,samples[i]));peak=Math.max(peak,Math.abs(s));v.setInt16(44+i*2,s<0?s*32768:s*32767,true);}
 let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));
 return {base64:btoa(binary),seconds,peak};
 }};
 `;
 code=code.replace('  window.ArenaAudio =',expose+'\n  window.ArenaAudio =');
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const manifest=[];
 try{
  const page=await browser.newPage();await page.setContent('<!doctype html><title>Offline soundtrack export</title>');
  await page.addScriptTag({content:code});
  const themes=await page.evaluate(()=>window.__soundtrack.themes);
  for(const theme of themes){
   const r=await page.evaluate(id=>window.__soundtrack.render(id),theme.id);
   assert(r.peak>.001&&Number.isFinite(r.peak));
   fs.writeFileSync(path.join(out,theme.id+'.wav'),Buffer.from(r.base64,'base64'));
   manifest.push({...theme,seconds:r.seconds,peak:r.peak});console.log(theme.id+' '+r.seconds.toFixed(1)+'s');
  }
  fs.writeFileSync(path.join(out,'tracks.json'),JSON.stringify(manifest,null,2));
  fs.writeFileSync(path.join(out,'README.txt'),'GnidaBot procedural soundtrack, exported 2026-11-04.\n'+
   'Actual game Web Audio synthesis; no imported anime recordings. Not a legal clearance certificate.\n'+
   'Finite listening renders of looping themes: 16 bars each, Chaplain 32 bars, plus fading tail.\n'+
   'WAV PCM16 mono, 24000 Hz. Contains music only, not SFX or media/Meow assets.\n'+
   'Source: webapp/arena-audio. Track titles: tracks.json.\n');
  console.log('PASS '+manifest.length+' non-silent music renders');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
