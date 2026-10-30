"""Phase 4: naming the item in a slot by matching its icon.

The brief flags this as the phase to be paranoid about, and it is right: at
bank-icon resolution several herbs are near-identical green leaves. The design
here leans on that warning in three ways.

* **Match where the art actually is.** A slot crop includes its border and, in
  the top-left, the stack-count digits painted *over* the icon. Both are
  compared away before scoring, so two different items are never separated by
  their quantity labels and never conflated by their shared border.
* **Allow a little slop.** The icon is not pixel-aligned to the slot, so each
  reference is swept over a small search window rather than compared at one
  fixed offset.
* **Report ambiguity instead of resolving it.** If the top two candidates score
  within ``margin`` of each other, the result is marked ambiguous and carries
  the runner-up. A wrong item name silently changes the bank's total value; an
  "unsure between these two" does not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: Every icon and slot is normalised to this size before comparison.
CANONICAL_SIZE = 36

#: How far a reference icon is swept over the slot, in canonical pixels.
SEARCH_SLOP = 4

#: How much of the final score comes from colour rather than shape.
#: Measured on the fixture bank: shape alone leaves 14 of 32 slots inside the
#: ambiguity margin even though its top pick is always right, because
#: same-shape items in adjacent hues correlate almost perfectly. Blending in a
#: masked hue/saturation histogram pushes the mean top-two margin from 0.10 to
#: 0.18 and clears every false ambiguity flag, while leaving genuinely
#: near-identical art -- the herbs -- correctly flagged.
COLOUR_WEIGHT = 0.30

#: Hue/saturation bins for the colour histogram.
_HIST_BINS = (24, 8)
_HIST_RANGES = (0, 180, 0, 256)


@dataclass
class IconEntry:
    """One reference icon from the library."""

    item_id: int
    name: str
    path: Path
    image: np.ndarray = field(repr=False)
    """Canonical-size BGR image."""

    mask: np.ndarray = field(repr=False)
    """Canonical-size uint8 mask: 255 where the icon has real art."""

    histogram: np.ndarray = field(repr=False)
    """Masked hue/saturation histogram of the icon's art."""


@dataclass
class IconMatch:
    """The outcome of matching one slot against the library."""

    item_id: int | None
    name: str
    score: float
    runner_up: str = ""
    runner_up_score: float = 0.0
    ambiguous: bool = False

    @property
    def identified(self) -> bool:
        return self.item_id is not None and not self.ambiguous

    @property
    def status(self) -> str:
        if self.item_id is None:
            return "unknown"
        return "ambiguous" if self.ambiguous else "ok"


class IconLibrary:
    """Reference icons, loaded once and matched against many slots."""

    def __init__(self, entries: list[IconEntry]) -> None:
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)

    @classmethod
    def load(cls, icon_dir: Path) -> "IconLibrary":
        """Load ``icon_dir``, using ``index.json`` for ids and display names.

        ``index.json`` maps a filename to ``{"item_id": int, "name": str}`` and
        is written by ``tools/fetch_icons.py``. A PNG with no index entry is
        still loaded, named after its filename and given a negative synthetic
        id, so the library is usable before the index exists.
        """
        import cv2

        icon_dir = Path(icon_dir)
        if not icon_dir.exists():
            return cls([])

        index: dict[str, dict] = {}
        index_path = icon_dir / "index.json"
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))

        entries: list[IconEntry] = []
        for n, path in enumerate(sorted(icon_dir.glob("*.png"))):
            raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if raw is None:
                continue
            image, mask = _normalise_reference(raw)
            meta = index.get(path.name, {})
            entries.append(
                IconEntry(
                    item_id=int(meta.get("item_id", -(n + 1))),
                    name=str(meta.get("name", path.stem.replace("_", " "))),
                    path=path,
                    image=image,
                    mask=mask,
                    histogram=_histogram(image, mask[:, :, 0]),
                )
            )
        return cls(entries)

    def match(
        self, cell: np.ndarray, threshold: float = 0.62, margin: float = 0.04
    ) -> IconMatch:
        """Identify the item in one slot crop."""
        if not self.entries:
            return IconMatch(item_id=None, name="", score=0.0)

        haystack = _normalise_slot(cell)
        haystack_hist = _histogram(haystack, _art_mask(haystack.shape[:2]))
        scored = sorted(
            ((_score(haystack, haystack_hist, e), e) for e in self.entries),
            key=lambda pair: pair[0],
            reverse=True,
        )

        best_score, best = scored[0]
        if best_score < threshold:
            return IconMatch(item_id=None, name="", score=float(best_score))

        second_score, second = (scored[1] if len(scored) > 1 else (0.0, None))
        ambiguous = second is not None and (best_score - second_score) < margin

        return IconMatch(
            item_id=best.item_id,
            name=best.name,
            score=float(best_score),
            runner_up=second.name if second is not None else "",
            runner_up_score=float(second_score),
            ambiguous=ambiguous,
        )


def _score(
    haystack: np.ndarray, haystack_hist: np.ndarray, entry: IconEntry
) -> float:
    """Blend shape correlation with colour similarity for one candidate.

    ``TM_CCOEFF_NORMED`` subtracts each patch's mean before correlating, which
    is what makes it discriminate. The un-centred ``TM_CCORR_NORMED`` scores
    almost everything above 0.99 -- measured on the fixture bank, its mean
    top-two margin was 0.03 against 0.10 here -- so near-identical and plainly
    different items become indistinguishable at the same threshold.
    """
    import cv2

    try:
        result = cv2.matchTemplate(
            haystack, entry.image, cv2.TM_CCOEFF_NORMED, mask=entry.mask
        )
    except cv2.error:
        # Masked TM_CCOEFF_NORMED needs OpenCV >= 4.3; fall back if older.
        result = cv2.matchTemplate(haystack, entry.image, cv2.TM_CCOEFF_NORMED)

    # A fully-masked comparison can produce inf/nan; treat those as no match.
    result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    shape_score = float(result.max()) if result.size else 0.0

    colour_score = float(
        cv2.compareHist(haystack_hist, entry.histogram, cv2.HISTCMP_CORREL)
    )
    colour_score = max(0.0, min(1.0, colour_score))

    return (1.0 - COLOUR_WEIGHT) * shape_score + COLOUR_WEIGHT * colour_score


def _histogram(bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Masked hue/saturation histogram, normalised for ``compareHist``."""
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, list(_HIST_BINS), list(_HIST_RANGES))
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist


def _art_mask(shape: tuple[int, int]) -> np.ndarray:
    """A slot mask that excludes the corner the stack count is drawn in."""
    height, width = shape
    mask = np.full((height, width), 255, np.uint8)
    mask[: int(height * 0.40), : int(width * 0.70)] = 0
    return mask


def _normalise_reference(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Canonicalise a reference icon and derive its transparency mask."""
    import cv2

    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)

    if raw.shape[2] == 4:
        alpha = raw[:, :, 3]
        bgr = raw[:, :, :3]
    else:
        bgr = raw
        # No alpha channel: treat near-black as background, which is how the
        # wiki renders icons that were saved without transparency.
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        alpha = np.where(gray > 12, 255, 0).astype(np.uint8)

    size = (CANONICAL_SIZE, CANONICAL_SIZE)
    bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
    mask = np.where(alpha > 80, 255, 0).astype(np.uint8)

    # The stack count is painted over the icon's top-left, so that corner
    # carries no reliable information about which item this is.
    corner_h = int(CANONICAL_SIZE * 0.40)
    corner_w = int(CANONICAL_SIZE * 0.70)
    mask[:corner_h, :corner_w] = 0

    mask3 = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    return bgr, mask3


def _normalise_slot(cell: np.ndarray) -> np.ndarray:
    """Strip a slot's border and scale it to leave room for the search sweep."""
    import cv2

    height, width = cell.shape[:2]
    inset_y = max(1, height // 12)
    inset_x = max(1, width // 12)
    interior = cell[inset_y : height - inset_y, inset_x : width - inset_x]
    if interior.size == 0:
        interior = cell

    target = CANONICAL_SIZE + SEARCH_SLOP
    return cv2.resize(interior, (target, target), interpolation=cv2.INTER_AREA)
