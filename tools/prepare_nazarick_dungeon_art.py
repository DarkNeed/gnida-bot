"""User-authorized alpha cleanup / smaller copies; generated originals stay intact."""
import json
from pathlib import Path
import shutil
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'art/nazarick-dungeon-v2'
OUT=ROOT/'webapp/assets/nazarick-dungeon-v2'

def main():
    paths=json.loads((ART/'SOURCES.json').read_text(encoding='utf-8'))
    (ART/'source').mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    metadata=[];sprites=[];backgrounds=[]
    for key,path in paths.items():
        raw=ART/'source'/f'{key}.png'
        if not raw.exists():shutil.copy2(path,raw)
        im=Image.open(raw).convert('RGBA')
        if key.startswith('bg_'):
            im=ImageOps.fit(im.convert('RGB'),(1600,900),method=Image.Resampling.LANCZOS)
            im.save(OUT/f'{key}.webp',quality=87);backgrounds.append((key,im))
        else:
            alpha=im.getchannel('A');hist=alpha.histogram()
            # A translucent character (Victim) keeps its interior; only edge fog is clipped.
            floor=65 if key=='victim' else 155
            im.putalpha(alpha.point(lambda a:round(max(0,min(1,(a-floor)/(245-floor)))*255)))
            bounds=im.getbbox()
            if not bounds:raise ValueError(f'Empty silhouette: {key}')
            im=im.crop(bounds);im.thumbnail((600,820),Image.Resampling.LANCZOS)
            canvas=Image.new('RGBA',(640,860));canvas.alpha_composite(im,((640-im.width)//2,840-im.height))
            canvas.save(OUT/f'{key}.png',optimize=True)
            thumb=canvas.copy();thumb.thumbnail((160,215),Image.Resampling.LANCZOS);thumb.save(OUT/f'{key}_thumb.png',optimize=True)
            sprites.append((key,canvas));metadata.append(dict(id=key,alpha_peak=max(j for j,n in enumerate(hist) if n),removed_floor=floor))
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
    sheet=Image.new('RGB',(4*256,((len(sprites)+3)//4)*370),'#182235');draw=ImageDraw.Draw(sheet)
    for i,(key,im) in enumerate(sprites):
        x=i%4*256;y=i//4*370;preview=im.copy();preview.thumbnail((240,325),Image.Resampling.LANCZOS)
        sheet.paste(preview,(x+(256-preview.width)//2,y),preview);draw.text((x+12,y+335),key,font=font,fill='#e0d6bf')
    sheet.save(ART/'sprites-review.jpg',quality=93)
    if backgrounds:
        sheet=Image.new('RGB',(1000,((len(backgrounds)+1)//2)*305),'#10182a');draw=ImageDraw.Draw(sheet)
        for i,(key,im) in enumerate(backgrounds):
            p=im.resize((500,281));x=i%2*500;y=i//2*305;sheet.paste(p,(x,y));draw.text((x+10,y+280),key,font=font,fill='white')
        sheet.save(ART/'backgrounds-review.jpg',quality=92)
    (ART/'EXPORT.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Prepared {len(sprites)} sprites and {len(backgrounds)} backgrounds. Originals preserved.')

if __name__=='__main__':main()
