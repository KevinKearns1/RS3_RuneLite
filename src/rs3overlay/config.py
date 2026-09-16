"""User-tunable settings, persisted as JSON next to the project."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class Config:
    """Everything the user might reasonably want to change."""

    # --- Phase 1: capture -------------------------------------------------
    hotkey: str = "<ctrl>+<alt>+b"
    """Global hotkey, in pynput's ``GlobalHotKeys`` notation."""

    window_title_contains: str = "RuneScape"
    """Substring used to find the game window. Empty string = full screen."""

    capture_dir: str = "captures"
    keep_captures: int = 50
    """How many PNGs to keep in ``capture_dir`` before pruning the oldest."""

    # --- Phase 2: bank detection -----------------------------------------
    bank_title_keywords: tuple[str, ...] = ("bank of gielinor", "bank of", "gielinor")
    min_bank_confidence: float = 0.45

    # --- Phase 3: OCR -----------------------------------------------------
    tesseract_cmd: str = ""
    """Absolute path to ``tesseract.exe``. Empty = look on PATH."""

    ocr_upscale: int = 4
    """Stack-count digits are tiny; upscaling before OCR matters a lot."""

    min_quantity_confidence: float = 0.5
    """A stack count read below this confidence is reported as unreadable
    rather than counted. The readers disagreeing, or a count whose digits
    contradict the colour it is drawn in, lands here -- and a slot silently
    valued at a misread quantity would corrupt the bank total far more than a
    slot openly marked unreadable."""

    glyph_templates_path: str = "assets/font/stack_digits.json"
    """Calibrated stack-count glyph bitmaps, from tools/calibrate_digits.py.
    When this file is absent the reader renders approximate templates from a
    local font instead, which is noticeably less accurate."""

    # --- Phase 4: icon matching ------------------------------------------
    icon_dir: str = "assets/icons"
    icon_match_threshold: float = 0.62
    """Below this correlation score a cell is reported as unidentified rather
    than guessed. Deliberately conservative: a wrong item is worse than a
    flagged unknown, especially for the near-identical herb icons."""

    icon_match_margin: float = 0.04
    """If the best and second-best candidates are within this margin, the match
    is reported as ambiguous instead of silently picking the winner."""

    # --- Phase 5: prices --------------------------------------------------
    price_cache_path: str = "cache/ge_prices.json"
    price_cache_ttl_seconds: int = 6 * 60 * 60
    ge_api_base: str = "https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json"
    ge_request_delay_seconds: float = 0.6
    """Politeness delay between GE API calls. Do not set this to zero."""

    user_agent: str = "RS3BankOverlay/0.6 (personal, read-only screen reader)"
    offline: bool = False
    """When true, never hit the network; use only what is already cached."""

    # --- Phase 6: overlay -------------------------------------------------
    overlay_x: int = 40
    overlay_y: int = 40
    overlay_width: int = 380
    overlay_height: int = 520
    overlay_opacity: float = 0.92
    overlay_click_through: bool = False
    overlay_max_rows: int = 18

    def resolve(self, relative: str) -> Path:
        """Resolve a config path against the project root."""
        path = Path(relative)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in raw.items() if k in known}
        if "bank_title_keywords" in clean:
            clean["bank_title_keywords"] = tuple(clean["bank_title_keywords"])
        return cls(**clean)

    def save(self, path: Path | None = None) -> Path:
        path = path or DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["bank_title_keywords"] = list(self.bank_title_keywords)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path
