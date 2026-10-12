#!/usr/bin/env python3
"""
make_icon.py - create the app icons for aero_auto.

Use priority:
  1) assets/Logoertblanc.png   (your supplied logo)
  2) assets/source.png         (any square/rect logo you drop in)
  3) generated placeholder with an 'AERO' mark

Outputs assets/icon.png (512x512) and assets/icon.ico (Windows multi-size).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def _placeholder(size=512):
    img = Image.new("RGBA", (size, size), (11, 34, 61, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([size * 0.06, size * 0.06, size * 0.94, size * 0.94],
                        radius=size * 0.12, fill=(13, 63, 128, 255),
                        outline=(247, 158, 11, 255), width=max(2, size // 90))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size // 4)
    except Exception:
        font = ImageFont.load_default()
    text = "AERO\nAUTO"
    d.multiline_text((size / 2, size / 2), text, fill="white",
                     font=font, anchor="mm", align="center",
                     stroke_width=max(1, size // 220), stroke_fill=(247, 158, 11, 255))
    return img


def main():
    if not os.path.isdir(ASSETS):
        os.makedirs(ASSETS, exist_ok=True)
    source = None
    for name in ("Logoertblanc.png", "source.png"):
        p = os.path.join(ASSETS, name)
        if os.path.exists(p):
            source = p
            print("using", p)
            break
    if source is None:
        print("no logo found in assets/ -> generating placeholder (drop Logoertblanc.png there to switch)")
        img = _placeholder()
    else:
        img = Image.open(source).convert("RGBA")

    icon_png = os.path.join(ASSETS, "icon.png")
    img.resize((512, 512), Image.LANCZOS).save(icon_png)

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.thumbnail((256, 256), Image.LANCZOS)
    icon_ico = os.path.join(ASSETS, "icon.ico")
    img.save(icon_ico, sizes=sizes)
    print("wrote", icon_png)
    print("wrote", icon_ico)
    return 0


if __name__ == "__main__":
    sys.exit(main())