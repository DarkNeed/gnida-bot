"""Extract approved art without repainting (user-authorized background removal).

Offline tooling only: Pillow, numpy and opencv-python-headless, not bot dependencies.
Original sheets are immutable. Exports are alpha-masked RGB copies, up to 512 x 768.
"""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / 'output/rpg-archclasses-review-v2'
V3 = ROOT / 'output/rpg-archclasses-review-v3'
SHEETS = [
    (V3 / 'warrior-path.png', 2, ((0, .465), (.466, .945)),
     ('warrior_berserker', 'warrior_knight', 'warrior_berserker_final', 'warrior_knight_final')),
    (V3 / 'priest-path.png', 2, ((0, .457), (.436, .953)),
     ('priest_bishop', 'priest_paladin', 'priest_bishop_final', 'priest_paladin_final')),
    (V3 / 'necromancers.png', 2, ((0, .910),),
     ('mage_necromancer', 'mage_necromancer_final')),
    (V2 / 'mage-path.png', 3, ((0, .462), (.477, .955)),
     (None, 'mage_elementalist', 'mage_archmage', None, 'mage_elementalist_final', 'mage_archmage_final')),
    (V2 / 'hunter-path.png', 2, ((0, .478), (.476, .952)),
     ('hunter_beast', 'hunter_moon', 'hunter_beast_final', 'hunter_moon_final')),
]


def extract(original, key=''):
    rgb = np.array(original.convert('RGB'))
    r, g, b = (rgb[:, :, i].astype(np.int16) for i in range(3))
    # The sheets' background is a dark navy gradient, not generic black.
    # Gray/black fabric, warm skin, gold and colored spells remain foreground.
    navy = (r < 52) & (g-r > 7) & (b-g > 5) & (b < 100) & (np.abs((g-r)-(b-g)) < 12)
    mask = np.where(navy, cv2.GC_PR_BGD, cv2.GC_PR_FGD).astype(np.uint8)
    mask[(~navy) & ((r+g+b > 170) | (b-r < 3))] = cv2.GC_FGD
    # Only navy pixels on the crop perimeter are definite background: do not
    # delete weapons/flames that reach the original cell boundary.
    edge = np.zeros(navy.shape, bool)
    edge[:2] = edge[-2:] = True
    edge[:, :2] = edge[:, -2:] = True
    mask[edge & navy] = cv2.GC_BGD
    cv2.setRNGSeed(173)
    cv2.grabCut(rgb, mask, None, np.zeros((1,65)), np.zeros((1,65)), 5, cv2.GC_INIT_WITH_MASK)
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    alpha[navy & (mask != cv2.GC_FGD)] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(alpha)
    largest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    main = (labels == largest).astype(np.uint8)
    distance = cv2.distanceTransform(1-main, cv2.DIST_L2, 3)
    keep = np.zeros(count, bool)
    keep[largest] = True
    for component in range(1,count):
        x,y,w,h,area=stats[component]
        # Detached magic near a hand can stay; caption letters, cell-edge
        # fragments of neighbors and far-away scraps cannot become sprites.
        if area>=350 and y>alpha.shape[0]*.12 and y+h < alpha.shape[0]*.90 and x>2 and x+w<alpha.shape[1]-2 and distance[labels==component].min()<25:
            keep[component]=True
        if key=='hunter_moon_final' and area>=20 and x>alpha.shape[1]*.65 and y>alpha.shape[0]*.03 and y+h<alpha.shape[0]*.35:
            keep[component]=True  # approved detached lunar shard above the hand
    alpha = (keep[labels] * 255).astype(np.uint8)
    rgba = np.dstack((rgb, alpha))
    rgba[alpha == 0] = 0
    return Image.fromarray(rgba)


def export(target, review, overwrite=False):
    target.mkdir(parents=True, exist_ok=True)
    review.parent.mkdir(parents=True, exist_ok=True)
    thumbs, report = [], []
    for source, columns, rows, keys in SHEETS:
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        with Image.open(source) as sheet:
            for index, key in enumerate(keys):
                if not key:
                    continue
                path = target / (key + '.png')
                if path.exists() and not overwrite:
                    raise FileExistsError(path)
                row, col = divmod(index, columns)
                box = (round(col*sheet.width/columns), round(rows[row][0]*sheet.height),
                       round((col+1)*sheet.width/columns), round(rows[row][1]*sheet.height))
                sprite = extract(sheet.crop(box),key)
                # A weapon or Phoenix's fire crosses into the adjacent knight
                # cell in the source sheet; those fragments are not its gear.
                if key in ('warrior_knight','warrior_knight_final'):
                    pixels=np.array(sprite)
                    red=(pixels[:,:,0].astype(float)>pixels[:,:,2]*1.15)&(pixels[:,:,0]>60)
                    red[:,round(sprite.width*.23):]=False
                    pixels[red]=0
                    sprite=Image.fromarray(pixels)
                bounds = sprite.getchannel('A').getbbox()
                if not bounds:
                    raise ValueError('Empty character: ' + key)
                sprite = ImageOps.contain(sprite.crop(bounds), (464, 720), Image.Resampling.LANCZOS)
                canvas = Image.new('RGBA', (512, max(96,sprite.height+48)))
                canvas.paste(sprite, ((512-sprite.width)//2, canvas.height-24-sprite.height))
                canvas.paste((0,0,0,0), (0,0), canvas.getchannel('A').point(lambda v:255 if v==0 else 0))
                canvas.save(path, optimize=True)
                thumbs.append((key,canvas))
                report.append(dict(id=key,source=str(source.relative_to(ROOT)),source_sha256=source_hash,
                                   crop=box,bytes=path.stat().st_size))
                print(key,path.stat().st_size)
    contact = Image.new('RGB', (1800, 6*470), '#131e2b')
    draw = ImageDraw.Draw(contact)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    for i,(key,sprite) in enumerate(thumbs):
        x,y=(i%6)*300,(i//6)*940
        thumb=ImageOps.contain(sprite,(280,410),Image.Resampling.LANCZOS)
        for offset,color in ((0,'#131e2b'),(470,'#c9c4bb')):
            draw.rectangle((x,y+offset,x+299,y+offset+469),fill=color)
            contact.paste(thumb,(x+(300-thumb.width)//2,y+offset+12),thumb)
            draw.text((x+8,y+offset+432),key,font=font,fill='white' if not offset else 'black')
    contact.save(review)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,default=ROOT/'webapp/assets/archclasses')
    parser.add_argument('--review',type=Path,default=ROOT/'output/rpg-archclasses-exports.png')
    parser.add_argument('--overwrite',action='store_true')
    args=parser.parse_args()
    report=export(args.target,args.review,args.overwrite)
    print(json.dumps(report,ensure_ascii=False,indent=2))
