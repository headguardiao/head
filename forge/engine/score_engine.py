from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from forge.engine.liquidity_engine import HeatmapBucket, LiquidityEngine
from forge.models import FundingRate, Liquidation, OpenInterest, OrderBookSnapshot, Side, Trade


@dataclass
class ScoreBreakdown:
    liquidity_score: float
    bias: str
    concentration_above_usd: float
    concentration_below_usd: float
    orderbook_imbalance: float
    oi_change_pct: float
    funding_rate: float
    liquidation_notional_usd: float
    top_walls: list[HeatmapBucket]
    confidence: float
    connected_exchanges: list[str]


class SymbolMarketState:
    """Rolling state for one symbol across all connected exchanges;
    computes LIQUIDITY_SCORE from the weighted components in PDF
    section 7 (concentration 25%, removal 15%, OI 15%, liquidations
    15%, orderbook imbalance 10%, CVD 10%, funding 5%, cross-exchange
    confirmation 5%)."""

    OI_WINDOW_SECONDS = 15 * 60
    LIQUIDATION_WINDOW_SECONDS = 15 * 60
    CVD_WINDOW_SECONDS = 15 * 60
    HEATMAP_HISTORY_SECONDS = 60

    def __init__(self, symbol: str, min_exchanges_for_full_confidence: int = 4):
        self.symbol = symbol
        self.liquidity_engine = LiquidityEngine(symbol)
        self.min_exchanges = min_exchanges_for_full_confidence
        self._oi_by_exchange: dict[str, float] = {}
        self._oi_history: deque[tuple[float, float]] = deque()
        self._funding_by_exchange: dict[str, float] = {}
        self._liquidations: deque[Liquidation] = deque()
        self._trades: deque[Trade] = deque()
        self._heatmap_history: deque[tuple[float, dict[float, float]]] = deque()

    # ---- ingestion ------------------------------------------------
    def on_orderbook(self, snap: OrderBookSnapshot) -> None:
        self.liquidity_engine.update(snap)
        self._record_heatmap_snapshot()

    def on_trade(self, trade: Trade) -> None:
        self._trades.append(trade)
        self._trim_window(self._trades, self.CVD_WINDOW_SECONDS, key=lambda t: t.timestamp)

    def on_open_interest(self, oi: OpenInterest) -> None:
        self._oi_by_exchange[oi.exchange] = oi.value_usd
        total = sum(self._oi_by_exchange.values())
        self._oi_history.append((time.time(), total))
        self._trim_window(self._oi_history, self.OI_WINDOW_SECONDS, key=lambda x: x[0])

    def on_funding(self, funding: FundingRate) -> None:
        self._funding_by_exchange[funding.exchange] = funding.rate

    def on_liquidation(self, liq: Liquidation) -> None:
        self._liquidations.append(liq)
        self._trim_window(self._liquidations, self.LIQUIDATION_WINDOW_SECONDS, key=lambda l: l.timestamp)

    def _record_heatmap_snapshot(self) -> None:
        now = time.time()
        if self._heatmap_history and now - self._heatmap_history[-1][0] < 5:
            return
        hm = {b.price: b.bid_notional_usd + b.ask_notional_usd for b in self.liquidity_engine.heatmap()}
        self._heatmap_history.append((now, hm))
        while self._heatmap_history and now - self._heatmap_history[0][0] > self.HEATMAP_HISTORY_SECONDS:
            self._heatmap_history.popleft()

    @staticmethod
    def _trim_window(dq: deque, window_seconds: float, key) -> None:
        now = time.time()
        while dq and now - key(dq[0]) > window_seconds:
            dq.popleft()

    # ---- component scores (each normalized to 0-100) ---------------
    def _concentration_score(self) -> tuple[float, float, float]:
        mid = self.liquidity_engine.mid_price()
        above = self.liquidity_engine.concentration_above(mid)
        below = self.liquidity_engine.concentration_below(mid)
        total = above + below
        if total == 0:
            return 0.0, 0.0, 0.0
        skew = abs(above - below) / total
        return skew * 100, above, below

    def _liquidity_removal_score(self) -> float:
        if len(self._heatmap_history) < 2:
            return 0.0
        _, old = self._heatmap_history[0]
        _, new = self._heatmap_history[-1]
        old_total = sum(old.values()) or 1.0
        removed = sum(v for p, v in old.items() if new.get(p, 0.0) < v * 0.5)
        return min(100.0, (removed / old_total) * 100)

    def _oi_score(self) -> tuple[float, float]:
        if len(self._oi_history) < 2:
            return 0.0, 0.0
        _, start_oi = self._oi_history[0]
        _, latest_oi = self._oi_history[-1]
        if start_oi == 0:
            return 0.0, 0.0
        change_pct = (latest_oi - start_oi) / start_oi * 100
        return min(100.0, abs(change_pct) * 5), change_pct

    def _liquidation_score(self) -> tuple[float, float]:
        notional = sum(l.price * l.qty for l in self._liquidations)
        mid = self.liquidity_engine.mid_price() or 1.0
        normalized = notional / (mid * 100)
        return min(100.0, normalized), notional

    def _imbalance_score(self) -> tuple[float, float]:
        imbalance = self.liquidity_engine.orderbook_imbalance()
        return abs(imbalance) * 100, imbalance

    def _cvd_score(self) -> float:
        buy = sum(t.price * t.qty for t in self._trades if t.side == Side.BUY)
        sell = sum(t.price * t.qty for t in self._trades if t.side == Side.SELL)
        total = buy + sell
        if total == 0:
            return 0.0
        return abs(buy - sell) / total * 100

    def _funding_score(self) -> tuple[float, float]:
        if not self._funding_by_exchange:
            return 0.0, 0.0
        avg = sum(self._funding_by_exchange.values()) / len(self._funding_by_exchange)
        # Typical funding rates are in the +/-0.01% to 0.1% range; scale
        # so an extreme (~0.5%) funding rate saturates the component.
        return min(100.0, abs(avg) * 100 * 20), avg

    def _cross_exchange_confirmation_score(self) -> float:
        n = len(self.liquidity_engine.connected_exchanges)
        return min(100.0, (n / self.min_exchanges) * 100)

    # ---- final -------------------------------------------------------
    def compute(self) -> ScoreBreakdown:
        concentration, above, below = self._concentration_score()
        removal = self._liquidity_removal_score()
        oi_score, oi_change_pct = self._oi_score()
        liq_score, liq_notional = self._liquidation_score()
        imbalance_score, imbalance = self._imbalance_score()
        cvd_score = self._cvd_score()
        funding_score, funding_rate = self._funding_score()
        confirmation_score = self._cross_exchange_confirmation_score()

        score = (
            concentration * 0.25
            + removal * 0.15
            + oi_score * 0.15
            + liq_score * 0.15
            + imbalance_score * 0.10
            + cvd_score * 0.10
            + funding_score * 0.05
            + confirmation_score * 0.05
        )

        bias = "NEUTRAL"
        if above > below * 1.15:
            bias = "BEARISH"  # more sell-side liquidity above price = resistance
        elif below > above * 1.15:
            bias = "BULLISH"  # more buy-side liquidity below price = support

        return ScoreBreakdown(
            liquidity_score=round(score, 1),
            bias=bias,
            concentration_above_usd=round(above, 2),
            concentration_below_usd=round(below, 2),
            orderbook_imbalance=round(imbalance, 3),
            oi_change_pct=round(oi_change_pct, 2),
            funding_rate=funding_rate,
            liquidation_notional_usd=round(liq_notional, 2),
            top_walls=self.liquidity_engine.top_walls(),
            confidence=round(confirmation_score, 1),
            connected_exchanges=self.liquidity_engine.connected_exchanges,
        )
