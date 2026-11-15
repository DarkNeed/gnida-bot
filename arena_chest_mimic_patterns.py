"""Chest jaws, a fixed tongue, boomerang coins and an inhaling mouth.

Keep all numbers in sync with the dedicated chest helpers in qte-unique/engine.
Only these six abilities use these shapes; other monsters keep their patterns.
"""
import math

FAMILIES=dict(chest_bite='grapple',chest_tongue='thrust',chest_coins='coins',
              chest_devour='grapple',chest_ravenous_bite='grapple',chest_ravenous_coins='coins')


def prepare(s,e,add):
    key=s['p']['skill'].get('base_id','')[12:]
    if key not in ('bite','tongue','coins','devour','ravenous_bite','ravenous_coins'):
        return False
    i=e['index'];d=s['d'];p=s['player']
    x=max(24,min(696,p['x']));y=max(24,min(296,p['y']))
    color='#daaab1';high=s['p']['skill'].get('npc_tier',0)>=3

    def jaws(delay=0):
        # Two moving jaws meet on the captured position, never follow the player.
        vertical=i%2==0
        for sign in (-1,1):
            if vertical:
                h=dict(type='line',ax=x-85,ay=y+sign*54,bx=x+85,by=y+sign*54,r=8,
                       chestMoveY=-sign*180,chestMoveX=0)
            else:
                h=dict(type='line',ax=x+sign*54,ay=y-70,bx=x+sign*54,by=y+70,r=8,
                       chestMoveX=-sign*180,chestMoveY=0)
            add(dict(h,color=color,motif='chest_teeth',tier='normal',weight=.24),delay,.30)

    def coins(delay=0,n=5):
        bx=max(18,min(702,x+(250 if i%2==0 else -250)))
        by=40+e['jitter']*240
        angle=math.atan2(y-by,x-bx)
        for j in range(n):
            theta=angle+(j-(n-1)/2)*.22
            add(dict(type='bullet',x=bx,y=by,vx=math.cos(theta)*300,vy=math.sin(theta)*300,
                     r=6,color='#d8c7a1',motif='chest_coin',tier='minor',weight=.10,
                     returnAt=.98 if j%2==0 else 0),delay,1.96 if j%2==0 else 1.8)

    if key in ('bite','ravenous_bite'):
        jaws()
        if key=='ravenous_bite':coins(.48,3)
    elif key=='tongue':
        bx=18 if i%2 else 702;by=40+e['jitter']*240
        a=math.atan2(y-by,x-bx);length=math.hypot(x-bx,y-by)+42
        add(dict(type='line',ax=bx,ay=by,bx=bx+math.cos(a)*length,by=by+math.sin(a)*length,
                 r=10,color='#d07991',motif='chest_tongue',tier='heavy',weight=.50),0,.24)
    elif key in ('coins','ravenous_coins'):
        coins(0,7 if high else 5)
        if key=='ravenous_coins':jaws(.48)
    else:
        bx=42 if i%2 else 678;by=max(55,min(265,y))
        add(dict(type='well',x=bx,y=by,r=34,pull=75,color=color,motif='chest_mouth',
                 tier='heavy',weight=.45),0,.85)
        a=math.atan2(y-by,x-bx)
        for j in (-1,0,1):
            theta=a+j*.32
            add(dict(type='bullet',x=bx,y=by,vx=math.cos(theta)*260,vy=math.sin(theta)*260,
                     r=7,color='#b9a28b',motif='chest_splinter',tier='minor',weight=.12),.28,1.65)
    return True


def block_threats(p,seed,params):
    key=p['skill'].get('base_id','')[12:]
    if key not in ('bite','tongue','coins','devour','ravenous_bite','ravenous_coins'):return None
    from arena_qte_patterns import random_values
    offset=math.floor(next(random_values(seed ^ p['seed']))*8)*math.pi/4
    tier=max(0,min(4,p['skill'].get('npc_tier',0)))
    count=4+(1 if tier>=3 else 0);result=[]
    for i in range(count):
        a=offset+i*math.pi/2;at=2+i*5.7/max(1,count-1)
        if key in ('bite','ravenous_bite'):
            specs=[(0,a,'slash','chest_teeth',.30),(.40,a+math.pi,'slash','chest_teeth',.30)]
            if key=='ravenous_bite':specs.append((.82,a+math.pi/2,'bolt','chest_coin',.10))
        elif key=='tongue':specs=[(0,a,'slash','chest_tongue',.50)]
        elif key in ('coins','ravenous_coins'):
            specs=[(0,a,'bolt','chest_coin',.10),(.30,a+math.pi/4,'bolt','chest_coin',.10),(.75,a+math.pi,'bolt','chest_coin',.20)]
            if key=='ravenous_coins':specs.append((1.08,a+math.pi/2,'slash','chest_teeth',.24))
        else:specs=[(0,a,'wave','chest_mouth',.50),(.52,a+math.pi/4,'bolt','chest_splinter',.12)]
        for delay,angle,kind,motif,weight in specs:
            result.append(dict(id='block:'+str(len(result)),at=at+delay,warning=max(.62,params['warning']),
                angle=math.atan2(math.sin(angle),math.cos(angle)),kind=kind,motif=motif,
                tier='heavy' if weight==.50 else 'normal' if weight>=.24 else 'minor',
                weight=weight,strike=0,resolved=False))
    for i,h in enumerate(result):h['strike']=min(p['strikes']-1,math.floor(i*p['strikes']/len(result)))
    return result
