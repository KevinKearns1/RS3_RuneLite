# Moving this to your Windows machine

Everything you need to install locally, in order. This project was developed in
a Linux cloud container; this is the list of what does *not* come with it.

## 1. Python 3.11 or newer

Download from [python.org](https://www.python.org/downloads/windows/).

**Tick "Add python.exe to PATH" in the installer.** Verify:

```powershell
python --version
```

## 2. Tesseract OCR (a system binary, not a pip package)

`pytesseract` is only a wrapper — the actual OCR engine is a separate `.exe`.

Installer: **<https://github.com/UB-Mannheim/tesseract/wiki>**

It installs to `C:\Program Files\Tesseract-OCR\tesseract.exe` by default. Either
add that folder to your PATH, or set it in `config.json`:

```json
{ "tesseract_cmd": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe" }
```

Verify with `rs3overlay doctor`, which reports where it found the binary.

## 3. The project itself

```powershell
git clone <your repo url>
cd RS3_RuneLite
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pywin32
```

`pywin32` is Windows-only and is why it is not in the base dependency list. It
provides two things:

- **Window targeting** — capturing just the RS3 client rather than your whole
  desktop. Without it, capture falls back to the primary monitor, which still
  works but wastes pixels.
- **Overlay click-through** — the `WS_EX_TRANSPARENT` style. Without it, the
  click-through toggle only half works.

## 4. Fetch the item icons

Needs internet access, and could not be run from the cloud environment (the
network policy there blocks `runescape.wiki`), so **this is the first thing to
test locally**:

```powershell
python tools\fetch_icons.py --popular
```

Start with `--dry-run` to see what it would fetch. This writes
`assets\icons\*.png` plus `index.json`. Nothing can be identified without it.

## 5. Calibrate the stack-count font

This is the step that decides whether quantities are read accurately — see
`ACCURACY.md` for why. Capture a few bank screenshots first:

```powershell
rs3overlay capture
```

Press `Ctrl+Alt+B` with your bank open, a few times, across tabs with stacked
items. Then:

```powershell
python tools\calibrate_digits.py captures\*.png
```

It shows each distinct glyph shape and asks which character it is. About 13
answers. Writes `assets\font\stack_digits.json`.

## 6. Check everything

```powershell
rs3overlay doctor
```

It reports every dependency, the Tesseract path, hotkey validity, whether the
icon library and glyph calibration exist, and what to run for anything missing.

## Running it

```powershell
rs3overlay run
```

Press `Ctrl+Alt+B` with your bank open.

## Windows-specific gotchas

- **Run RS3 in windowed or borderless mode.** True exclusive fullscreen can
  produce black captures, because there is no composited desktop copy to read.
- **Global hotkeys and elevation.** If RS3 runs as administrator and this does
  not, Windows will not deliver the hotkey while RS3 has focus. Run both the
  same way.
- **Display scaling.** The grid detector handles UI scale automatically, but if
  you change Windows display scaling, re-run the glyph calibration — the font
  rasterises differently at a different scale.
- **Multiple monitors.** Without `pywin32` the fallback captures the *primary*
  monitor only. Install it if RS3 lives on a second screen.

## Optional

- **`wmctrl`** — Linux only, ignore on Windows.
- **`pyobjc-framework-Quartz`** — macOS only, ignore on Windows.

## Quick reference

| What | Where from | Required? |
|---|---|---|
| Python 3.11+ | python.org | yes |
| Tesseract OCR binary | UB-Mannheim installer | yes, for stack counts |
| pip dependencies | `pip install -e .` | yes |
| `pywin32` | `pip install pywin32` | strongly recommended |
| Item icons | `tools\fetch_icons.py` | yes, for identification |
| Glyph calibration | `tools\calibrate_digits.py` | strongly recommended |
