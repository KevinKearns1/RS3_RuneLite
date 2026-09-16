# RS3 Bank Value Overlay

A passive, read-only overlay that reads your RuneScape 3 bank off the screen and
tells you what it is worth at Grand Exchange prices.

```
Ctrl+Alt+B  ->  screenshot  ->  find the bank  ->  read each slot  ->  price it  ->  overlay
```

## The boundaries

This tool **looks**. It never touches.

- **No reading or writing RS3's process memory.** Screen pixels only.
- **No simulated input.** It never sends clicks or keystrokes to the game.
- **No automated gameplay actions** of any kind.

These are enforced in code, not just documented: `rs3overlay/safety.py` refuses
to start if an automation or memory-reading library has been imported, and
`tests/test_safety.py` fails the build if any source file references an input
controller. `rs3overlay about` prints the boundaries.

If a feature would need any of the above, it does not get built — see
`docs/RUNELITE_FEATURES.md` for which RuneLite features that rules out and why.

## Status

Phases 1–6 of the brief are built and tested. 71 tests pass.

| Phase | State |
|---|---|
| 1. Hotkey screenshot capture | done |
| 2. Bank detection + grid cropping | done — exact geometry, survives UI scaling |
| 3. OCR quantity reading | **built, 66% on synthetic fixtures** — needs calibration, see below |
| 4. Icon identification | done — 32/32 correct, near-identical art flagged not guessed |
| 5. GE price lookup + valuation | done — cached, offline-capable |
| 6. Overlay UI | done — frameless, always-on-top, click-through toggle, remembers position |

### Read this before trusting a number

**This was built without a single real RS3 screenshot.** The cloud environment
it was written in blocks `runescape.wiki` and `secure.runescape.com`, so there
were no real icons, no real bank captures and no live prices. Everything is
validated against synthetic RS3-shaped fixtures.

The structural work transfers. The **stack-count OCR does not yet** — it reads
66% of synthetic counts, against the brief's 95% target, and closing that gap
needs `tools/calibrate_digits.py` run against your own screenshots. Full
numbers, including what was tried and rejected, are in `docs/ACCURACY.md`.

The pipeline is built so that gap is visible rather than dangerous: a count the
reader is unsure about is reported as unreadable and **excluded from the total**,
and the overlay always says how many slots it actually managed to value.

## Getting started

Windows setup, including the two things that are not pip packages, is in
**`docs/INSTALL_WINDOWS.md`**.

```bash
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip
rs3overlay doctor                   # what is installed, what is missing
```

```bash
python tools/fetch_icons.py --popular      # build the reference icon library
rs3overlay capture                          # Phase 1 on its own: hotkey -> PNG
python tools/calibrate_digits.py captures/*.png
rs3overlay run                              # the overlay
```

## Commands

| Command | What it does |
|---|---|
| `rs3overlay doctor` | Check this machine's setup and say what to fix |
| `rs3overlay about` | Print the read-only boundaries |
| `rs3overlay windows` | List windows the capturer can see, and which it would grab |
| `rs3overlay capture` | Phase 1 alone: hotkey, screenshot, save a PNG |
| `rs3overlay capture --once` | Capture immediately, no hotkey |
| `rs3overlay analyze <png>` | Run the whole pipeline over a saved screenshot |
| `rs3overlay analyze <png> --json` | Same, machine-readable |
| `rs3overlay run` | The overlay app |
| `rs3overlay init` | Write a `config.json` with the defaults |

## How it works

| Module | Job |
|---|---|
| `capture/window.py` | Ask the OS where the RS3 window is (read-only enumeration) |
| `capture/screenshot.py` | Grab those pixels with `mss` |
| `capture/hotkey.py` | Listen for the hotkey — listen only, never synthesise |
| `vision/grid.py` | Find the slot lattice from the periodicity of the edge map |
| `vision/bank.py` | Confirm it is a bank and not an inventory or trade window |
| `vision/ocr.py` | Isolate the stack count by colour, read it, score confidence |
| `vision/glyphs.py` | Match count glyphs against templates with a segmenting DP |
| `vision/icons.py` | Identify the item by shape + colour, flag ambiguity |
| `data/ge.py` | GE prices, cached on disk, polite, offline-capable |
| `data/valuation.py` | Roll slots into a total, keeping failures visible |
| `ui/overlay.py` | The always-on-top window |
| `safety.py` | The boundaries, as enforceable code |

Two design decisions worth knowing:

**The grid is inferred, not calibrated.** The brief allowed requiring a fixed
window size for the MVP. Instead the detector recovers cell pitch and phase from
the edge projection's periodicity, so it works at whatever UI scale you run.

**Uncertainty is reported, never resolved silently.** An unidentifiable icon, two
icons that look alike, a count that contradicts the colour it is drawn in — all
of these produce a flagged slot that is excluded from the total, not a
confident-looking guess. A wrong item or a misread quantity corrupts the answer
invisibly; an openly unreadable slot does not.

## Development

```bash
.venv/bin/python -m pytest              # 71 tests
python tools/make_fixtures.py icons     # regenerate synthetic fixtures
python tools/make_fixtures.py bank
```

Fixtures are generated rather than committed as binaries, so a change to the
generator cannot silently drift from what the tests assert about it.

## Documentation

- **`docs/INSTALL_WINDOWS.md`** — everything to install on your machine
- **`docs/ACCURACY.md`** — measured numbers, and what was tried and rejected
- **`docs/RUNELITE_FEATURES.md`** — RuneLite research, and our feature list
- **`RS3_Bank_Overlay_Project_Brief.md`** — the original brief
