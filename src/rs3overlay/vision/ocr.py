"""Phase 3: reading the stack count off a slot.

Two things make this harder than "run Tesseract on the crop":

* The text is tiny, stylised, and drawn with a hard black outline over
  arbitrary item art. Tesseract needs it isolated and upscaled first.
* Past certain thresholds the game abbreviates -- ``41.1K``, ``1.2M``, ``2B``
  -- so the parser has to understand suffixes, not just digits.

RuneScape also colour-codes the count, and that colour is a genuinely useful
second signal: yellow under 100K, white from 100K, green from 10M. We use it
both to isolate the glyphs from the item art behind them and to sanity-check
the magnitude the OCR came back with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .glyphs import GlyphTemplates

#: HSV ranges for the three stack-count colours, as (low, high) pairs.
#: OpenCV hue is 0-179.
_COLOUR_RANGES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "yellow": ((20, 90, 120), (38, 255, 255)),
    "white": ((0, 0, 190), (179, 45, 255)),
    "green": ((40, 90, 110), (85, 255, 255)),
}

#: What each colour implies about magnitude, used only as a sanity check.
_COLOUR_BOUNDS: dict[str, tuple[int, float]] = {
    "yellow": (1, 99_999),
    "white": (100_000, 9_999_999),
    "green": (10_000_000, float("inf")),
}

_SUFFIX_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

_STACK_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([KMB]?)\s*$", re.IGNORECASE)


@dataclass
class OCRSettings:
    """Knobs for the OCR pass."""

    tesseract_cmd: str = ""
    upscale: int = 4

    def apply(self) -> None:
        """Point pytesseract at a specific binary, if the user configured one."""
        if not self.tesseract_cmd:
            return
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd


@dataclass
class StackReading:
    """What we read out of one slot's count region."""

    quantity: int | None
    raw_text: str
    colour: str
    confidence: float

    @property
    def ok(self) -> bool:
        return self.quantity is not None


def parse_stack_text(text: str) -> int | None:
    """Turn a stack label into an integer.

    Handles ``"137"``, ``"1,234"``, ``"41.1K"``, ``"1.2M"``, ``"2B"``. Returns
    ``None`` for anything it does not confidently understand -- an unreadable
    count should surface as unknown, not as a plausible-looking wrong number.
    """
    if not text:
        return None

    cleaned = text.strip().replace(" ", "").replace("O", "0").replace("o", "0")
    # A comma is a thousands separator only when it groups three digits;
    # otherwise the game is using it as a decimal point in some locales.
    if re.fullmatch(r"\d{1,3}(,\d{3})+", cleaned):
        return int(cleaned.replace(",", ""))

    match = _STACK_PATTERN.match(cleaned)
    if not match:
        return None

    number, suffix = match.groups()
    number = number.replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        return None

    if suffix:
        value *= _SUFFIX_MULTIPLIERS[suffix.upper()]
    elif "." in number:
        # A bare decimal with no suffix is not a thing the game draws; it is
        # almost always a misread dot in the middle of digits.
        return None

    if value < 0:
        return None
    return int(round(value))


#: A colour must have at least this many outline-adjacent pixels to be
#: considered the stack-count colour at all.
_MIN_OUTLINE_PIXELS = 6

#: ...and at least this fraction of its pixels must touch the outline.
_MIN_OUTLINE_RATIO = 0.2


def _outline_adjacency(region: np.ndarray) -> np.ndarray:
    """Mask of pixels sitting next to something near-black.

    The game draws stack counts with a hard dark outline, and item art does
    not have one around every pixel. That difference is what lets us pick the
    text colour out of a slot whose icon happens to share it.
    """
    import cv2

    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    dark = (gray < 60).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    return cv2.dilate(dark, kernel)


def dominant_stack_colour(region: np.ndarray) -> str:
    """Which of the three stack-count colours the digits are drawn in.

    Ranking by raw pixel count does not work: a green item icon behind a
    yellow count outnumbers the count's own pixels and wins the vote, and the
    subsequent mask then contains the icon instead of the digits. Measured on
    the fixture bank, raw counts got 29 of 32 slots right; ranking by
    *outline-adjacent* pixels gets 32 of 32.
    """
    import cv2

    if region.size == 0:
        return "none"

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    near_dark = _outline_adjacency(region)

    best, best_adjacent = "none", 0
    for name, (low, high) in _COLOUR_RANGES.items():
        mask = cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
        total = int(mask.sum() // 255)
        if total == 0:
            continue
        adjacent = int(cv2.bitwise_and(mask, near_dark).sum() // 255)
        if adjacent < _MIN_OUTLINE_PIXELS:
            continue
        if adjacent / total < _MIN_OUTLINE_RATIO:
            continue
        if adjacent > best_adjacent:
            best, best_adjacent = name, adjacent

    return best


def stack_text_mask(region: np.ndarray, colour: str) -> np.ndarray:
    """Binary image of just the count glyphs, black-on-white for Tesseract."""
    import cv2

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    if colour in _COLOUR_RANGES:
        low, high = _COLOUR_RANGES[colour]
        mask = cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
        # Keep only the outlined pixels, so a same-coloured icon behind the
        # digits does not leak into the text.
        mask = cv2.bitwise_and(mask, _outline_adjacency(region))
    else:
        # No colour lock: fall back to "much brighter than its surroundings".
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    # Close single-pixel gaps left by the glyphs' dark outline.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return cv2.bitwise_not(mask)


def count_region(cell: np.ndarray) -> np.ndarray:
    """The part of a slot where the stack count is drawn (its top-left)."""
    height, width = cell.shape[:2]
    return cell[: max(1, int(height * 0.45)), : max(1, int(width * 0.85))]


def read_stack_count(
    cell: np.ndarray,
    settings: OCRSettings | None = None,
    templates: "GlyphTemplates | None" = None,
) -> StackReading:
    """Read the stack count from one slot crop.

    Two readers run and then vote. The glyph reader
    (:mod:`rs3overlay.vision.glyphs`) is the accurate one when its templates
    match the font in front of it; Tesseract is the one that still says
    something useful when they do not. Agreement between them is the strongest
    signal available, so it is scored highest; disagreement falls back to
    whichever answer is consistent with the colour the count is drawn in.

    A slot with no count drawn on it holds exactly one of the item, which is
    how the game renders unstacked items -- so "no text found" means 1, not
    "unknown".
    """
    import cv2

    settings = settings or OCRSettings()
    settings.apply()

    region = count_region(cell)
    colour = dominant_stack_colour(region)
    if colour == "none":
        return StackReading(quantity=1, raw_text="", colour="none", confidence=0.9)

    inverted = stack_text_mask(region, colour)
    binary = cv2.bitwise_not(inverted)

    glyph_value, glyph_text, glyph_score = _read_with_glyphs(binary, templates)
    tess_value, tess_text = _read_with_tesseract(inverted, settings)

    return _combine(colour, glyph_value, glyph_text, glyph_score, tess_value, tess_text)


def _read_with_glyphs(
    binary: np.ndarray, templates: "GlyphTemplates | None"
) -> tuple[int | None, str, float]:
    if templates is None or not templates:
        return None, "", 0.0
    from .glyphs import read_text

    text, score = read_text(binary, templates)
    return parse_stack_text(text), text, score


def _read_with_tesseract(
    inverted: np.ndarray, settings: OCRSettings
) -> tuple[int | None, str]:
    """Tesseract on the upscaled mask. Best of a few page-segmentation modes.

    A single mode is not reliable here: measured across the fixture bank, psm 7,
    8 and 13 each read counts the others missed, so we take the first that
    parses rather than betting on one.
    """
    import cv2

    try:
        import pytesseract
    except ImportError:
        return None, ""

    scale = max(1, settings.upscale)
    enlarged = cv2.resize(
        inverted, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
    )
    # Thicken the glyphs slightly: eroding a white background grows black text.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    enlarged = cv2.erode(enlarged, kernel)
    # A quiet border stops Tesseract clipping glyphs that touch the edge.
    enlarged = cv2.copyMakeBorder(
        enlarged, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255
    )

    for psm in (8, 13, 7):
        config = f"--psm {psm} --oem 3 -c tessedit_char_whitelist=0123456789KMB"
        try:
            text = pytesseract.image_to_string(enlarged, config=config).strip()
        except Exception:  # noqa: BLE001 - a missing binary is survivable
            return None, ""
        value = parse_stack_text(text)
        if value is not None:
            return value, text
    return None, ""


def _consistent(value: int | None, colour: str) -> bool:
    """Whether a quantity agrees with the colour band it was drawn in."""
    if value is None:
        return False
    low, high = _COLOUR_BOUNDS.get(colour, (0, float("inf")))
    return low <= value <= high


def _combine(
    colour: str,
    glyph_value: int | None,
    glyph_text: str,
    glyph_score: float,
    tess_value: int | None,
    tess_text: str,
) -> StackReading:
    if glyph_value is not None and glyph_value == tess_value:
        confidence = 0.95 if _consistent(glyph_value, colour) else 0.6
        return StackReading(glyph_value, glyph_text, colour, confidence)

    candidates = [
        (glyph_value, glyph_text, 0.5 + 0.4 * glyph_score),
        (tess_value, tess_text, 0.55),
    ]
    consistent = [c for c in candidates if _consistent(c[0], colour)]
    if consistent:
        value, text, confidence = max(consistent, key=lambda c: c[2])
        return StackReading(value, text, colour, confidence)

    # Nothing agreed with the colour. Report the best guess, flagged low, so
    # the caller shows it as uncertain rather than folding it into a total.
    for value, text, confidence in candidates:
        if value is not None:
            return StackReading(value, text, colour, 0.3)

    return StackReading(None, glyph_text or tess_text, colour, 0.0)


def ocr_words(image: np.ndarray, settings: OCRSettings | None = None) -> list[str]:
    """Every word Tesseract finds in ``image``. Used for bank-title detection."""
    import cv2
    import pytesseract

    settings = settings or OCRSettings()
    settings.apply()

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    scale = 2
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(enlarged, config="--psm 6 --oem 3")
    return [w for w in re.split(r"\s+", text) if w]
