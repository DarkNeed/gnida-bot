/* Reproducible difficulty probes, not a human win-rate estimator or live autopilot. */
const E=require('../webapp/qte-unique/engine');
const policies={idle:()=>({x:0,y:0}),right:()=>({x:1,y:0}),up:()=>({x:0,y:-1}),
  circle:t=>({x:Math.cos(t*1.6),y:Math.sin(t*1.6)}),
  box:t=>[{x:1,y:0},{x:0,y:1},{x:-1,y:0},{x:0,y:-1}][Math.floor(t/.65)%4],
  zigzag:t=>({x:Math.floor(t/.55)%2?1:-1,y:Math.floor(t/1.1)%2?1:-1})};
const sets={hard:{enemyAccuracy:100,evasion:0},equal:{enemyAccuracy:75,evasion:25},easy:{enemyAccuracy:50,evasion:75}};
const ids=['warning_shot','first_line','falling_star','moon_arc','bum_punch','mana_shot','meow','humiliate','smack','red_etude','hunter_shot','holy_judgment'];
function measure(catalog){const result={};
  for(const id of ids){const skill=catalog.find(s=>s.base_id===id&&s.origin==='Базовый навык');if(!skill)continue;
    const p=E.profile(skill);result[id]={};
    for(const [name,stats] of Object.entries(sets)){let clean=0,contacts=0,weight=0,runs=0;
      for(const seed of [3,17,29,43,81])for(const policy of Object.values(policies)){
        const s=E.defense(p,{accuracy:75,enemyEvasion:25,...stats},seed,{damageBase:0,endOnDeath:false});
        while(!s.ended)E.defenseStep(s,1/120,policy(Math.max(0,s.time-s.preparation)));
        clean+=!s.contacts.length;contacts+=s.contacts.length;weight+=s.contacts.reduce((n,c)=>n+c.weight,0);runs++;
      }
      result[id][name]={clean:+(clean/runs).toFixed(3),contacts:+(contacts/runs).toFixed(2),weight:+(weight/runs).toFixed(2)};
    }
  }return result;
}
module.exports=measure;
if(require.main===module){let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>{
  const catalog=JSON.parse(input);
  if(process.argv.includes('--paths')){
    const record=require('./qte_patterns_trace.cjs');
    for(const id of ['warning_shot','bayonet','first_line','last_line','falling_star','moon_arc','silent_cut','bum_punch']){
      const skill=catalog.find(s=>s.base_id===id&&s.origin==='Базовый навык');
      for(const seed of [3,17,29]){
        const r=record({kind:'defense',defense_preparation:1,profile:skill,seed,perfect:true,stats:{accuracy:45,enemyEvasion:70,enemyAccuracy:100,evasion:0}});
        if(r.result.contacts.length)throw new Error('Not clean '+id+' '+seed);
      }
      console.log('PASS reachable at accuracy 100 / evasion 0:',id);
    }
  }else process.stdout.write(JSON.stringify(measure(catalog),null,2));
});}
