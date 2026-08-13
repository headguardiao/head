from __future__ import annotations

from forge.models import PriceLevel


class LocalOrderBook:
    """Maintains a local bid/ask book from a snapshot plus incremental
    deltas. A delta level with qty == 0 removes that price level. Bids
    are exposed sorted descending, asks ascending.
    """

    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def clear(self) -> None:
        self._bids.clear()
        self._asks.clear()

    def apply_snapshot(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self._bids = {p: q for p, q in bids if q > 0}
        self._asks = {p: q for p, q in asks if q > 0}

    def apply_delta(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        for p, q in bids:
            if q <= 0:
                self._bids.pop(p, None)
            else:
                self._bids[p] = q
        for p, q in asks:
            if q <= 0:
                self._asks.pop(p, None)
            else:
                self._asks[p] = q

    @property
    def is_empty(self) -> bool:
        return not self._bids or not self._asks

    def top_n(self, n: int) -> tuple[list[PriceLevel], list[PriceLevel]]:
        bids = sorted(self._bids.items(), key=lambda x: -x[0])[:n]
        asks = sorted(self._asks.items(), key=lambda x: x[0])[:n]
        return (
            [PriceLevel(p, q) for p, q in bids],
            [PriceLevel(p, q) for p, q in asks],
        )

    def best_bid(self) -> float | None:
        return max(self._bids) if self._bids else None

    def best_ask(self) -> float | None:
        return min(self._asks) if self._asks else None
