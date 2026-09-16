# RS3 Bank Value Overlay — Project Brief & Claude Code Kickoff

A personal desktop overlay for RuneScape 3 that reads your bank via screen capture + OCR/image
recognition (no memory reading, no automation) and shows the total GE value of what's in it.
Think "Alt1 Toolkit price checker," but built for RS3 by you, for you.

---

## Hard boundaries (read this first, and keep it true for the life of the project)

This has to stay a **passive, read-only** tool or it crosses from "utility" into "cheat client / bot,"
which is a bannable offense under Jagex's rules. Every future session on this project should hold the line:

- **No reading or writing RS3's process memory.** Ever. Screen pixels only.
- **No simulated input.** The tool never sends clicks or keystrokes to the game. You drive the game;
  the tool only *looks*.
- **No automated gameplay actions** of any kind (auto-clicking bank tabs, auto-anything).
- If a future feature idea would require crossing one of these lines, stop and flag it instead of
  building it.

Everything below is designed to respect those lines.

## Vision / MVP scope

1. User presses a hotkey while their RS3 bank is open.
2. Tool grabs a screenshot of the game window.
3. Confirms a bank interface is actually open (template-match the "BANK OF GIELINOR" header).
4. Crops the item grid out of the screenshot.
5. For each grid cell: OCR the stack-count number, and identify the item icon by matching it
   against a local reference-icon library.
6. Looks up each identified item's current price via RS3's official Grand Exchange API.
7. Shows a breakdown + total value in a small always-on-top overlay window.
8. MVP only reads whatever bank tab is currently visible — no auto-switching tabs. You manually
   click through tabs and re-press the hotkey per tab.

## Recommended stack

- **Python 3.11+** — best ecosystem for this (OCR + computer vision libraries are mature and easy
  to iterate on). If you'd rather do it in C#/.NET or Electron, that's viable too — say so up front
  and Claude Code should adjust the plan, but default to Python unless you have a reason not to.
- `mss` — fast screen capture
- `pytesseract` + the Tesseract OCR binary — reading the stack-count numbers
- `opencv-python` — icon template matching / grid detection
- `requests` — GE price API calls
- `PyQt6` (or Tkinter if you want zero extra install friction) — the transparent, always-on-top
  overlay window
- A local folder of reference item icons, downloaded once and cached (source: the RuneScape Wiki)

## Data sources

- **Icon reference images + item IDs:** RuneScape Wiki (runescape.wiki) — item pages have the
  clean icon image and item ID.
- **Prices:** RS3's official Grand Exchange API —
  `https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json?item=<id>`
  (per-item lookup; there's also a graph endpoint for price history if you ever want trends).
  Cache prices locally — no need to hit this every capture.

## Known hard parts — expect to iterate here

- **OCR on the game's stylized yellow-on-dark font**, especially at small sizes, will need real
  image preprocessing (upscale, threshold) and testing against real screenshots before it's reliable.
- **Distinguishing visually similar item icons** — we ran into this directly building the Overload
  planner: several herbs are near-identical green leaf icons at bank-icon resolution. Template
  matching should do better than a human eyeballing a thumbnail, but validate it against real
  screenshots with known ground truth (we have some from the Overload project) rather than assuming
  it just works.
- **Large stacks render as abbreviated text** (e.g. "41.1K", "1.2M") once you cross certain
  thresholds — the OCR/parsing needs to handle that, not just raw digit strings. (Your own bank
  screenshots so far were all under that threshold, so this can wait until it actually comes up.)
- **Grid position shifts with window size / UI scale** — MVP can require a fixed, calibrated window
  size; resolution-independence is a later phase, not day one.
- **GE API rate limits** — cache aggressively, don't refetch prices you already have from the last
  few minutes.

## Phased build plan

Work through these in order. Each phase should end in something you can actually run and see
working before moving to the next — **stop and get it committed to git after each phase**, don't
let multiple phases pile up uncommitted.

1. **Screen capture + hotkey trigger** — global hotkey, screenshot the RS3 window, save to disk.
   Done when: pressing the hotkey reliably saves a PNG of the game window.
2. **Bank detection + grid cropping** — confirm the bank UI is open, crop out just the item grid.
   Done when: you can point it at any of your bank screenshots and it correctly isolates the grid.
3. **OCR quantity reading** — read the stack-count number off each grid cell.
   Done when: it correctly reads the numbers off a test screenshot with >95% accuracy.
4. **Icon identification** — build the reference icon library, match each cell against it.
   Done when: it correctly names the item in each cell of a test screenshot — this is the phase to
   spend the most validation time on, given what we saw with the herb icons.
5. **GE price lookup + valuation** — resolve identified items to prices, sum the total, cache results.
6. **Overlay UI** — transparent always-on-top window showing the breakdown + total, refreshed on
   hotkey. Polish: click-through toggle, remembers its screen position, dark theme to match RS3.
7. **(Stretch, later)** — multiple tabs in one pass, resolution independence, exporting results into
   the Overload planner spreadsheet we already built.

## Prompt to paste into Claude Code to kick this off

```
I'm building a personal, passive screen-reading overlay for RuneScape 3 (RS3) that shows the
total Grand Exchange value of my bank. This must stay a read-only tool: it only takes
screenshots of what's already drawn on screen and reads pixels. It must NEVER send simulated
clicks or keystrokes to the game, and must NEVER read or write the game's process memory — no
automation of any gameplay action, ever. If a future request from me would cross either of
those lines, stop and flag it back to me instead of implementing it.

Read RS3_Bank_Overlay_Project_Brief.md in this repo for the full spec, recommended stack, data
sources, and phased build plan. Set up the project structure and a virtual environment, then
build Phase 1 (hotkey screenshot capture) end-to-end with a simple manual test, and stop there
for my review before starting Phase 2. Ask before installing anything with a system-level
dependency (like the Tesseract OCR binary) so I know what's landing on my machine. Once Phase 1
works, remind me to commit before we move on.
```

Save this whole file as `RS3_Bank_Overlay_Project_Brief.md` at the root of a new repo, paste the
prompt above into Claude Code in that repo, and you're off.
