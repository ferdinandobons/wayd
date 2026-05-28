#!/usr/bin/env python3
"""Convert an image to high-quality ASCII art for WAYD posts.

Uses Jarvis-Judice-Ninke error diffusion dithering with a sparse character
set and brightness threshold — matching the asciiart.eu aesthetic:
light/background areas become spaces, only edges and shadows get chars.

Usage:
  img2ascii.py --image PATH [--width N] [--invert] [--threshold N]
               [--contrast F] [--caption TEXT]

Prints JSON to stdout: {"ok": true, "art": "...", "chars": N}
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shared  # noqa: E402

# Sparse ramp dark→light. Last entry is space (bright pixels).
_RAMP_DARK = "@%#*+:. "
_RAMP_LIGHT = _RAMP_DARK[::-1]


def image_to_ascii(
    image_path: str,
    width: int = 120,
    invert: bool = False,
    contrast: float = 1.5,
    threshold: int = 200,
    caption: str = "",
    max_chars: int | None = None,
) -> str:
    """Return ASCII art string using JJN dithering + threshold. Raises ValueError on failure."""
    try:
        from PIL import Image, ImageEnhance, ImageOps  # type: ignore[import]
    except ImportError:
        raise ValueError("Pillow is required: pip install Pillow")

    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        raise ValueError(f"Image not found: {image_path}")
    except Exception as exc:
        raise ValueError(f"Cannot open image: {exc}")

    img = img.convert("RGB")

    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    gray = img.convert("L")

    # Equalize histogram so the full 0-255 range is used regardless of image tone
    gray = ImageOps.equalize(gray)

    aspect = img.height / img.width
    height = max(1, int(width * aspect * 0.45))

    if max_chars is not None:
        caption_cost = len(caption) + 2 if caption else 0
        while width >= 20:
            if width * height + height + caption_cost <= max_chars:
                break
            width = int(width * 0.9)
            height = max(1, int(width * aspect * 0.45))

    gray = gray.resize((width, height), Image.LANCZOS)

    ramp = _RAMP_LIGHT if invert else _RAMP_DARK
    n_chars = len(ramp) - 1  # last slot = space, reserved for threshold
    step = threshold / n_chars

    px = [[float(gray.getpixel((x, y))) for x in range(width)] for y in range(height)]

    lines: list[str] = []
    for y in range(height):
        row: list[str] = []
        for x in range(width):
            old = max(0.0, min(255.0, px[y][x]))

            if old >= threshold:
                # Bright pixel → space, distribute error
                err = old - 255.0
                char = " "
            else:
                level = min(n_chars - 1, int(old / step))
                err = old - level * step
                char = ramp[level]

            # Jarvis-Judice-Ninke error diffusion kernel (denominator 48)
            for dy, dx, w in (
                (0, 1, 7), (0, 2, 5),
                (1, -2, 3), (1, -1, 5), (1, 0, 7), (1, 1, 5), (1, 2, 3),
                (2, -2, 1), (2, -1, 3), (2, 0, 5), (2, 1, 3), (2, 2, 1),
            ):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    px[ny][nx] += err * w / 48.0

            row.append(char)
        lines.append("".join(row).rstrip())

    art = "\n".join(lines)
    if caption:
        art = art + "\n\n" + caption
    return art


def main() -> None:
    parser = argparse.ArgumentParser(description="High-quality image → ASCII art (JJN dithering).")
    parser.add_argument("--image", required=True)
    parser.add_argument("--width", type=int, default=120)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--caption", default="")
    parser.add_argument("--contrast", type=float, default=1.5)
    parser.add_argument("--threshold", type=int, default=200)
    parser.add_argument("--max-chars", type=int, default=None)
    args = parser.parse_args()

    try:
        art = image_to_ascii(
            image_path=args.image,
            width=args.width,
            invert=args.invert,
            contrast=args.contrast,
            threshold=args.threshold,
            caption=args.caption,
            max_chars=args.max_chars,
        )
    except ValueError as exc:
        shared.emit({"ok": False, "code": "img2ascii_error", "message": str(exc)})
        sys.exit(1)

    shared.emit({"ok": True, "art": art, "chars": len(art)})


if __name__ == "__main__":
    main()
