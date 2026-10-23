"""Mechanical game export: contain approved originals, preserve RGBA/proportions."""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'art' / 'casino-v1' / 'source'
TARGET = ROOT / 'webapp' / 'assets' / 'casino'


if __name__ == '__main__':
    for source in SOURCE.glob('*.png'):
        with Image.open(source) as image:
            sprite = ImageOps.contain(image.convert('RGBA'), (512, 768), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (512, 768))
        canvas.alpha_composite(sprite, ((512-sprite.width)//2, 768-sprite.height))
        destination = TARGET / source.name
        canvas.save(destination, optimize=True)
        print(destination.name, destination.stat().st_size)
