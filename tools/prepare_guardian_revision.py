"""Approved deterministic image downscaling. Preserve generated source and alpha."""
from pathlib import Path
from PIL import Image
import argparse

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--variant',default='gargantua-v2',choices=('gargantua-v2','gargantua-phase2-v1'))
variant=parser.parse_args().variant
source=ROOT/f'art/nazarick-dungeon-v2/source/{variant}.png'
im=Image.open(source).convert('RGBA')
bounds=im.getbbox()
if not bounds:raise ValueError('Empty Gargantua sprite')
im=im.crop(bounds)
canvas=(640,860) if variant=='gargantua-v2' else (860,700)
im.thumbnail((canvas[0]-40,canvas[1]-50),Image.Resampling.LANCZOS)
out=Image.new('RGBA',canvas)
out.alpha_composite(im,((canvas[0]-im.width)//2,canvas[1]-20-im.height))
out.save(ROOT/f'webapp/assets/nazarick-dungeon-v2/{variant}.png',optimize=True)
print(f'Prepared {variant}; source and other variants untouched.')
