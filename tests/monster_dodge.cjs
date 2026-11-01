/* Offline balance probe. Uses visible telegraphs, 200ms reaction and held input;
 * never loaded by the game, and never reads future waves or random seeds. */
const E=require('../webapp/qte-unique/engine');
const moves=[{x:0,y:0},...Array.from({length:8},(_,i)=>({x:Math.cos(i*Math.PI/4),y:Math.sin(i*Math.PI/4)}))];
function clone(s){return {...s,player:{...s.player},events:[],hazards:s.hazards.filter(h=>h.at<=s.time-.20).map(h=>({...h})),contacts:[],received:[],hitIds:s.hitIds.slice()};}
function control(s){
 let best=moves[0],score=Infinity;
 for(const move of moves){
  const trial=clone(s);
  E.defenseStep(trial,.55,move);
  let risk=trial.contacts.reduce((n,c)=>n+c.weight,0)*1000;
  for(const h of trial.hazards)if(h.start<=trial.time+.18&&E.touches(h,trial.player,trial.player,Math.max(trial.time,h.start),0))risk+=20;
  risk+=Math.hypot(trial.player.x-360,trial.player.y-160)/1500;
  if(risk<score){score=risk;best=move;}
 }
 return best;
}
function run(skill,stats,seed,policy='reactive'){
 const s=E.defense(E.profile(skill),stats,seed,{damageBase:0,hp:1000000,endOnDeath:false});
 const proof={ticks:Math.round(s.duration*120),inputs:[]};let command={},last='',next=0;
 for(let tick=0;tick<proof.ticks;tick++){
  if(tick>=next){
   command=policy==='idle'?{}:policy==='circle'?{x:Math.cos(s.time*1.6),y:Math.sin(s.time*1.6)}:control(s);
   next=tick+18; // A player changes direction at most once every 150ms.
   const encoded=JSON.stringify(command);if(encoded!==last){proof.inputs.push({t:tick,...command});last=encoded;}
  }
  E.defenseStep(s,1/120,command);
 }
 return {proof,hits:s.contacts.length,weight:s.contacts.reduce((n,c)=>n+c.weight,0),contacts:s.contacts.map(c=>({id:c.id,strike:c.strike,weight:c.weight,tier:c.tier,tick:Math.round(c.time*120)}))};
}
module.exports={run,control};
if(require.main===module){let data='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>data+=s);process.stdin.on('end',()=>{
 const cases=JSON.parse(data);process.stdout.write(JSON.stringify(cases.map(c=>({skill:c.skill.base_id,tier:c.skill.npc_tier,seed:c.seed,...run(c.skill,c.stats,c.seed,c.policy)}))));
});}
