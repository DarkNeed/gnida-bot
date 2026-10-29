"""User-authorized alpha-only halo removal. Keep original art and RGB intact.

Uses the solid-alpha support approach of prepare_pet_sprites.py, but never
rescales foreground opacity, resizes, crops, or repaints the monster itself.
Offline art tool; Pillow is not an extra dependency of the running bot.
"""
import json
from pathlib import Path
import shutil
from PIL import Image, ImageChops, ImageFilter

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'art/guild-v1'


def clean_alpha(image):
    image=image.convert('RGBA')
    original=image.getchannel('A')
    # A two-pixel antialiased fringe protects fur, moss and thin weapon edges.
    support=original.point(lambda v:255 if v>=160 else 0).filter(ImageFilter.MaxFilter(5))
    alpha=ImageChops.multiply(original,support).point(lambda v:0 if v<20 else v)
    image.putalpha(alpha)
    return image


def export():
    manifest=json.loads((ART/'SOURCES.json').read_text(encoding='utf-8'))
    source_dir=ART/'source';source_dir.mkdir(exist_ok=True)
    report=[]
    for record in manifest['files']:
        key=record['id'];source=source_dir/(key+'.png')
        if not source.exists():shutil.copyfile(record['source'],source)
        target=ROOT/'webapp/assets/guild'/(key+'-v1.png')
        with Image.open(source) as original:
            original=original.convert('RGBA');result=clean_alpha(original)
            result.save(target,optimize=True)
            removed=ImageChops.subtract(original.getchannel('A'),result.getchannel('A'))
            report.append(dict(id=key,source=str(source.relative_to(ROOT)),
                target=str(target.relative_to(ROOT)),size=list(result.size),
                pixels_cleaned=sum(removed.histogram()[1:]),bytes=target.stat().st_size))
            print(key,report[-1]['pixels_cleaned'],'pixels cleaned')
    (ART/'EXPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':export()
