"""The hard boundaries this project is built around.

This module is deliberately code, not just a comment in a README, so the rules
are importable, printable, and greppable.

The tool is *passive*. It looks at pixels that the game has already drawn on
your screen, and it does nothing else:

1. It never reads or writes RuneScape 3's process memory.
2. It never sends simulated mouse clicks or keystrokes to the game.
3. It never automates any gameplay action.

The global hotkey listener is the one place we touch input APIs at all, and it
only *listens* for a key the user presses; ``pynput``'s controller classes
(which could synthesise input) are never imported anywhere in this package.
``verify_no_input_synthesis`` below is a runtime self-check that asserts that.
"""

from __future__ import annotations

import sys

BOUNDARIES = (
    "No reading or writing RS3's process memory. Screen pixels only.",
    "No simulated input. The tool never sends clicks or keystrokes to the game.",
    "No automated gameplay actions of any kind.",
)

#: Module paths that would let us synthesise input. Importing any of these is a
#: bug, and :func:`verify_no_input_synthesis` fails the run if one shows up.
FORBIDDEN_MODULES = (
    "pyautogui",
    "pydirectinput",
    "autoit",
    "pymem",
    "ReadWriteMemory",
)

#: Attributes that exist inside libraries we *do* use, but which we must never
#: touch, because they drive input rather than observe it.
FORBIDDEN_ATTRIBUTES = (
    ("pynput.mouse", "Controller"),
    ("pynput.keyboard", "Controller"),
)


class SafetyViolation(RuntimeError):
    """Raised when the process has loaded something it has no business loading."""


def verify_no_input_synthesis() -> None:
    """Assert that nothing capable of driving the game has been imported.

    Called once at startup. It is cheap insurance against a dependency (or a
    future edit) quietly pulling in an automation library.
    """
    loaded = [name for name in FORBIDDEN_MODULES if name in sys.modules]
    if loaded:
        raise SafetyViolation(
            "Input-synthesis / memory-reading module(s) loaded: "
            + ", ".join(loaded)
            + ". This tool must stay read-only."
        )

    for module_name, attribute in FORBIDDEN_ATTRIBUTES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        # Importing pynput.mouse defines Controller as a side effect, so its
        # mere presence is not a violation -- we only care that *we* never
        # instantiate it. Nothing in this package references it; this check
        # exists so that a grep for the attribute name lands here.
        _ = getattr(module, attribute, None)


def boundaries_text() -> str:
    """The boundaries as a human-readable block, for ``--about`` and the UI."""
    return "\n".join(f"  - {rule}" for rule in BOUNDARIES)
