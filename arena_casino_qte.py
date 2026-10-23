"""Casino attack patterns. Mirrored in the shared JavaScript simulations."""
import math


def prepare(s,e,add,beam,circle,bullet):
    p,d=s['p'],s['d'];i=e['index'];x,y=s['player']['x'],s['player']['y']
    if p['kind']=='casino_cards':
        bx=35 if i%2 else 685;by=40+e['jitter']*240
        theta=math.atan2(y-by,x-bx)
        for j in range(-2,3):
            a=theta+j*(.18-.04*d['intensity'])
            bullet(bx,by,math.cos(a)*d['speed']*.92,math.sin(a)*d['speed']*.92,6 if j==0 else 4,0,
                   motif='casino_card',tier='normal' if j==0 else 'minor',weight=.30 if j==0 else .08)
        if i%2:
            # A delayed second dealer catches one-direction movement; still telegraphed.
            bx=720-bx;theta=math.atan2(y-160,x-bx)
            bullet(bx,160,math.cos(theta)*d['speed']*.85,math.sin(theta)*d['speed']*.85,6,.24,motif='casino_card',weight=.30)
    elif p['kind']=='casino_roulette':
        add(dict(type='ring',x=x,y=y,r=22,speed=250+85*d['intensity'],gap=e['angle'],
                 gapWidth=1.8-.35*d['intensity'],thickness=9,motif='casino_roulette',weight=.6,tier='heavy'),0,1.25)
        bx=35 if i%2 else 685;a=math.atan2(y-160,x-bx)
        bullet(bx,160,math.cos(a)*d['speed']*.78,math.sin(a)*d['speed']*.78,5,.38,motif='casino_coin',weight=.12,tier='minor')
    elif p['kind']=='casino_slots':
        # Three reels: announced moving gaps, then a central jackpot coin.
        half=72-18*d['intensity'];gap=max(half+12,min(320-half-12,y+(-1 if i%2 else 1)*48))
        for top,height in ((0,gap-half),(gap+half,320-gap-half)):
            add(dict(type='rect',x=0,y=top,w=720,h=height,label=str(7),motif='casino_reel',weight=.35,tier='normal'),0,.18)
        bx=35 if i%2 else 685;theta=math.atan2(gap-160,x-bx)
        for j in (-1,0,1):
            a=theta+j*.19
            bullet(bx,160,math.cos(a)*d['speed']*.90,math.sin(a)*d['speed']*.90,8 if j==0 else 4,.30,
                   motif='casino_coin',weight=.75 if j==0 and i==len(s['events'])-1 else .3 if j==0 else .08,
                   tier='heavy' if j==0 else 'minor')
    elif p['kind']=='casino_dice':
        face=2+i%5
        pips={2:[(-1,-1),(1,1)],3:[(-1,-1),(0,0),(1,1)],4:[(-1,-1),(1,-1),(-1,1),(1,1)],5:[(-1,-1),(1,-1),(0,0),(-1,1),(1,1)]}[face]
        for dx,dy in pips:
            add(dict(type='circle',x=x+dx*38,y=y+dy*38,r=18,motif='casino_pip',face=face,weight=.22,tier='normal'),0,.28)
        bx=40 if i%2 else 680;by=40 if i%2 else 280;a=math.atan2(y-by,x-bx)
        bullet(bx,by,math.cos(a)*d['speed']*.80,math.sin(a)*d['speed']*.80,12,.42,motif='casino_die',face=face,weight=.45,tier='heavy')
    elif p['kind']=='casino_jackpot':
        vertical=i%2==0;half=58-8*d['intensity'];axis=720 if vertical else 320
        at=x if vertical else y;gap=max(half+12,min(axis-half-12,at+(-1 if i%4<2 else 1)*50))
        for lo,length in ((0,gap-half),(gap+half,axis-gap-half)):
            add(dict(type='rect',x=lo if vertical else 0,y=0 if vertical else lo,
                     w=length if vertical else 720,h=320 if vertical else length,
                     label='7',motif='casino_reel',weight=.35,tier='normal'),0,.16)
        if vertical:beam(gap,0,gap,320,9,.32,.14)
        else:beam(0,gap,720,gap,9,.32,.14)
        bx=32 if i%2 else 688;by=48 if i%3 else 272;a=math.atan2(y-by,x-bx)
        for j in (-1,0,1):
            angle=a+j*.17
            bullet(bx,by,math.cos(angle)*d['speed'],math.sin(angle)*d['speed'],6,.49,
                   motif='casino_coin',weight=.25 if j==0 else .10,tier='normal' if j==0 else 'minor')
        if i==5:
            add(dict(type='ring',x=x,y=y,r=22,speed=290,gap=e['angle'],gapWidth=1.6,
                     thickness=10,motif='casino_jackpot',weight=.8,tier='critical'),.50,1.0)


def block_threats(p,seed,params):
    if not p['kind'].startswith('casino_'):return None
    from arena_qte_patterns import random_values
    r=random_values(seed^p['seed']);offset=math.floor(next(r)*8)*math.pi/4
    result=[]
    def add(at,angle,weight=.3,kind='bolt',motif='casino_card',**extra):
        result.append(dict(at=at,warning=max(.60,params['warning'])+(.16 if kind=='wave' else 0),
            angle=math.atan2(math.sin(angle),math.cos(angle)),kind=kind,motif=motif,weight=weight,
            tier='critical' if weight>=.8 else 'heavy' if weight>=.6 else 'normal' if weight>=.3 else 'minor',resolved=False,**extra))
    if p['kind']=='casino_cards':
        for i in range(5):
            a=offset+i*p['polarity']*math.pi/2;at=2+i*1.4
            add(at,a,.12);add(at+.42,a if i%2==0 else a+math.pi/2,.3)
    elif p['kind']=='casino_roulette':
        for i in range(4):
            a=offset+p['polarity']*i*math.pi/2;at=2+i*1.65
            add(at,a,.45,'bolt','casino_ball',originAngle=a-p['polarity']*math.pi*1.5,label='ШАРИК · ПОЙМАЙ СЕКТОР')
            if i in (1,3):add(at+.55,a+math.pi/2,0,'feint','casino_zero',label='НОЛЬ · ОПУСТИ ЩИТ')
            else:add(at+.55,a+math.pi/2,.3,'bolt','casino_ball',originAngle=a,label='ОБРАТНАЯ СТАВКА')
        add(8.65,offset,.8,'wave','casino_bank',label='БАНК · ПОДНИМИ ЩИТ ЗАНОВО')
    elif p['kind']=='casino_dice':
        for round,face in enumerate((2,3,4)):
            a=offset+round*math.pi/2
            for pip in range(face):
                add(2+round*2.25+pip*.44,a+(pip%2)*math.pi/2,.60 if pip==face-1 else .18,
                    'slash','casino_die',face=face,pip=pip+1,label=f'КОСТЬ {face} · УДАР {pip+1}/{face}')
    elif p['kind']=='casino_jackpot':
        for reel in range(3):
            a=offset+reel*math.pi/2
            for j in range(3):
                direction=a+(j if reel%2==0 else -j)*math.pi/2
                add(2+reel*2+j*.46,direction,.6 if j==2 else .3,'slash','casino_reel',reel=reel+1,label=f'БАРАБАН {reel+1} · {j+1}/3')
        add(7.65,offset,0,'feint','casino_zero',label='СБОЙ 000 · ОПУСТИ ЩИТ')
        add(8.25,offset,.8,'wave','casino_bank',label='ДЖЕКПОТ · НОВЫЙ БЛОК')
        add(8.92,offset+math.pi,.6,'slash','casino_coin',label='ВЫПЛАТА · ПОСЛЕДНЯЯ МОНЕТА')
    else:
        for i in range(3):
            a=offset+i*p['polarity']*math.pi*2/3;at=2+i*2.25
            add(at,a,.12,'bolt','casino_coin');add(at+.48,a+math.pi/2,.3,'slash','casino_reel');add(at+1.08,a+math.pi,.6,'wave','casino_reel')
        add(8.9,offset,.75,'slash','casino_coin')
    result.sort(key=lambda e:e['at'])
    for i,e in enumerate(result):e.update(id=f'block:{i}',strike=min(p['strikes']-1,math.floor(i*p['strikes']/len(result))))
    return result
