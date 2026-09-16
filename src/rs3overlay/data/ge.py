"""The RS3 Grand Exchange price API, with an on-disk cache in front of it.

The brief is explicit that we should cache aggressively and not refetch prices
we already hold, so the cache is the primary interface and the network is the
fallback: ``price_for`` only reaches out when an entry is missing or stale.

The API returns prices as display strings rather than numbers -- ``"2.4m"``,
``"41.1k"``, ``"1,234"`` -- so :func:`parse_ge_price` is doing real work, not
just ``int()``.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


@dataclass
class PriceQuote:
    """One item's cached price."""

    item_id: int
    name: str
    price: int
    fetched_at: float
    stale: bool = False

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


def parse_ge_price(value: object) -> int | None:
    """Turn the GE API's price field into an integer.

    The field is an ``int`` for small numbers and a suffixed string for large
    ones, and the string may carry a leading ``+``/``-`` for trend fields.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if not isinstance(value, str):
        return None

    text = value.strip().replace(",", "").replace("+", "")
    if not text:
        return None

    negative = text.startswith("-")
    text = text.lstrip("-")

    multiplier = 1
    if text and text[-1].lower() in _SUFFIXES:
        multiplier = _SUFFIXES[text[-1].lower()]
        text = text[:-1]

    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return None

    result = int(round(float(text) * multiplier))
    return -result if negative else result


class GEPriceClient:
    """Cached client for ``catalogue/detail.json``.

    Parameters mirror :class:`~rs3overlay.config.Config`; the client never
    mutates the config it is given.
    """

    def __init__(
        self,
        cache_path: Path,
        ttl_seconds: int = 6 * 60 * 60,
        api_base: str = "https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json",
        user_agent: str = "RS3BankOverlay/0.6",
        request_delay: float = 0.6,
        offline: bool = False,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_seconds
        self.api_base = api_base
        self.user_agent = user_agent
        self.request_delay = request_delay
        self.offline = offline

        self._cache: dict[str, dict] = {}
        self._last_request = 0.0
        self._dirty = False
        self._load_cache()

    # --- cache ------------------------------------------------------------

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt cache is a nuisance, not a failure; start a fresh one.
            self._cache = {}

    def flush(self) -> None:
        """Persist the cache, if anything changed since it was loaded."""
        if not self._dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
        tmp.replace(self.cache_path)
        self._dirty = False

    def cached_quote(self, item_id: int) -> PriceQuote | None:
        entry = self._cache.get(str(item_id))
        if not entry:
            return None
        fetched_at = float(entry.get("fetched_at", 0.0))
        return PriceQuote(
            item_id=item_id,
            name=str(entry.get("name", "")),
            price=int(entry.get("price", 0)),
            fetched_at=fetched_at,
            stale=(time.time() - fetched_at) > self.ttl_seconds,
        )

    def store(self, item_id: int, name: str, price: int) -> None:
        self._cache[str(item_id)] = {
            "name": name,
            "price": price,
            "fetched_at": time.time(),
        }
        self._dirty = True

    # --- network ----------------------------------------------------------

    def price_for(self, item_id: int) -> PriceQuote | None:
        """Current price for ``item_id``, from cache when possible.

        A stale cached quote is preferred over nothing: if the GE API is down
        or we are offline, a six-hour-old price still values the bank roughly
        right, and the staleness is carried on the quote for the UI to show.
        """
        cached = self.cached_quote(item_id)
        if cached is not None and not cached.stale:
            return cached
        if self.offline:
            return cached

        fetched = self._fetch(item_id)
        if fetched is None:
            return cached
        return fetched

    def prices_for(self, item_ids: list[int]) -> dict[int, PriceQuote]:
        """Look up many items, hitting the network only for what we lack."""
        quotes: dict[int, PriceQuote] = {}
        for item_id in dict.fromkeys(item_ids):  # de-duplicate, keep order
            quote = self.price_for(item_id)
            if quote is not None:
                quotes[item_id] = quote
        self.flush()
        return quotes

    def _fetch(self, item_id: int) -> PriceQuote | None:
        import requests

        self._respect_rate_limit()
        try:
            response = requests.get(
                self.api_base,
                params={"item": item_id},
                headers={"User-Agent": self.user_agent},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - any failure falls back to cache
            return None

        item = payload.get("item") or {}
        price = parse_ge_price((item.get("current") or {}).get("price"))
        if price is None:
            return None

        name = str(item.get("name", ""))
        self.store(item_id, name, price)
        return PriceQuote(
            item_id=item_id, name=name, price=price, fetched_at=time.time()
        )

    def _respect_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request = time.time()
