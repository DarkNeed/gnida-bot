import unittest
import json
from pathlib import Path
from test_ainz_phases import encounter
from arena_ainz_phases import SUMMON_COOLDOWN
from arena_nazarick import SKILLS,summon,set_intent
from arena_ainz_patterns import shapes
from arena_qte_patterns import profile,difficulty


class AinzPressureTests(unittest.TestCase):
    def test_harvest_route_from_real_shared_spawn_replays_without_damage(self):
        from arena_qte_combined import combine,replay
        f=json.loads((Path(__file__).with_name('fixtures')/'ainz-harvest-route.json').read_text())
        member=dict(f['challenge'],version=2,encounter_enemy='boss',defense_mode='dodge',strikes=1,name='Жатва',damage_base=40)
        stage=combine([member],10,1000)
        result=replay(stage,f['proof'],30)
        self.assertEqual(result['sources']['boss']['pattern_dodge']['contacts'],[])

    def test_fourth_phase_has_dense_fast_mobile_salvos(self):
        event=dict(index=0,jitter=.4,angle=.8,at=1.18)
        for move,minimum in ((1,24),(2,31),(3,20)):
            hs=shapes(self.state(4,move),event)
            bolts=[h for h in hs if h['type']=='bullet']
            self.assertGreaterEqual(len(bolts),minimum)
            self.assertTrue(all((h['vx']**2+h['vy']**2)**.5>=209.999 for h in bolts))
        split=shapes(self.state(4,1),event)
        self.assertTrue(any(h.get('ainzPath')=='slidePolyline' for h in split))
        harvest=shapes(self.state(4,2),event)
        sweeps=[h for h in harvest if h.get('ainzPath')=='sweepLine']
        self.assertEqual(len(sweeps),2)
        self.assertTrue(all(h['dy']<0 for h in sweeps))

    def test_unnamed_execution_move_keeps_previous_version(self):
        hs=shapes(self.state(4,0),dict(index=0,jitter=.4,angle=.8,at=1.18))
        bolts=[h for h in hs if h['type']=='bullet']
        self.assertEqual(len(bolts),5)
        self.assertTrue(all(h['motif']=='crystal' and h['returnAt']==.85 and h['delay']==1.5 for h in bolts))
        self.assertTrue(all(abs((h['vx']**2+h['vy']**2)**.5-140)<1e-8 for h in bolts))
        sweep=next(h for h in hs if h.get('ainzPath')=='sweepLine')
        self.assertEqual((abs(sweep['dy']),sweep['duration'],sweep['delay']),(90,.72,.65))
        ring=next(h for h in hs if h['type']=='ring')
        self.assertEqual((ring['gapWidth'],ring['delay'],ring['duration']),(1.45,1.0,1.5))

    def test_time_stop_is_three_independent_slotted_curtains(self):
        event=dict(index=0,jitter=.4,angle=.8,at=1.18)
        a=self.state(6,0);b=self.state(6,0);b['player']=dict(x=520,y=55)
        hs=shapes(a,event);self.assertEqual(hs,shapes(b,event))
        bolts=[h for h in hs if h.get('timeWall') is not None]
        self.assertEqual({h['timeWall'] for h in bolts},{0,1,2})
        self.assertGreater(len(bolts),25)
        self.assertTrue(all(h['ainzPath']=='wave' and h['amplitude']>0 for h in bolts))

    def test_live_boss_presentation_has_no_tactical_solution(self):
        from arena_ainz_phases import presentation
        from arena_nazarick import set_intent
        for phase in range(1,7):
            d=encounter(phase);v=presentation(d)
            self.assertTrue(all(k not in v for k in ('strength','weakness','advice')))
            self.assertNotIn('Уязвимость',{p['name'] for p in d['boss']['passive_details']})
        d=encounter(6);d['boss']['own_turns']=1;set_intent(d)
        self.assertNotIn('4%',d['enemy_intents']['boss']['text'])

    def state(self,phase,move):
        sid=f'nz_ainz6_p{phase}_{move}'
        return dict(p=profile(dict(id=sid,base_id=sid,name=sid,class_id='raid',damage_type='magic')),
                    player=dict(x=360,y=160),d=difficulty(dict(accuracy=100,enemyEvasion=0,enemyAccuracy=100,evasion=0)),preparation=1)

    def test_summon_uses_boss_actions_not_party_rounds_and_never_refills_one_survivor(self):
        d=encounter();summon(d);m=d['nazarick'];boss=d['boss'];ready=m['ainz_summon_ready']
        self.assertEqual(ready-boss.get('own_turns',0),SUMMON_COOLDOWN)
        d['enemies']['boss_lich']['hp']=0;boss['own_turns']=ready+10;d['round']=10000
        m['ainz_preview_move']=2;set_intent(d)
        self.assertEqual(d['enemy_intents']['boss']['kind'],'attack')
        summon(d);self.assertEqual(d['enemies']['boss_lich']['hp'],0)
        d['enemies']['boss_knight']['hp']=0;boss['own_turns']=ready-1
        set_intent(d);self.assertEqual(d['enemy_intents']['boss']['kind'],'attack')
        summon(d);self.assertEqual(d['enemies']['boss_lich']['hp'],0)
        boss['own_turns']=ready;set_intent(d)
        self.assertEqual(d['enemy_intents']['boss']['kind'],'summon')
        summon(d);self.assertGreater(d['enemies']['boss_lich']['hp'],0)
        self.assertEqual(m['ainz_summon_ready'],ready+SUMMON_COOLDOWN)
        self.assertEqual(SKILLS['nz_ainz6_p1_2'].cooldown,SUMMON_COOLDOWN)

    def test_heavy_earth_and_electric_circuit_have_distinct_mechanics(self):
        event=dict(index=0,jitter=.4,angle=.8,at=1.18)
        axe=[h for move in range(4) for h in shapes(self.state(4,move),event)]
        knight=[h for move in range(4) for h in shapes(self.state(5,move),event)]
        self.assertIn('rubble',{h.get('motif') for h in axe})
        self.assertIn('ring',{h['type'] for h in axe})
        self.assertNotIn('ricochet',{h.get('ainzPath') for h in axe})
        self.assertIn('ricochet',{h.get('ainzPath') for h in knight})
        self.assertIn('conductor',{h.get('motif') for h in knight})
        self.assertNotIn('rubble',{h.get('motif') for h in knight})
        self.assertFalse(any(h.get('returnAt') for h in knight))

    def test_time_stop_boundaries_wait_for_player_release(self):
        s=self.state(6,0);event=dict(index=0,jitter=.4,angle=.8,at=1.18)
        walls=[h for h in shapes(s,event) if h.get('terrain')]
        self.assertEqual(len(walls),4)
        for h in walls:self.assertAlmostEqual(event['at']+s['d']['warning']+h['delay'],4.15)
        # Player is released at preparation+2.5, .65s before walls/projectiles.
        self.assertGreater(4.15-(s['preparation']+2.5),.6)

    def test_seven_colors_keep_disjoint_windows_even_with_pressure(self):
        s=self.state(1,0);prior=0
        for index in range(7):
            at=1.18+index*2.55
            hs=shapes(s,dict(index=index,jitter=.4,angle=.8,at=at))
            self.assertEqual(len({h['color'] for h in hs}),1)
            self.assertGreaterEqual(min(at+s['d']['warning']+h['delay'] for h in hs),prior)
            prior=max(at+s['d']['warning']+h['delay']+h['duration'] for h in hs)
