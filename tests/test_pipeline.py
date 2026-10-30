"""End to end: a screenshot in, a defensible total out."""

from __future__ import annotations

import cv2

from rs3overlay.app import analyze_file
from rs3overlay.config import Config


def _config(icon_dir, price_cache) -> Config:
    return Config(
        icon_dir=str(icon_dir),
        price_cache_path=str(price_cache),
        offline=True,
    )


def test_reads_the_fixture_bank(bank_image, icon_dir, price_cache, bank_truth):
    result = analyze_file(bank_image, _config(icon_dir, price_cache))

    assert result.ok
    assert result.detection.found
    assert len(result.valuation.slots) == len(bank_truth["slots"])
    assert result.valuation.total > 0


def test_every_counted_slot_names_a_real_item(bank_image, icon_dir, price_cache, bank_truth):
    """Nothing reaches the total without an item, a quantity and a price."""
    result = analyze_file(bank_image, _config(icon_dir, price_cache))
    names = {s["name"] for s in bank_truth["slots"]}

    for slot in result.valuation.counted_slots:
        assert slot.item_id is not None
        assert slot.quantity and slot.quantity > 0
        assert slot.unit_price is not None
        assert slot.name in names


def test_unresolved_slots_are_surfaced_not_hidden(bank_image, icon_dir, price_cache):
    """A total from 29 of 32 slots must not look like a total from all 32."""
    result = analyze_file(bank_image, _config(icon_dir, price_cache))
    valuation = result.valuation

    assert len(valuation.counted_slots) + len(valuation.problem_slots) == len(valuation.slots)
    for slot in valuation.problem_slots:
        assert slot.note or slot.status != "ok"
        assert slot.total == 0 or not slot.counted
    assert str(len(valuation.counted_slots)) in valuation.summary()


def test_refuses_a_screenshot_that_is_not_a_bank(non_bank_image, icon_dir, price_cache):
    result = analyze_file(non_bank_image, _config(icon_dir, price_cache))
    assert not result.ok
    assert result.valuation is None
    assert result.error


def test_the_total_is_the_sum_of_what_it_shows(bank_image, icon_dir, price_cache):
    result = analyze_file(bank_image, _config(icon_dir, price_cache))
    valuation = result.valuation
    assert valuation.total == sum(
        s.quantity * s.unit_price for s in valuation.counted_slots
    )
