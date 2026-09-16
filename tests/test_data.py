"""Phase 5: price caching, offline behaviour, and rolling up a total."""

from __future__ import annotations

import json
import time

from rs3overlay.data.ge import GEPriceClient
from rs3overlay.data.valuation import BankValuation, ValuedSlot, value_slots


def _client(tmp_path, **kwargs) -> GEPriceClient:
    return GEPriceClient(cache_path=tmp_path / "prices.json", offline=True, **kwargs)


def test_offline_client_never_calls_the_network(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("offline client must not make requests")

    monkeypatch.setattr("requests.get", explode)
    client = _client(tmp_path)
    assert client.price_for(4151) is None


def test_fresh_cache_entries_are_served_without_fetching(tmp_path):
    client = _client(tmp_path)
    client.store(4151, "Abyssal whip", 1_500_000)
    quote = client.price_for(4151)
    assert quote is not None
    assert quote.price == 1_500_000
    assert not quote.stale


def test_stale_entries_are_still_returned_when_offline(tmp_path):
    """A six-hour-old price beats no price at all -- but it is flagged."""
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps({
        "4151": {"name": "Abyssal whip", "price": 1_000, "fetched_at": time.time() - 99_999}
    }))
    client = GEPriceClient(cache_path=cache, ttl_seconds=60, offline=True)
    quote = client.price_for(4151)
    assert quote is not None and quote.stale


def test_cache_survives_a_round_trip(tmp_path):
    client = _client(tmp_path)
    client.store(4151, "Abyssal whip", 1_500_000)
    client.flush()
    assert GEPriceClient(cache_path=tmp_path / "prices.json", offline=True) \
        .cached_quote(4151).price == 1_500_000


def test_a_corrupt_cache_does_not_crash_startup(tmp_path):
    cache = tmp_path / "prices.json"
    cache.write_text("{not json at all")
    assert GEPriceClient(cache_path=cache, offline=True).cached_quote(1) is None


def test_total_counts_only_fully_resolved_slots(tmp_path):
    client = _client(tmp_path)
    client.store(10, "Good item", 100)

    slots = [
        ValuedSlot(0, 0, 10, "Good item", 5, None),
        ValuedSlot(0, 1, None, "", 3, None, status="unknown"),
        ValuedSlot(0, 2, 10, "Good item", None, None, status="unreadable"),
        ValuedSlot(0, 3, 99, "Unpriced item", 7, None),
    ]
    valuation = value_slots(slots, client)

    assert valuation.total == 500
    assert len(valuation.counted_slots) == 1
    assert {s.status for s in valuation.problem_slots} == {
        "unknown", "unreadable", "unpriced"
    }


def test_summary_states_how_much_of_the_bank_was_read():
    valuation = BankValuation(slots=[
        ValuedSlot(0, 0, 1, "A", 2, 10),
        ValuedSlot(0, 1, None, "", None, None, status="unknown"),
    ])
    summary = valuation.summary()
    assert "1/2" in summary
