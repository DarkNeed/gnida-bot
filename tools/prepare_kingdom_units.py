"""User-approved alpha cleanup and reduced UI copies. Originals stay immutable.

Offline tooling: Pillow, numpy, OpenCV (already used by approved RPG extraction).
No RGB repainting: segmentation changes alpha, then exports a resized WebP copy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'art/kingdom-units-v1'
TARGET=ROOT/'webapp/assets/kingdom/units'
NAMES={'militia':'Ополчение','vagrants':'Свора с вокзала','shields':'Щитоносцы','archers':'Следопыты',
       'agents':'Бархатные агенты','paladins':'Паладины','priests':'Жрецы','skeletons':'Костяная смена','necromancers':'Некроманты'}


def clean(image):
    rgba=np.array(image.convert('RGBA'));rgb=rgba[:,:,:3].copy();a=rgba[:,:,3]
    blur=cv2.GaussianBlur(rgb.astype(np.float32),(0,0),2)
    texture=np.abs(rgb.astype(np.float32)-blur).mean(axis=2)
    brightness=rgb.max(axis=2)
    mask=np.full(a.shape,cv2.GC_PR_BGD,np.uint8)
    mask[(a>230)&(texture>1.2)]=cv2.GC_PR_FGD
    mask[(a>235)&(texture>3)&(brightness>40)]=cv2.GC_FGD
    mask[a<8]=cv2.GC_BGD
    if (mask==cv2.GC_FGD).sum()<100:raise ValueError('Too few reliable foreground seeds')
    cv2.setRNGSeed(173)
    cv2.grabCut(rgb,mask,None,np.zeros((1,65)),np.zeros((1,65)),5,cv2.GC_INIT_WITH_MASK)
    keep=np.isin(mask,(cv2.GC_FGD,cv2.GC_PR_FGD)).astype(np.uint8)
    count,labels,stats,_=cv2.connectedComponentsWithStats(keep)
    if count<2:raise ValueError('Empty sprite')
    largest=1+np.argmax(stats[1:,cv2.CC_STAT_AREA]);main=(labels==largest).astype(np.uint8)
    distance=cv2.distanceTransform(1-main,cv2.DIST_L2,3)
    accepted=np.zeros(count,bool);accepted[largest]=True
    for component in range(1,count):
        if stats[component,cv2.CC_STAT_AREA]>=30 and distance[labels==component].min()<12:accepted[component]=True
    alpha=accepted[labels].astype(np.uint8)*255
    alpha=cv2.GaussianBlur(alpha,(3,3),.4)
    rgba[:,:,3]=np.minimum(a,alpha);rgba[rgba[:,:,3]==0]=0
    return Image.fromarray(rgba)


def run(only=None):
    TARGET.mkdir(parents=True,exist_ok=True);(ART/'source').mkdir(exist_ok=True)
    manifest=json.loads((ART/'manifest.json').read_text(encoding='utf-8'));reports=[]
    for entry in manifest['units']:
        key=entry['id'];original=ART/'source'/(key+'.png')
        if not original.exists():shutil.copy2(entry['generated_path'],original)
        if only and key!=only:continue
        with Image.open(original) as image:
            sprite=clean(image);box=sprite.getchannel('A').getbbox()
            if not box:raise ValueError('Empty: '+key)
            small=ImageOps.contain(sprite.crop(box),(344,536),Image.Resampling.LANCZOS)
            canvas=Image.new('RGBA',(384,576));canvas.alpha_composite(small,((384-small.width)//2,556-small.height))
            canvas.save(TARGET/(key+'.webp'),format='WEBP',quality=88,method=6)
            reports.append(dict(id=key,source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                                output=str((TARGET/(key+'.webp')).relative_to(ROOT)),bytes=(TARGET/(key+'.webp')).stat().st_size))
    (ART/('export-'+only+'.json' if only else 'export.json')).write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(900,990),'#12222f');draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
    for i,key in enumerate(NAMES):
        path=TARGET/(key+'.webp')
        if not path.exists():continue
        with Image.open(path) as im:
            thumb=ImageOps.contain(im,(270,285),Image.Resampling.LANCZOS)
            x=(i%3)*300+(300-thumb.width)//2;y=(i//3)*330
            sheet.paste(thumb,(x,y),thumb)
            draw.text(((i%3)*300+150,y+300),NAMES[key],font=font,fill='#d8c6a4',anchor='mm')
    out=ROOT/'output/kingdom-units-review.jpg';sheet.save(out,quality=94)
    print(json.dumps(dict(review=str(out),exports=reports),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--only',choices=NAMES)
    run(parser.parse_args().only)
