"""Phase 2: confirm a bank interface is actually on screen.

Two independent signals, because either one alone has a failure mode:

* **Title OCR** -- look for "The Bank of Gielinor" in the upper part of the
  image. Strong when it works, but the title is stylised and OCR can miss it.
* **Grid structure** -- a bank is the only RS3 interface showing a large
  regular lattice of item slots. Robust to OCR failure, but a full inventory
  or a trade screen is a smaller lattice of the same kind, hence the
  minimum-columns requirement.

We require the grid, and treat the title as a confidence boost. That ordering
matters: valuing a *trade window* as if it were your bank would be a silently
wrong answer, which is worse than refusing to read.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .grid import GridSpec, find_grid
from .ocr import OCRSettings, ocr_words

#: A bank grid is wide. An inventory is 4 columns; a bank is typically 8+.
MIN_BANK_COLUMNS = 6
MIN_BANK_ROWS = 2


@dataclass
class BankDetection:
    """What we concluded about a screenshot."""

    found: bool
    confidence: float
    grid: GridSpec | None = None
    title_found: bool = False
    title_text: str = ""
    reason: str = ""

    def __bool__(self) -> bool:
        return self.found


def detect_bank(
    image: np.ndarray,
    keywords: tuple[str, ...] = ("bank of gielinor", "bank of", "gielinor"),
    min_confidence: float = 0.45,
    ocr_settings: OCRSettings | None = None,
) -> BankDetection:
    """Decide whether ``image`` shows an open bank, and where its grid is."""
    title_found, title_text = _find_title(image, keywords, ocr_settings)

    grid = find_grid(image)
    if grid is None:
        return BankDetection(
            found=False,
            confidence=0.1 if title_found else 0.0,
            title_found=title_found,
            title_text=title_text,
            reason="no regular item grid found",
        )

    if grid.cols < MIN_BANK_COLUMNS or grid.rows < MIN_BANK_ROWS:
        return BankDetection(
            found=False,
            confidence=0.2,
            grid=grid,
            title_found=title_found,
            title_text=title_text,
            reason=(
                f"grid is {grid.cols}x{grid.rows}, too small for a bank "
                f"(need at least {MIN_BANK_COLUMNS}x{MIN_BANK_ROWS}) -- "
                "this looks like an inventory or trade window"
            ),
        )

    # Grid quality already accounts for how cleanly periodic the lattice is.
    confidence = 0.55 * grid.quality + (0.45 if title_found else 0.0)
    confidence = min(1.0, confidence)

    found = confidence >= min_confidence
    return BankDetection(
        found=found,
        confidence=confidence,
        grid=grid,
        title_found=title_found,
        title_text=title_text,
        reason="" if found else f"confidence {confidence:.2f} below threshold",
    )


def _find_title(
    image: np.ndarray,
    keywords: tuple[str, ...],
    ocr_settings: OCRSettings | None,
) -> tuple[bool, str]:
    """OCR the top strip of the image looking for the bank header."""
    height = image.shape[0]
    strip = image[: max(1, int(height * 0.30))]
    try:
        words = ocr_words(strip, ocr_settings)
    except Exception:  # noqa: BLE001 - Tesseract missing is not fatal here
        return False, ""

    joined = " ".join(w.lower() for w in words)
    for keyword in keywords:
        if keyword.lower() in joined:
            return True, keyword
    return False, ""
