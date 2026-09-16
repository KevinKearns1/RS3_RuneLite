#!/usr/bin/env python3
"""Build the reference icon library from runescape.wiki.

Run this once on a machine with internet access. It writes
``assets/icons/<slug>.png`` plus an ``index.json`` mapping each file to its
item id and display name, which is what :class:`rs3overlay.vision.icons.
IconLibrary` reads.

    python tools/fetch_icons.py --popular
    python tools/fetch_icons.py --names "Abyssal whip" "Dragon bones"
    python tools/fetch_icons.py --from-list my_bank.txt

Item ids come from the wiki's Semantic MediaWiki "Item ID" property; icons
come from the item's inventory image (``File:<name>.png``). Both are fetched
through the public MediaWiki API with a descriptive User-Agent, one item at a
time with a politeness delay -- please leave that delay alone.

Note: this script could not be exercised against the live wiki in the cloud
environment it was written in (egress to runescape.wiki was blocked there), so
treat the first local run as the real test. ``--dry-run`` prints what it would
fetch without writing anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ICON_DIR = PROJECT_ROOT / "assets" / "icons"
API = "https://runescape.wiki/api.php"
USER_AGENT = "RS3BankOverlay/0.6 (personal read-only bank valuation tool)"

#: A small starter set: high-value staples plus the herb family the brief
#: warns about, so the ambiguity path gets exercised on real art early.
POPULAR = [
    "Abyssal whip", "Dragon bones", "Dragon claw", "Armadyl godsword",
    "Bandos chestplate", "Bandos tassets", "Saradomin sword", "Zamorakian spear",
    "Onyx", "Dragonstone", "Ruby", "Diamond", "Emerald", "Sapphire",
    "Coal", "Iron ore", "Runite ore", "Adamantite ore", "Gold ore",
    "Magic logs", "Yew logs", "Maple logs", "Willow logs",
    "Shark", "Rocktail", "Sailfish", "Monkfish",
    "Grimy guam leaf", "Grimy marrentill", "Grimy tarromin", "Grimy harralander",
    "Grimy ranarr weed", "Grimy toadflax", "Grimy irit leaf", "Grimy avantoe",
    "Grimy kwuarm", "Grimy snapdragon", "Grimy cadantine", "Grimy lantadyme",
    "Grimy dwarf weed", "Grimy torstol",
    "Super restore (4)", "Saradomin brew (4)", "Prayer potion (4)",
    "Extreme attack (4)", "Extreme strength (4)", "Overload (4)",
    "Death rune", "Blood rune", "Nature rune", "Law rune", "Air rune",
    "Cannonball", "Feather", "Vial of water", "Clean torstol",
]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class WikiClient:
    def __init__(self, delay: float = 0.5) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self._last = 0.0

    def _wait(self) -> None:
        elapsed = time.time() - self._last
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last = time.time()

    def _get(self, **params) -> dict:
        self._wait()
        params.setdefault("format", "json")
        response = self.session.get(API, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def item_id(self, name: str) -> int | None:
        """Read the item's numeric id off its wiki page via SMW."""
        try:
            payload = self._get(
                action="ask",
                query=f"[[{name}]]|?Item ID|?All Item ID|limit=1",
            )
        except requests.RequestException:
            return None

        results = (payload.get("query") or {}).get("results") or {}
        for entry in results.values():
            printouts = entry.get("printouts") or {}
            for key in ("Item ID", "All Item ID"):
                values = printouts.get(key) or []
                if values:
                    try:
                        return int(values[0])
                    except (TypeError, ValueError):
                        continue
        return None

    def icon_url(self, name: str) -> str | None:
        """URL of the item's inventory icon file."""
        for title in (f"File:{name}.png", f"File:{name} detail.png"):
            try:
                payload = self._get(
                    action="query", titles=title, prop="imageinfo", iiprop="url"
                )
            except requests.RequestException:
                continue
            pages = (payload.get("query") or {}).get("pages") or {}
            for page in pages.values():
                if "missing" in page:
                    continue
                info = (page.get("imageinfo") or [{}])[0]
                url = info.get("url")
                if url:
                    return url
        return None

    def download(self, url: str) -> bytes | None:
        self._wait()
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            return None


def fetch(names: list[str], icon_dir: Path, dry_run: bool, delay: float) -> int:
    client = WikiClient(delay=delay)
    icon_dir.mkdir(parents=True, exist_ok=True)

    index_path = icon_dir / "index.json"
    index: dict[str, dict] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))

    existing_names = {entry.get("name") for entry in index.values()}
    failures = 0

    for name in names:
        if name in existing_names:
            print(f"  skip   {name} (already in index)")
            continue

        if dry_run:
            print(f"  would fetch {name}")
            continue

        item_id = client.item_id(name)
        url = client.icon_url(name)
        if url is None:
            print(f"  FAIL   {name}: no icon file found")
            failures += 1
            continue

        blob = client.download(url)
        if not blob:
            print(f"  FAIL   {name}: download failed")
            failures += 1
            continue

        filename = f"{slugify(name)}.png"
        (icon_dir / filename).write_bytes(blob)
        index[filename] = {
            "item_id": item_id if item_id is not None else -1,
            "name": name,
            "source": url,
        }
        flag = "" if item_id is not None else "  (no item id -- prices unavailable)"
        print(f"  ok     {name} -> {filename}{flag}")

    if not dry_run:
        index_path.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {index_path} ({len(index)} icons)")

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--popular", action="store_true", help="fetch the starter set")
    parser.add_argument("--names", nargs="+", default=[], help="explicit item names")
    parser.add_argument("--from-list", type=Path, help="file with one item name per line")
    parser.add_argument("--icon-dir", type=Path, default=DEFAULT_ICON_DIR)
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    names: list[str] = list(args.names)
    if args.popular:
        names.extend(POPULAR)
    if args.from_list:
        names.extend(
            line.strip()
            for line in args.from_list.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )

    if not names:
        parser.error("nothing to fetch: pass --popular, --names or --from-list")

    seen: dict[str, None] = dict.fromkeys(names)
    print(f"fetching {len(seen)} icon(s) into {args.icon_dir}")
    return fetch(list(seen), args.icon_dir, args.dry_run, args.delay)


if __name__ == "__main__":
    sys.exit(main())
