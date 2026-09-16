"""Global hotkey listening.

This is the only place the project touches an input API, and it is strictly a
*listener*: ``pynput.keyboard.GlobalHotKeys`` observes key events the OS is
already dispatching. We never import or construct ``pynput``'s ``Controller``
classes, which are the ones that could synthesise input.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable


class HotkeyListener:
    """Runs a hotkey -> callback binding on a background thread.

    Parameters
    ----------
    hotkey:
        pynput ``GlobalHotKeys`` notation, e.g. ``"<ctrl>+<alt>+b"``.
    callback:
        Invoked on the listener thread each time the hotkey fires. Exceptions
        raised by the callback are swallowed and reported through
        ``on_error`` so one bad capture cannot kill the listener.
    """

    def __init__(
        self,
        hotkey: str,
        callback: Callable[[], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.hotkey = hotkey
        self._callback = callback
        self._on_error = on_error
        self._listener = None
        self._lock = threading.Lock()
        self._busy = False

    def _fire(self) -> None:
        # Ignore a re-press while the previous capture is still running; the
        # pipeline takes a moment and queued repeats help nobody.
        with self._lock:
            if self._busy:
                return
            self._busy = True
        try:
            self._callback()
        except BaseException as exc:  # noqa: BLE001 - listener must survive
            if self._on_error is not None:
                self._on_error(exc)
        finally:
            with self._lock:
                self._busy = False

    def start(self) -> None:
        from pynput import keyboard

        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys({self.hotkey: self._fire})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        """Block until the listener stops. Used by the headless CLI runner."""
        if self._listener is not None:
            self._listener.join()

    def __enter__(self) -> "HotkeyListener":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


#: ``<ctrl>+<alt>+b``: one or more parts joined by ``+``, each either a
#: ``<name>`` modifier/special key or a single character.
_HOTKEY_PART = re.compile(r"^(<[a-z0-9_]+>|[^<>+\s])$", re.IGNORECASE)


def validate_hotkey(hotkey: str) -> str | None:
    """Return an error message if ``hotkey`` is not usable, else ``None``.

    The syntax check runs first and without importing a backend, because
    ``pynput``'s parser needs a display connection: on a headless machine it
    raises about a missing X server, which says nothing about whether the
    user's hotkey string is well formed.
    """
    if not hotkey or not hotkey.strip():
        return "hotkey is empty"

    parts = hotkey.split("+")
    for part in parts:
        if not _HOTKEY_PART.match(part.strip()):
            return (
                f"{part.strip()!r} is not a valid hotkey part; expected a single "
                "character or a name in angle brackets, e.g. '<ctrl>+<alt>+b'"
            )

    try:
        from pynput import keyboard

        keyboard.HotKey.parse(hotkey)
    except Exception:  # noqa: BLE001 - backend unavailable, or unknown key name
        # Whether a backend can be reached is a separate question from whether
        # the string is well formed -- pynput raises ImportError for a missing
        # display, which says nothing about the hotkey. Report that through
        # :func:`backend_error` instead, so `doctor` can show both.
        return None
    return None


def backend_error() -> str | None:
    """Why global hotkeys will not work here, if they will not.

    Separate from :func:`validate_hotkey` so a headless machine reports "no
    display" rather than blaming the user's key combination.
    """
    try:
        from pynput import keyboard

        keyboard.HotKey.parse("<ctrl>+a")
    except Exception as exc:  # noqa: BLE001 - surfacing the library's message
        return str(exc).splitlines()[0]
    return None
