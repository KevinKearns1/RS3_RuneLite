"""Phase 1, minus the parts that need a real screen."""

from __future__ import annotations

import time

import numpy as np

from rs3overlay.capture.hotkey import validate_hotkey
from rs3overlay.capture.screenshot import CaptureResult, save_capture
from rs3overlay.capture.window import WindowRect, find_game_window
from rs3overlay.config import Config


def test_window_rect_converts_to_a_capture_box():
    rect = WindowRect("RuneScape", 100, 50, 800, 600)
    assert rect.as_bbox() == {"left": 100, "top": 50, "width": 800, "height": 600}
    assert (rect.right, rect.bottom) == (900, 650)


def test_the_largest_matching_window_wins(monkeypatch):
    """RS3 sessions usually have a launcher matching on title too."""
    windows = [
        WindowRect("RuneScape Launcher", 0, 0, 400, 300),
        WindowRect("RuneScape", 0, 0, 1920, 1080),
        WindowRect("Notepad", 0, 0, 900, 900),
    ]
    monkeypatch.setattr("rs3overlay.capture.window.list_windows", lambda: windows)
    assert find_game_window("RuneScape").width == 1920


def test_no_match_returns_none_so_capture_can_fall_back(monkeypatch):
    monkeypatch.setattr("rs3overlay.capture.window.list_windows", lambda: [])
    assert find_game_window("RuneScape") is None


def test_empty_title_never_matches():
    assert find_game_window("") is None


def test_saving_a_capture_writes_a_png_and_prunes(tmp_path):
    def capture() -> CaptureResult:
        image = np.zeros((10, 10, 3), np.uint8)
        return CaptureResult(image=image, rect=None, captured_at=time.time())

    written = [save_capture(capture(), tmp_path, keep=3) for _ in range(5)]
    assert all(p.suffix == ".png" for p in written)
    # Same-second captures must not overwrite each other...
    assert len(set(written)) == 5
    # ...and only the newest `keep` survive.
    assert len(list(tmp_path.glob("bank-*.png"))) == 3


def test_hotkey_validation_accepts_the_default_and_rejects_nonsense():
    assert validate_hotkey(Config().hotkey) is None
    assert validate_hotkey("not a hotkey at all") is not None


def test_config_round_trips(tmp_path):
    path = tmp_path / "config.json"
    original = Config(hotkey="<ctrl>+<alt>+v", icon_match_threshold=0.71)
    original.save(path)

    loaded = Config.load(path)
    assert loaded.hotkey == "<ctrl>+<alt>+v"
    assert loaded.icon_match_threshold == 0.71
    assert isinstance(loaded.bank_title_keywords, tuple)


def test_unknown_config_keys_are_ignored(tmp_path):
    """An old config file must not break a newer build."""
    path = tmp_path / "config.json"
    path.write_text('{"hotkey": "<ctrl>+b", "a_setting_we_removed": 1}')
    assert Config.load(path).hotkey == "<ctrl>+b"
