"""Prepare the approved drawings, without regenerating or redrawing their contents.

The user approved programmatic fringe cleanup. Keep the source atlas untouched;
remove faint alpha speckles, crop each glyph and resample from the original once.
"""

from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "webapp/assets/status-effects-v1.png"
DESTINATION = ROOT / "webapp/assets/status-effects-v3"
ICON_SIZE = 144  # Four physical pixels per 36 CSS pixels, also ample for the modal.


def clean_icon(icon: Image.Image) -> Image.Image:
    icon = icon.convert("RGBA")
    alpha = icon.getchannel("A").filter(ImageFilter.MedianFilter(3))
    alpha = alpha.point(lambda value: max(0, round((value - 64) * 255 / 191)))
    width, height = icon.size
    pixels = list(alpha.get_flattened_data())
    visited = bytearray(width * height)
    # Remove isolated edge noise, but preserve separate intentional drops/stars.
    minimum_area = max(16, round(width * height * 0.0003))
    for start, value in enumerate(pixels):
        if not value or visited[start]:
            continue
        pending = deque([start])
        visited[start] = 1
        component = []
        while pending:
            point = pending.popleft()
            component.append(point)
            x, y = point % width, point // width
            for nx in range(max(0, x - 1), min(width, x + 2)):
                for ny in range(max(0, y - 1), min(height, y + 2)):
                    other = ny * width + nx
                    if pixels[other] and not visited[other]:
                        visited[other] = 1
                        pending.append(other)
        if len(component) < minimum_area:
            for point in component:
                pixels[point] = 0
    alpha.putdata(pixels)
    icon.putalpha(alpha)
    box = alpha.getbbox()
    if box is None:
        raise ValueError("The status glyph is empty")
    return icon.crop(box)


def prepare(atlas: Image.Image) -> list[Image.Image]:
    result = []
    for index in range(16):
        column, row = index % 4, index // 4
        # Integer source boundaries avoid half-pixel atlas positioning at runtime.
        tile = atlas.crop(
            (
                column * atlas.width // 4,
                row * atlas.height // 4,
                (column + 1) * atlas.width // 4,
                (row + 1) * atlas.height // 4,
            )
        )
        glyph = clean_icon(tile)
        glyph.thumbnail((ICON_SIZE - 16, ICON_SIZE - 16), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE))
        canvas.alpha_composite(
            glyph, ((ICON_SIZE - glyph.width) // 2, (ICON_SIZE - glyph.height) // 2)
        )
        result.append(canvas)
    return result


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as atlas:
        icons = prepare(atlas)
    for index, icon in enumerate(icons):
        icon.save(DESTINATION / f"{index}.png", optimize=True)
    print(f"Prepared {len(icons)} original status drawings in {DESTINATION}")


if __name__ == "__main__":
    main()
