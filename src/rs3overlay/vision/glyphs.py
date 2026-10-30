"""Reading stack counts by matching individual glyph bitmaps.

Tesseract is built for prose: it wants a baseline, a language model, and more
than a handful of pixels per character. A bank stack count is the opposite of
that -- two or three characters from a 13-symbol alphabet, drawn at around ten
pixels tall in a fixed bitmap font, with a hard black outline. Measured on the
fixture bank, the best of 54 Tesseract configurations reached 17 of 32 counts
(53%) against the brief's 95% target, and no amount of preprocessing moved it
far.

What fits the problem is the structure Tesseract throws away: the alphabet is
tiny and the font is fixed, so each character can be compared against a
reference bitmap directly. The catch is that the game's outline welds adjacent
digits together -- the ``00`` of ``100`` arrives as a single blob -- so cutting
on connected components does not work either.

So the reader segments and recognises in one pass, with a small dynamic
program. Reading the text strip left to right, every position asks "which
character, at which width, best explains the pixels starting here?", and the
DP keeps the highest-scoring tiling of the whole strip. Scores are weighted by
the width each character covers, which makes segmentations with different
character counts directly comparable -- otherwise the search just invents extra
narrow characters to accumulate more terms.

Templates come from :func:`render_templates` (rendered from a TTF, which is
what the synthetic fixtures use) or from a calibration file produced by
``tools/calibrate_digits.py`` against real screenshots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: The full alphabet a stack count can use.
ALPHABET = "0123456789KMB"

#: Every template and every text strip is scaled to this height before
#: matching, which is what makes the reader independent of UI scale.
GLYPH_H = 16

#: Width tolerance, in pixels, either side of a template's natural width.
WIDTH_SLOP = 2

#: A character must beat this correlation to be placed at all.
MIN_GLYPH_SCORE = 0.40

#: Minimum mean score for a whole reading to be trusted.
MIN_TEXT_SCORE = 0.55


@dataclass
class GlyphTemplates:
    """One bitmap per character, all scaled to :data:`GLYPH_H` tall."""

    bitmaps: dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.bitmaps)

    def __bool__(self) -> bool:
        return bool(self.bitmaps)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "glyph_h": GLYPH_H,
            "bitmaps": {
                char: bitmap.astype(np.uint8).tolist()
                for char, bitmap in self.bitmaps.items()
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GlyphTemplates":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            {
                char: np.asarray(bitmap, dtype=np.uint8)
                for char, bitmap in payload["bitmaps"].items()
            }
        )


def read_text(binary: np.ndarray, templates: GlyphTemplates) -> tuple[str, float]:
    """Read a stack label out of a white-on-black binary image.

    Returns ``(text, mean_score)``. An empty string means the strip could not
    be explained confidently, which callers should treat as unknown rather
    than as zero.
    """
    import cv2

    if not templates or binary.size == 0:
        return "", 0.0

    strip = _to_strip(binary)
    if strip is None:
        return "", 0.0

    width = strip.shape[1]
    # Pre-scale every template to every width it is allowed to take, so the
    # inner DP loop is pure correlation.
    variants: list[tuple[str, int, np.ndarray]] = []
    for char, bitmap in templates.bitmaps.items():
        natural = bitmap.shape[1]
        for candidate in range(max(2, natural - WIDTH_SLOP), natural + WIDTH_SLOP + 1):
            resized = cv2.resize(
                bitmap, (candidate, GLYPH_H), interpolation=cv2.INTER_AREA
            )
            variants.append((char, candidate, resized))

    NEG = float("-inf")
    best = [NEG] * (width + 1)
    back: list[tuple[int, str, float] | None] = [None] * (width + 1)
    best[0] = 0.0

    column_empty = ~strip.any(axis=0)

    for x in range(width):
        if best[x] == NEG:
            continue
        # Inter-character spacing: stepping over a blank column is free.
        if column_empty[x] and best[x] > best[x + 1]:
            best[x + 1] = best[x]
            back[x + 1] = (x, "", 0.0)

        for char, w, template in variants:
            end = x + w
            if end > width:
                continue
            score = _correlate(strip[:, x:end], template)
            if score < MIN_GLYPH_SCORE:
                continue
            # Weighting by width makes tilings of different character counts
            # comparable: every column is scored exactly once either way.
            total = best[x] + score * w
            if total > best[end]:
                best[end] = total
                back[end] = (x, char, score)

    if best[width] == NEG:
        return "", 0.0

    chars: list[str] = []
    scores: list[float] = []
    position = width
    while position > 0:
        step = back[position]
        if step is None:
            return "", 0.0
        previous, char, score = step
        if char:
            chars.append(char)
            scores.append(score)
        position = previous

    if not chars:
        return "", 0.0

    chars.reverse()
    mean_score = float(np.mean(scores))
    if mean_score < MIN_TEXT_SCORE:
        return "", mean_score
    return "".join(chars), mean_score


def _to_strip(binary: np.ndarray) -> np.ndarray | None:
    """Crop to the ink and scale it to the canonical height."""
    import cv2

    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any() or not cols.any():
        return None

    top, bottom = np.where(rows)[0][[0, -1]]
    left, right = np.where(cols)[0][[0, -1]]
    cropped = binary[top : bottom + 1, left : right + 1]

    height, width = cropped.shape
    if height < 3 or width < 2:
        return None

    scale = GLYPH_H / height
    new_w = max(2, int(round(width * scale)))
    resized = cv2.resize(cropped, (new_w, GLYPH_H), interpolation=cv2.INTER_AREA)
    return (resized > 96).astype(np.uint8) * 255


def _correlate(a: np.ndarray, b: np.ndarray) -> float:
    """Zero-mean normalised correlation between two equal-sized bitmaps."""
    af = a.astype(np.float32).ravel()
    bf = b.astype(np.float32).ravel()
    af -= af.mean()
    bf -= bf.mean()
    denominator = float(np.linalg.norm(af) * np.linalg.norm(bf))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(af, bf) / denominator)


def _crop_to_ink(binary: np.ndarray) -> np.ndarray:
    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any() or not cols.any():
        return binary
    top, bottom = np.where(rows)[0][[0, -1]]
    left, right = np.where(cols)[0][[0, -1]]
    return binary[top : bottom + 1, left : right + 1]


def normalise_glyph(binary: np.ndarray) -> np.ndarray:
    """Scale one character's bitmap to :data:`GLYPH_H`, keeping its aspect."""
    import cv2

    cropped = _crop_to_ink(binary)
    height, width = cropped.shape
    if height < 1 or width < 1:
        return np.zeros((GLYPH_H, 2), np.uint8)
    scale = GLYPH_H / height
    new_w = max(2, int(round(width * scale)))
    resized = cv2.resize(cropped, (new_w, GLYPH_H), interpolation=cv2.INTER_AREA)
    return (resized > 96).astype(np.uint8) * 255


def render_templates(
    font_path: str | None = None, render_size: int = 11
) -> GlyphTemplates:
    """Build templates by rendering the alphabet through the read pipeline.

    Each character is drawn the way the game draws it -- stack colour over the
    slot background, with the hard dark outline -- and then pushed through the
    same colour isolation and normalisation the reader applies to a real slot.
    Rendering a clean glyph instead measures something the reader never sees:
    the outline changes the mask's shape, and matching a clean bitmap against
    an outlined one costs real accuracy.

    This is still only as good as the font, which is the catch. RS3 does not
    draw stack counts in DejaVu or Arial, so templates rendered on your machine
    are an approximation; ``tools/calibrate_digits.py`` builds them from your
    own screenshots instead, which is what the accuracy numbers in
    ``docs/ACCURACY.md`` are measured against.
    """
    import cv2
    from PIL import Image, ImageDraw

    from .ocr import dominant_stack_colour, stack_text_mask

    font = _load_font(font_path, render_size)
    bitmaps: dict[str, np.ndarray] = {}
    for char in ALPHABET:
        box = render_size * 4
        canvas = Image.new("RGB", (box, box), (34, 30, 22))
        draw = ImageDraw.Draw(canvas)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((render_size + dx, render_size + dy), char, fill=(0, 0, 0), font=font)
        draw.text((render_size, render_size), char, fill=(0, 255, 255), font=font)

        bgr = cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
        colour = dominant_stack_colour(bgr)
        binary = cv2.bitwise_not(stack_text_mask(bgr, colour))
        strip = _to_strip(binary)
        if strip is not None:
            bitmaps[char] = strip
    return GlyphTemplates(bitmaps)


def _load_font(font_path: str | None, size: int):
    from PIL import ImageFont

    candidates = [font_path] if font_path else []
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()
