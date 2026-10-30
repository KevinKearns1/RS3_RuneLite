#!/usr/bin/env python3
"""Generate test fixtures: synthetic item icons and synthetic bank screenshots.

Real screenshots are the ground truth that matters, but you cannot write tests
against screenshots you do not have yet -- and the pipeline needs to be
provably correct on *something* before it is pointed at a live bank. So this
generates RS3-shaped inputs with known answers:

* ``icons`` draws a set of distinct item icons, deliberately including
  near-identical pairs, because telling two similar herbs apart is the failure
  mode the brief calls out.
* ``bank`` lays those icons into a bank-styled panel -- dark background,
  bordered slot lattice, a "The Bank of Gielinor" header, stack counts in the
  game's yellow/white/green bands -- and writes the ground truth beside it.

    python tools/make_fixtures.py icons --count 24 --out tests/fixtures/icons
    python tools/make_fixtures.py bank --icons tests/fixtures/icons \\
        --out tests/fixtures/bank_8x5.png

Once you have real screenshots, drop them in ``tests/fixtures/`` with a
matching ``<name>.truth.json`` and the same tests will run against those.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The interface palette we are imitating.
PANEL_BG = (18, 16, 12)
SLOT_BG = (34, 30, 22)
SLOT_BORDER = (72, 64, 46)
HEADER_TEXT = (232, 220, 192)

STACK_COLOURS = {
    "yellow": (255, 255, 0),
    "white": (255, 255, 255),
    "green": (0, 255, 128),
}


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


# --- icons ----------------------------------------------------------------


def make_icon(seed: int, size: int = 32, hue: float | None = None,
              shape: str | None = None) -> Image.Image:
    """Draw one distinct item icon with a transparent background."""
    rng = random.Random(seed)
    hue = rng.random() if hue is None else hue
    shape = shape or rng.choice(["potion", "gem", "leaf", "bar", "log"])

    base = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.75, 0.85))
    dark = tuple(int(c * 0.55) for c in base)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    m = size // 8

    if shape == "potion":
        draw.rectangle([size // 2 - 3, m, size // 2 + 3, m * 3], fill=dark + (255,))
        draw.ellipse([m, m * 3, size - m, size - m], fill=base + (255,), outline=dark + (255,))
    elif shape == "gem":
        draw.polygon(
            [(size // 2, m), (size - m, size // 2), (size // 2, size - m), (m, size // 2)],
            fill=base + (255,), outline=dark + (255,),
        )
    elif shape == "leaf":
        draw.ellipse([m, m, size - m, size - m * 2], fill=base + (255,), outline=dark + (255,))
        draw.line([(size // 2, m * 2), (size // 2, size - m)], fill=dark + (255,), width=2)
    elif shape == "bar":
        draw.polygon(
            [(m, size - m * 2), (size - m, size - m * 2), (size - m * 2, m * 3), (m * 2, m * 3)],
            fill=base + (255,), outline=dark + (255,),
        )
    else:  # log
        draw.rounded_rectangle(
            [m, size // 3, size - m, size - size // 3], radius=4,
            fill=base + (255,), outline=dark + (255,),
        )

    return image


def generate_icons(out_dir: Path, count: int, similar_pairs: int) -> int:
    """Write ``count`` icons plus an index.json, including near-identical pairs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    unique = max(0, count - similar_pairs * 2)
    item_id = 1000

    for i in range(unique):
        icon = make_icon(seed=i, hue=i / max(1, unique))
        name = f"Test item {i:02d}"
        filename = f"test_item_{i:02d}.png"
        icon.save(out_dir / filename)
        index[filename] = {"item_id": item_id, "name": name}
        item_id += 1

    # Pairs that differ only slightly in hue -- the herb problem, synthesised.
    for p in range(similar_pairs):
        hue = 0.28 + p * 0.004
        for variant, offset in (("a", 0.0), ("b", 0.006)):
            icon = make_icon(seed=900 + p, hue=hue + offset, shape="leaf")
            name = f"Similar herb {p}{variant}"
            filename = f"similar_herb_{p}{variant}.png"
            icon.save(out_dir / filename)
            index[filename] = {"item_id": item_id, "name": name}
            item_id += 1

    (out_dir / "index.json").write_text(
        json.dumps(index, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(f"wrote {len(index)} icons to {out_dir}")
    return 0


# --- bank screenshot ------------------------------------------------------


def stack_colour_for(quantity: int) -> str:
    if quantity >= 10_000_000:
        return "green"
    if quantity >= 100_000:
        return "white"
    return "yellow"


def format_stack(quantity: int) -> str:
    """Abbreviate the way the game does above the display thresholds."""
    if quantity >= 10_000_000:
        return f"{quantity // 1_000_000}M"
    if quantity >= 100_000:
        return f"{quantity // 1_000}K"
    return str(quantity)


def render_bank(
    icon_dir: Path,
    out_path: Path,
    cols: int = 8,
    rows: int = 5,
    cell: int = 40,
    fill_ratio: float = 0.8,
    seed: int = 7,
    scale: float = 1.0,
) -> int:
    """Render a bank-like screenshot and its ground-truth JSON."""
    rng = random.Random(seed)

    index_path = icon_dir / "index.json"
    if not index_path.exists():
        print(f"no index.json in {icon_dir} -- run 'make_fixtures.py icons' first")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    icon_files = sorted(index)
    if not icon_files:
        print("icon index is empty")
        return 1

    pad = 24
    header_h = 46
    width = pad * 2 + cols * cell
    height = pad * 2 + header_h + rows * cell

    image = Image.new("RGB", (width, height), PANEL_BG)
    draw = ImageDraw.Draw(image)

    # Header, so the title-OCR path has something real to find.
    title = "The Bank of Gielinor"
    font = _font(20)
    text_w = draw.textbbox((0, 0), title, font=font)[2]
    draw.text(((width - text_w) // 2, pad // 2 + 6), title, fill=HEADER_TEXT, font=font)

    grid_x = pad
    grid_y = pad + header_h
    truth: list[dict] = []
    count_font = _font(11)

    for row in range(rows):
        for col in range(cols):
            left = grid_x + col * cell
            top = grid_y + row * cell
            draw.rectangle(
                [left, top, left + cell, top + cell],
                fill=SLOT_BG, outline=SLOT_BORDER, width=1,
            )

            if rng.random() > fill_ratio:
                continue

            filename = rng.choice(icon_files)
            meta = index[filename]
            icon = Image.open(icon_dir / filename).convert("RGBA")
            icon_size = cell - 8
            icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
            image.paste(icon, (left + 4, top + 4), icon)

            magnitude = rng.choice([1, 2, 2, 3, 4, 5, 7])
            quantity = rng.randint(1, 9) * (10 ** (magnitude - 1))
            label = format_stack(quantity)
            colour = STACK_COLOURS[stack_colour_for(quantity)]

            # The game draws a hard black outline behind the digits; reproduce
            # it, because that outline is exactly what makes the OCR hard.
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((left + 3 + dx, top + 2 + dy), label, fill=(0, 0, 0), font=count_font)
            draw.text((left + 3, top + 2), label, fill=colour, font=count_font)

            truth.append(
                {
                    "row": row, "col": col,
                    "item_id": meta["item_id"], "name": meta["name"],
                    "icon_file": filename,
                    "quantity": quantity, "label": label,
                }
            )

    if scale != 1.0:
        image = image.resize(
            (int(width * scale), int(height * scale)), Image.LANCZOS
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)

    truth_path = out_path.with_suffix(".truth.json")
    truth_path.write_text(
        json.dumps(
            {
                "grid": {"cols": cols, "rows": rows, "cell": cell,
                         "x0": grid_x, "y0": grid_y, "scale": scale},
                "slots": truth,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_path} ({image.width}x{image.height}, {len(truth)} filled slots)")
    print(f"wrote {truth_path}")
    return 0


def render_non_bank(out_path: Path, seed: int = 3) -> int:
    """A screenshot that is *not* a bank, for the false-positive test."""
    rng = random.Random(seed)
    image = Image.new("RGB", (640, 420), (26, 34, 20))
    draw = ImageDraw.Draw(image)
    for _ in range(140):
        x, y = rng.randint(0, 620), rng.randint(0, 400)
        draw.ellipse([x, y, x + rng.randint(6, 40), y + rng.randint(6, 40)],
                     fill=(rng.randint(20, 90), rng.randint(40, 120), rng.randint(20, 70)))
    # A 4-column inventory, which must not be mistaken for a bank.
    for row in range(7):
        for col in range(4):
            left, top = 480 + col * 36, 60 + row * 36
            draw.rectangle([left, top, left + 36, top + 36],
                           fill=SLOT_BG, outline=SLOT_BORDER)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"wrote {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    icons = sub.add_parser("icons", help="generate synthetic reference icons")
    icons.add_argument("--out", type=Path, default=PROJECT_ROOT / "tests/fixtures/icons")
    icons.add_argument("--count", type=int, default=24)
    icons.add_argument("--similar-pairs", type=int, default=2)

    bank = sub.add_parser("bank", help="render a synthetic bank screenshot")
    bank.add_argument("--icons", type=Path, default=PROJECT_ROOT / "tests/fixtures/icons")
    bank.add_argument("--out", type=Path, default=PROJECT_ROOT / "tests/fixtures/bank_8x5.png")
    bank.add_argument("--cols", type=int, default=8)
    bank.add_argument("--rows", type=int, default=5)
    bank.add_argument("--cell", type=int, default=40)
    bank.add_argument("--fill-ratio", type=float, default=0.8)
    bank.add_argument("--seed", type=int, default=7)
    bank.add_argument("--scale", type=float, default=1.0,
                      help="resample the finished image, to test UI scaling")

    nonbank = sub.add_parser("non-bank", help="render a non-bank screenshot")
    nonbank.add_argument("--out", type=Path,
                         default=PROJECT_ROOT / "tests/fixtures/not_a_bank.png")

    args = parser.parse_args(argv)
    if args.command == "icons":
        return generate_icons(args.out, args.count, args.similar_pairs)
    if args.command == "bank":
        return render_bank(args.icons, args.out, args.cols, args.rows, args.cell,
                           args.fill_ratio, args.seed, args.scale)
    return render_non_bank(args.out)


if __name__ == "__main__":
    sys.exit(main())
