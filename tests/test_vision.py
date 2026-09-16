"""Phases 2-4 against the synthetic bank, whose answers we know exactly."""

from __future__ import annotations

import cv2
import numpy as np

from rs3overlay.vision.bank import detect_bank
from rs3overlay.vision.grid import find_grid, is_empty_cell, slice_cells
from rs3overlay.vision.icons import IconLibrary
from rs3overlay.vision.ocr import dominant_stack_colour, count_region


# --- Phase 2: the grid ----------------------------------------------------


def test_grid_geometry_matches_ground_truth(bank_image, bank_truth):
    image = cv2.imread(str(bank_image))
    grid = find_grid(image)

    expected = bank_truth["grid"]
    assert grid is not None
    assert (grid.cols, grid.rows) == (expected["cols"], expected["rows"])
    assert grid.cell_w == expected["cell"]
    assert grid.cell_h == expected["cell"]
    # Canny puts the edge on the border pixel itself, so allow one pixel.
    assert abs(grid.x0 - expected["x0"]) <= 1
    assert abs(grid.y0 - expected["y0"]) <= 1


def test_grid_survives_ui_scaling(tmp_path, icon_dir):
    """The detector must not need a calibrated window size."""
    import subprocess, sys
    from pathlib import Path

    tool = Path(__file__).parents[1] / "tools" / "make_fixtures.py"
    out = tmp_path / "scaled.png"
    subprocess.run(
        [sys.executable, str(tool), "bank", "--icons", str(icon_dir),
         "--out", str(out), "--scale", "1.25"],
        check=True, capture_output=True,
    )
    grid = find_grid(cv2.imread(str(out)))
    assert grid is not None
    assert (grid.cols, grid.rows) == (8, 5)
    # Cells should have grown with the image rather than staying at 40px.
    assert grid.cell_w > 40


def test_empty_slots_are_skipped(bank_image, bank_truth):
    image = cv2.imread(str(bank_image))
    cells = slice_cells(image, find_grid(image))
    assert len(cells) == len(bank_truth["slots"])


def test_is_empty_cell_ignores_the_slot_border():
    cell = np.full((40, 40, 3), (34, 30, 22), np.uint8)
    cv2.rectangle(cell, (0, 0), (39, 39), (72, 64, 46), 1)
    assert is_empty_cell(cell)


# --- Phase 2: is this actually a bank? ------------------------------------


def test_detects_the_bank(bank_image):
    detection = detect_bank(cv2.imread(str(bank_image)))
    assert detection.found
    assert detection.confidence >= 0.5


def test_rejects_a_screen_that_is_not_a_bank(non_bank_image):
    """A 4-column inventory must not be valued as if it were the bank."""
    detection = detect_bank(cv2.imread(str(non_bank_image)))
    assert not detection.found
    assert "inventory" in detection.reason or "grid" in detection.reason


# --- Phase 3: the stack-count colour --------------------------------------


def test_stack_colour_is_read_correctly_for_every_slot(loaded_cells):
    """Ranking colours by raw pixel count used to lose to green item art."""

    def expected(quantity: int) -> str:
        if quantity >= 10_000_000:
            return "green"
        return "white" if quantity >= 100_000 else "yellow"

    wrong = [
        (truth["label"], expected(truth["quantity"]), got)
        for cell, truth in loaded_cells
        if (got := dominant_stack_colour(count_region(cell.image)))
        != expected(truth["quantity"])
    ]
    assert not wrong, f"colour misread on {wrong}"


# --- Phase 4: which item is it? -------------------------------------------


def test_every_slot_resolves_to_the_right_item(loaded_cells, icon_dir):
    """Rank-1 identification must be exact on every filled slot."""
    library = IconLibrary.load(icon_dir)
    assert len(library) > 0

    wrong = []
    for cell, truth in loaded_cells:
        match = library.match(cell.image)
        if match.item_id is not None and match.name != truth["name"]:
            wrong.append((truth["name"], match.name, round(match.score, 3)))
    assert not wrong, f"misidentified: {wrong}"


def test_distinct_items_are_not_flagged_ambiguous(loaded_cells, icon_dir):
    """Ambiguity is for genuinely similar art, not for everything."""
    library = IconLibrary.load(icon_dir)
    ambiguous = [t["name"] for cell, t in loaded_cells if library.match(cell.image).ambiguous]
    assert not ambiguous, f"unexpectedly ambiguous: {ambiguous}"


def _as_slot(icon_path) -> np.ndarray:
    """Paint a reference icon into a slot the way the bank draws it."""
    raw = cv2.imread(str(icon_path), cv2.IMREAD_UNCHANGED)
    cell = np.full((40, 40, 3), (34, 30, 22), np.uint8)
    cv2.rectangle(cell, (0, 0), (39, 39), (72, 64, 46), 1)
    icon = cv2.resize(raw, (32, 32), interpolation=cv2.INTER_AREA)
    alpha = icon[:, :, 3:4] / 255.0
    cell[4:36, 4:36] = (icon[:, :, :3] * alpha + cell[4:36, 4:36] * (1 - alpha)).astype(np.uint8)
    return cell


def test_near_identical_icons_are_flagged_rather_than_guessed(icon_dir):
    """The herb problem: when two items look the same, say so.

    The fixture set contains deliberately near-identical pairs. Silently
    picking one would put a wrong item -- and its price -- into the total.
    """
    library = IconLibrary.load(icon_dir)
    for name in ("similar_herb_0a", "similar_herb_0b", "similar_herb_1a"):
        match = library.match(_as_slot(icon_dir / f"{name}.png"))
        assert match.ambiguous, f"{name} should be ambiguous, got {match.name}"
        assert match.runner_up, "an ambiguous match must name the alternative"
        assert not match.identified


def test_an_unknown_icon_is_reported_not_guessed(icon_dir):
    """Something not in the library must come back unknown."""
    library = IconLibrary.load(icon_dir)
    noise = np.random.default_rng(0).integers(0, 255, (40, 40, 3), dtype=np.uint8)
    match = library.match(noise, threshold=0.9)
    assert match.item_id is None
    assert match.status == "unknown"
