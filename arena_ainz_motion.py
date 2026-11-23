"""Analytic projectile paths, identical to AinzQTE.motion in the browser."""
import math


def geometry(h,age):
    path=h['ainzPath']
    if path=='slidePolyline':
        return dict(h,points=[[x+age*h['dx'],y+age*h['dy']] for x,y in h['points']])
    if path=='driftRect':
        offset=math.sin(age*h['frequency']+h['offset'])-math.sin(h['offset'])
        return dict(h,x=h['x']+offset*h['driftX'],y=h['y']+offset*h['driftY'])
    if path=='sweepLine':
        return dict(h,ax=h['ax']+age*h['dx'],ay=h['ay']+age*h['dy'],
                    bx=h['bx']+age*h['dx'],by=h['by']+age*h['dy'])
    if path=='ricochet':
        def reflect(p,v,lo,hi):
            width=hi-lo;u=(p-lo+v*age)%(2*width)
            return (lo+u,v) if u<width else (hi-(u-width),-v)
        x,vx=reflect(h['x'],h['vx'],h['minX'],h['maxX'])
        y,vy=reflect(h['y'],h['vy'],h['minY'],h['maxY'])
        return dict(h,x=x,y=y,vx=vx,vy=vy)
    if path=='sealDrift':
        return dict(h,x=h['x']+math.sin(age*h['frequency'])*h['driftX'],
                    y=h['y']+math.sin(age*h['frequency']*.7)*h['driftY'])
    if path=='bezier':
        u=min(1,age/h['pathTime']);v=1-u
        x=v**3*h['x']+3*v*v*u*h['c1x']+3*v*u*u*h['c2x']+u**3*h['tx']
        y=v**3*h['y']+3*v*v*u*h['c1y']+3*v*u*u*h['c2y']+u**3*h['ty']
        vx=3*(v*v*(h['c1x']-h['x'])+2*v*u*(h['c2x']-h['c1x'])+u*u*(h['tx']-h['c2x']))/h['pathTime']
        vy=3*(v*v*(h['c1y']-h['y'])+2*v*u*(h['c2y']-h['c1y'])+u*u*(h['ty']-h['c2y']))/h['pathTime']
    elif path=='wave':
        length=math.hypot(h['vx'],h['vy']) or 1;nx,ny=-h['vy']/length,h['vx']/length
        damping=math.exp(-age*3)
        envelope=1-damping
        phase=age*h['frequency']
        sine=math.sin(phase)
        offset=h['amplitude']*sine*envelope
        derivative=h['amplitude']*(h['frequency']*math.cos(phase)*envelope+3*sine*damping)
        x,y=h['x']+h['vx']*age+nx*offset,h['y']+h['vy']*age+ny*offset
        vx,vy=h['vx']+nx*derivative,h['vy']+ny*derivative
    elif path=='orbitLaunch':
        t=min(age,h['releaseAt']);a=h['orbitAngle']+h['orbitSpeed']*t;r=h['orbitRadius']+h['spiral']*t
        x,y=h['cx']+math.cos(a)*r,h['cy']+math.sin(a)*r
        vx=math.cos(a)*h['spiral']-math.sin(a)*r*h['orbitSpeed']
        vy=math.sin(a)*h['spiral']+math.cos(a)*r*h['orbitSpeed']
        if age>h['releaseAt']:
            length=math.hypot(vx,vy) or 1
            vx,vy=vx/length*h['launchSpeed'],vy/length*h['launchSpeed']
            x+=vx*(age-h['releaseAt']);y+=vy*(age-h['releaseAt'])
    else:
        raise ValueError('Unknown Ainz trajectory')
    return dict(h,x=x,y=y,vx=vx,vy=vy)
