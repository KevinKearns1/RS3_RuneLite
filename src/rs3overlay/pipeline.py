"""Wiring phases 2-5 together: screenshot in, priced breakdown out."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config
from .data.ge import GEPriceClient
from .data.valuation import BankValuation, ValuedSlot, value_slots
from .vision.bank import BankDetection, detect_bank
from .vision.glyphs import GlyphTemplates, render_templates
from .vision.grid import slice_cells
from .vision.icons import IconLibrary
from .vision.ocr import OCRSettings, read_stack_count


@dataclass
class AnalysisResult:
    """Everything one capture produced, successful or not."""

    detection: BankDetection
    valuation: BankValuation | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.valuation is not None and not self.error


class BankAnalyzer:
    """Runs the read pipeline. Holds the icon library and price cache open.

    Both are expensive to build and cheap to reuse, so one analyzer should
    live for the lifetime of the app rather than being rebuilt per hotkey.
    """

    def __init__(self, config: Config, icons: IconLibrary | None = None,
                 price_client: GEPriceClient | None = None) -> None:
        self.config = config
        self.icons = icons if icons is not None else IconLibrary.load(
            config.resolve(config.icon_dir)
        )
        self.prices = price_client if price_client is not None else GEPriceClient(
            cache_path=config.resolve(config.price_cache_path),
            ttl_seconds=config.price_cache_ttl_seconds,
            api_base=config.ge_api_base,
            user_agent=config.user_agent,
            request_delay=config.ge_request_delay_seconds,
            offline=config.offline,
        )
        self.ocr_settings = OCRSettings(
            tesseract_cmd=config.tesseract_cmd, upscale=config.ocr_upscale
        )
        self.glyphs = self._load_glyphs()

    def _load_glyphs(self) -> GlyphTemplates:
        """Calibrated templates if the user has made some, else rendered ones."""
        path = self.config.resolve(self.config.glyph_templates_path)
        if path.exists():
            try:
                calibrated = GlyphTemplates.load(path)
            except (OSError, ValueError, KeyError):
                calibrated = GlyphTemplates()
            if calibrated:
                # Fill any character the user has not labelled yet from the
                # rendered set, so a partial calibration is still usable.
                merged = dict(render_templates().bitmaps)
                merged.update(calibrated.bitmaps)
                return GlyphTemplates(merged)
        return render_templates()

    def analyze(self, image: np.ndarray) -> AnalysisResult:
        """Read one screenshot end to end."""
        detection = detect_bank(
            image,
            keywords=self.config.bank_title_keywords,
            min_confidence=self.config.min_bank_confidence,
            ocr_settings=self.ocr_settings,
        )
        if not detection.found or detection.grid is None:
            return AnalysisResult(
                detection=detection,
                error=detection.reason or "no bank interface detected",
            )

        if not len(self.icons):
            # Without a library every slot comes back "no icon match", which
            # tells the user nothing about what is actually wrong.
            return AnalysisResult(
                detection=detection,
                error=(
                    "icon library is empty ("
                    f"{self.config.resolve(self.config.icon_dir)}). "
                    "Run: python tools/fetch_icons.py --popular"
                ),
            )

        cells = slice_cells(image, detection.grid, skip_empty=True)
        if not cells:
            return AnalysisResult(detection=detection, error="bank grid is empty")

        slots: list[ValuedSlot] = []
        for cell in cells:
            slots.append(self._read_cell(cell))

        valuation = value_slots(slots, self.prices)
        return AnalysisResult(detection=detection, valuation=valuation)

    def _read_cell(self, cell) -> ValuedSlot:
        match = self.icons.match(
            cell.image,
            threshold=self.config.icon_match_threshold,
            margin=self.config.icon_match_margin,
        )

        try:
            reading = read_stack_count(cell.image, self.ocr_settings, self.glyphs)
            if reading.confidence < self.config.min_quantity_confidence:
                # Low confidence means the two readers disagreed, or the digits
                # contradict the colour band. Either way the number is not
                # trustworthy enough to multiply a price by.
                quantity = None
                qty_note = (
                    f"stack count uncertain (read {reading.raw_text!r}, "
                    f"confidence {reading.confidence:.2f})"
                )
            else:
                quantity = reading.quantity
                qty_note = "" if reading.ok else "stack count unreadable"
        except Exception as exc:  # noqa: BLE001 - a missing Tesseract is survivable
            quantity = None
            qty_note = f"OCR failed: {exc}"

        if match.item_id is None:
            return ValuedSlot(
                row=cell.row, col=cell.col, item_id=None, name="",
                quantity=quantity, unit_price=None, match_score=match.score,
                status="unknown",
                note=f"no icon match (best {match.score:.2f})",
            )

        if match.ambiguous:
            return ValuedSlot(
                row=cell.row, col=cell.col, item_id=match.item_id, name=match.name,
                quantity=quantity, unit_price=None, match_score=match.score,
                status="ambiguous",
                note=(
                    f"could be {match.name} ({match.score:.2f}) or "
                    f"{match.runner_up} ({match.runner_up_score:.2f})"
                ),
            )

        if quantity is None:
            return ValuedSlot(
                row=cell.row, col=cell.col, item_id=match.item_id, name=match.name,
                quantity=None, unit_price=None, match_score=match.score,
                status="unreadable", note=qty_note,
            )

        return ValuedSlot(
            row=cell.row, col=cell.col, item_id=match.item_id, name=match.name,
            quantity=quantity, unit_price=None, match_score=match.score,
            status="ok",
        )
