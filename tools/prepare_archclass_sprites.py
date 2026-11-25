"""Export user-approved preview art as compact, consistent battle sprites.

Run from the repository root. Never modifies original preview images.
"""

from pathlib import Path

from PIL import Image, ImageOps

from arena_archclasses import ARCHCLASSES
from arena_cultist import FORMS as CULT_FORMS
from arena_rpg import RPG_BRANCHES

ROOT = Path(__file__).resolve().parents[1]


def fit_sprite(source, path, *, trim_threshold=0):
    """Deployment copy: no repainting or background masking, preserve alpha."""
    with Image.open(source) as original:
        sprite = original.convert("RGBA")
    alpha = sprite.getchannel("A")
    # Ignore faint pixels only when finding the crop; keep alpha inside it.
    bounds = (alpha.point(lambda value: 255 if value > trim_threshold else 0)
              if trim_threshold else alpha).getbbox()
    if not bounds:
        raise ValueError(f"Empty sprite: {source}")
    sprite = ImageOps.contain(sprite.crop(bounds), (464, 720), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (512, 768), (0, 0, 0, 0))
    canvas.paste(sprite, ((512 - sprite.width) // 2, 744 - sprite.height))
    canvas.save(path, optimize=True)


def export():
    target = ROOT / "webapp" / "assets" / "archclasses"
    target.mkdir(parents=True, exist_ok=True)
    for key in ARCHCLASSES:
        if key in CULT_FORMS:
            continue  # Cultist sprites have their own generated sources.
        if key in RPG_BRANCHES:
            # RPG branches currently reuse the approved initial class sprites.
            # Their export pipeline is tools/prepare_rpg_sprites.py.
            continue
        revision = "revision4" if key.startswith("middle_") else "revision3"
        source = ROOT / "output" / "archclass-review" / revision / (key + ".png")
        path = target / (key + ".png")
        fit_sprite(source, path)
        print(key, path.stat().st_size)


if __name__ == "__main__":
    export()
