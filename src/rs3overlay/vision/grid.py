"""Finding the item lattice, without hardcoding a resolution.

The brief allowed "require a fixed, calibrated window size" for the MVP. We do
better than that for roughly the same effort, because the structure we are
looking for is strongly periodic and periodicity is easy to measure:

1. Edge-detect the screenshot. Slot borders light up; item art mostly does not.
2. Project those edges onto each axis. A grid produces an evenly spaced comb.
3. Autocorrelate each projection to recover the cell *pitch* (the spacing).
4. Given the pitch, sweep the *phase* to find where the first border sits.

That yields the grid geometry at whatever UI scale the user happens to run,
and it gives us a quality score for free -- how comb-like the projection
actually is -- which Phase 2 reuses as its confidence signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: RS3 bank slots are ~36px at 100% UI scale. Allow a wide range so the
#: detector still works at 125%/150% scaling and on high-DPI displays.
MIN_PITCH = 18
MAX_PITCH = 96

#: Below this, the projection is not comb-like enough to call a grid.
MIN_QUALITY = 0.30


@dataclass(frozen=True)
class GridSpec:
    """Where the lattice is and how big its cells are."""

    x0: int
    y0: int
    cell_w: int
    cell_h: int
    cols: int
    rows: int
    quality: float

    def cell_box(self, row: int, col: int) -> tuple[int, int, int, int]:
        """``(left, top, right, bottom)`` of one cell, in image coordinates."""
        left = self.x0 + col * self.cell_w
        top = self.y0 + row * self.cell_h
        return left, top, left + self.cell_w, top + self.cell_h

    @property
    def box(self) -> tuple[int, int, int, int]:
        """Bounding box of the whole grid."""
        return (
            self.x0,
            self.y0,
            self.x0 + self.cols * self.cell_w,
            self.y0 + self.rows * self.cell_h,
        )


@dataclass
class Cell:
    """One slot cut out of the screenshot."""

    row: int
    col: int
    box: tuple[int, int, int, int]
    image: np.ndarray
    """BGR crop of the slot, including its border."""

    @property
    def index(self) -> int:
        return self.row, self.col


def find_grid(image: np.ndarray) -> GridSpec | None:
    """Recover the item grid from a screenshot, or ``None`` if there isn't one."""
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # Canny rather than a raw gradient: we want thin, binary border lines, not
    # a response proportional to how bright the item art happens to be.
    edges = cv2.Canny(gray, 50, 150)

    col_profile = edges.sum(axis=0).astype(np.float64)
    row_profile = edges.sum(axis=1).astype(np.float64)

    col_result = _analyse_axis(col_profile)
    row_result = _analyse_axis(row_profile)
    if col_result is None or row_result is None:
        return None

    x0, cell_w, cols, col_quality = col_result
    y0, cell_h, rows, row_quality = row_result

    quality = min(col_quality, row_quality)
    if quality < MIN_QUALITY:
        return None

    return GridSpec(
        x0=x0,
        y0=y0,
        cell_w=cell_w,
        cell_h=cell_h,
        cols=cols,
        rows=rows,
        quality=float(quality),
    )


def _analyse_axis(profile: np.ndarray) -> tuple[int, int, int, float] | None:
    """Recover ``(origin, pitch, count, quality)`` from one edge projection."""
    if profile.size < MIN_PITCH * 3:
        return None

    centred = profile - profile.mean()
    if not np.any(centred):
        return None

    pitch = _dominant_pitch(centred)
    if pitch is None:
        return None

    origin, count, quality = _fit_comb(profile, pitch)
    if count < 2:
        return None
    return origin, pitch, count, quality


def _dominant_pitch(centred: np.ndarray) -> int | None:
    """The lag with the strongest self-similarity, i.e. the cell spacing."""
    correlation = np.correlate(centred, centred, mode="full")[centred.size - 1 :]
    if correlation[0] <= 0:
        return None
    normalised = correlation / correlation[0]

    hi = min(MAX_PITCH, normalised.size - 1)
    if hi <= MIN_PITCH:
        return None

    window = normalised[MIN_PITCH : hi + 1]
    best_lag = int(np.argmax(window)) + MIN_PITCH

    # A harmonic of the true pitch correlates just as well as the pitch
    # itself, and argmax has no reason to prefer the fundamental. Step down to
    # the smallest divisor that still correlates nearly as strongly, so an
    # 8-column grid is not reported as 4 columns of double-width cells.
    best_score = normalised[best_lag]
    for divisor in (4, 3, 2):
        candidate = best_lag // divisor
        if candidate < MIN_PITCH:
            continue
        if normalised[candidate] >= best_score * 0.80:
            return candidate
    return best_lag


#: Teeth are sampled over a small window rather than a single row/column.
#: The true pitch is rarely a whole number of pixels once the UI is scaled, so
#: a border can sit between two integer positions and all but vanish from the
#: exact sample -- which cost a whole row of an upscaled bank before this.
_TOOTH_SLOP = 1


def _tooth_energy(profile: np.ndarray, positions: np.ndarray) -> np.ndarray:
    """Strongest value within +/- :data:`_TOOTH_SLOP` of each tooth."""
    length = profile.size
    stacked = [
        profile[np.clip(positions + shift, 0, length - 1)]
        for shift in range(-_TOOTH_SLOP, _TOOTH_SLOP + 1)
    ]
    return np.max(np.stack(stacked), axis=0)


def _fit_comb(profile: np.ndarray, pitch: int) -> tuple[int, int, float]:
    """Find where the comb starts, how many teeth it has, and how good it is.

    ``quality`` is the mean energy on the teeth divided by the mean energy
    everywhere -- a clean lattice scores well above 1, noise scores near 1. We
    squash it into 0..1 so callers can treat it as a confidence.
    """
    length = profile.size
    overall_mean = float(profile.mean()) or 1.0

    best_offset = 0
    best_strength = -1.0
    for offset in range(pitch):
        positions = np.arange(offset, length, pitch)
        if positions.size < 3:
            continue
        strength = float(_tooth_energy(profile, positions).mean())
        if strength > best_strength:
            best_strength = strength
            best_offset = offset

    positions = np.arange(best_offset, length, pitch)
    energy = _tooth_energy(profile, positions)
    # Teeth carrying almost no edge energy are past the end of the lattice
    # (empty interface background), so trim to the contiguous strong run.
    threshold = max(overall_mean, best_strength * 0.35)
    strong = energy >= threshold
    start, end = _longest_true_run(strong)
    if end - start < 2:
        return best_offset, 0, 0.0

    # The window sampling above deliberately blurs each tooth by a pixel, so
    # snap the reported origin back onto the actual border it found -- every
    # cell crop is offset from this, and a two-pixel drift shifts them all.
    origin = _snap(profile, int(positions[start]))
    # N borders bound N-1 cells.
    count = int(end - start - 1)
    ratio = best_strength / overall_mean
    quality = float(np.clip((ratio - 1.0) / 2.0, 0.0, 1.0))
    return origin, count, quality


def _snap(profile: np.ndarray, position: int) -> int:
    """Move ``position`` onto the strongest sample within the tooth window."""
    low = max(0, position - _TOOTH_SLOP)
    high = min(profile.size, position + _TOOTH_SLOP + 1)
    if low >= high:
        return position
    return int(low + np.argmax(profile[low:high]))


def _longest_true_run(mask: np.ndarray) -> tuple[int, int]:
    """``(start, end)`` of the longest contiguous ``True`` run, end-exclusive."""
    best = (0, 0)
    start = None
    for i, value in enumerate(mask):
        if value and start is None:
            start = i
        elif not value and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if start is not None and mask.size - start > best[1] - best[0]:
        best = (start, int(mask.size))
    return best


def slice_cells(
    image: np.ndarray, grid: GridSpec, skip_empty: bool = True
) -> list[Cell]:
    """Cut ``image`` into cells, optionally dropping the empty slots."""
    cells: list[Cell] = []
    height, width = image.shape[:2]
    for row in range(grid.rows):
        for col in range(grid.cols):
            left, top, right, bottom = grid.cell_box(row, col)
            if right > width or bottom > height:
                continue
            crop = image[top:bottom, left:right]
            if skip_empty and is_empty_cell(crop):
                continue
            cells.append(Cell(row=row, col=col, box=(left, top, right, bottom), image=crop))
    return cells


def is_empty_cell(cell: np.ndarray, std_threshold: float = 12.0) -> bool:
    """An empty slot is flat background inside its border.

    We measure the interior only, so the slot's own border -- present whether
    or not the slot holds anything -- does not mask the emptiness.
    """
    if cell.size == 0:
        return True
    inset_y = max(1, cell.shape[0] // 6)
    inset_x = max(1, cell.shape[1] // 6)
    interior = cell[inset_y:-inset_y, inset_x:-inset_x]
    if interior.size == 0:
        return True
    return float(interior.std()) < std_threshold
