"""Guardian-specific choreography. Kept in parity with revisionShapes in JS."""
import math


def schedule(who,phase,move):
    if who=='victim' and phase==2:return (12,37.4) if move==4 else (3,3.4)
    if who=='cocytus' and move==4:return (5,3.4) if phase==2 else (3,3.0)
    if who=='sebas':return (1,0) if move==3 else (4,3.8)
    if who=='gargantua':return (1,0) if move==3 else (3,3.0)
    if who=='cocytus' and move==2:return 2,3.0
    if who=='aura' and move==1:return 3,3.0
    if who=='mare' and move in (0,2,4):return 2,3.0
    return None


def shapes(s,e):
    a=s['p']['skill']['base_id'].split('_');who=a[1];phase=int(a[2][1:]);move=int(a[3]);i=e['index']
    if schedule(who,phase,move) is None:return None
    x,y=s['player']['x'],s['player']['y'];sign=1 if i%2 else -1;d=s['d'];out=[]
    color=dict(gargantua='#c9b195',cocytus='#88ceff',aura='#b8db7b',mare='#82c581',sebas='#dbe9ee',victim='#e9abd7')[who]
    motif=dict(gargantua='stone',cocytus='ice',aura='whip',mare='root',sebas='fist',victim='sigil')[who]
    def add(h,delay=0,duration=.24):out.append({'color':color,'motif':motif,**h,'delay':delay,'duration':duration})
    def rect(rx,ry,w,h,delay=0,label='',**extra):add(dict(type='rect',x=rx,y=ry,w=w,h=h,label=label,**extra),delay,.32)
    def cut(ax,ay,bx,by,delay=0,r=8,**extra):add(dict(type='line',ax=ax,ay=ay,bx=bx,by=by,r=r,weight=.28,tier='heavy',**extra),delay,.22)
    def circle(cx,cy,r,delay=0,**extra):add(dict(type='circle',x=cx,y=cy,r=r,weight=.22,tier='normal',**extra),delay,.28)
    def shots(bx,by,n=3,delay=0,speed=.65,spread=.26,kind=None):
        aim=math.atan2(y-by,x-bx)
        for j in range(n):
            ang=aim+(j-(n-1)/2)*spread
            add(dict(type='bullet',x=bx,y=by,vx=math.cos(ang)*d['speed']*speed,vy=math.sin(ang)*d['speed']*speed,r=6,
                motif=kind or motif,length=17,weight=.09,tier='minor'),delay,2.0)
    def ring(cx,cy,delay=0,kind=None):add(dict(type='ring',x=cx,y=cy,r=18,speed=145,thickness=8,gap=sign*.65,gapWidth=1.1,motif=kind or motif,weight=.24,tier='heavy'),delay,1.8)
    def passage(center,half,delay,label):
        center=max(half+12,min(308-half,center))
        for lo,hi in ((0,center-half),(center+half,320)):
            if hi>lo:rect(0,lo,720,hi-lo,delay,label,weight=.27,tier='heavy')
        rect(0,center-half,720,half*2,delay,'ПРОХОД →',visualOnly=True,color='#83edba',motif='passage')
    if move==3:return out
    if who=='gargantua':
        if move in (0,4):
            rx=max(12,min(608,x-50+sign*(20 if move==4 else 0)))
            rect(rx,0,100,320,.3,'КАМЕННАЯ ЛАДОНЬ' if move==0 else 'ОБВАЛ',weight=.35,tier='heavy',motif='stone')
            shots(20 if i%2 else 700,40+(i%3)*120,5 if phase==2 else 3,.65,.63)
            if move==4:ring(x,y,1.0)
        elif move==1:
            shots(20 if i%2 else 700,35+(i%3)*125,5,.1,.75,.18)
            circle(x,y,36,.85,motif='stone')
            if phase==2:shots(360,12,3,1.05,.62,.45)
        else:
            circle(x,y,42,.15,motif='stone');ring(x,y,.6)
            if phase==2:cut(0,max(25,min(295,y+sign*48)),720,max(25,min(295,y+sign*48)),1.1,10,motif='stone')
    elif who=='cocytus':
        if move==2:
            if phase==1:
                passage(y+sign*30,51,1.0,'МОРОЗ — ОПАСНО')
                shots(700 if i%2 else 20,40+(i%3)*120,3,1.35,.45,.33)
            else:
                for j in range(4):
                    cx=max(22,min(698,x+(j-1)*100))
                    rect(cx-17,0,34,320,.35+j*.35,'ЛЕДЯНОЙ ПИК',weight=.18,tier='normal')
        elif move==4:
            if phase==1:
                cut(0,y,720,y,.65,22,motif='ice')
                ring(x,y,1.0,'ice');shots(700 if i%2 else 20,20,3,1.15,.68,.34)
            else:
                k=i%5
                if k==0:cut(0,y,720,y,.4,14)
                elif k==1:cut(x,0,x,320,.4,14)
                elif k==2:circle(x,y,45,.3);ring(x,y,.8)
                elif k==3:shots(700 if i%2 else 20,40+i*35,5,.3,.78,.22)
                else:
                    cut(x-220,0,x+220,320,.45,12,motif='lightning')
                    cut(x+220,0,x-220,320,.95,12,motif='lightning')
                for h in out:h['strike']=min(s['p']['strikes']-1,k)
    elif who=='aura':
        # The whip crosses the sampled player, then sweeps back through space.
        points=[[k*45,max(8,min(312,y+sign*90*math.sin((k/16-x/720)*math.pi*1.2)))] for k in range(17)]
        add(dict(type='polyline',points=points,r=9,motif='whip',weight=.28,tier='heavy'),.25,.26)
        cut(x-sign*150,0,x+sign*150,320,.90,8,motif='whip')
        shots(20 if i%2 else 700,160,3,1.2,.63,.27,'arrow')
    elif who=='mare':
        if move==0:
            circle(x,y,37,.35);circle(max(40,min(680,x+sign*95)),max(40,min(280,y-sign*40)),32,1.15)
        elif move==2:
            passage(y+sign*26,58,1.15,'РАЗЛОМ — ОПАСНО')
            circle(x,y,28,.35)
        else:
            if phase==1:
                cut(0,y,720,y,.4,15,motif='flame');shots(20 if i%2 else 700,40+i*130,5,.95,.57,.32,'stone')
            else:
                circle(x,y,42,.4);cut(x-sign*160,0,x+sign*160,320,1.10,12,motif='stone')
                shots(20 if i%2 else 700,160,5,1.35,.62,.31,'stone')
        # Visible roots now really erupt, briefly, instead of fake permanent walls.
        rect(0,292 if i%2==0 else 0,720,28,1.6,'КОРНИ',weight=.15,tier='normal',motif='root')
    elif who=='sebas':
        if phase==2 and move==0:
            cut(0,y,720,y,.2,12,motif='claw')
            shots(360,20,5,.7,.82,.20,'claw');shots(360,300,3,1.2,.73,.30,'flame')
        elif phase==2 and move==1:
            for j in range(3):cut(x-150+(j-1)*60,0,x+150+(j-1)*60,320,.2+j*.34,9,motif='claw')
            ring(x,y,1.25,'claw')
        elif phase==2 and move==2:
            circle(x,y,37,.2,motif='claw')
            for j in range(6):
                angle=j*math.pi/3
                add(dict(type='bullet',x=x+math.cos(angle)*85,y=y+math.sin(angle)*85,vx=0,vy=0,r=6,
                    orbit=True,cx=x,cy=y,orbitAngle=angle,orbitRadius=85,spiral=20,orbitSpeed=sign*1.8,motif='claw',weight=.09,tier='minor'),.55,1.7)
        elif move==0:
            shots(700 if i%2 else 20,y,5,.15,.88,.18)
            cut(x-180,0,x+180,320,.85,8,motif='claw' if phase==2 else 'fist')
        elif move==1:
            cut(0,y,720,y,.2,10);shots(20 if i%2 else 700,320-y,5,.85,.83,.24)
            if phase==2:ring(x,y,1.2,'claw')
        elif move==2:
            circle(x,y,32,.2,motif='claw' if phase==2 else 'fist')
            for j in range(3):
                ang=j*math.pi*2/3+i*.5
                shots(360+math.cos(ang)*340,160+math.sin(ang)*145,2,.55+j*.32,.76,.20,'claw' if phase==2 else 'fist')
        else:
            cut(0,y,720,y,.25,17,motif='claw' if phase==2 else 'fist')
            cut(x,0,x,320,.8,11,motif='claw' if phase==2 else 'fist')
            if phase==2:ring(x,y,1.1,'claw');shots(700 if i%2 else 20,160,5,1.35,.74,.26,'flame')
            else:shots(700 if i%2 else 20,160,5,1.15,.86,.20)
        # Seal alternating edges and retarget between waves, not continuously.
        # These are real hit zones, with the same visible warning as the combo.
        rect(0 if i%2==0 else 678,0,42,320,.85,'ДАВЛЕНИЕ',weight=.12,tier='normal',motif='claw' if phase==2 else 'fist')
        if move in (0,1):circle(x,y,29,1.2,motif='claw' if phase==2 else 'fist')
        for h in out:
            if h['type']=='bullet':h['vx']*=1.22;h['vy']*=1.22;h['r']+=1
            if h.get('orbit'):h['orbitSpeed']*=1.2
        for h in out:h['strike']=min(s['p']['strikes']-1,i)
    elif who=='victim':
        section=(i//2)%6
        if section==0:
            cut(0,y,720,y,.2,8,motif='chain');cut(x,0,x,320,1.15,7,motif='chain')
            shots(20 if i%2 else 700,40+(i%3)*120,5,1.8,.58,.26,'sigil')
        elif section==1:
            shots(20,40,7,.15,.61,.24,'sigil');shots(700,280,7,1.05,.62,.24,'sigil')
            ring(x,y,1.6,'chain')
        elif section==2:
            for j in range(3):
                angle=sign*(.35+j*.9);dx=math.cos(angle)*850;dy=math.sin(angle)*850
                cut(x-dx,y-dy,x+dx,y+dy,.2+j*.72,7,motif='chain')
            circle(x,y,31,2.3,motif='sigil')
        elif section==3:
            passage(y+sign*22,51,.7,'СТЕНА ПЕЧАТИ')
            shots(20 if i%2 else 700,160,7,1.45,.57,.22,'sigil')
            cut(x,0,x,320,2.4,8,motif='chain')
        elif section==4:
            for j in range(8):
                angle=j*math.pi/4
                add(dict(type='bullet',x=x+math.cos(angle)*95,y=y+math.sin(angle)*95,vx=0,vy=0,r=6,
                    orbit=True,cx=x,cy=y,orbitAngle=angle,orbitRadius=95,spiral=18,orbitSpeed=sign*1.5,motif='sigil',weight=.055,tier='minor'),.35,2.6)
            circle(x,y,34,.9,motif='sigil');ring(x,y,1.8,'chain')
        else:
            passage(y+sign*24,48,.65,'ПОСЛЕДНЯЯ ПЕЧАТЬ')
            for j in range(2):shots(20 if (i+j)%2 else 700,40+j*240,7,.9+j*.85,.65,.20,'sigil')
            ring(x,y,1.65,'chain')
        for h in out:
            if not h.get('visualOnly'):h['weight']=.085 if h['type']=='bullet' else .22 if h['type']=='ring' else .18
    return out
