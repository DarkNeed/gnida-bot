"""Export approved RPG cutouts; never repaint or overwrite their source art.

The user authorized alpha-only halo cleanup. The same cleanup as pets keeps
dark clothes intact; do not use RGB black/white colour keying.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_pet_sprites import clean_alpha

RPG_SPRITES = {'warrior': 'Воин', 'mage': 'Маг', 'priest': 'Жрец', 'hunter': 'Охотник'}


def export(source, target, review):
    target.mkdir(parents=True, exist_ok=True)
    review.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (1200, 660), '#172334')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24)
    for index, (key, name) in enumerate(RPG_SPRITES.items()):
        with Image.open(source / (key + '.png')) as original:
            sprite = clean_alpha(original)
        bounds = sprite.getchannel('A').getbbox()
        if not bounds:
            raise ValueError('Empty sprite: ' + key)
        sprite = ImageOps.contain(sprite.crop(bounds), (464, 720), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (512, 768), (0, 0, 0, 0))
        canvas.paste(sprite, ((512 - sprite.width) // 2, 744 - sprite.height))
        # Remove hidden RGB introduced by resizing; retain visible edge alpha.
        canvas.paste((0, 0, 0, 0), (0, 0), canvas.getchannel('A').point(lambda v: 255 if v == 0 else 0))
        path = target / (key + '.png')
        canvas.save(path, optimize=True)
        thumb = ImageOps.contain(canvas, (290, 580), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (index * 300 + (300 - thumb.width) // 2, 18), thumb)
        draw.text((index * 300 + 28, 616), name, font=font, fill='#f6d28b')
        print(key, canvas.size, path.stat().st_size, canvas.getchannel('A').getbbox())
    sheet.save(review)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'art' / 'rpg-v1')
    parser.add_argument('--target', type=Path, default=ROOT / 'webapp' / 'assets' / 'rpg')
    parser.add_argument('--review', type=Path, default=ROOT / 'output' / 'rpg-sprites-review.png')
    args = parser.parse_args()
    export(args.source, args.target, args.review)
