/* Isolated playable encounter, using the same queue and unmodified QTE patterns. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./engine.js'):root.ActionQueueLab);if(typeof module==='object'&&module.exports)module.exports=api;else root.PartyBattle=api;})(globalThis,function(A){
'use strict';
const ACTIONS={
 split:{id:'split',name:'Раскол брони',skill:'shot',base:'armor_split',cost:20,cast:1.7,power:65,description:'Быстрее вражеского каста. Полное попадание добивает слабого бомжа.'},
 execute:{id:'execute',name:'Казнь',skill:'shot',base:'warrior_execute',cost:34,cast:3.5,power:105,description:'Мощнее, но медленнее. Бомж может успеть выпустить атаку.'},
 barrier:{id:'barrier',name:'Поставить барьер',skill:'barrier',cost:25,cast:1.3,description:'65 щита на этот раунд. Собственное действие, не перехват.'},
 focus:{id:'focus',name:'Перевести дыхание',skill:'focus',cost:0,cast:1.7,description:'Восстановление 45 энергии при завершении действия.'},
};
const copy=x=>JSON.parse(JSON.stringify(x));
function find(catalog,id){const s=catalog.find(s=>s.base_id===id&&s.origin==='Базовый навык')||catalog.find(s=>s.base_id===id);if(!s)throw new Error('Нет исходного навыка '+id);return s;}
function config(catalog,{scenario='mix',action='split',target='mage',intercept=null,round=1}={}){
 const selected=ACTIONS[action]||ACTIONS.split,full=A.actors(),hero={...full[0],name:'Ты · Воин',sprite:'warrior',hp:280,maxHp:280,mp:100,maxMp:100,speed:20,skill:selected.skill,castOverride:selected.cast,existingSkill:{...find(catalog,selected.base||'armor_split'),cost:selected.cost},target,directDamage:0},
  priest={...full[2],name:'Союзник · Жрец',hp:190,maxHp:190,mp:100,maxMp:100,skill:'heal',castOverride:4.2,target:'hero'},
  bum={...full[3],id:'bum',name:'Бомж',sprite:'ragamuffin',hp:58,maxHp:58,mp:100,maxMp:100,speed:18,skill:'rifle',castOverride:3,existingSkill:{...find(catalog,'bum_punch'),cost:8},attackPower:5,target:'hero',targets:['hero']},
  mage={...full[4],id:'mage',name:'Маг',sprite:'mage',hp:360,maxHp:360,mp:240,maxMp:240,speed:18,skill:'ice',castOverride:3,existingSkill:{...find(catalog,'mana_blob'),cost:24},attackPower:24,target:scenario==='cover'?'priest':'hero',targets:scenario==='sweep'?['hero','priest']:scenario==='cover'?['priest']:['hero']};
 if(selected.skill!=='shot')delete hero.directDamage;
 const cfg={preset:'duo',useExisting:true,multiTarget:true,targetCounts:true,strictOverlap:true,directCombat:true,actors:[hero,priest,bum,mage],target,mode:'dodge',evasion:20,accuracy:85,armor:12,seed:17+(round-1)*997,reactionCost:0,scenario,action,round};
 if(intercept){const source=cfg.actors.find(a=>a.id===intercept&&a.team==='enemies');if(source&&source.targets.length===1&&source.targets[0]==='priest'){source.originalTarget='priest';source.target='hero';source.targets=['hero'];cfg.reactionCost=8;cfg.intercept=source.id;}}
 return cfg;
}
function intents(cfg,previous){return cfg.actors.filter(a=>a.team==='enemies'&&(previous?.actors[a.id]?.hp??a.hp)>0).map(a=>({source:a.id,name:a.name,color:a.color,skill:a.existingSkill.name,targets:a.targets.filter(id=>(previous?.actors[id]?.hp??cfg.actors.find(a=>a.id===id).hp)>0),originalTarget:a.originalTarget||null,count:a.targets.length,at:A.PREPARATION+a.castOverride/(1+a.speed*.018),power:a.attackPower}));}
function plan(catalog,options={},previous=null){
 const cfg=config(catalog,options);
 if(previous){if(previous.actors.priest.hp<=0){const mage=cfg.actors.find(a=>a.id==='mage');mage.target='hero';mage.targets=['hero'];delete mage.originalTarget;cfg.reactionCost=0;delete cfg.intercept;}
  else if(Math.min(previous.actors.priest.maxMp,previous.actors.priest.mp+Math.round(previous.actors.priest.maxMp*.08))<30){const priest=cfg.actors.find(a=>a.id==='priest');priest.skill='focus';priest.target='priest';priest.castOverride=1.7;}
  if(previous.actors[options.target||'mage'].hp<=0){const target=['bum','mage'].find(id=>previous.actors[id].hp>0)||'mage';cfg.target=target;cfg.actors[0].target=target;}}
 return cfg;
}
function start(cfg,previous,damage=0,critical=false){const ready=copy(cfg);if(ready.actors[0].directDamage!==undefined){ready.actors[0].directDamage=damage;ready.actors[0].directCritical=critical;}const state=A.create(ready,previous);state.battleChoice=cfg.action;return state;}
function canStart(cfg,previous){const hero=previous?.actors.hero||cfg.actors[0];const actual=A.SKILLS[cfg.actors[0].skill].kind==='damage'?cfg.actors[0].existingSkill.cost:A.SKILLS[cfg.actors[0].skill].cost;const available=previous?Math.min(hero.maxMp,hero.mp+Math.round(hero.maxMp*.08)):hero.mp;return hero.hp>0&&available>=actual+cfg.reactionCost;}
return {ACTIONS,config,plan,start,intents,canStart};
});
