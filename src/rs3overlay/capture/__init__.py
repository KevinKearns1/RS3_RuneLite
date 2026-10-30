"""Phase 1: find the game window, grab its pixels, trigger on a hotkey.

Nothing in this package writes to the game. ``hotkey`` listens for a key the
user presses; ``screenshot`` reads the framebuffer. That is the whole surface.
"""

from .screenshot import CaptureResult, ScreenCapturer, save_capture
from .window import WindowRect, find_game_window, list_windows

__all__ = [
    "CaptureResult",
    "ScreenCapturer",
    "save_capture",
    "WindowRect",
    "find_game_window",
    "list_windows",
]
