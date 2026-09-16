"""Pure parsing, where the game's own formatting is the spec."""

from __future__ import annotations

import pytest

from rs3overlay.data.ge import parse_ge_price
from rs3overlay.data.valuation import format_gp
from rs3overlay.vision.ocr import parse_stack_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", 1),
        ("137", 137),
        ("1,234", 1234),
        ("41.1K", 41_100),
        ("41.1k", 41_100),
        ("1.2M", 1_200_000),
        ("2B", 2_000_000_000),
        ("3000K", 3_000_000),
        (" 55 ", 55),
    ],
)
def test_parses_the_formats_the_game_draws(text, expected):
    assert parse_stack_text(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "abc", "1.2", "K", "--5", "1..2"])
def test_rejects_what_it_cannot_read(text):
    """An unreadable count must be None, never a plausible-looking guess."""
    assert parse_stack_text(text) is None


@pytest.mark.parametrize(
    "value,expected",
    [(1234, 1234), ("1,234", 1234), ("2.4m", 2_400_000), ("41.1k", 41_100),
     ("1b", 1_000_000_000), ("+500", 500), ("-250", -250), ("", None), (None, None)],
)
def test_parses_ge_price_strings(value, expected):
    assert parse_ge_price(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(999, "999"), (1500, "1.50K"), (25_000, "25.0K"), (2_400_000, "2.40M"),
     (15_000_000, "15.0M"), (3_100_000_000, "3.10B")],
)
def test_formats_gp_like_the_game(value, expected):
    assert format_gp(value) == expected
