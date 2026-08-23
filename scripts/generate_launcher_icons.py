#!/usr/bin/env python3
"""Regenerate Android launcher icons from the approved Lily logo asset.

Uses ONLY desktop/app/assets/images/logo_transparent_officiel.png as source.
Writes mipmap webp launchers (square + round) at all densities.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path("/home/ayman/car-rental-system")
LOGO = ROOT / "mobile/app/src/main/res/drawable/logo_transparent_officiel.png"
MIPMAP = ROOT / "mobile/app/src/main/res"

DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def build_canvas(size: int) -> Image.Image:
    """White rounded-canvas with the logo centered at ~78% width."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    logo = Image.open(LOGO).convert("RGBA")
    target_w = int(size * 0.78)
    ratio = target_w / logo.width
    target_h = max(1, int(logo.height * ratio))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    pos = ((size - target_w) // 2, (size - target_h) // 2)
    img.alpha_composite(logo, pos)
    return img


def make_round(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, img.size[0] - 1, img.size[1] - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main():
    for folder, size in DENSITIES.items():
        out_dir = MIPMAP / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        square = build_canvas(size)
        round_img = make_round(square)
        square.save(out_dir / "ic_launcher.webp", "WEBP", quality=90)
        round_img.save(out_dir / "ic_launcher_round.webp", "WEBP", quality=90)
        print(f"wrote {folder}: {size}px")


if __name__ == "__main__":
    main()
