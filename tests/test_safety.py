"""The boundaries are the point of the project, so they get tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from rs3overlay import safety

SRC = Path(__file__).parents[1] / "src"


def test_verify_passes_on_a_clean_process():
    safety.verify_no_input_synthesis()


def test_verify_rejects_an_automation_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyautogui", object())
    with pytest.raises(safety.SafetyViolation, match="pyautogui"):
        safety.verify_no_input_synthesis()


def test_no_module_constructs_an_input_controller():
    """No source file may instantiate pynput's Controller classes.

    Those are the only things in our dependency set that can send input to the
    game. Listening for a hotkey is fine; constructing a controller is not.
    """
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "safety.py":
            continue  # it names them in order to forbid them
        text = path.read_text(encoding="utf-8")
        for needle in ("mouse.Controller", "keyboard.Controller", "Controller()"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, f"input-synthesis usage found: {offenders}"


def test_no_memory_reading_dependency():
    """Nothing in the project may import a process-memory library."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("import pymem", "ReadWriteMemory", "OpenProcess"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, f"memory access found: {offenders}"


def test_about_command_states_the_boundaries():
    result = subprocess.run(
        [sys.executable, "-m", "rs3overlay.cli", "about"],
        capture_output=True, text=True, check=True,
    )
    assert "read-only" in result.stdout
    assert "memory" in result.stdout.lower()
