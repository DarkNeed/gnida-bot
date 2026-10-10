"""Export user-approved preview art as compact, consistent battle sprites.

Run from the repository root. Never modifies original preview images.
"""

from pathlib import Path

from PIL import Image, ImageOps

from arena_archclasses import ARCHCLASSES

ROOT = Path(__file__).resolve().parents[1]


def export():
    target = ROOT / "webapp" / "assets" / "archclasses"
    target.mkdir(parents=True, exist_ok=True)
    for key in ARCHCLASSES:
        revision = "revision4" if key.startswith("middle_") else "revision3"
        source = ROOT / "output" / "archclass-review" / revision / (key + ".png")
        with Image.open(source) as original:
            sprite = original.convert("RGBA")
        bounds = sprite.getchannel("A").getbbox()
        if not bounds:
            raise ValueError(f"Empty sprite: {key}")
        sprite = ImageOps.contain(sprite.crop(bounds), (464, 720), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (512, 768), (0, 0, 0, 0))
        canvas.paste(sprite, ((512 - sprite.width) // 2, 744 - sprite.height))
        path = target / (key + ".png")
        canvas.save(path, optimize=True)
        print(key, path.stat().st_size)


if __name__ == "__main__":
    export()
