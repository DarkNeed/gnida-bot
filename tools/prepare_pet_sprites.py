"""User-authorized alpha-only halo cleanup, size normalization and review sheet.

Original generated PNGs are never modified. RGB artwork is not repainted.
"""
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1] / "art" / "pets-v1"


def clean_alpha(original):
    image = original.convert("RGBA")
    alpha = image.getchannel("A")
    # Keep a narrow antialiased fringe around solid artwork, including whiskers.
    # Broad low-opacity clouds cannot survive outside this support mask.
    support = alpha.point(lambda value: 255 if value >= 160 else 0)
    support = support.filter(ImageFilter.MaxFilter(5))
    alpha = ImageChops.multiply(alpha, support)
    alpha = alpha.point(lambda value: 0 if value < 20 else min(255, round(value * 255 / 250)))
    image.putalpha(alpha)
    # Clear hidden RGB so viewers/exporters cannot resurrect the background.
    empty = alpha.point(lambda value: 255 if value == 0 else 0)
    image.paste((0, 0, 0, 0), (0, 0), empty)
    return image


def export():
    catalog = json.loads((ROOT / "PROMPTS.json").read_text(encoding="utf-8"))["pets"]
    clean = ROOT / "clean"
    clean.mkdir(exist_ok=True)
    report = []
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    font = ImageFont.truetype(str(font_path), 22)
    small = ImageFont.truetype(str(font_path), 15)
    sheet = Image.new("RGB", (1400, 1720), "#0b1019")
    draw = ImageDraw.Draw(sheet)
    draw.text((36, 25), "ПИТОМЦЫ АРЕНЫ · 16 СПУТНИКОВ", font=font, fill="#e3b96a")
    draw.text((36, 61), "Первый набор спрайтов · эскизы для утверждения", font=small, fill="#929fb1")
    for index, pet in enumerate(catalog):
        source = ROOT / (pet["id"] + ".png")
        with Image.open(source) as original:
            sprite = clean_alpha(original)
        box = sprite.getchannel("A").getbbox()
        if box is None:
            raise ValueError("Empty sprite: " + pet["id"])
        sprite = ImageOps.contain(sprite.crop(box), (688, 704), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (768, 768))
        canvas.paste(sprite, ((768 - sprite.width) // 2, (768 - sprite.height) // 2))
        target = clean / (pet["id"] + ".png")
        canvas.save(target, optimize=True)
        x = 20 + index % 4 * 345
        y = 105 + index // 4 * 399
        draw.rounded_rectangle((x, y, x + 328, y + 382), radius=15, fill="#151e2b", outline="#2c3746")
        thumbnail = ImageOps.contain(canvas, (306, 306), Image.Resampling.LANCZOS)
        sheet.paste(thumbnail, (x + 11, y + 10), thumbnail)
        draw.text((x + 14, y + 323), pet["name"], font=font, fill="#e8e6df")
        draw.text((x + 14, y + 354), f"{index + 1:02} · PNG / прозрачный фон", font=small, fill="#8c9caf")
        report.append(dict(id=pet["id"], original_size=Image.open(source).size,
                           export_size=(768, 768), bytes=target.stat().st_size))
        print(pet["id"], target.stat().st_size)
    sheet.save(ROOT / "contact-sheet.jpg", quality=93)
    (ROOT / "EXPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export()
