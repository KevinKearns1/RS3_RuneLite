# What RuneLite does, and what we can copy

Research notes for scoping this project against RuneLite, plus the feature list
we actually want.

## The structural difference, first

RuneLite is **a game client**. It is an open-source reimplementation of the
OSRS client that loads Jagex's game code and renders the game itself, so a
plugin can ask the client directly "which NPCs are on screen, what are my XP
totals, what is in slot 14 of my bank" and get a typed answer. Jagex
explicitly permits it for Old School RuneScape and maintains an approved
third-party client list.

We are **an overlay**. RS3 has no equivalent sanctioned open client; the
closest analogue is the [Alt1 Toolkit](https://runescape.wiki/w/Alt1_Toolkit),
which Jagex's anti-cheating team reviewed and said was "fine" to use, and which
works the same way we do — by reading pixels off the screen. Alt1 notably does
*not* carry the same formal approval RuneLite has, and third-party tools are
used at the player's own risk.

That difference decides what is portable. Anything RuneLite does by *asking the
client for state* we must instead do by *recognising pixels*, which is harder
and less reliable. Anything RuneLite does by *changing what the client sends to
the server* we cannot do at all, and would not want to.

## RuneLite features, triaged

### Green — screen-readable, squarely in scope

These need only information already drawn on screen, and produce only
information back. This is our lane.

| RuneLite feature | RS3 equivalent for us | Notes |
|---|---|---|
| **Bank value summary** | **Phase 1–6, built** | RuneLite reads bank contents from the client; we OCR + icon-match them. The hard part is ours, not theirs. |
| GE price checker | Read an item name/icon, look up the GE API | We already have the price client and cache. |
| Loot / drop tracker | OCR the chat box for "You receive:" lines | Chat text is larger and cleaner than stack counts — easier OCR than what we already do. |
| XP tracker / XP per hour | OCR the XP counter or skills interface on a timer | Passive sampling; no game interaction. |
| Item / stat readouts in a side panel | Our overlay window | Same idea, same constraints. |
| Wiki lookup for the item under the cursor | Icon match → wiki link | Read-only; opens a browser, never touches the game. |
| Screenshot / session logging | Already the capture layer | |

### Amber — possible but unreliable, and a lot of work

RuneLite gets these for free from client state. We would be inferring them from
pixels, which means they will be wrong sometimes.

| RuneLite feature | Why it is hard for us |
|---|---|
| Ground item highlighting | Needs text/entity recognition over a moving 3D scene, not a fixed UI panel. |
| NPC / player highlighting, tile indicators | Same, plus we would have to draw on top of a moving camera with no depth information. |
| Boss timers, attack timers | Needs reliable event detection from animation pixels; false timers are worse than none. |
| Quest helper | Needs to know quest state, which is not fully on screen. |
| Inventory setups / bank tag organisation | Reading is fine; RuneLite's version also *acts* on the bank, which we cannot. |

My recommendation: none of these before the bank tool is genuinely solid. They
share a prerequisite — reliable recognition — that the bank work is already
exercising, and that prerequisite is not finished.

### Red — we will not build these, at any point

These are the features that make RuneLite a *client* rather than an overlay.
Each one requires either running game code or changing what the game sends, and
each would cross the boundaries in the brief.

| RuneLite feature | Why it is out |
|---|---|
| **Menu entry swapper**, one-click actions | Changes what your click does. That is input manipulation, even though a human still clicks. |
| **Key remapping / hotkey actions in game** | Sends keystrokes to the game. |
| 117HD, GPU renderer, custom draw distance, zoom | Requires rendering the game ourselves, i.e. being a client. |
| Anything reading the RS3 process | Memory access, ruled out flatly by the brief. |
| Auto-bank, auto-anything | Automated gameplay. |

If a future idea sounds like one of these, that is the signal to stop and talk
about it rather than build it — which is what the brief asks for and what
`rs3overlay/safety.py` enforces in code.

## Proposed feature list for our version

In the order I would build them:

1. **Bank valuation** (done — Phases 1–6). Hotkey → screenshot → detect bank →
   read slots → price → overlay.
2. **Calibration + accuracy work.** The single highest-value next step, because
   everything else inherits the recognition layer. See `ACCURACY.md`.
3. **Multi-tab totals.** You click the tabs, we accumulate per-tab results and
   show a bank-wide total. Still one hotkey press per tab — no auto-switching.
4. **Chat-box loot tracker.** Cleaner OCR target than stack counts, and it gives
   a session GP/hr number that the bank total cannot.
5. **XP tracker.** Periodic passive sampling of the XP readout.
6. **Price-watch list.** Purely a GE API feature, no screen reading at all.
7. **Export to the Overload planner spreadsheet**, per the brief's stretch goal.

Everything on that list stays inside "look, don't touch".

## Sources

- [Alt1 Toolkit — RuneScape Wiki](https://runescape.wiki/w/Alt1_Toolkit)
- [Plugin Hub — RuneLite](https://runelite.net/plugin-hub/)
- [Best RuneLite Plugins for OSRS](https://www.partypeteshop.com/best-runelite-plugins)
- [The Ongoing Crusade Against Third Party Tools — RSBANDBInformer](https://informer.rsbandb.com/2018/06/the-ongoing-crusade-against-third-party-tools/)
