"""Command-line entry points.

``rs3overlay doctor`` is the one to run first on a new machine: it reports
what is installed, what is missing, and what to do about it, without needing
the game open.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import Config, DEFAULT_CONFIG_PATH
from .safety import boundaries_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rs3overlay",
        description="Passive, read-only GE valuation of your RS3 bank.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config", type=Path, default=None, help="path to config.json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("about", help="print the project's read-only boundaries")
    sub.add_parser("doctor", help="check this machine's setup")
    sub.add_parser("windows", help="list visible windows the capturer can see")
    sub.add_parser("init", help="write a config.json with the defaults")

    capture = sub.add_parser(
        "capture", help="Phase 1 manual test: hotkey -> screenshot -> PNG"
    )
    capture.add_argument(
        "--once", action="store_true", help="capture immediately instead of waiting"
    )

    analyze = sub.add_parser("analyze", help="run the full pipeline over a PNG")
    analyze.add_argument("image", type=Path)
    analyze.add_argument(
        "--offline", action="store_true", help="never hit the GE API"
    )
    analyze.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )

    run = sub.add_parser("run", help="the overlay app (Phase 6)")
    run.add_argument(
        "--no-save", action="store_true", help="do not write captures to disk"
    )

    args = parser.parse_args(argv)
    config = Config.load(args.config)

    handlers = {
        "about": lambda: _about(),
        "doctor": lambda: _doctor(config),
        "windows": lambda: _windows(config),
        "init": lambda: _init(args.config),
        "capture": lambda: _capture(config, once=args.once),
        "analyze": lambda: _analyze(config, args),
        "run": lambda: _run(config, save=not args.no_save),
    }
    return handlers[args.command]()


def _about() -> int:
    print(f"rs3overlay {__version__} -- a passive, read-only screen reader.\n")
    print("Boundaries this tool is built to respect:")
    print(boundaries_text())
    print(
        "\nIt reads pixels the game has already drawn. It does not read game "
        "memory,\nand it never sends clicks or keystrokes to the game."
    )
    return 0


def _doctor(config: Config) -> int:
    from .capture.hotkey import backend_error, validate_hotkey
    from .vision.icons import IconLibrary

    ok = True
    print(f"rs3overlay {__version__} -- environment check\n")

    print(f"python            {sys.version.split()[0]}")
    print(f"platform          {sys.platform}")

    for module in ("cv2", "mss", "numpy", "requests", "pytesseract", "pynput", "PyQt6"):
        try:
            __import__(module)
            print(f"{module:<18}ok")
        except ImportError as exc:
            ok = False
            # pynput's "no display" message is a multi-line essay; one line of
            # it is enough here, and `hotkey backend` below says more.
            print(f"{module:<18}MISSING ({str(exc).splitlines()[0]})")

    tesseract = config.tesseract_cmd or shutil.which("tesseract")
    if tesseract and Path(tesseract).exists() or shutil.which("tesseract"):
        print(f"tesseract binary  {tesseract or shutil.which('tesseract')}")
    else:
        ok = False
        print("tesseract binary  MISSING -- stack counts cannot be read")
        print("                  Windows: https://github.com/UB-Mannheim/tesseract/wiki")

    error = validate_hotkey(config.hotkey)
    print(f"hotkey            {config.hotkey}" + ("" if not error else f"  INVALID: {error}"))
    ok = ok and not error

    backend = backend_error()
    if backend:
        ok = False
        print(f"hotkey backend    UNAVAILABLE: {backend}")
    else:
        print("hotkey backend    ok")

    glyphs = config.resolve(config.glyph_templates_path)
    if glyphs.exists():
        print(f"glyph templates   calibrated ({glyphs})")
    else:
        print("glyph templates   not calibrated -- using approximate rendered ones")
        print("                  run: python tools/calibrate_digits.py captures/*.png")

    icon_dir = config.resolve(config.icon_dir)
    library = IconLibrary.load(icon_dir)
    if len(library):
        print(f"icon library      {len(library)} icons in {icon_dir}")
    else:
        ok = False
        print(f"icon library      EMPTY ({icon_dir})")
        print("                  run: python tools/fetch_icons.py --popular")

    cache = config.resolve(config.price_cache_path)
    print(f"price cache       {'present' if cache.exists() else 'not created yet'} ({cache})")

    print("\n" + ("all good" if ok else "some checks failed -- see above"))
    return 0 if ok else 1


def _windows(config: Config) -> int:
    from .capture.window import find_game_window, list_windows

    windows = list_windows()
    if not windows:
        print("No windows enumerated. On Linux install wmctrl; on macOS install")
        print("pyobjc-framework-Quartz. Capture will fall back to full screen.")
        return 1

    for window in windows:
        print(f"{window.width:>5}x{window.height:<5} @ {window.left},{window.top}  {window.title}")

    match = find_game_window(config.window_title_contains)
    print(f"\nwould capture: {match.title if match else 'full screen (no match)'}")
    return 0


def _init(path: Path | None) -> int:
    written = Config().save(path)
    print(f"wrote {written}")
    return 0


def _capture(config: Config, once: bool) -> int:
    from .capture.hotkey import HotkeyListener
    from .capture.screenshot import ScreenCapturer, save_capture
    from .safety import verify_no_input_synthesis

    verify_no_input_synthesis()
    capture_dir = config.resolve(config.capture_dir)

    def grab() -> None:
        with ScreenCapturer(config.window_title_contains) as capturer:
            result = capturer.capture()
        path = save_capture(result, capture_dir, keep=config.keep_captures)
        print(f"saved {path}  ({result.size[0]}x{result.size[1]} from {result.source})")

    if once:
        grab()
        return 0

    print(f"Press {config.hotkey} with your bank open. Ctrl+C here to stop.")
    print(f"Captures go to {capture_dir}")
    listener = HotkeyListener(config.hotkey, grab, on_error=lambda e: print(f"error: {e}"))
    listener.start()
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        listener.stop()
    return 0


def _analyze(config: Config, args) -> int:
    import json

    from .app import analyze_file
    from .data.valuation import format_gp

    if args.offline:
        config.offline = True

    result = analyze_file(args.image, config)

    if args.json:
        print(json.dumps(_result_as_dict(result), indent=2))
        return 0 if result.ok else 1

    detection = result.detection
    print(f"bank detected: {detection.found}  (confidence {detection.confidence:.2f})")
    if detection.grid:
        grid = detection.grid
        print(
            f"grid: {grid.cols}x{grid.rows} cells of {grid.cell_w}x{grid.cell_h}px "
            f"at ({grid.x0},{grid.y0}), quality {grid.quality:.2f}"
        )
    if not result.ok or result.valuation is None:
        print(f"error: {result.error}")
        return 1

    valuation = result.valuation
    print()
    for slot in valuation.top_slots:
        print(
            f"  {slot.quantity:>12,} x {slot.name:<32} "
            f"{format_gp(slot.total):>10}  ({slot.match_score:.2f})"
        )
    for slot in valuation.problem_slots:
        label = slot.name or f"r{slot.row}c{slot.col}"
        print(f"  [{slot.status:<10}] {label:<32} {slot.note}")

    print(f"\n{valuation.summary()}")
    if valuation.prices_stale:
        print("note: some prices came from cache and may be stale")
    return 0


def _result_as_dict(result) -> dict:
    payload = {
        "ok": result.ok,
        "error": result.error,
        "detection": {
            "found": result.detection.found,
            "confidence": round(result.detection.confidence, 3),
            "title_found": result.detection.title_found,
            "reason": result.detection.reason,
        },
    }
    if result.detection.grid:
        grid = result.detection.grid
        payload["grid"] = {
            "x0": grid.x0, "y0": grid.y0,
            "cell_w": grid.cell_w, "cell_h": grid.cell_h,
            "cols": grid.cols, "rows": grid.rows,
            "quality": round(grid.quality, 3),
        }
    if result.valuation is not None:
        payload["total"] = result.valuation.total
        payload["slots"] = [
            {
                "row": s.row, "col": s.col, "item_id": s.item_id, "name": s.name,
                "quantity": s.quantity, "unit_price": s.unit_price,
                "total": s.total, "status": s.status,
                "match_score": round(s.match_score, 3), "note": s.note,
            }
            for s in result.valuation.slots
        ]
    return payload


def _run(config: Config, save: bool) -> int:
    from .app import OverlayApp

    app = OverlayApp(config, save_screenshots=save)
    try:
        return app.run()
    finally:
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
