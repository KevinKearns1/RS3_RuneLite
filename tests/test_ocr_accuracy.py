"""Stack-count reading, measured rather than assumed.

These thresholds encode what the reader actually achieves on the synthetic
fixtures today, not what we wish it achieved. The brief's target is >95%, and
the honest position is documented in ``docs/ACCURACY.md``: the rendered glyph
templates are an approximation of a font this project has never seen, and
closing that gap needs calibration against real screenshots.

What these tests do protect is the property that matters more than raw
accuracy -- that a count the reader is unsure about is *reported* as unsure,
so it never silently multiplies a price.
"""

from __future__ import annotations

import pytest

from rs3overlay.vision.glyphs import render_templates
from rs3overlay.vision.ocr import read_stack_count

#: Current measured accuracy is 66%. Sitting the gate a little under that
#: catches a regression without failing on noise.
MIN_ACCURACY = 0.60

#: Of the counts the reader calls high-confidence, this fraction must be right.
#: This is the number the bank total actually depends on.
MIN_HIGH_CONFIDENCE_PRECISION = 0.80

HIGH_CONFIDENCE = 0.9


@pytest.fixture(scope="module")
def templates():
    return render_templates()


@pytest.fixture(scope="module")
def readings(loaded_cells, templates):
    return [
        (read_stack_count(cell.image, templates=templates), truth)
        for cell, truth in loaded_cells
    ]


def test_overall_accuracy_holds(readings):
    correct = sum(1 for r, t in readings if r.quantity == t["quantity"])
    accuracy = correct / len(readings)
    assert accuracy >= MIN_ACCURACY, (
        f"stack-count accuracy fell to {accuracy:.0%} "
        f"({correct}/{len(readings)}); floor is {MIN_ACCURACY:.0%}"
    )


def test_confident_readings_are_usually_right(readings):
    confident = [(r, t) for r, t in readings if r.confidence >= HIGH_CONFIDENCE]
    assert confident, "the reader should be confident about at least some slots"

    correct = sum(1 for r, t in confident if r.quantity == t["quantity"])
    precision = correct / len(confident)
    assert precision >= MIN_HIGH_CONFIDENCE_PRECISION, (
        f"high-confidence precision fell to {precision:.0%} "
        f"({correct}/{len(confident)})"
    )


def test_a_wrong_reading_is_not_dressed_up_as_confident(readings):
    """The failure that would corrupt a bank total silently.

    A count that contradicts the colour it is drawn in -- yellow digits
    claiming six hundred billion -- must come back with low confidence so the
    pipeline drops it.
    """
    bounds = {"yellow": (1, 99_999), "white": (100_000, 9_999_999),
              "green": (10_000_000, float("inf"))}
    for reading, _ in readings:
        if reading.quantity is None or reading.colour not in bounds:
            continue
        low, high = bounds[reading.colour]
        if not (low <= reading.quantity <= high):
            assert reading.confidence < HIGH_CONFIDENCE, (
                f"{reading.quantity} in {reading.colour} was reported "
                f"at confidence {reading.confidence}"
            )


def test_an_unstacked_item_reads_as_one(loaded_cells, templates):
    """No number drawn means a single item, which is not the same as unknown."""
    import numpy as np

    blank = np.full((40, 40, 3), (34, 30, 22), np.uint8)
    reading = read_stack_count(blank, templates=templates)
    assert reading.quantity == 1
    assert reading.colour == "none"
