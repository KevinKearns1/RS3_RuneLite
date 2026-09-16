"""Locating the RuneScape window.

This is read-only window *enumeration*: we ask the OS where a window is, we
never focus, move, resize or send anything to it. Each platform gets its own
backend, and every backend degrades to "no window found" rather than raising,
so callers can always fall back to a full-screen grab.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowRect:
    """A window's position and size in screen coordinates."""

    title: str
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_bbox(self) -> dict[str, int]:
        """The dict shape ``mss`` wants."""
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def list_windows() -> list[WindowRect]:
    """Every visible top-level window we can see, best-effort per platform."""
    system = platform.system()
    if system == "Windows":
        return _list_windows_win32()
    if system == "Linux":
        return _list_windows_x11()
    if system == "Darwin":
        return _list_windows_macos()
    return []


def find_game_window(title_contains: str = "RuneScape") -> WindowRect | None:
    """The largest visible window whose title contains ``title_contains``.

    Size is the tiebreaker because RS3 tends to have satellite windows (the
    launcher, a browser tab) that match on title but are not the client.
    """
    if not title_contains:
        return None
    needle = title_contains.casefold()
    matches = [
        w
        for w in list_windows()
        if needle in w.title.casefold() and w.width > 200 and w.height > 200
    ]
    if not matches:
        return None
    return max(matches, key=lambda w: w.width * w.height)


# --- platform backends ----------------------------------------------------


def _list_windows_win32() -> list[WindowRect]:
    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore
    except ImportError:
        return []

    found: list[WindowRect] = []

    def _collect(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        # Skip cloaked/minimised windows, which report bogus rects.
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement and placement[1] == win32con.SW_SHOWMINIMIZED:
            return
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        # GetClientRect is window-relative; translate to screen coordinates so
        # the grab excludes the title bar and borders.
        left, top = win32gui.ClientToScreen(hwnd, (left, top))
        right, bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
        found.append(
            WindowRect(title, left, top, max(0, right - left), max(0, bottom - top))
        )

    win32gui.EnumWindows(_collect, None)
    return found


def _list_windows_x11() -> list[WindowRect]:
    if not shutil.which("wmctrl"):
        return []
    try:
        output = subprocess.run(
            ["wmctrl", "-lG"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []

    found: list[WindowRect] = []
    for line in output.splitlines():
        # id desktop x y w h host title...
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        try:
            x, y, w, h = (int(p) for p in parts[2:6])
        except ValueError:
            continue
        found.append(WindowRect(parts[7], x, y, w, h))
    return found


def _list_windows_macos() -> list[WindowRect]:
    try:
        from Quartz import (  # type: ignore
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListExcludeDesktopElements,
            kCGWindowListOptionOnScreenOnly,
        )
    except ImportError:
        return []

    options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    found: list[WindowRect] = []
    for info in CGWindowListCopyWindowInfo(options, kCGNullWindowID) or []:
        title = info.get("kCGWindowName") or info.get("kCGWindowOwnerName") or ""
        bounds = info.get("kCGWindowBounds") or {}
        if not bounds:
            continue
        found.append(
            WindowRect(
                str(title),
                int(bounds.get("X", 0)),
                int(bounds.get("Y", 0)),
                int(bounds.get("Width", 0)),
                int(bounds.get("Height", 0)),
            )
        )
    return found
