"""Shared fixtures.

The synthetic bank images and their ground truth are generated rather than
committed as binaries, so a change to the generator cannot silently drift away
from what the tests assert about it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parents[1]
TOOL = PROJECT_ROOT / "tools" / "make_fixtures.py"


def _generate(*args: str) -> None:
    subprocess.run([sys.executable, str(TOOL), *args], check=True, capture_output=True)


@pytest.fixture(scope="session")
def icon_dir() -> Path:
    directory = FIXTURES / "icons"
    if not (directory / "index.json").exists():
        _generate("icons", "--out", str(directory))
    return directory


@pytest.fixture(scope="session")
def bank_image(icon_dir: Path) -> Path:
    path = FIXTURES / "bank_8x5.png"
    if not path.exists():
        _generate("bank", "--icons", str(icon_dir), "--out", str(path))
    return path


@pytest.fixture(scope="session")
def bank_truth(bank_image: Path) -> dict:
    return json.loads(bank_image.with_suffix(".truth.json").read_text())


@pytest.fixture(scope="session")
def non_bank_image() -> Path:
    path = FIXTURES / "not_a_bank.png"
    if not path.exists():
        _generate("non-bank", "--out", str(path))
    return path


@pytest.fixture(scope="session")
def price_cache() -> Path:
    """A cache covering every fixture item, so valuation runs offline."""
    import time

    path = FIXTURES / "ge_prices.json"
    index = json.loads((FIXTURES / "icons" / "index.json").read_text())
    cache = {
        str(meta["item_id"]): {
            "name": meta["name"],
            "price": (i + 1) * 137,
            "fetched_at": time.time(),
        }
        for i, (_, meta) in enumerate(sorted(index.items()))
    }
    path.write_text(json.dumps(cache, indent=1))
    return path


@pytest.fixture(scope="session")
def loaded_cells(bank_image, bank_truth):
    """Every non-empty cell of the fixture bank, paired with its truth row."""
    import cv2

    from rs3overlay.vision.grid import find_grid, slice_cells

    image = cv2.imread(str(bank_image))
    grid = find_grid(image)
    assert grid is not None, "fixture bank must have a detectable grid"
    truth = {(s["row"], s["col"]): s for s in bank_truth["slots"]}
    return [(cell, truth[(cell.row, cell.col)]) for cell in slice_cells(image, grid)]
