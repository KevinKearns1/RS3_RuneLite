"""Phases 2-4: turn a screenshot into a list of (item, quantity) guesses."""

from .bank import BankDetection, detect_bank
from .grid import Cell, GridSpec, find_grid, slice_cells
from .icons import IconLibrary, IconMatch
from .ocr import OCRSettings, parse_stack_text, read_stack_count

__all__ = [
    "BankDetection",
    "detect_bank",
    "Cell",
    "GridSpec",
    "find_grid",
    "slice_cells",
    "IconLibrary",
    "IconMatch",
    "OCRSettings",
    "parse_stack_text",
    "read_stack_count",
]
