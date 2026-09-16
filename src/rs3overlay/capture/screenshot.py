"""Grabbing pixels off the screen.

``mss`` reads the framebuffer the compositor has already produced. There is no
game-process involvement at all: if you alt-tabbed away and the window were
hidden, we would capture whatever is drawn there instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .window import WindowRect, find_game_window


@dataclass
class CaptureResult:
    """One screenshot plus where it came from."""

    image: np.ndarray
    """H x W x 3 array in BGR order, matching OpenCV's convention."""

    rect: WindowRect | None
    """The window we targeted, or ``None`` for a full-screen grab."""

    captured_at: float

    @property
    def source(self) -> str:
        return self.rect.title if self.rect else "full screen"

    @property
    def size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]


class ScreenCapturer:
    """Holds an ``mss`` handle open so repeat captures stay fast.

    ``mss`` instances are not thread-safe and are bound to the thread that
    created them, so the capturer lazily creates one per call site that needs
    it rather than sharing a single global.
    """

    def __init__(self, window_title_contains: str = "RuneScape") -> None:
        self.window_title_contains = window_title_contains
        self._sct = None

    def _handle(self):
        if self._sct is None:
            import mss

            self._sct = mss.mss()
        return self._sct

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def __enter__(self) -> "ScreenCapturer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def capture(self) -> CaptureResult:
        """Grab the game window, falling back to the primary monitor."""
        sct = self._handle()
        rect = find_game_window(self.window_title_contains)
        if rect is not None and rect.width > 0 and rect.height > 0:
            bbox = rect.as_bbox()
        else:
            rect = None
            # monitors[0] is the union of all monitors; [1] is the primary one,
            # which is almost always what the user means.
            monitors = sct.monitors
            bbox = monitors[1] if len(monitors) > 1 else monitors[0]

        raw = sct.grab(bbox)
        # mss hands back BGRA; drop alpha and keep BGR for OpenCV.
        image = np.asarray(raw, dtype=np.uint8)[:, :, :3]
        return CaptureResult(image=image, rect=rect, captured_at=time.time())


def save_capture(
    result: CaptureResult, capture_dir: Path, keep: int = 50, prefix: str = "bank"
) -> Path:
    """Write a capture to ``capture_dir`` and prune old ones.

    Returns the path written.
    """
    import cv2

    capture_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds, not just seconds: two captures must never land on the same
    # name. A collision counter alone is not enough, because pruning deletes
    # older files and so frees their names for a later capture to reuse.
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(result.captured_at))
    micros = int((result.captured_at % 1) * 1_000_000)
    path = capture_dir / f"{prefix}-{stamp}-{micros:06d}.png"

    suffix = 1
    while path.exists():
        path = capture_dir / f"{prefix}-{stamp}-{micros:06d}-{suffix}.png"
        suffix += 1

    cv2.imwrite(str(path), result.image)
    _prune(capture_dir, keep, prefix)
    return path


def _prune(capture_dir: Path, keep: int, prefix: str) -> None:
    if keep <= 0:
        return
    existing = sorted(
        capture_dir.glob(f"{prefix}-*.png"), key=lambda p: p.stat().st_mtime
    )
    for stale in existing[:-keep]:
        stale.unlink(missing_ok=True)
