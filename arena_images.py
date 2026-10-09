"""Validate untrusted fighter art; never store filenames, scripts or PNG metadata."""

from io import BytesIO
from PIL import Image, UnidentifiedImageError

MAX_SPRITE_BYTES = 2 * 1024 * 1024
MAX_SPRITE_SIDE = 1024


def normalize_sprite(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_SPRITE_BYTES:
        raise ValueError("PNG должен весить не больше 2 МБ.")
    try:
        with Image.open(BytesIO(raw), formats=["PNG"]) as source:
            if not all(16 <= side <= MAX_SPRITE_SIDE for side in source.size):
                raise ValueError("Каждая сторона PNG должна быть от 16 до 1024 пикселей.")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Пока поддерживается одна поза, без анимированных PNG.")
            source.load()
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            low, high = alpha.getextrema()
            if high == 0:
                raise ValueError("Картинка полностью прозрачная — бойца не видно.")
            if low == 255:
                raise ValueError("Нужен PNG с прозрачным фоном, а не сплошным прямоугольником.")
            # A fresh image removes EXIF, text chunks and other caller-supplied metadata.
            clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
            output = BytesIO()
            clean.save(output, format="PNG")
            result = output.getvalue()
            if len(result) > MAX_SPRITE_BYTES:
                raise ValueError("PNG после обработки слишком большой. Уменьши разрешение.")
            return result
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError("Не удалось прочитать PNG. Попробуй экспортировать его заново.") from error
