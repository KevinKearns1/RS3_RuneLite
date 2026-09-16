"""A frameless, always-on-top breakdown of the last bank read.

The window is deliberately inert: it shows text and nothing it does reaches
the game. The one platform-specific call here is the Windows click-through
toggle, which sets ``WS_EX_TRANSPARENT`` on *our own* window so mouse events
fall through to whatever is underneath. That is the opposite of sending
input -- it makes this window stop receiving it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..data.valuation import BankValuation, format_gp
from ..pipeline import AnalysisResult

# RS3's interface palette, so the overlay sits next to the game without
# looking like a system dialog parked on top of it.
_BG = "#12100c"
_PANEL = "#1d1a13"
_BORDER = "#3d372b"
_TEXT = "#e8dcc0"
_MUTED = "#9a8f76"
_GOLD = "#ffd34d"
_WARN = "#e0a33a"
_BAD = "#d4664a"

_STATUS_COLOURS = {
    "ok": _TEXT,
    "ambiguous": _WARN,
    "unknown": _BAD,
    "unpriced": _WARN,
    "unreadable": _WARN,
}


class OverlayWindow(QWidget):
    """The overlay. Call :meth:`show_result` from the Qt thread."""

    #: Emitted from the hotkey thread; Qt marshals it onto the UI thread for us.
    result_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)

    def __init__(self, config: Config, on_close: Callable[[], None] | None = None):
        super().__init__()
        self.config = config
        self._on_close = on_close
        self._drag_origin = None

        self.setWindowTitle("RS3 Bank Value")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowOpacity(config.overlay_opacity)
        self.setGeometry(
            config.overlay_x,
            config.overlay_y,
            config.overlay_width,
            config.overlay_height,
        )

        self._build_ui()
        self._apply_theme()

        self.result_ready.connect(self.show_result)
        self.status_changed.connect(self._set_status)

        if config.overlay_click_through:
            self.set_click_through(True)

    # --- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        self._title = QLabel("RS3 Bank Value")
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(self._title)
        header.addStretch(1)

        self._pin_button = QPushButton("click-through")
        self._pin_button.setCheckable(True)
        self._pin_button.setChecked(self.config.overlay_click_through)
        self._pin_button.setToolTip(
            "Let mouse clicks pass through this window to whatever is behind it."
        )
        self._pin_button.toggled.connect(self.set_click_through)
        header.addWidget(self._pin_button)

        close_button = QPushButton("x")
        close_button.setFixedWidth(24)
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)
        root.addLayout(header)

        self._total = QLabel("--")
        self._total.setObjectName("total")
        self._total.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        root.addWidget(self._total)

        self._subtitle = QLabel(f"Press {self.config.hotkey} with your bank open")
        self._subtitle.setObjectName("muted")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("divider")
        root.addWidget(divider)

        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._rows.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows_host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, 1)

        self._status = QLabel("ready")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{ background: {_BG}; color: {_TEXT};
                       font-family: 'Segoe UI', sans-serif; font-size: 12px; }}
            QLabel#total {{ color: {_GOLD}; }}
            QLabel#muted {{ color: {_MUTED}; font-size: 11px; }}
            QFrame#divider {{ color: #3d372b; }}
            QScrollArea {{ background: {_BG}; }}
            QPushButton {{ background: {_PANEL}; border: 1px solid #3d372b;
                           border-radius: 3px; padding: 2px 6px; color: {_MUTED}; }}
            QPushButton:hover {{ color: {_TEXT}; border-color: #5c5340; }}
            QPushButton:checked {{ color: {_GOLD}; border-color: {_GOLD}; }}
            """
        )
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(_BG))
        self.setPalette(palette)

    # --- behaviour --------------------------------------------------------

    def set_click_through(self, enabled: bool) -> None:
        """Toggle whether clicks land on this window or pass through it."""
        self.config.overlay_click_through = enabled
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        # Qt's attribute alone is not enough on Windows; the extended window
        # style has to be updated too, or the window keeps swallowing clicks.
        if sys.platform == "win32":
            self._apply_win32_click_through(enabled)

    def _apply_win32_click_through(self, enabled: bool) -> None:
        try:
            import win32con  # type: ignore
            import win32gui  # type: ignore
        except ImportError:
            return
        hwnd = int(self.winId())
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if enabled:
            style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
        else:
            style &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._drag_origin = None
        self._remember_position()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._remember_position()
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)

    def _remember_position(self) -> None:
        geometry = self.geometry()
        self.config.overlay_x = geometry.x()
        self.config.overlay_y = geometry.y()
        self.config.overlay_width = geometry.width()
        self.config.overlay_height = geometry.height()
        try:
            self.config.save()
        except OSError:
            pass

    # --- content ----------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _clear_rows(self) -> None:
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def show_result(self, result: AnalysisResult) -> None:
        """Render one analysis. Safe to call with a failed result."""
        self._clear_rows()

        if not result.ok or result.valuation is None:
            self._total.setText("--")
            self._subtitle.setText(result.error or "no bank detected")
            self._status.setText(
                f"detection confidence {result.detection.confidence:.2f}"
            )
            return

        valuation = result.valuation
        self._total.setText(format_gp(valuation.total))
        self._subtitle.setText(valuation.summary())
        self._render_rows(valuation)

        notes = []
        if valuation.prices_stale:
            notes.append("some prices are cached/stale")
        problems = valuation.problem_slots
        if problems:
            notes.append(f"{len(problems)} slot(s) not counted")
        self._status.setText("; ".join(notes) if notes else "all slots valued")

    def _render_rows(self, valuation: BankValuation) -> None:
        limit = self.config.overlay_max_rows
        for slot in valuation.top_slots[:limit]:
            suffix = " *" if slot.price_stale else ""
            self._rows.insertWidget(
                self._rows.count() - 1,
                _row_widget(
                    f"{slot.quantity:,} x {slot.name}",
                    format_gp(slot.total) + suffix,
                    _STATUS_COLOURS["ok"],
                ),
            )

        hidden = len(valuation.counted_slots) - limit
        if hidden > 0:
            self._rows.insertWidget(
                self._rows.count() - 1,
                _row_widget(f"+ {hidden} more slot(s)", "", _MUTED),
            )

        for slot in valuation.problem_slots:
            label = slot.name or f"slot r{slot.row}c{slot.col}"
            self._rows.insertWidget(
                self._rows.count() - 1,
                _row_widget(
                    f"{label} - {slot.note or slot.status}",
                    slot.status,
                    _STATUS_COLOURS.get(slot.status, _MUTED),
                ),
            )


def _row_widget(left: str, right: str, colour: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)

    left_label = QLabel(left)
    left_label.setStyleSheet(f"color: {colour};")
    left_label.setWordWrap(False)
    layout.addWidget(left_label, 1)

    if right:
        right_label = QLabel(right)
        right_label.setStyleSheet(f"color: {colour};")
        right_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(right_label)

    return row


def run_overlay_app(config: Config, on_ready: Callable[[OverlayWindow], None]):
    """Start Qt, build the overlay, hand it to ``on_ready``, and run the loop."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = OverlayWindow(config)
    window.show()
    on_ready(window)
    return app.exec()
