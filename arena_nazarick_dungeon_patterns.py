"""Authoritative replay of webapp/nazarick-dungeon-qte.js (720×320)."""
import math

COLORS=dict(gargantua='#c8ad76',cocytus='#8edcff',aura='#b0da79',mare='#73bd83',victim='#edacd0',sebas='#d7e2e7',yuri='#b0b8de',narberal='#8ccfff',lupusregina='#e9b187',solution='#91cfb4',entoma='#dc8ba8',cz='#c5be94')
MOTIFS=dict(gargantua='stone',cocytus='ice',aura='arrow',mare='root',victim='sigil',sebas='fist',yuri='fist',narberal='orb',lupusregina='claw',solution='venom',entoma='beetle',cz='bullet')
FAMILIES=dict(gargantua=('impact','impact','impact','impact','impact'),cocytus=('slash','slash','ice','ice','slash'),
 aura=('thrust','slash','beast','edict','beast'),mare=('paint','thrust','impact','holy','fire'),victim=('mana','edict','script','holy','script'),
 sebas=('thrust','impact','slash','holy','impact'),yuri=('impact','impact','slash','holy','impact'),narberal=('lightning',)*5,
 lupusregina=('beast','beast','impact','holy','beast'),solution=('paint','paint','paint','holy','paint'),entoma=('thrust','paint','beast','holy','beast'),cz=('thrust',)*5)

def shapes(s,e):
    from arena_nazarick_revision_patterns import shapes as revision_shapes
    revision=revision_shapes(s,e)
    if revision is not None:return revision
    a=s['p']['skill']['base_id'].split('_');who=a[1];phase=int(a[2][1:]);move=int(a[3])
    if who not in COLORS:return None
    x,y=s['player']['x'],s['player']['y'];i=e['index'];sign=1 if i%2 else -1;d=s['d'];out=[]
    # Explicit dictionary merge also permits a primitive-specific motif.
    def add(h,delay=0,duration=.25):out.append({'color':COLORS[who],'motif':MOTIFS[who],**h,'delay':delay,'duration':duration})
    def line(angle,delay=0,width=6):
        dx=math.cos(angle)*850;dy=math.sin(angle)*850
        add(dict(type='line',ax=x-dx,ay=y-dy,bx=x+dx,by=y+dy,r=width*d['beamScale'],motif='cut',tier='heavy',weight=.45),delay,.23)
    def volley(bx,by,delay=0,n=3,speed=.70):
        a=math.atan2(y-by,x-bx)
        for j in range(n):
            angle=a+(j-(n-1)/2)*.25
            add(dict(type='bullet',x=bx,y=by,vx=math.cos(angle)*d['speed']*speed,vy=math.sin(angle)*d['speed']*speed,
                r=7 if j==n//2 else 5,tier='normal',weight=.20,length=22),delay,2.4)
    def circle(cx,cy,delay=0,r=35):
        add(dict(type='circle',x=max(r+10,min(710-r,cx)),y=max(r+10,min(310-r,cy)),r=r,
            motif='root' if who=='mare' else 'sigil',tier='normal',weight=.28),delay,.28)
    def corridor(delay=0):
        center=max(62,min(258,y+sign*36));half=max(49,d['gap']*.52)
        for a,b in ((0,max(0,center-half)),(min(320,center+half),320)):
            if b>a:add(dict(type='rect',x=0,y=a,w=720,h=b-a,label='МОРОЗ' if who=='cocytus' else 'РАЗЛОМ',tier='heavy',weight=.45),delay,.25)
    if move==3:
        if who=='aura' and phase==2:
            for j in range(3):
                volley(20 if j%2 else 700,45+j*110,j*.65,3,.48)
        return out
    if move==4:
        if who=='gargantua':
            for j in range(3):
                cx=max(55,min(665,x+(j-1)*145))
                add(dict(type='rect',x=cx-42,y=0,w=84,h=320,label='ВАЛУН',motif='stone',tier='heavy',weight=.42),.30+j*.65,.28)
                volley(20 if j%2 else 700,50+j*100,.65+j*.65,1,.50)
        elif who=='cocytus':
            for j in range(5):
                angle=sign*(.20+j*.57)
                dx=math.cos(angle)*850;dy=math.sin(angle)*850
                add(dict(type='line',ax=x-dx,ay=y-dy,bx=x+dx,by=y+dy,r=(8 if j==4 else 5)*d['beamScale'],
                    motif='lightning' if j==4 else 'ice',color='#c4edff' if j==4 else COLORS[who],tier='heavy' if j==4 else 'normal',weight=.40 if j==4 else .22),.10+j*.48,.18)
        elif who=='aura':
            for j in range(3):
                bx=20 if j%2 else 700;by=45+((i+j)%3)*110;a=math.atan2(y-by,x-bx)
                add(dict(type='bullet',x=bx,y=by,vx=math.cos(a)*d['speed']*.65,vy=math.sin(a)*d['speed']*.65,r=9,motif='wolf',length=27,homing=.22,turnRate=.75,tier='heavy',weight=.35),j*.64,2.4)
                volley(360,20,.30+j*.64,2,.61)
        elif who=='mare':
            for j in range(3):
                if phase==1:
                    cy=30+((i+j)%3)*125
                    add(dict(type='rect',x=0,y=cy,w=720,h=28,label='ЛАВА',motif='flame',color='#ed7847',tier='heavy',weight=.4),.25+j*.65,.24)
                else:
                    circle(x+(j-1)*115,y,.30+j*.60,38);line(sign*(.35+j*.70),.62+j*.60,6)
        elif who=='victim':
            for j in range(4):
                line(sign*(j*.65+.2),.20+j*.52,5)
                if j%2==0:volley(360,20,.48+j*.52,2,.45)
        elif who in ('sebas','yuri'):
            for j in range(3):
                a=sign*(.25+j*1.0);dx=math.cos(a)*850;dy=math.sin(a)*850
                add(dict(type='line',ax=x-dx,ay=y-dy,bx=x+dx,by=y+dy,r=10 if j==2 else 6,motif='fist',tier='heavy' if j==2 else 'normal',weight=.45 if j==2 else .25),.16+j*.65,.20)
            if who=='sebas' and phase==2:circle(x+sign*100,y,1.85,38)
        elif who=='narberal':
            for j in range(3 if phase==1 else 4):
                bx=0 if j%2 else 720;by=30+((i+j)%3)*125;tx=x+(j-1)*90;ty=y;dx=tx-bx;dy=ty-by;length=math.hypot(dx,dy) or 1
                points=[]
                for k in range(15):
                    f=k/14;zig=math.sin(k*2.6+j)*math.sin(f*math.pi)*24
                    points.append([bx+dx*f-dy/length*zig,by+dy*f+dx/length*zig])
                add(dict(type='polyline',points=points,r=5*d['beamScale'],motif='lightning',color='#9bdcff',tier='heavy',weight=.33),.15+j*.58,.20)
        elif who=='lupusregina':
            for j in range(3):
                circle(x+(j-1)*85,y,.22+j*.64,32);line(sign*(.55+j*.6),.54+j*.64,6)
        elif who=='solution':
            for j in range(3):
                circle(x+(j-1)*120,y+sign*25,.35+j*.60,43)
                volley(20 if j%2 else 700,50+j*100,.60+j*.60,3,.43)
        elif who=='entoma':
            for j in range(3):
                bx=20 if j%2 else 700;by=45+j*110;a=math.atan2(y-by,x-bx)
                for k in range(4):
                    angle=a+(k-1.5)*.30
                    add(dict(type='bullet',x=bx,y=by,vx=math.cos(angle)*d['speed']*.62,vy=math.sin(angle)*d['speed']*.62,r=4,motif='fly',tier='minor',weight=.08),j*.64,2.4)
                if j==1:line(sign*.65,1.25,4)
        elif who=='cz':
            for j in range(3):volley(20 if j%2 else 700,40+j*115,.12+j*.70,3,.76)
        total=max((h['delay'] for h in out),default=1) or 1
        for j,h in enumerate(out):
            h['strike']=min(s['p']['strikes']-1,j if who=='cocytus' else int(h['delay']/total*s['p']['strikes']))
        return out
    if who=='gargantua':
        if move==0:
            line(sign*.5,.20,10)
            if phase==2:volley(20 if sign>0 else 700,40+e['jitter']*240,.90,3,.63)
        elif move==1:
            volley(700,35+e['jitter']*250,0,5 if phase==2 else 3,.62);circle(x+sign*95,y,.85,40)
        else:
            corridor(.35)
            if phase==2:line(sign*1.15,1.1,7)
    elif who=='cocytus':
        if move==0:line(sign*.65,.10);line(-sign*.65,.90)
        elif move==1:
            for j in range(4 if phase==2 else 3):line(sign*(.25+j*.65),j*.50,5)
        else:corridor(.30);volley(690,160,1.,3,.66)
    elif who=='aura':
        if move==0:volley(20,40+e['jitter']*240,0,3,.78);volley(700,280-e['jitter']*240,.80,3 if phase==2 else 1,.75)
        elif move==1:
            a=sign*.45;add(dict(type='polyline',points=[[x+math.cos(a+j*.19)*105,y+math.sin(a+j*.19)*105] for j in range(19)],r=7,motif='halberd',tier='heavy',weight=.45),.35,.30)
            if phase==2:volley(20,160,1.05,1,.73)
        else:
            for j in range(3 if phase==2 else 2):volley(700 if j%2 else 20,35+((i+j)%3)*120,j*.60,1,.64)
    elif who=='mare':
        if move==0:circle(x,y,.45,34);circle(x+sign*110,y-sign*30,1.1,34)
        elif move==1:volley(30,40+e['jitter']*240,.15,5 if phase==2 else 3,.63);volley(690,280-e['jitter']*240,.95,1,.66)
        else:
            corridor(.40)
            if phase==2:circle(x+sign*90,y,1.15,40)
    elif who=='victim':
        if move==0:volley(360,20,.10,5 if phase==2 else 3,.48);volley(360,300,.95,3,.48)
        elif move==1:
            circle(x,y,.50,48 if phase==2 else 38)
            if phase==2:circle(x-sign*130,y+sign*30,1.15,38)
        else:
            line(sign*.70,.35,5)
            if phase==2:line(-sign*.70,1.,5);volley(700,160,1.3,1,.52)
    elif who in ('sebas','yuri'):
        if move==0:volley(700,y,.15,1,.91 if who=='sebas' else .78);volley(20,320-y,.95,1,.78)
        elif move==1:
            line(sign*.25,.20,7);line(-sign*.25,.95,7)
            if phase==2:volley(700,y,1.5,1,.80)
        else:
            add(dict(type='polyline',points=[[x+math.cos(j*.22)*100,y+math.sin(j*.22)*100] for j in range(23)],r=7,motif='halberd',tier='heavy',weight=.5),.40,.27)
            if phase==2:line(sign*.85,1.2)
    elif who=='narberal':
        if move==0:volley(700,35+e['jitter']*250,.05,5 if phase==2 else 3,.65)
        elif move==2:
            for j in range(4):
                cx=90+j*180+sign*18
                add(dict(type='polyline',points=[[cx+math.sin(k*2.7+j)*math.sin(k*math.pi/12)*18,k*320/12] for k in range(13)],r=5*d['beamScale'],motif='lightning',tier='normal',weight=.3),.20+j*.28,.20)
            if phase==2:volley(700,160,1.35,3,.57)
        else:
            for j in range(3 if phase==2 else 2):
                cx=max(24,min(696,x+(j-1)*110));points=[[cx+math.sin(k*2.1+i)*math.sin(k*math.pi/12)*22,k*320/12] for k in range(13)]
                add(dict(type='polyline',points=points,r=5*d['beamScale'],motif='lightning',tier='normal',weight=.3),.25+j*.65,.20)
    elif who=='lupusregina':
        if move==0:line(sign*.55,.20);line(-sign*.55,1.)
        elif move==1:circle(x,y,.45,36);volley(20,160,1.1,3 if phase==2 else 1,.76)
        else:
            line(sign*1.05,.35,9)
            if phase==2:circle(x+sign*110,y,1.1,40)
    elif who=='solution':
        if move==0:volley(700,160,.15,5 if phase==2 else 3,.50);volley(20,40+e['jitter']*240,.95,3,.52)
        elif move==1:line(sign*.8,.35,6);line(math.pi/2,1.10,5)
        else:circle(x,y,.45,42);circle(x+sign*120,y-sign*35,1.25,35)
    elif who=='entoma':
        if move==0:volley(700,30+e['jitter']*260,.10,3,.68);volley(20,290-e['jitter']*260,.9,3 if phase==2 else 1,.65)
        elif move==1:line(sign*.7,.35,4);line(-sign*.7,1.1,4)
        else:volley(360,20,.10,5 if phase==2 else 3,.58);volley(700,280,1.,3,.56)
    elif who=='cz':
        if move==0:
            volley(20 if sign>0 else 700,y,.15,1,.90)
            if phase==2:volley(700 if sign>0 else 20,320-y,.90,1,.87)
        elif move==1:
            for j in range(3):volley(700,35+((i+j)%3)*120,j*.55,1,.79)
        else:volley(20,60,.10,3 if phase==2 else 1,.75);volley(700,260,.95,3,.75)
    return out

def blocks(p,seed,params,rng):
    a=p['skill']['base_id'].split('_');who=a[1];phase=int(a[2][1:]);move=int(a[3])
    if who not in COLORS:return None
    if move==3 and (who!='aura' or phase!=2):return []
    if who in ('gargantua','sebas'):
        out=[];random=rng((seed^p['seed'])&0xffffffff);offset=random()*math.pi*2
        for wave in range(3):
            count=3 if move in (1,2) else 2
            for j in range(count):
                angle=offset+(wave*2+j)*math.pi/3
                heavy=j==0 and who=='gargantua' or j==count-1 and move==4
                kind='wave' if heavy and (who=='gargantua' or phase==2) else 'bolt' if who=='gargantua' else 'slash'
                out.append(dict(id=f'block:{len(out)}',at=2.1+wave*2.1+j*(.52 if who=='gargantua' else .37),warning=max(.85,params['warning']),angle=math.atan2(math.sin(angle),math.cos(angle)),kind=kind,motif='stone' if who=='gargantua' else 'claw' if phase==2 else 'fist',color=COLORS[who],tier='heavy' if heavy else 'minor',weight=.3 if heavy else .1,strike=min(p['strikes']-1,wave),resolved=False))
        return out
    if who=='victim' and phase==2 and move==4:
        out=[]
        for part in range(6):
            count=8 if part in (1,4) else 6
            for j in range(count):
                a=(part+j*(.5 if part==4 else 1))*math.pi/3
                feint=part in (2,5) and j==0
                wave=j==count-1 or part==3 and j==2
                kind='feint' if feint else 'wave' if wave else 'bolt' if part in (1,4) else 'slash'
                out.append(dict(id=f'block:{len(out)}',at=2.2+part*7+j*(.64 if count==8 else .85),warning=max(.76,params['warning']),angle=math.atan2(math.sin(a),math.cos(a)),kind=kind,motif='sigil' if kind=='bolt' else 'chain',color=COLORS[who],tier='heavy' if wave else 'minor',weight=0 if feint else .22 if wave else .075,strike=0,resolved=False))
        return out
    r=rng((seed^p['seed'])&0xffffffff);offset=math.floor(r()*8)*math.pi/4;out=[];count=5 if phase==2 else 4
    if move==4:count=3 if who in ('gargantua','sebas','yuri') else 5 if who=='cocytus' else 6
    for i in range(count):
        turn=i*math.pi/2 if who=='cocytus' else i%2*math.pi if who=='cz' else i%2*math.pi/2 if who in ('sebas','yuri') else i*math.pi/3 if who in ('mare','gargantua') else (i+move)*math.pi/4
        angle=offset+p['polarity']*turn
        if move==1:angle+=i%2*math.pi/2
        if move==2:angle-=i*math.pi/6
        kind='wave' if move==2 and who in ('mare','gargantua','victim') else 'bolt' if who in ('aura','cz','entoma','narberal','solution') else 'slash'
        if move==4:
            kind='wave' if who in ('gargantua','mare','victim') else 'slash' if who in ('cocytus','sebas','yuri','lupusregina') else 'bolt'
            angle=offset+p['polarity']*(i%2*math.pi if who=='cz' else i*math.pi/2 if who=='cocytus' else i*math.pi/3)
        at=2.2+i*((2.0 if count==3 else 1.05) if move==4 else (1.3 if phase==2 else 1.65));warning=max(.88 if move==4 else .82,params['warning']);weight=.5 if kind=='wave' else .3
        out.append(dict(id='',at=at,warning=warning,angle=math.atan2(math.sin(angle),math.cos(angle)),kind=kind,motif=MOTIFS[who],color=COLORS[who],tier='heavy' if kind=='wave' else 'normal',weight=weight,strike=0,resolved=False))
        if phase==2 and move==1:out.append(dict(id='',at=at+.65,warning=warning,angle=math.atan2(math.sin(angle+math.pi/2),math.cos(angle+math.pi/2)),kind='bolt',motif=MOTIFS[who],color=COLORS[who],tier='minor',weight=.1,strike=0,resolved=False))
    out.sort(key=lambda e:e['at'])
    for i,e in enumerate(out):e.update(id='block:'+str(i),strike=min(p['strikes']-1,math.floor(i*p['strikes']/len(out))))
    return out
