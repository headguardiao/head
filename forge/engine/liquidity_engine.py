from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from forge.models import OrderBookSnapshot
from forge.normalizer import notional_usd


@dataclass
class HeatmapBucket:
    price: float
    bid_notional_usd: float
    ask_notional_usd: float


class LiquidityEngine:
    """Aggregates per-exchange order books for one symbol into a single
    price-bucketed liquidity heatmap, expressed in USD notional so
    exchanges with different contract specs stay comparable (PDF
    section 5-6: never sum raw contract quantities across exchanges;
    work in notional and normalized price buckets)."""

    def __init__(self, symbol: str, bucket_pct: float = 0.0005):
        self.symbol = symbol
        self.bucket_pct = bucket_pct
        self._latest: dict[str, OrderBookSnapshot] = {}

    def update(self, snapshot: OrderBookSnapshot) -> None:
        self._latest[snapshot.exchange] = snapshot

    def mid_price(self) -> float | None:
        bids, asks = [], []
        for snap in self._latest.values():
            if snap.bids:
                bids.append(snap.bids[0].price)
            if snap.asks:
                asks.append(snap.asks[0].price)
        if not bids or not asks:
            return None
        return (max(bids) + min(asks)) / 2

    def _bucket_key(self, price: float, mid: float) -> float:
        step = mid * self.bucket_pct
        if step <= 0:
            return price
        return round(price / step) * step

    def heatmap(self) -> list[HeatmapBucket]:
        mid = self.mid_price()
        if mid is None:
            return []
        buckets: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for snap in self._latest.values():
            for level in snap.bids:
                key = self._bucket_key(level.price, mid)
                buckets[key][0] += notional_usd(level.price, level.qty)
            for level in snap.asks:
                key = self._bucket_key(level.price, mid)
                buckets[key][1] += notional_usd(level.price, level.qty)
        return sorted(
            (HeatmapBucket(price=p, bid_notional_usd=v[0], ask_notional_usd=v[1]) for p, v in buckets.items()),
            key=lambda b: b.price,
        )

    def concentration_above(self, mid: float | None = None) -> float:
        mid = mid if mid is not None else self.mid_price()
        if mid is None:
            return 0.0
        return sum(b.ask_notional_usd for b in self.heatmap() if b.price >= mid)

    def concentration_below(self, mid: float | None = None) -> float:
        mid = mid if mid is not None else self.mid_price()
        if mid is None:
            return 0.0
        return sum(b.bid_notional_usd for b in self.heatmap() if b.price < mid)

    def top_walls(self, n: int = 5) -> list[HeatmapBucket]:
        hm = self.heatmap()
        return sorted(hm, key=lambda b: b.bid_notional_usd + b.ask_notional_usd, reverse=True)[:n]

    def orderbook_imbalance(self) -> float:
        """-1 (all sell pressure) to +1 (all buy pressure), based on
        top-10-level notional across every connected exchange."""
        bid_total = 0.0
        ask_total = 0.0
        for snap in self._latest.values():
            bid_total += sum(notional_usd(l.price, l.qty) for l in snap.bids[:10])
            ask_total += sum(notional_usd(l.price, l.qty) for l in snap.asks[:10])
        total = bid_total + ask_total
        if total == 0:
            return 0.0
        return (bid_total - ask_total) / total

    @property
    def connected_exchanges(self) -> list[str]:
        return list(self._latest.keys())
