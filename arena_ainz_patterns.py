"""Six-phase Ainz: curved, tracking and orbit/release patterns.
Mirrored by webapp/ainz-qte.js; no client-authored outcomes.
"""
import math
from arena_ainz_phases import PHASES, MOVES

COLORS=('#ef4545','#81bdff','#a882e8','#75b985','#f3d48b','#d78db6','#dfe8ee')
STATUSES=('burn','shock','curse','venom','exposed','sealed','frailty')


def active_duration(phase,move):
    if (phase,move)==(1,0):return 18.8
    if (phase,move)==(6,0):return 10.4
    return 9.2 if phase in (4,5,6) else 8.8


def schedule(phase,move):
    if (phase,move)==(1,0):return 7,15.3
    if (phase,move)==(6,0):return 2,5.2
    return (3,4.8) if phase==4 or (phase,move)==(6,1) else (4,4.8)


def shapes(s,e):
    parts=s['p']['skill']['base_id'].split('_');phase,move=int(parts[2][1:]),int(parts[3])
    x,y=s['player']['x'],s['player']['y'];d=s['d'];i=e['index'];sign=1 if i%2 else -1
    color=PHASES[phase-1]['color'];status=MOVES[phase-1][move][5];out=[]
    clamp=lambda v,a,b:max(a,min(b,v))
    def add(h,delay=.25,duration=.26,**extra):
        out.append(dict({'color':color,'status':status,'tier':'normal','weight':.22,**h},delay=delay,duration=duration,**extra))
    def shot(bx,by,angle,delay=.25,motif='dagger',speed=.62,**extra):
        add(dict(type='bullet',x=bx,y=by,vx=math.cos(angle)*d['speed']*speed,vy=math.sin(angle)*d['speed']*speed,
            r=6,motif=motif,**extra),delay,2.6)
    def fan(bx,by,n=5,delay=.25,motif='dagger',spread=.28,homing=0,tint=None):
        a=math.atan2(y-by,x-bx)
        for j in range(n):
            extra=dict(homing=homing,turnRate=.95) if homing else {}
            shot(bx,by,a+(j-(n-1)/2)*spread,delay,motif,.60,**extra)
            if tint:out[-1]['color']=tint
    def curve(bx,by,bend=85,delay=.25,motif='dagger',time=2.3,tint=None):
        dx,dy=2*(x-bx),2*(y-by);length=math.hypot(dx,dy) or 1;nx,ny=-dy/length,dx/length
        add(dict(type='bullet',x=bx,y=by,vx=dx/time,vy=dy/time,r=7,length=18,motif=motif,
            ainzPath='bezier',c1x=bx+dx/3+nx*bend,c1y=by+dy/3+ny*bend,
            c2x=bx+dx*2/3-nx*bend,c2y=by+dy*2/3-ny*bend,
            tx=bx+dx,ty=by+dy,pathTime=time),delay,time)
        if tint:out[-1]['color']=tint
    def wave(bx,by,angle,delay=.25,motif='spear',amplitude=22,frequency=3.4,**extra):
        shot(bx,by,angle,delay,motif,.67,ainzPath='wave',amplitude=amplitude,frequency=frequency,**extra)
    def orbit(angle,delay=.25,motif='staff_orb',radius=128,spiral=-18,omega=1.4,release=1.1,**extra):
        radius_hit=extra.pop('r',8)
        add(dict(type='bullet',x=360+math.cos(angle)*radius,y=160+math.sin(angle)*radius,vx=0,vy=0,
            cx=360,cy=160,r=radius_hit,motif=motif,ainzPath='orbitLaunch',orbitAngle=angle,
            orbitRadius=radius,orbitSpeed=omega,spiral=spiral,releaseAt=release,launchSpeed=d['speed']*.72,**extra),delay,2.7)
    def cut(ax,ay,bx,by,delay=.6,r=7,motif='blade',duration=.26,**extra):
        add(dict(type='line',ax=ax,ay=ay,bx=bx,by=by,r=r*d['beamScale'],motif=motif,**extra),delay,duration)
    def ribbon(cx,cy,delay=.7,motif='lightning',width=6,vertical=False):
        pts=[]
        for j in range(19):
            u=j/18
            pts.append([cx+math.sin(u*math.pi*4+i*.7)*26 if vertical else 720*u,
                        320*u if vertical else cy+math.sin(u*math.pi*4+i*.7)*26])
        add(dict(type='polyline',points=pts,r=width*d['beamScale'],motif=motif),delay,.32)
    def well(cx,cy,delay=.4,r=48):
        add(dict(type='well',x=clamp(cx,r+10,710-r),y=clamp(cy,r+10,310-r),r=r,pull=40,motif='blackhole'),delay,1.6)
    if phase==1:
        if move==0:
            stone=i%7
            if stone==0:
                for side in (-1,1):curve(360+side*335,45+e['jitter']*230,side*95,.12,'fire',1.85)
            elif stone==1:
                for j in range(3):ribbon(110+j*250,160,.15+j*.38,vertical=True)
                wave(20,50,math.atan2(y-50,x-20),.65,'lightning',35)
            elif stone==2:
                well(x+sign*90,y,.2,46)
                curve(690 if sign>0 else 30,160,sign*120,.7,'void',1.3)
            elif stone==3:
                fan(25,50,5,.15,'venom',.3,.65)
                fan(695,270,3,.65,'venom',.35,.45)
            elif stone==4:
                for j in range(3):wave(20,60+j*100,0,.15+j*.18,'holy_ray',22,4.2)
            elif stone==5:
                for j in range(5):orbit(j*math.tau/5+i*.2,.1,'sigil',104,-12,sign*1.6,.65)
            else:
                curve(25,60,120,.1,'skull',1.8);curve(695,260,-120,.5,'bone',1.6)
            for h in out:
                h.update(color=COLORS[stone],status=STATUSES[stone],stone=stone)
                h['duration']=min(h['duration'],max(.1,2.15-h['delay']))
        elif move==1:
            well(x+sign*90,y,.3,50)
            for j in range(4):orbit(i*.4+j*math.pi/2,.35,'void',135,-22,sign*1.7,1.2)
            curve(25 if i%2 else 695,45+e['jitter']*230,sign*110,1.0,'skull',1.7)
        elif move==2:
            for j in range(3):curve(25,60+j*100,sign*100,.2+j*.22,'bone',2.0)
        else:
            for j in range(3):
                curve(22,35+j*125,80+j*25,.15+j*.22,'bone',2.2)
                curve(698,285-j*125,-80-j*25,.7+j*.16,'skull',2.0)
    elif phase==2:
        if move==0:
            orbit(i*.6,.15,'dagger',126,-12,1.7,.95,length=24,ainzSprite='blades',color='#ecd7a0')
            orbit(i*.6+math.pi,.45,'dagger',126,-12,-1.7,.95,length=24,ainzSprite='blades',color='#bfcced')
            curve(22 if i%2 else 698,55+e['jitter']*210,sign*115,1.0,'dagger',1.7)
        elif move==1:
            fan(22,70,3,.15,'dagger',.45,.65,'#ecd7a0')
            fan(698,250,3,.7,'dagger',.45,.65,'#bfcced')
            curve(360,12,sign*130,1.1,'dagger',1.65)
        elif move==2:
            curve(22,50,130,.15,'dagger',2.1,'#ecd7a0')
            curve(698,270,-130,.7,'dagger',1.8,'#bfcced')
            for j in range(3):shot(360,18,math.pi/2+(j-1)*.42,1.1,'dagger',.57,turn=sign*.65)
        else:
            bx=30 if i%2 else 690
            fy=80+(i%3)*80
            cut(bx,fy,bx+sign*580,fy+sign*85,.75,6,'blade',.55,clockTurn=sign*.45)
            curve(360,308,-sign*140,.85,'dagger',1.9)
            curve(360,12,sign*140,1.2,'dagger',1.8)
    elif phase==3:
        if move==0:
            curve(22,70+e['jitter']*180,sign*110,.45,'spear',2.2)
            out[-1].update(r=8,length=30,ainzSprite='bow')
            for side in (-1,1):wave(22,160+side*85,math.atan2(y-160-side*85,x-22),.85,'spear',28)
        elif move==1:
            gap=clamp(y+sign*72,75,245)
            for by in (25,70,115,160,205,250,295):
                if abs(by-gap)>47:wave(22,by,0,.45,'spear',16,3.6,ainzLane=gap)
            curve(698,160,sign*130,1.2,'spear',1.8)
        elif move==2:
            for j in range(5):orbit(j*math.tau/5+i*.4,.25,'spear',112,6,sign*1.5,.85,length=22)
            curve(30 if i%2 else 690,25,sign*120,1.15,'spear',1.9)
        else:
            ribbon(360,y,.95,'holy_ray',11)
            for j in range(3):curve(22,45+j*115,(j-1)*110,.3+j*.3,'spear',2.0)
    elif phase in (4,5):
        from arena_ainz_pressure import shapes as pressure_shapes
        return pressure_shapes(s,e)
    else:
        if move==0:
            from arena_ainz_pressure import time_curtains
            out.extend(time_curtains(s,e))
        elif move==1:
            cx=clamp(x+sign*85,90,630);cy=clamp(y-sign*35,75,245)
            add(dict(type='safe_zone',x=cx,y=cy,r=44,motif='sigil',label='СМЕРТЬ',uniform=True,
                ainzPath='sealDrift',driftX=18,driftY=10,frequency=1.2),1.35,.22)
            for j in range(2):
                add(dict(type='decoy',x=clamp(cx+(1 if cx<360 else -1)*(185+j*175),80,640),
                    y=clamp(cy+(j*2-1)*70,75,245),r=44,motif='sigil',label='ЖИЗНЬ',uniform=True,
                    visualOnly=True,ainzPath='sealDrift',driftX=18,driftY=10,frequency=1.2),1.35,.22)
            for h in out:h.update(color='#b7a0cf',status='curse',weight=.5)
        elif move==2:
            for j in range(7):
                orbit(j*math.tau/7+i*.35,.15+j*.035,'staff_orb',138,-22,sign*(1.1+j*.05),1.15)
                out[-1].update(color=COLORS[j],status=STATUSES[j],stone=j,staff=True)
            curve(360,18,sign*150,1.25,'staff_orb',1.8)
            out[-1].update(status='sealed',color=COLORS[5],stone=5,staff=True)
        else:
            well(x+sign*100,y,.35,45)
            ribbon(360,y,.6,'void',8)
            for j in range(3):curve(22 if j%2 else 698,35+j*125,sign*(100+j*40),.4+j*.35,'void',2.1)
    from arena_ainz_pressure import shapes as pressure_shapes
    pressure=pressure_shapes(s,e)
    return out+pressure


def blocks(p,seed,params):
    from arena_qte_patterns import random_values
    parts=p['skill']['base_id'].split('_');phase,move=int(parts[2][1:]),int(parts[3])
    r=random_values((seed^p['seed'])&0xffffffff);offset=math.floor(next(r)*8)*math.pi/4;out=[]
    if (phase,move)==(6,0):
        for cycle in range(2):
            for j in range(7):
                angle=offset+(j+cycle)*math.tau/7;at=3.9+cycle*5.2+j*.32
                out.append(dict(id='',at=at,warning=at-(1.05+cycle*5.2+j*.10),
                    freezeStart=1.5+cycle*5.2,freezeEnd=3.5+cycle*5.2,angle=math.atan2(math.sin(angle),math.cos(angle)),
                    kind='bolt',motif='staff_orb',color=COLORS[j],status=STATUSES[j],stone=j,
                    tier='normal',weight=.22,strike=0,resolved=False))
    elif (phase,move)==(1,0):
        for stone in range(7):
            for j in range(3):
                angle=offset+stone*math.tau/7+j*.55
                out.append(dict(id='',at=2.05+stone*2.55+j*.62,warning=max(.85,params['warning']),
                    angle=math.atan2(math.sin(angle),math.cos(angle)),kind='wave' if j==2 and stone in (2,5) else 'bolt',
                    motif=('fire','lightning','blackhole','venom','holy','sigil','skull')[stone],color=COLORS[stone],
                    status=STATUSES[stone],stone=stone,tier='normal',weight=.22,strike=0,resolved=False))
    elif phase in (4,5):
        for wave in range(3):
            for j in range(2 if phase==4 else 3):
                angle=offset+wave*math.tau/3+j*(math.pi/2 if phase==4 else math.tau/7)+move*.35
                heavy=phase==4 and j==0
                out.append(dict(id='',at=2.1+wave*2.05+j*(.7 if phase==4 else .42),
                    warning=max(1.15 if heavy else .85,params['warning']),angle=math.atan2(math.sin(angle),math.cos(angle)),
                    kind='wave' if heavy else 'bolt',motif='rubble' if phase==4 and j else 'bloodblade' if phase==4 else 'lightning',
                    color=PHASES[phase-1]['color'],status=MOVES[phase-1][move][5],tier='heavy' if heavy else 'normal',
                    weight=.42 if heavy else .2,strike=0,resolved=False))
    else:
        for wave in range(3):
            count=3 if phase in (2,3) else 2
            for j in range(count):
                heavy=phase in (4,5,6) and j==count-1
                angle=offset+wave*(math.pi/2 if move%2 else math.pi*2/3)+j*(math.pi if phase==2 else math.pi/3)+move*.25
                at=2.1+wave*2.05+j*(.46 if phase==2 else .62)
                out.append(dict(id='',at=at,warning=max(1.05 if heavy else .85,params['warning']),
                    angle=math.atan2(math.sin(angle),math.cos(angle)),kind='wave' if heavy else 'bolt' if phase in (1,3) else 'slash',
                    motif={1:'skull',2:'dagger',3:'spear',4:'bloodblade',5:'lightning',6:'void'}[phase],
                    color=PHASES[phase-1]['color'],status=MOVES[phase-1][move][5],tier='heavy' if heavy else 'normal',
                    weight=.45 if heavy else .22,strike=0,resolved=False,ainzSprite={2:'blades',3:'bow',4:'axe',5:'sword'}.get(phase,'')))
    for index,h in enumerate(out):h['id']=f'block:{index}'
    return out
