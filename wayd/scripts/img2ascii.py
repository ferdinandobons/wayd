#!/usr/bin/env python3
"""Convert an image to high-quality ASCII art for WAYD posts.

Produces results comparable to asciiart.eu: edge-enhanced, sharpened,
contrast-boosted, with a dense 70-char gradient.

Usage:
  img2ascii.py --image PATH [--width N] [--invert] [--caption TEXT]
               [--edge-weight F] [--sharpen] [--contrast F]

Prints JSON to stdout: {"ok": true, "art": "...", "chars": N}

Options:
  --image PATH       Image file (JPEG, PNG, GIF, WebP, DNG, …)
  --width N          Width in chars (default: 80). Height auto-calculated.
  --invert           Invert brightness (for light-background images).
  --caption TEXT     Text appended below the art (2 blank lines separator).
  --threshold N      Brightness cutoff 0-255; pixels above this become spaces
                     (default: 140). Lower = more sparse; higher = denser.
  --edge-weight F    How much edge detection to blend in, 0.0–1.0 (default 0.3).
  --sharpen          Apply sharpening before conversion (default: on).
  --no-sharpen       Disable sharpening.
  --contrast F       Contrast multiplier (default: 2.2). 1.0 = no change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shared  # noqa: E402

# Sparse character set — dark to light (last char = space for bright areas).
# Matches asciiart.eu "Space Density 6" aesthetic: lots of whitespace,
# dense chars only in shadows/edges. Far more legible than a 70-char ramp.
_CHARS_DARK = "@%#*+=-:. "
_CHARS_LIGHT = _CHARS_DARK[::-1]


def _px(luminance: int, threshold: int, chars: str) -> str:
    """Return a character for a given pixel luminance.

    Pixels brighter than `threshold` become spaces (light/sky areas).
    Darker pixels are mapped across the non-space portion of `chars`.
    """
    if luminance >= threshold:
        return " "
    idx = int(luminance / threshold * (len(chars) - 2))
    return chars[max(0, min(len(chars) - 2, idx))]


def image_to_ascii(
    image_path: str,
    width: int = 80,
    invert: bool = False,
    threshold: int = 140,
    edge_weight: float = 0.3,
    sharpen: bool = True,
    contrast: float = 2.2,
    caption: str = "",
    max_chars: int | None = None,
) -> str:
    """Return ASCII art string. Raises ValueError on failure.

    Uses a sparse character set with a brightness threshold — pixels above
    the threshold become spaces, producing the airy asciiart.eu aesthetic
    where light areas (sky, backgrounds) are empty and only shadows/edges
    carry characters.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter  # type: ignore[import]
    except ImportError:
        raise ValueError("Pillow is required: pip install Pillow")

    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        raise ValueError(f"Image not found: {image_path}")
    except Exception as exc:
        raise ValueError(f"Cannot open image: {exc}")

    img = img.convert("RGB")

    if sharpen:
        img = ImageEnhance.Sharpness(img).enhance(3.0)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    gray = img.convert("L")

    # Terminal chars are ~2:1 tall:wide; 0.45 corrects aspect ratio.
    aspect = img.height / img.width
    height = max(1, int(width * aspect * 0.45))

    if max_chars is not None:
        caption_cost = len(caption) + 2 if caption else 0
        while width >= 20:
            if width * height + height + caption_cost <= max_chars:
                break
            width = int(width * 0.9)
            height = max(1, int(width * aspect * 0.45))

    base = gray.resize((width, height), Image.LANCZOS)
    edge_src = gray.filter(ImageFilter.GaussianBlur(1)).filter(ImageFilter.FIND_EDGES)
    edges = edge_src.resize((width, height), Image.LANCZOS)

    base_px = base.tobytes()
    edge_px = edges.tobytes()

    chars = _CHARS_LIGHT if invert else _CHARS_DARK
    lines: list[str] = []

    for row in range(height):
        row_chars = []
        for col in range(width):
            idx = row * width + col
            b = base_px[idx]
            e = edge_px[idx]
            blended = int(b * (1 - edge_weight) + (255 - e) * edge_weight)
            blended = max(0, min(255, blended))
            row_chars.append(_px(blended, threshold, chars))
        lines.append("".join(row_chars).rstrip())  # trim trailing spaces

    art = "\n".join(lines)
    if caption:
        art = art + "\n\n" + caption
    return art


def main() -> None:
    parser = argparse.ArgumentParser(description="High-quality image → ASCII art.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--caption", default="")
    parser.add_argument("--threshold", type=int, default=140)
    parser.add_argument("--edge-weight", type=float, default=0.3)
    parser.add_argument("--sharpen", dest="sharpen", action="store_true", default=True)
    parser.add_argument("--no-sharpen", dest="sharpen", action="store_false")
    parser.add_argument("--contrast", type=float, default=2.2)
    parser.add_argument("--max-chars", type=int, default=None)
    args = parser.parse_args()

    try:
        art = image_to_ascii(
            image_path=args.image,
            width=args.width,
            invert=args.invert,
            threshold=args.threshold,
            edge_weight=args.edge_weight,
            sharpen=args.sharpen,
            contrast=args.contrast,
            caption=args.caption,
            max_chars=args.max_chars,
        )
    except ValueError as exc:
        shared.emit({"ok": False, "code": "img2ascii_error", "message": str(exc)})
        sys.exit(1)

    shared.emit({"ok": True, "art": art, "chars": len(art)})


if __name__ == "__main__":
    main()
