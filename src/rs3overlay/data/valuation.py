"""Turning identified slots into a priced breakdown."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ge import GEPriceClient, PriceQuote


@dataclass
class ValuedSlot:
    """One bank slot, priced."""

    row: int
    col: int
    item_id: int | None
    name: str
    quantity: int | None
    unit_price: int | None
    match_score: float = 0.0
    status: str = "ok"
    """One of ``ok``, ``ambiguous``, ``unknown``, ``unpriced``, ``unreadable``."""

    note: str = ""
    price_stale: bool = False

    @property
    def total(self) -> int:
        if self.quantity is None or self.unit_price is None:
            return 0
        return self.quantity * self.unit_price

    @property
    def counted(self) -> bool:
        """Whether this slot contributed to the bank total."""
        return self.status == "ok" and self.total > 0


@dataclass
class BankValuation:
    """The whole readable-bank answer for one capture."""

    slots: list[ValuedSlot] = field(default_factory=list)
    prices_stale: bool = False

    @property
    def total(self) -> int:
        return sum(s.total for s in self.slots if s.counted)

    @property
    def counted_slots(self) -> list[ValuedSlot]:
        return [s for s in self.slots if s.counted]

    @property
    def problem_slots(self) -> list[ValuedSlot]:
        """Slots we could not fully resolve, worst first.

        Surfacing these is the point: a total computed from 40 of 48 slots is
        a different claim from a total computed from all 48, and the UI should
        never let those look the same.
        """
        order = {"unknown": 0, "ambiguous": 1, "unreadable": 2, "unpriced": 3}
        return sorted(
            (s for s in self.slots if not s.counted),
            key=lambda s: (order.get(s.status, 9), -s.match_score),
        )

    @property
    def top_slots(self) -> list[ValuedSlot]:
        return sorted(self.counted_slots, key=lambda s: s.total, reverse=True)

    def summary(self) -> str:
        return (
            f"{len(self.counted_slots)}/{len(self.slots)} slots valued, "
            f"total {format_gp(self.total)}"
        )


def value_slots(
    slots: list[ValuedSlot], client: GEPriceClient
) -> BankValuation:
    """Attach prices to ``slots`` and roll them up.

    Slots that never resolved to an item keep their existing status; only
    identified-but-unpriced slots are downgraded here.
    """
    item_ids = [s.item_id for s in slots if s.item_id is not None and s.status == "ok"]
    quotes: dict[int, PriceQuote] = client.prices_for(item_ids) if item_ids else {}

    any_stale = False
    for slot in slots:
        if slot.status != "ok" or slot.item_id is None:
            continue
        quote = quotes.get(slot.item_id)
        if quote is None:
            slot.status = "unpriced"
            slot.note = "no GE price available"
            continue
        slot.unit_price = quote.price
        slot.price_stale = quote.stale
        any_stale = any_stale or quote.stale
        if quote.name and not slot.name:
            slot.name = quote.name
        if slot.quantity is None:
            slot.status = "unreadable"
            slot.note = "could not read stack count"

    return BankValuation(slots=slots, prices_stale=any_stale)


def format_gp(value: int) -> str:
    """Format a gp amount the way the game does, to 3 significant figures."""
    negative = value < 0
    amount = abs(value)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if amount >= limit:
            scaled = amount / limit
            text = f"{scaled:.2f}{suffix}" if scaled < 10 else f"{scaled:.1f}{suffix}"
            return ("-" if negative else "") + text
    return ("-" if negative else "") + f"{amount:,}"
