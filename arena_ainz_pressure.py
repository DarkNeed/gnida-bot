"""Spatial pressure and two intentionally different warrior-pattern languages.
Mirrored in AinzQTE.pressure. All terrain is real, server-replayed damage.
"""
import math


def time_curtains(s,e):
    """Three slotted walls from different directions; none aims at the player."""
    cycle=e['index']%2;base=cycle*5.2;prep=s.get('preparation',1);out=[]
    colors=('#ef4545','#81bdff','#a882e8','#75b985','#f3d48b','#d78db6','#dfe8ee')
    statuses=('burn','shock','curse','venom','exposed','sealed','frailty')
    gaps=(270 if cycle==0 else 450,200 if cycle==0 else 120,360)
    for wall in range(3):
        for j in range(15 if wall!=1 else 12):
            lane=150+j*30 if wall!=1 else 28+j*24
            if abs(lane-gaps[wall])< (44 if wall!=1 else 38):continue
            bx,by,vx,vy=(lane,-45,0,245) if wall==0 else (765,lane,-330,0) if wall==1 else (lane,365,0,-235)
            delay=wall*.1-s['d']['warning']-.18
            start=e.get('at',prep+base+.18)+s['d']['warning']+delay
            freeze_begin=prep+base+.5;release=prep+base+3.15+wall*.38
            out.append(dict(type='bullet',x=bx,y=by,vx=vx,vy=vy,r=6.5,motif='staff_orb',stone=j%7,
                color=colors[j%7],status=statuses[j%7],tier='normal',weight=.26,staff=True,
                ainzPath='wave',amplitude=9,frequency=4.2,
                freezeAt=max(0,freeze_begin-start),freezeFor=max(0,release-max(freeze_begin,start)),
                delay=delay,duration=release-start+1.5,timeWall=wall))
    return out


def shapes(s,e):
    phase,move=int(s['p']['skill']['base_id'].split('_')[2][1:]),int(s['p']['skill']['base_id'].split('_')[3])
    i=e['index'];sign=1 if i%2 else -1;d=s['d'];x,y=s['player']['x'],s['player']['y'];out=[]
    color=('#b69bff','#dac9ae','#f3d48b','#cb435e','#92cfff','#bb8bdd')[phase-1]
    status={1:'curse',2:'bleed',3:'exposed',4:'frailty',5:'shock',6:'sealed'}[phase]
    if (phase,move)==(1,0):
        color=('#ef4545','#81bdff','#a882e8','#75b985','#f3d48b','#d78db6','#dfe8ee')[i%7]
        status=('burn','shock','curse','venom','exposed','sealed','frailty')[i%7]
    def add(h,delay=.4,duration=.25,**extra):
        out.append(dict({'color':color,'status':status,'tier':'minor','weight':.14,**h},delay=delay,duration=duration,**extra))
    def bolt(bx,by,vx,vy,delay=.4,motif='lightning',duration=3,**extra):
        add(dict(type='bullet',x=bx,y=by,vx=vx,vy=vy,r=extra.pop('r',7),motif=motif,**extra),delay,duration)
    def line(ax,ay,bx,by,delay=.75,duration=.26,r=6,motif='lightning',**extra):
        add(dict(type='line',ax=ax,ay=ay,bx=bx,by=by,r=r,motif=motif,**extra),delay,duration)
    def corridor(width,amplitude=0,duration=2.7,delay=.15):
        # Side danger moves slowly, preserving a broad contiguous route.
        for bx in (360-width/2-900,360+width/2):
            add(dict(type='rect',x=bx,y=0,w=900,h=320,motif='territory',ainzPath='driftRect',
                driftX=amplitude,driftY=0,frequency=.85,offset=i*.8,terrain=True),delay,duration,weight=.18)
    def ricochet(bx,by,a,delay=.5,speed=150):
        bolt(bx,by,math.cos(a)*speed,math.sin(a)*speed,delay,'lightning',3.0,
             ainzPath='ricochet',minX=105,maxX=615,minY=38,maxY=282,r=7)
    def fracture(bx,delay=.6):
        points=[[bx+math.sin(j*1.7+i)*18,j*320/12] for j in range(13)]
        add(dict(type='polyline',points=points,r=8,motif='fracture',ainzPath='slidePolyline',dx=sign*75,dy=0),delay,.55,weight=.24)
    if (phase,move)==(1,2) or (phase,move)==(6,1):return []
    corridor(360 if (phase,move)==(6,0) else 440 if phase in (2,5) else 480,0 if (phase,move)==(6,0) else 35,
             2.0 if (phase,move)==(6,0) else 1.9 if (phase,move)==(1,0) else 2.7,
             2.97-d['warning'] if (phase,move)==(6,0) else .15)
    if (phase,move)==(6,0):
        for yy in (-858,278):
            add(dict(type='rect',x=0,y=yy,w=720,h=900,motif='time_wall',terrain=True),2.97-d['warning'],2.0,weight=.18,status='curse')
        return out
    for yy in (-876,296):
        add(dict(type='rect',x=0,y=yy,w=720,h=900,motif='territory',terrain=True),.15,
            1.9 if (phase,move)==(1,0) else 2.7,weight=.18)
    if phase not in (4,5):
        # Independent streams cross the arena rather than sharing a single aim.
        lanes=(65+((i*67+move*31)%190),255-((i*53+move*41)%190))
        for j,yy in enumerate(lanes):
            vx=sign*(125+j*15);bx=35 if sign>0 else 685
            bolt(bx,yy,vx,(-1 if j else 1)*18,.5+j*.5,
                 'spear' if phase==3 else ('fire','lightning','void','venom','holy_ray','sigil','bone')[i%7] if (phase,move)==(1,0) else 'bone' if phase==1 else 'dagger' if phase==2 else 'staff_orb',
                 1.1 if (phase,move)==(1,0) else 3.6,
                 ainzPath='wave',amplitude=22,frequency=3.1,weight=.12)
        return out
    if phase==4:
        # Heavy terrain, delayed impact and rubble: no electricity or orbits.
        if move==0:
            yy=65+(i%3)*80
            line(0,yy,720,yy,.65,.72,11,'ground_shear',ainzPath='sweepLine',dx=0,dy=sign*90,weight=.3)
            add(dict(type='ring',x=max(150,min(570,x)),y=max(85,min(235,y)),r=18,speed=155,
                gap=e.get('angle',i*.7),gapWidth=1.45,thickness=9,motif='shockwave'),1.0,1.5,weight=.28)
            for j in range(5):
                a=j*math.tau/5+i*.4
                bolt(360,160,math.cos(a)*140,math.sin(a)*140,1.5,'crystal',2.0,returnAt=.85,r=6)
        elif move==1:
            for j in range(3):fracture(155+j*170,.25+j*.3)
            for row in range(2):
                gap=(i*2+row*3+1)%11
                for j in range(12):
                    if j in (gap,gap+1):continue
                    bolt(100+j*48,-24,sign*(25+row*20),255+row*30,.35+row*.62+(j%3)*.065,'rubble',1.65,r=7,weight=.08)
            for j in range(4):
                a=math.atan2(y-160,x-(35 if sign>0 else 685))+(j-1.5)*.24
                bolt(35 if sign>0 else 685,160,math.cos(a)*240,math.sin(a)*240,1.05,'crystal',1.8,r=6,weight=.1)
        elif move==2:
            for row in range(3):
                gap=(i*3+row*2+2)%11
                for j in range(12):
                    if j in (gap,gap+1):continue
                    bolt(100+j*48,-24,sign*(18+row*15),265,.25+row*.46+(j%2)*.09,'rubble',1.65,r=7,weight=.08)
            gapx=220+(i%3)*130
            for ax,bx in ((0,gapx-48),(gapx+48,720)):
                line(ax,310,bx,310,.8,.9,7,'ground_shear',ainzPath='sweepLine',dx=0,dy=-300,weight=.25)
            bolt(x,-24,0,285,1.1,'rubble',1.5,r=10,weight=.12)
        else:
            for j in range(2):
                a=i*.7+j*math.pi
                line(360,160,360+math.cos(a)*300,160+math.sin(a)*300,.4,.60,9,'bloodblade',clockTurn=sign*2.6,weight=.3)
            for row in range(2):
                for j in range(10):
                    a=i*.5+j*math.tau/10+row*.31
                    bolt(360,160,math.cos(a)*225,math.sin(a)*225,.85+row*.5,'crystal',1.65,returnAt=.65,r=5.5,weight=.08)
        return out
    # White champion: alternating circuits, ricochets, re-strikes and fencing.
    if move==0:
        nodes=[(150,75),(360,175),(570,75)]
        for j,(bx,by) in enumerate(nodes):
            add(dict(type='circle',x=bx,y=by,r=17,motif='conductor'),.45+j*.35,.35,weight=.18)
            if j<2:line(bx,by,*nodes[j+1],.8+j*.45,.28,7)
        ricochet(160,90,.5+sign*.3,.6);ricochet(560,240,math.pi+.5-sign*.3,1.2)
    elif move==1:
        for j in range(3):
            line(170+j*185,0,170+j*185,320,.5+j*.45,.26,6)
            line(90,65+j*95,630,65+j*95,1.1+j*.4,.25,6)
        ricochet(360,50,1.1+i*.3,.8)
    elif move==2:
        for j in range(3):
            yy=65+j*95
            line(90,yy,630,320-yy,.45+j*.38,.18,7,'blade',weight=.22)
            line(90,yy,630,320-yy,1.35+j*.38,.18,5,'lightning',weight=.18)
        ricochet(150,160,.65*sign,.8)
    else:
        for j in range(2):
            cx=230+j*260;cy=160;r=74
            points=[[cx-r,cy-r],[cx+r,cy-r],[cx+r,cy+r],[cx-r,cy+r],[cx-r,cy-r]]
            add(dict(type='polyline',points=points,r=6,motif='lightning'),.65+j*.6,.3,weight=.2)
        ricochet(160,60,.7,.45);ricochet(560,260,math.pi+.7,1.05)
        line(0,160,720,160,1.7,.25,7)
    return out
