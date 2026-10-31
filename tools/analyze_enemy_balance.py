"""Deterministic crude movement probes, not a claim about human difficulty."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_guild_rules import MONSTERS, SKILLS, RANKS


def main():
    cases=[]
    for mid,m in MONSTERS.items():
        if m['rank'] not in ('B','A','S'):continue
        tier=max(0,min(4,RANKS.index(m['rank'])-2))
        for sid in m['skills']:
            skill=SKILLS[sid]
            cases.append(dict(monster=mid,rank=m['rank'],skill=dict(id=sid+':probe',base_id=sid,name=skill.name,class_id=skill.class_id,damage_type=skill.damage_type,
                tags=list(skill.tags),strikes=3 if 'three_strike' in skill.tags else 1,npc_tier=tier,monster_pattern=2)))
    script="""
const E=require('./webapp/qte-unique/engine');let input='';process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>{
const results=JSON.parse(input).map(c=>{const probes={};for(const policy of ['idle','edge','circle','zigzag']){let clean=0,hits=0;for(const seed of [17,89,323]){
const s=E.defense(E.profile(c.skill),{accuracy:98,enemyEvasion:0,enemyAccuracy:98,evasion:0},seed,{damageBase:0,hp:100000,endOnDeath:false});
for(let tick=0;tick<936;tick++){const t=tick/120,move=policy==='idle'?{}:policy==='edge'?{target:{x:20,y:20}}:policy==='circle'?{x:Math.cos(t*2),y:Math.sin(t*2)}:{x:Math.floor(t)%2?1:-1,y:Math.floor(t*2)%2?1:-1};E.defenseStep(s,1/120,move);}hits+=s.contacts.length;if(!s.contacts.length)clean++;}probes[policy]={clean,hits};}return {monster:c.monster,rank:c.rank,skill:c.skill.base_id,probes};});process.stdout.write(JSON.stringify(results,null,2));});
"""
    output=subprocess.run(['node','-e',script],input=json.dumps(cases),cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',check=True)
    print(output.stdout)


if __name__=='__main__':main()
