const assert=require('node:assert/strict'),A=require('../tools/action_queue_lab/engine.js');
let raw='';process.stdin.on('data',b=>raw+=b);process.stdin.on('end',()=>{
const catalog=JSON.parse(raw),find=id=>catalog.find(s=>s.base_id===id&&s.origin==='Базовый навык')||catalog.find(s=>s.base_id===id);
function config(mode='dodge'){const c=A.config('crossfire');c.useExisting=true;c.multiTarget=true;c.mode=mode;for(const a of c.actors){a.existingSkill=find({hero:'mana_shot',guard:'armor_split',priest:'holy_strike',gunner:'warning_shot',caster:'mana_shot',duelist:'warrior_execute'}[a.id]);a.target={hero:'gunner',guard:'gunner',priest:'guard',gunner:'hero',caster:'guard',duelist:'priest'}[a.id];}return c;}
function run(c){const s=A.create(c);while(!s.ended&&s.time<90)A.step(s,1/60,{});assert(s.ended);return s;}
for(const mode of ['dodge','block']){
 const c=config(mode),s=run(c),q=s.queue;assert.equal(q.find(a=>a.actor==='caster').target,'guard');assert.equal(q.find(a=>a.actor==='duelist').target,'priest');
 const jobs=Object.values(s.fields).flatMap(f=>f.world.jobs);assert(jobs.some(j=>j.source==='guard'&&j.target==='gunner'&&j.skill.base_id==='armor_split'),'Knight must have original attack scene');assert(jobs.some(j=>j.source==='hero'&&j.target==='gunner'));assert.equal(s.fields.hero.world.jobs.filter(j=>j.source==='guard').length,0,'Outgoing slash must not hit hero');
 assert(s.contacts.some(c=>c.target==='gunner'&&['hero','guard'].includes(c.source)),'Outgoing scenes must actually deal damage');assert(s.contacts.some(c=>c.target==='guard'&&c.source==='caster'),'Enemy must really attack the ally');assert(s.actors.gunner.hp<s.actors.gunner.maxHp);
 assert.equal(s.contacts.filter(c=>c.target==='hero').reduce((n,c)=>n+c.damage,0),s.damage);assert.equal(s.fields.guard.damage,s.contacts.filter(c=>c.target==='guard').reduce((n,c)=>n+c.damage,0));
 assert.notEqual(s.fields.hero.world,s.fields.guard.world);assert.notEqual(s.fields.hero.player,s.fields.guard.player);assert(s.bySource['guard>gunner']);
 const saved=s.actors.guard.hp,next=A.create(c,s);assert.equal(next.actors.guard.hp,saved);assert.equal(next.fields.guard.shield,0);
 console.log('PASS '+mode+': individual targets, original allied attacks, separate fields, real HP and attribution');
}
const deadHero=config();deadHero.actors[0].hp=1;const s=run(deadHero);assert(s.actors.hero.hp===0);assert(s.time>s.contacts.find(c=>c.target==='hero'&&c.damage===1).time,'Allies must continue after hero falls');
const healer=config();healer.actors.find(a=>a.id==='guard').hp=150;const early=A.create(healer);while(early.time<4.1&&!early.ended)A.step(early,1/120,{});assert(early.fields.guard.healed>0);assert.equal(early.fields.hero.healed,0,'Healing must use selected recipient');
const invalid=config();invalid.actors.find(a=>a.id==='caster').target='gunner';assert.equal(A.buildQueue(invalid).find(a=>a.actor==='caster').target,'hero','Hostile skill cannot target own team');
console.log('PASS team survival, selected healing recipient and target validation');
});
