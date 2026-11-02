"""Draws the LyricLoom icon (no external image assets). Run once when changing the brand."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 512


def lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded night-sky tile.
    top, bottom = (22, 24, 54), (58, 31, 90)
    for y in range(SIZE):
        draw.line([(0, y), (SIZE, y)], fill=lerp(top, bottom, y / SIZE) + (255,))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=112, fill=255)
    img.putalpha(mask)

    # Stars.
    import random

    rng = random.Random(7)
    d = ImageDraw.Draw(img)
    for _ in range(48):
        x, y = rng.randrange(30, SIZE - 30), rng.randrange(30, 300)
        r = rng.choice((1, 1, 1, 2))
        d.ellipse([x, y, x + r, y + r], fill=(220, 230, 255, rng.randrange(90, 220)))

    # Three lyric lines: two dim, the current one gold.
    d.rounded_rectangle([92, 322, 420, 346], radius=12, fill=(101, 113, 153, 255))
    d.rounded_rectangle([92, 370, 360, 394], radius=12, fill=(255, 209, 102, 255))
    d.rounded_rectangle([92, 418, 300, 442], radius=12, fill=(101, 113, 153, 255))

    # A music note, the "sung" word.
    d.ellipse([300, 174, 372, 246], fill=(139, 233, 253, 255))
    d.rounded_rectangle([352, 116, 376, 210], radius=12, fill=(139, 233, 253, 255))
    d.polygon([(376, 116), (436, 92), (436, 142), (376, 166)], fill=(139, 233, 253, 255))

    out = ROOT / "packaging" / "windows" / "LyricLoom.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    png = ROOT / "lyricloom" / "assets" / "icon.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.Resampling.LANCZOS).save(png)
    print(out)
    print(png)


if __name__ == "__main__":
    main()
