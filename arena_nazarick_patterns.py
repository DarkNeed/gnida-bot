"""Nazarick patterns; shared primitive semantics with webapp/nazarick-qte.js."""
import math


def identity(p):
    parts=p['skill'].get('base_id','').split('_')
    if len(parts)!=4 or parts[0]!='nz':return None
    return parts[1],int(parts[2][1:]),int(parts[3])


STONE_COLORS=('#ff593c','#70c6ff','#b69bff','#86e478','#f4db75','#ee86da','#e4edff')
STONE_STATUSES=('burn','shock','curse','venom','exposed','sealed','frailty')


def active_duration(p):
    which=identity(p)
    return 18.8 if which==('ainz',1,0) else 10.4 if which==('ainz',2,0) else 6.8


def block_duration(p):
    return 1+active_duration(p) if identity(p) in (('ainz',1,0),('ainz',2,0)) else 9.5


def schedule(p,count,span):
    which=identity(p)
    if which==('ainz',1,0):return 7,15.3
    if which==('ainz',2,0):return 2,5.2
    if which in (('demiurge',1,2),('demiurge',2,1),('ainz',2,1)):return 3,4.0
    if which==('ainz',2,2):return 3,4.4
    return count,span


def shapes(s, e):
    who, phase, move = identity(s['p'])
    x, y = s['player']['x'], s['player']['y']
    d, i = s['d'], e['index']
    sign = 1 if i % 2 else -1
    color = COLORS.get(who, '#9ba9de')
    out = []
    def add(h, delay=0, duration=.24, **extra):
        out.append({'color':color, **h, 'delay':delay, 'duration':duration, **extra})
    def line(ax, ay, bx, by, width=7, delay=0, **extra):
        add(dict(type='line', ax=ax, ay=ay, bx=bx, by=by, r=width*d['beamScale']), delay, **extra)
    def bolt(bx, by, motif='needle', delay=0, n=3, tracking=0, speed=.65):
        a = math.atan2(y-by, x-bx)
        for j in range(n):
            angle = a+(j-(n-1)/2)*.23
            core = j == n//2
            add(dict(type='bullet', x=bx, y=by, vx=math.cos(angle)*d['speed']*speed,
                vy=math.sin(angle)*d['speed']*speed, r=7 if core else 4,
                motif=motif, length=35 if motif=='spear' else 14 if motif in ('needle','feather') else 0,
                homing=tracking, turnRate=1.45 if motif=='bat' else .90,
                tier='heavy' if core else 'minor', weight=.48 if core else .10),
                delay, 2.65)
    def lightning(ax, ay, bx, by, delay=0, weak=False):
        dx, dy = bx-ax, by-ay
        length = math.hypot(dx,dy) or 1
        points = []
        for j in range(13):
            f=j/12
            zig=math.sin(j*2.7+i*.8)*math.sin(f*math.pi)*(13 if weak else 23)
            points.append([ax+dx*f-dy/length*zig, ay+dy*f+dx/length*zig])
        add(dict(type='polyline', points=points, r=(4 if weak else 7)*d['beamScale'],
            motif='lightning', color='#a3bfff' if weak else '#b5dcff'),delay,.20)
    def corridor(vertical=False, delay=0):
        half=max(52,d['gap']*.55-4*(phase-1));axis=720 if vertical else 320
        center=max(half+12,min(axis-half-12,(x if vertical else y)+sign*40))
        for lo,length in ((0,center-half),(center+half,axis-center-half)):
            add(dict(type='rect',x=lo if vertical else 0,y=0 if vertical else lo,
                w=length if vertical else 720,h=320 if vertical else length,
                label='ПРЕКЛОНИСЬ',status='curse'),delay,.18)
    def hole(cx,cy,r=55,delay=0,weak=False):
        add(dict(type='well',x=max(r+12,min(708-r,cx)),y=max(r+12,min(308-r,cy)),
            r=r,pull=45 if weak else 75,motif='blackhole',color='#9864e8',
            tier='heavy',weight=.55),delay,.80 if weak else 1.05)
    def safe_seal(delay=1.0, radius=70):
        cx=max(78,min(642,x+sign*100));cy=max(75,min(245,y-sign*35))
        add(dict(type='safe_zone',x=cx,y=cy,r=radius,motif='sigil',label='СЮДА',
            color='#7fe5ac',status='curse',tier='heavy',weight=.55),delay,.16)
        return cx,cy
    def orbit(stone, angle, delay=0, radius=112, spiral=55):
        # Geometry is replayed on the server, including curved swept collisions.
        omega=sign*1.9;cx,cy=360,160
        add(dict(type='bullet',x=cx+math.cos(angle)*radius,y=cy+math.sin(angle)*radius,
            vx=math.cos(angle)*spiral-math.sin(angle)*radius*omega,
            vy=math.sin(angle)*spiral+math.cos(angle)*radius*omega,
            r=8,motif='staff_orb',orbit=True,cx=cx,cy=cy,orbitRadius=radius,
            orbitAngle=angle,orbitSpeed=omega,spiral=spiral,staff=True,
            color=STONE_COLORS[stone],stone=stone,status=STONE_STATUSES[stone],
            tier='normal',weight=.23),delay,1.85)
    if who=='shalltear':
        if phase==1 and move==0:
            bolt(30 if sign>0 else 690,35+e['jitter']*250,tracking=.70)
        elif phase==1 and move==1:
            bolt(25,40+e['jitter']*220,'bat',n=3,tracking=.85,speed=.47)
            bolt(695,280-e['jitter']*220,'bat',.45,n=1,tracking=.65,speed=.47)
        elif phase==1:
            for bx in (220,500):
                # Aim THROUGH the recorded position, including the gap between the eyes.
                line(bx,20,bx+(x-bx)*4,20+(y-20)*4,6,.30,
                    motif='eye',clockTurn=sign*(.18 if bx==220 else -.18),duration=.42,tier='heavy',weight=.5)
        elif move==0:
            bolt(30 if sign>0 else 690,y,'spear',n=3,speed=.92)
            bolt(x,sign>0 and 12 or 308,'spear',.65,n=3,speed=.85)
        elif move==1:
            bolt(25,y,'spear',n=1,speed=.86)
            bolt(25,y,'spear',.70,n=1,speed=.86)
            bolt(695,320-y,'bat',.95,n=1,tracking=.7,speed=.48)
        else:
            bolt(30,30+e['jitter']*260,'needle',n=3,tracking=.7,speed=.72)
            bolt(690,290-e['jitter']*260,'bat',.50,n=1,tracking=.9,speed=.52)
    elif who=='demiurge':
        if phase==1 and move==0:
            angle=.40+sign*.8
            for j in range(2):
                a=angle+j*1.15
                line(x-math.cos(a)*850,y-math.sin(a)*850,x+math.cos(a)*850,y+math.sin(a)*850,
                    6,j*.60,motif='cut',status='curse')
        elif phase==1 and move==1:
            corridor();corridor(True,.70)
        elif phase==1:
            cx,cy=safe_seal(1.0,44+e['jitter']*26)
            out[-1].update(uniform=True,label='ПУТЬ',color='#e47562')
            add(dict(type='circle',x=cx+(200 if cx<360 else -200),y=cy,
                r=44+((e['jitter']+.47)%1)*26,motif='sigil',label='ЛОВУШКА',
                uniform=True,color='#e47562',status='curse'),1.0,.16)
        elif move==0:
            # Alternating walls leave a broad navigable middle, never an instant enclosure.
            add(dict(type='rect',x=0,y=0,w=720,h=32,motif='fire',status='burn',label='ОГОНЬ'),0,.60)
            add(dict(type='rect',x=0,y=288,w=720,h=32,motif='fire',status='burn',label='ОГОНЬ'),0,.60)
            bolt(690,40+e['jitter']*240,'fire',.35,n=3,speed=.66)
            bolt(30,280-e['jitter']*240,'fire',.65,n=3,speed=.64)
            bolt(130+i%4*150,22 if i%2 else 298,'fire',.85,n=1,speed=.62)
            for h in out[5:]:h['weight']=min(h.get('weight',.2),.22)
        elif move==1:
            tx=max(55,min(665,x+s['player'].get('vx',0)*.28))
            ty=max(50,min(270,y+s['player'].get('vy',0)*.28))
            cx,cy=safe_seal(1.0,48)
            # The cut is announced now, but lands only AFTER the shelter has closed.
            line(tx-650,ty-sign*350,tx+650,ty+sign*350,7,1.65,motif='cut',status='curse')
        else:
            bolt(40,25,'fire',n=3,speed=.65)
            bolt(680,295,'fire',.50,n=3,speed=.65)
    elif who=='albedo':
        if move==0 and phase==1 or move==1 and phase==2:
            bolt(25,35+e['jitter']*240,'feather',n=5,speed=.65)
            if phase==2:bolt(695,285-e['jitter']*240,'feather',.55,n=3,speed=.65)
        elif move==1 or move==0:
            angle=sign*.55
            # Real halberd arc: identical visible and collidable polyline.
            points=[[x+math.cos(angle+j*.15)*110,y+math.sin(angle+j*.15)*110] for j in range(23)]
            add(dict(type='polyline',points=points,r=10*d['beamScale'],motif='halberd',tier='heavy',weight=.6),.12,.24)
            line(x-650,y-sign*300,x+650,y+sign*300,7,.75,motif='purple_ray')
        else:
            bolt(690,y,'spear',n=1,speed=.88)
            line(0,y+sign*42,720,y+sign*42,10,.65,motif='purple_ray',tier='heavy',weight=.6)
    elif who=='pandora':
        if phase==1 and move==0:
            lightning(x-50,0,x+25,320,.30,True)
        elif phase==1 and move==1:
            hole(x+sign*95,y,37,.35,True)
        elif phase==1:
            # One announced sweep, not intersecting full-field death zones.
            line(0,y,720,y,7,.65,motif='death',color='#a79acc')
        elif move==0:
            bolt(690 if sign>0 else 30,y,'spear',n=3,speed=.74)
            bolt(25 if sign>0 else 695,320-y,'needle',.55,n=5,tracking=.25,speed=.64)
        elif move==1:
            if s['p']['skill'].get('copy_skill',{}).get('base_id')=='mana_shot':
                bolt(-20 if i%2 else 740,60+e['jitter']*200,'orb',.20,n=3,speed=.50)
                bolt(740 if i%2 else -20,260-e['jitter']*200,'orb',.95,n=3,speed=.48)
            elif i%3==0:lightning(x-70,0,x+40,320,.45,True)
            elif i%3==1:bolt(690,45+e['jitter']*220,'mask',n=3,tracking=.45,speed=.52)
            else:line(0,y,720,y,6,.40,motif='copied_cut',color='#dca2ff')
        else:
            for side in (-1,1):
                bolt(360+side*320,160+side*100,'mask',.20 if side<0 else .65,n=5,tracking=.35,speed=.65)
            bolt(170+i%3*180,12 if i%2 else 308,'mask',.90,n=3,speed=.58)
    elif who=='ainz':
        if phase==1 and move==0:
            # One complete color per wave. No hazards survive into the next stone.
            j=i%7;c=STONE_COLORS[j]
            if j==0:
                bolt(30,45+e['jitter']*230,'fire',n=5,speed=.86)
                bolt(690,275-e['jitter']*230,'fire',.55,n=3,speed=.80)
            elif j==1:
                lightning(x-90,0,x+80,320,.10)
                lightning(x+110,0,x-70,320,.85)
                for k,bx in enumerate((100,260,460,620)):
                    lightning(bx,0,bx+sign*45,320,.35+k*.30,True)
            elif j==2:
                hole(x+sign*85,y,64,.20)
                bolt(690 if sign>0 else 30,160,'staff_orb',.65,n=3,speed=.72)
            elif j==3:
                add(dict(type='ring',x=360+sign*150,y=160,r=18,speed=175,
                    gap=math.atan2(y-160,x-360-sign*150),gapWidth=1.65,thickness=7,
                    status='curse',motif='venom',weight=.28,tier='normal'),.12,1.7)
                bolt(30,40,'venom',.65,n=3,speed=.76)
            elif j==4:
                line(x-650,y-270,x+650,y+270,6,.15,motif='holy_ray')
                line(x-650,y+270,x+650,y-270,6,.90,motif='holy_ray')
            elif j==5:
                for jx in (-1,0,1):
                    add(dict(type='circle',x=max(35,min(685,x+jx*95)),y=max(40,min(280,y-jx*45)),
                        r=32,motif='sigil',status='curse',weight=.22,tier='normal'),.15+abs(jx)*.5,.25)
            else:
                bolt(690,30+e['jitter']*260,'skull',n=3,speed=.78)
                bolt(30,290-e['jitter']*260,'bone',.55,n=5,speed=.80)
            for h in out:
                h['color']=c;h['stone']=i%7;h['status']=STONE_STATUSES[i%7]
                h['duration']=min(h['duration'],max(.1,2.10-h['delay']))
                h['weight']=min(h.get('weight',.35),.35)
        elif phase==1 and move==1:
            hole(x+sign*95,y,58,.35)
            if i%2:hole(x-sign*145,320-y,48,.95)
        elif phase==1:
            bolt(690,40+e['jitter']*240,'bone',n=5,speed=.75)
        elif move==0:
            # Two isolated stop/place/release cycles. Old blades vanish before the next freeze.
            cycle=i%2;base=cycle*5.2
            release=s.get('preparation',0)+base+3.15
            for j in range(14):
                bx=30 if j%2 else 690;by=22+(j%7)*46
                a=math.atan2(y-by,x-bx)
                delay=.10+j*.12;stone=(j+cycle*3)%7
                start=e.get('at',0)+d['warning']+delay
                add(dict(type='bullet',x=bx,y=by,vx=math.cos(a)*d['speed']*.88,
                    vy=math.sin(a)*d['speed']*.88,r=6,motif='staff_orb' if j%2 else 'frozen_blade',
                    color=STONE_COLORS[stone],stone=stone,status=STONE_STATUSES[stone],freezeAt=0,freezeFor=max(0,release-start),
                    pendingLaunch=True,staff=True,cycle=cycle,tier='normal',weight=.18),
                    delay,max(.1,release-start+1.9))
        elif move==1:
            cx,cy=safe_seal(1.35)
            out[-1].update(color='#cfb2f0',label='СМЕРТЬ',staff=True,uniform=True,
                status='curse',tier='heavy',weight=.55,r=44+e['jitter']*12)
            # Identical shapes and colors: read the inscription, not a visual giveaway.
            for j,side in enumerate((-1,1)):
                add(dict(type='decoy',x=max(80,min(640,cx+(1 if cx<360 else -1)*(190+j*190))),
                    y=max(76,min(244,cy-side*48)),r=44+((e['jitter']+j*.37+.23)%1)*12,motif='sigil',
                    color='#cfb2f0',label='ЖИЗНЬ',uniform=True,staff=True,visualOnly=True),1.35,.16)
        else:
            # Three escalating constellations, with real orbiting colored staff gems.
            j=i%3
            for k in range(7):orbit(k,k*math.pi*2/7+i*.37,.12+k*.035,95,48)
            if j==0:
                line(0,y-45,720,y-45,5,.75,motif='staff_laser',color=STONE_COLORS[0],status='burn')
            elif j==1:
                lightning(x-80,0,x+90,320,.20)
                out[-1].update(stone=1,status='shock',color=STONE_COLORS[1])
            else:
                hole(x+sign*100,y,48,.20)
                out[-1].update(stone=2,status='curse')
                line(x-650,y+200,x+650,y-200,5,1.05,motif='staff_laser',color=STONE_COLORS[5],status='sealed')
            for h in out:
                h['staff']=True
                h['duration']=min(h['duration'],max(.1,2.05-h['delay']))
                h['weight']=min(h.get('weight',.35),.35)
    elif who in ('knight','hellguard'):
        line(x-600,y-sign*240,x+600,y+sign*240,8,.20,motif='halberd',
            **(dict(status='burn') if who=='hellguard' else {}))
        bolt(690,y,'spear',.7,n=1,speed=.70)
    elif who=='pyromancer':
        bolt(690,40+e['jitter']*240,'fire',n=5,speed=.65)
        bolt(30,280-e['jitter']*240,'fire',.40,n=3,speed=.62)
        add(dict(type='circle',x=x,y=y,r=26,motif='sigil',status='curse'),.65,.24)
    else:
        bolt(690,40+e['jitter']*240,'skull',n=3,speed=.65)
        bolt(30,280-e['jitter']*240,'bone',.45,n=3,speed=.62)
        line(x,0,x,320,5,.85,motif='bone',color='#e4dfda')
    for h in out:
        if h.get('motif')=='fire':h['status']='burn'
        if h.get('motif') in ('bone','skull'):h['color']='#e4dfda'
    return out


COLORS=dict(shalltear='#ff244c',demiurge='#e74620',albedo='#8145cf',
    pandora='#b48bd8',ainz='#a58aff',knight='#8d8fb6',lich='#75c89e',
    hellguard='#ef4723',pyromancer='#ff642b')


def time_stopped(s):
    ident=identity(s['p'])
    elapsed=s['time']-s.get('preparation',0)
    return ident==('ainz',2,0) and 0<=elapsed<10.4 and .5 <= elapsed%5.2 < 2.5


def advance_homing(h,p,t,dt):
    if not h.get('homing') or t<h['start']:return
    h['lastX'],h['lastY']=h.get('px',h['x']),h.get('py',h['y'])
    a=math.atan2(h['vy'],h['vx'])
    if t-h['start']<h['homing']:
        target=math.atan2(p['y']-h['lastY'],p['x']-h['lastX'])
        turn=math.atan2(math.sin(target-a),math.cos(target-a))
        a+=max(-h['turnRate']*dt,min(h['turnRate']*dt,turn))
        speed=math.hypot(h['vx'],h['vy'])
        h['vx'],h['vy']=math.cos(a)*speed,math.sin(a)*speed
    h['px']=h['lastX']+h['vx']*dt
    h['py']=h['lastY']+h['vy']*dt


def prepare(s,e,add):
    for h in shapes(s,e):
        delay=h.pop('delay');duration=h.pop('duration')
        add(h,delay,duration)


def block_threats(p,seed,params):
    which=identity(p)
    if not which:return None
    who,phase,move=which
    from arena_qte_patterns import random_values
    r=random_values((seed^p['seed'])&0xffffffff)
    offset=math.floor(next(r)*8)*math.pi/4
    out=[]
    if who=='ainz' and (phase,move) in ((1,0),(2,0)):
        if phase==1:
            for stone in range(7):
                for j in range(3):
                    angle=offset+stone*math.pi*2/7+j*.55
                    out.append(dict(id='',at=2.05+stone*2.55+j*.62,warning=max(.85,params['warning']),
                        angle=math.atan2(math.sin(angle),math.cos(angle)),kind='wave' if stone in (2,5) and j==2 else 'bolt',
                        motif=('fire','lightning','blackhole','venom','holy','sigil','skull')[stone],
                        color=STONE_COLORS[stone],stone=stone,tier='normal',weight=.24,strike=0,resolved=False))
        else:
            for cycle in range(2):
                for j in range(5):
                    angle=offset+(j+cycle)*math.pi*2/3
                    at=4.2+cycle*5.2+j*.32
                    out.append(dict(id='',at=at,warning=at-(1.05+cycle*5.2+j*.10),
                        freezeStart=1.5+cycle*5.2,freezeEnd=3.5+cycle*5.2,
                        angle=math.atan2(math.sin(angle),math.cos(angle)),kind='bolt',motif='staff_orb',
                        color=STONE_COLORS[j],stone=j,status=STONE_STATUSES[j],tier='normal',weight=.24,strike=0,resolved=False))
        for index,event in enumerate(out):
            event['id']=f'block:{index}'
            if 'stone' in event:event['status']=STONE_STATUSES[event['stone']]
        return out
    for i in range(3 if who=='ainz' and phase==2 and move==1 else 4 if phase==1 else 5):
        at=(3.85+i*1.10) if who=='ainz' and phase==2 and move==0 else 2.1+i*(1.65 if phase==1 else 1.35)
        angle=offset+p['polarity']*i*math.pi/2
        if who=='shalltear':angle=offset+p['polarity']*(i%2*math.pi if move==0 else i*math.pi/4 if move==1 else i*math.pi/2)
        elif who=='demiurge':angle=offset+((i*3+move)%8)*math.pi/4
        elif who=='albedo':angle=offset+(i%2)*math.pi/2
        elif who=='pandora':angle=offset+((i+move*2)%4)*math.pi/2
        elif who=='ainz':angle=offset+i*math.pi*(2/7 if move==0 else 2/3 if move==1 else .5)
        motif={'shalltear':('thread','bat','eye') if phase==1 else ('lance','echo','blood'),
            'demiurge':('sigil','order','trap') if phase==1 else ('fire','plan','demon'),
            'albedo':('wing','shaft','shield') if phase==1 else ('crack','wing','axe'),
            'pandora':('false_light','mask','mask'), 'ainz':('staff_orb','blackhole','bone') if phase==1 else ('freeze','death','meteor')}.get(who,('bone',)*3)[min(move,2)]
        def add(t,a,weight=.3,kind='slash'):
            out.append(dict(id='',at=t,warning=max(.72,params['warning'])+(.30 if motif=='freeze' else 0),
                angle=math.atan2(math.sin(a),math.cos(a)),kind=kind,motif=motif,
                tier='critical' if weight>=1 else 'heavy' if weight>=.6 else 'normal' if weight>=.3 else 'minor',
                weight=weight,strike=0,resolved=False))
        add(at,angle,.6 if move==2 else .3,'wave' if who=='demiurge' and phase==2 or who=='ainz' and move==1 else 'slash')
        if who=='shalltear' and phase==2 and move==1:add(at+.62,angle,.3)
        elif who=='albedo':add(at+.65,angle+(math.pi/2 if move==1 else 0),.6,'wave' if phase==2 else 'slash')
        elif who=='pandora' and phase==2:add(at+.65,angle+math.pi/2,.3)
        elif who=='ainz' and move==0:add(at+.55,angle+math.pi/4,.1,'bolt')
        elif who=='demiurge' and move==1:add(at+.65,angle+math.pi/2,.3)
        elif who=='shalltear' and move==0:add(at+.55,angle+math.pi,.1,'bolt')
        elif who=='shalltear' and move==2:add(at+.60,angle,.6,'wave')
        elif who=='demiurge' and move==2:add(at+.62,angle,.1,'bolt')
        elif who=='pandora' and move==1:add(at+.65,angle,.6,'wave')
    out.sort(key=lambda e:e['at'])
    for index,event in enumerate(out):
        if who=='lich':event.update(color='#e4dfda',motif='skull' if index%2 else 'bone')
        if who=='ainz' and phase==2 and move==2:
            stone=index%7;event.update(motif='staff_orb',stone=stone,color=STONE_COLORS[stone],status=STONE_STATUSES[stone])
        if who in ('demiurge','hellguard','pyromancer'):
            event['status']='burn' if phase==2 and move==0 or who in ('hellguard','pyromancer') else 'curse'
    delay=max(0,1.02-min(e['at']-e['warning'] for e in out))
    for i,e in enumerate(out):e.update(id=f'block:{i}',at=e['at']+delay,strike=min(p['strikes']-1,math.floor(i*p['strikes']/len(out))))
    return out
