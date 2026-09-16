#!/usr/bin/env python3
"""Teach the reader your client's stack-count font, once.

Why this exists: the glyph reader in ``rs3overlay.vision.glyphs`` matches each
character against a reference bitmap, and it is only as good as those bitmaps.
The built-in templates are rendered from whatever bold sans font your machine
has, which is *not* the font RS3 draws stack counts in -- on the synthetic
fixtures that approximation reads about two thirds of counts correctly (see
``docs/ACCURACY.md``). Templates built from your own screenshots remove the
guess.

It deliberately does not try to infer the labels for you. Automatically
segmenting a label like ``100`` and assuming the pieces line up with its
characters was tried and measured: seeded from rendered templates it drove
fixture accuracy *down*, from 19/32 to 15/32, because a bad segmentation
averages bad pixels into the template and the error compounds. So this asks
you instead, and only about characters it can isolate cleanly.

    python tools/calibrate_digits.py captures/*.png

For each distinct glyph it finds, it prints the bitmap as text and asks which
character it is. Press enter to skip one you cannot read. Roughly 13 answers
covers the alphabet; more samples per character make the template cleaner.
Results go to ``assets/font/stack_digits.json``, which the app loads
automatically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rs3overlay.config import Config  # noqa: E402
from rs3overlay.vision import glyphs as G  # noqa: E402
from rs3overlay.vision.grid import find_grid, slice_cells  # noqa: E402
from rs3overlay.vision.ocr import (  # noqa: E402
    count_region,
    dominant_stack_colour,
    stack_text_mask,
)

#: Two candidate glyphs closer than this are treated as the same shape, so you
#: are not asked about the same ``0`` fifty times.
DEDUPE_SCORE = 0.93


def candidates_from(image: np.ndarray) -> list[np.ndarray]:
    """Every cleanly-isolated character bitmap in one bank screenshot."""
    grid = find_grid(image)
    if grid is None:
        return []

    found: list[np.ndarray] = []
    for cell in slice_cells(image, grid, skip_empty=True):
        region = count_region(cell.image)
        colour = dominant_stack_colour(region)
        if colour == "none":
            continue
        binary = cv2.bitwise_not(stack_text_mask(region, colour))

        count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        heights = [stats[i][3] for i in range(1, count)]
        if not heights:
            continue
        line_height = int(np.median(heights))

        for label in range(1, count):
            x, y, w, h, area = stats[label]
            # Only take components that are plausibly a single character:
            # full line height, and not wide enough to be two merged glyphs.
            if h < max(4, line_height - 1) or h > line_height + 1:
                continue
            if area < 4 or w > h * 1.1:
                continue
            found.append(binary[y : y + h, x : x + w])
    return found


def dedupe(patches: list[np.ndarray]) -> list[list[np.ndarray]]:
    """Group visually identical glyphs so each shape is asked about once."""
    groups: list[list[np.ndarray]] = []
    normalised: list[np.ndarray] = []
    for patch in patches:
        norm = G.normalise_glyph(patch)
        placed = False
        for i, reference in enumerate(normalised):
            width = min(norm.shape[1], reference.shape[1])
            if width < 2:
                continue
            score = G._correlate(norm[:, :width], reference[:, :width])
            if score >= DEDUPE_SCORE:
                groups[i].append(patch)
                placed = True
                break
        if not placed:
            groups.append([patch])
            normalised.append(norm)
    return groups


def show(patch: np.ndarray) -> None:
    for row in patch:
        print("   " + "".join("#" if value else "." for value in row))


def build(groups: list[list[np.ndarray]], answers: dict[int, str]) -> G.GlyphTemplates:
    """Average each labelled group into one template."""
    by_char: dict[str, list[np.ndarray]] = {}
    for index, char in answers.items():
        by_char.setdefault(char, []).extend(groups[index])

    bitmaps: dict[str, np.ndarray] = {}
    for char, patches in by_char.items():
        strips = [s for s in (G._to_strip(p) for p in patches) if s is not None]
        if not strips:
            continue
        width = max(2, int(np.median([s.shape[1] for s in strips])))
        stack = np.stack(
            [cv2.resize(s, (width, G.GLYPH_H), interpolation=cv2.INTER_AREA) for s in strips]
        )
        bitmaps[char] = (stack.mean(axis=0) > 110).astype(np.uint8) * 255
    return G.GlyphTemplates(bitmaps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("screenshots", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--max-prompts", type=int, default=40, help="stop asking after this many"
    )
    args = parser.parse_args(argv)

    config = Config.load()
    out = args.out or config.resolve(config.glyph_templates_path)

    patches: list[np.ndarray] = []
    for path in args.screenshots:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"skipping unreadable file: {path}")
            continue
        found = candidates_from(image)
        print(f"{path}: {len(found)} isolated glyph(s)")
        patches.extend(found)

    if not patches:
        print(
            "\nNo isolated glyphs found. That usually means the screenshots are "
            "not bank\nscreens, or every count in them is a single unstacked "
            "item with no number\ndrawn. Capture a few tabs with stacked items "
            "and try again."
        )
        return 1

    groups = dedupe(patches)
    groups.sort(key=len, reverse=True)
    print(f"\n{len(patches)} glyphs collapsed into {len(groups)} distinct shapes.")
    print(f"Type the character for each. Enter skips. Alphabet: {G.ALPHABET}\n")

    answers: dict[int, str] = {}
    for index, group in enumerate(groups[: args.max_prompts]):
        show(group[0])
        try:
            reply = input(f"   seen {len(group)}x -- which character? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nstopping early")
            break
        if not reply:
            continue
        char = reply[0].upper()
        if char not in G.ALPHABET:
            print(f"   '{char}' is not in the alphabet, skipping")
            continue
        answers[index] = char

    if not answers:
        print("nothing labelled, not writing a template file")
        return 1

    templates = build(groups, answers)
    templates.save(out)
    missing = [c for c in G.ALPHABET if c not in templates.bitmaps]
    print(f"\nwrote {out} with {len(templates)} character(s)")
    if missing:
        print(
            "not yet covered: " + "".join(missing) +
            "\nThe reader falls back to its rendered template for those. Run "
            "again with\nmore screenshots to fill them in."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
