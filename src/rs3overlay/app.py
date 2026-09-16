"""The live app: hotkey -> capture -> analyse -> overlay."""

from __future__ import annotations

import traceback
from pathlib import Path

import cv2

from .capture.hotkey import HotkeyListener, validate_hotkey
from .capture.screenshot import ScreenCapturer, save_capture
from .config import Config
from .pipeline import AnalysisResult, BankAnalyzer
from .safety import verify_no_input_synthesis


class OverlayApp:
    """Owns the analyzer, the capturer and the hotkey for one session."""

    def __init__(self, config: Config, save_screenshots: bool = True) -> None:
        self.config = config
        self.save_screenshots = save_screenshots
        self.analyzer = BankAnalyzer(config)
        self.window = None
        self._listener: HotkeyListener | None = None
        # Each capture happens on the hotkey thread, so the capturer is built
        # there rather than shared from the main thread (mss is thread-bound).
        self._capturer: ScreenCapturer | None = None

    def run(self) -> int:
        """Show the overlay and block until it is closed."""
        from .ui.overlay import run_overlay_app

        verify_no_input_synthesis()

        error = validate_hotkey(self.config.hotkey)
        if error:
            raise ValueError(f"hotkey {self.config.hotkey!r} is not valid: {error}")

        return run_overlay_app(self.config, self._start_listening)

    def _start_listening(self, window) -> None:
        self.window = window
        window.status_changed.emit(
            f"listening for {self.config.hotkey} ({len(self.analyzer.icons)} icons loaded)"
        )
        self._listener = HotkeyListener(
            self.config.hotkey, self.on_hotkey, on_error=self._report_error
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
        if self._capturer is not None:
            self._capturer.close()

    def on_hotkey(self) -> None:
        """Runs on the hotkey thread. Must not touch Qt widgets directly."""
        if self.window is not None:
            self.window.status_changed.emit("capturing...")

        if self._capturer is None:
            self._capturer = ScreenCapturer(self.config.window_title_contains)

        capture = self._capturer.capture()
        if self.save_screenshots:
            save_capture(
                capture,
                self.config.resolve(self.config.capture_dir),
                keep=self.config.keep_captures,
            )

        result = self.analyzer.analyze(capture.image)
        if self.window is not None:
            # Qt queues this across the thread boundary for us.
            self.window.result_ready.emit(result)

    def _report_error(self, exc: BaseException) -> None:
        traceback.print_exception(exc)
        if self.window is not None:
            self.window.status_changed.emit(f"error: {exc}")


def analyze_file(path: Path, config: Config) -> AnalysisResult:
    """Run the pipeline over a PNG on disk. Used by tests and the CLI."""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"could not read image: {path}")
    return BankAnalyzer(config).analyze(image)
