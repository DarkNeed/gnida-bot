"""Export the approved NPC cutouts, retaining untouched source PNGs.

The user explicitly approved alpha-only halo removal and smaller UI copies.
Run from any working directory with the project's Pillow-enabled Python.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'art/npc-workers-v1'
TARGET = ROOT / 'webapp/assets/npc-workers-v1'
LABELS = {'accountant': 'Гоблин-счетовод', 'skeleton': 'Скелет',
          'paladin': 'Бывший паладин', 'diplomat': 'Дипломат',
          'miner': 'Шахтёр', 'mechanic': 'Механик'}


def clean(source):
    image = Image.open(source).convert('RGBA')
    # Drawing is near-opaque (max 254); the generated fog is translucent.
    # Change alpha only: do not repaint or chroma-key any character pixels.
    alpha = image.getchannel('A').point(lambda v: max(0, min(255, round((v - 160) * 255 / 85))))
    if not alpha.getbbox():
        raise ValueError(f'Empty cutout: {source}')
    image.putalpha(alpha)
    return image.crop(alpha.getbbox())


def fit(image, size):
    thumb = image.copy()
    thumb.thumbnail((size[0] - 16, size[1] - 16), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', size)
    canvas.alpha_composite(thumb, ((size[0] - thumb.width) // 2, size[1] - 8 - thumb.height))
    return canvas


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    results = []
    sheet = Image.new('RGB', (1440, 930), '#101b2b')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 19)
    small = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 15)
    for row, gender in enumerate(('male', 'female')):
        for col, (profession, label) in enumerate(LABELS.items()):
            key = f'{profession}-{gender}'
            original = ART / 'source' / f'{key}.png'
            cutout = clean(original)
            sizes = {}
            for suffix, size in (('', (512, 768)), ('-small', (160, 240))):
                path = TARGET / f'{key}{suffix}.png'
                fit(cutout, size).save(path, optimize=True)
                sizes[suffix or 'sprite'] = path.stat().st_size
            results.append(dict(id=key, bytes=sizes))
            x, y = col * 240, row * 465
            draw.rounded_rectangle((x+7, y+8, x+233, y+455), radius=12, fill='#19283e', outline='#344761')
            preview = fit(cutout, (220, 390))
            sheet.paste(preview, (x+10, y+10), preview)
            draw.text((x+120, y+407), label, font=font, fill='#e0e8f4', anchor='mt')
            draw.text((x+120, y+434), 'Мужской' if gender == 'male' else 'Женский', font=small, fill='#aabbd2', anchor='mt')
    sheet.save(ART / 'contact-sheet.jpg', quality=92)
    (ART / 'EXPORT.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
