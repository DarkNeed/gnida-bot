"""Package generated status illustrations without altering their alpha or artwork.

Usage: python tools/prepare_status_art_v4.py --source-dir <imagegen output directory>
Only normal tight framing, downscaling and transparent padding are performed.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'art/status-effects-v4/generation.json'
DEST = ROOT / 'webapp/assets/status-effects-v4'


def package(source: Path) -> Image.Image:
    with Image.open(source) as image:
        image = image.convert('RGBA')
        alpha = image.getchannel('A')
        if alpha.getextrema() != (0, 255):
            raise ValueError(f'Expected transparent, opaque artwork: {source}')
        bbox = alpha.getbbox()
        if not bbox:
            raise ValueError(f'Empty image: {source}')
        image = image.crop(bbox)
        image.thumbnail((128, 128), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (144, 144))
        canvas.paste(image, ((144-image.width)//2, (144-image.height)//2))
        return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    DEST.mkdir(parents=True, exist_ok=True)
    entries = manifest['assets']
    columns, cell_w, cell_h = 8, 184, 204
    sheet = Image.new('RGB', (columns*cell_w, ((len(entries)+columns-1)//columns)*cell_h), '#101b2b')
    draw = ImageDraw.Draw(sheet)
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    font = ImageFont.truetype(str(font_path), 14) if font_path.exists() else ImageFont.load_default()
    for index, entry in enumerate(entries):
        source = args.source_dir / entry['source']
        icon = package(source)
        icon.save(DEST / (entry['key']+'.png'), optimize=True)
        x, y = index % columns * cell_w, index // columns * cell_h
        sheet.paste(icon, (x+20, y+2), icon)
        # The small copy is the real HUD size, displayed next to the label.
        small = icon.resize((32, 32), Image.Resampling.LANCZOS)
        sheet.paste(small, (x+8, y+156), small)
        draw.text((x+44, y+155), entry['label'], font=font, fill='#dce7f5')
        draw.text((x+44, y+175), entry['key'], font=font, fill='#8092ad')
    review = ROOT / 'art/status-effects-v4/review.png'
    sheet.save(review)
    print(f'Packaged {len(entries)} icons: {DEST}')
    print(f'Review: {review}')


if __name__ == '__main__':
    main()
