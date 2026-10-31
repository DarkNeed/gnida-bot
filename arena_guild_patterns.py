"""Monster-specific, telegraphed patterns; mirrored in qte-unique/engine."""
import math

FAMILIES = dict(stab='slash',net='paint',fang='beast',hex='mana',smash='impact',bone='death',soul='death',claw='beast',fire='fire',ice='ice',lightning='lightning',acid='paint',sticky='paint',poison_bite='beast',pounce='beast',cleaver='slash',troll_quake='impact',spectral_blade='slash',rune_cross='lightning',stone_rain='impact',venom_rain='paint',dragon_dive='beast',tail='slash',wings='fire',ice_tomb='ice',soul_prison='death',grave_crown='death',crypt_blades='slash',ancient_sun='fire',ash_orbit='fire')


def prepare(s, e, add):
    key = s['p']['skill'].get('base_id', '')[6:]
    if key not in FAMILIES or s['p']['skill'].get('monster_pattern') != 2:
        return False
    d, p, i = s['d'], s['p'], e['index']
    x, y = s['player']['x'], s['player']['y']
    tx = max(20, min(700, x+s['player'].get('vx',0)*d['lead']))
    ty = max(20, min(300, y+s['player'].get('vy',0)*d['lead']))
    angle = e['angle']
    color = '#83c6ae' if key in ('soul','bone','soul_prison','grave_crown') else '#b6ddfa' if key in ('ice','ice_tomb') else '#e78654' if key in ('fire','wings','ancient_sun','ash_orbit') else '#ba9ddf' if key in ('hex','lightning','rune_cross','spectral_blade','crypt_blades') else '#a9bc75' if key in ('acid','sticky','venom_rain','net','poison_bite') else '#d3b69c'

    def beam(a,b,c,f,r=12,delay=0,motif='blade'):
        add(dict(type='line',ax=a,ay=b,bx=c,by=f,r=r*d['beamScale'],color=color,motif=motif,tier='heavy'),delay,.22)

    def slash(a,delay=0):
        dx,dy=math.cos(a)*900,math.sin(a)*900
        beam(tx-dx,ty-dy,tx+dx,ty+dy,12,delay)

    def circle(cx,cy,r=35,delay=0):
        add(dict(type='circle',x=cx,y=cy,r=r,color=color,tier='heavy'),delay,.28)

    def fan(bx,by,a,n=5,spread=.18,delay=0,motif='soul'):
        for j in range(n):
            theta=a+(j-(n-1)/2)*spread
            add(dict(type='bullet',x=bx,y=by,vx=math.cos(theta)*d['speed']*.80,vy=math.sin(theta)*d['speed']*.80,r=7 if j==n//2 else 5,
                     color=color,motif=motif,tier='normal' if j==n//2 else 'minor'),delay,2.2)

    def aimed(n=5,delay=0,motif='soul',top=False):
        bx,by=((40+e['jitter']*640,-18 if i%2 else 338) if top else (-18 if i%2 else 738,40+e['jitter']*240))
        fan(bx,by,math.atan2(ty-by,tx-bx),n,.15,delay,motif)

    def ring():
        add(dict(type='ring',x=tx,y=ty,r=20,speed=200,gap=angle,gapWidth=1.65,thickness=9,color=color,tier='normal'),.30,1.3)

    if key in ('stab','cleaver','spectral_blade','crypt_blades','tail'):
        slash(angle)
        if key!='stab':slash(angle+(math.pi/2 if key in ('tail','crypt_blades') else .7),.30)
        if key=='crypt_blades':aimed(5,.5,'bone',True)
    elif key in ('fang','claw','poison_bite','pounce','dragon_dive'):
        circle(tx,ty,32 if key!='dragon_dive' else 42)
        slash(angle,.24)
        if key in ('claw','dragon_dive'):slash(angle+1.1,.48)
        if key=='poison_bite':aimed(3,.45,'web')
    elif key in ('smash','troll_quake','stone_rain'):
        if key=='stone_rain':
            for j in range(3):circle(max(25,min(695,tx+(j-1)*75)),max(25,min(295,ty+(j-1)*40)),25,j*.16)
        else:circle(tx,ty,38);ring()
        if key=='troll_quake':beam(0,ty,720,ty,10,.45)
    elif key in ('net','sticky'):
        beam(tx,0,tx,320,10,0,'web');beam(0,ty,720,ty,10,.26,'web')
        if key=='net':aimed(3,.5,'web')
    elif key in ('acid','venom_rain'):
        aimed(5 if key=='acid' else 7,0,'paint',key=='venom_rain')
        circle(tx,ty,24,.35)
        if key=='venom_rain':aimed(5,.38,'paint')
    elif key in ('bone','soul','hex','soul_prison','grave_crown'):
        aimed(7 if key in ('bone','grave_crown') else 5,0,'bone' if key=='bone' else 'soul')
        if key in ('soul_prison','grave_crown'):
            add(dict(type='well',x=360+math.cos(angle)*170,y=160+math.sin(angle)*70,r=25,pull=70,color=color,tier='normal'),.15,.9)
            aimed(5,.38,'soul',True)
        elif key=='hex':beam(0,ty,720,ty,9,.30)
        elif key=='soul':aimed(3,.32,'soul',True)
    elif key in ('fire','wings','ancient_sun','ash_orbit'):
        aimed(7,0,'flame',key=='wings')
        if key=='fire':circle(tx,ty,30,.36)
        elif key=='wings':aimed(5,.34,'flame')
        elif key=='ancient_sun':
            circle(tx,ty,42,.12)
            for j in range(6):fan(360,160,angle+j*math.tau/6,1,0,.45,'flame')
        else:
            for j in range(8):
                a=angle+j*math.tau/8
                add(dict(type='bullet',x=360+math.cos(a)*130,y=160+math.sin(a)*130,vx=math.cos(a+.8)*280,vy=math.sin(a+.8)*280,r=6,turn=.65,color=color,motif='flame',tier='minor'),.20,1.7)
    elif key in ('ice','ice_tomb'):
        gap=70+e['jitter']*580
        for j in range(13):
            bx=30+j*55
            if abs(bx-gap)>48:fan(bx,-15 if i%2 else 335,math.pi/2 if i%2 else -math.pi/2,1,0,0,'crystal')
        if key=='ice_tomb':beam(0,ty,720,ty,10,.4,'crystal')
    elif key in ('lightning','rune_cross'):
        beam(tx,0,tx,320,12,0,'spark')
        for j in (-1,1):beam(max(10,min(710,tx+j*100)),0,max(10,min(710,tx-j*65)),320,9,.23,'spark')
        if key=='rune_cross':beam(0,ty,720,ty,10,.5,'spark')
    return True


def block_threats(p, seed, params):
    key=p['skill'].get('base_id','')[6:]
    if key not in FAMILIES or p['skill'].get('monster_pattern') != 2:return None
    from arena_qte_patterns import random_values
    random=random_values(seed ^ p['seed']); offset=math.floor(next(random)*8)*math.pi/4
    tier=max(0,min(4,p['skill'].get('npc_tier',0)))
    cycles=4+tier//2; result=[]
    mode=sum(map(ord,key))%3
    for i in range(cycles):
        a=offset+p['polarity']*i*(math.pi/2 if mode==0 else math.pi/4)
        at=2+i*6.1/max(1,cycles-1)
        specs=[(at,a,'bolt',.3),(at+.35,a+(math.pi/2 if mode!=1 else 0),'slash',.3)]
        if i%2:specs.append((at+.74,a,'wave' if mode==2 else 'bolt',.6 if mode==2 else .1))
        for t,angle,kind,weight in specs:
            angle=math.atan2(math.sin(angle),math.cos(angle))
            result.append(dict(id='block:'+str(len(result)),at=t,warning=max(.5,params['warning'])+(.16 if kind=='wave' else 0),angle=angle,kind=kind,
                               motif='bone' if FAMILIES[key]=='death' else 'flame' if FAMILIES[key]=='fire' else 'crystal' if FAMILIES[key]=='ice' else 'blade',
                               tier='heavy' if weight==.6 else 'normal' if weight==.3 else 'minor',weight=weight,strike=0,resolved=False))
    for i,e in enumerate(result):e['strike']=min(p['strikes']-1,math.floor(i*p['strikes']/len(result)))
    return result
