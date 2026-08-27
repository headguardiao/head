// Full weighted LIQUIDITY_SCORE from the architecture doc (PDF section 7):
// concentration 25%, liquidity removal 15%, open interest 15%,
// liquidations 15%, order-book imbalance 10%, CVD 10%, funding 5%,
// cross-exchange confirmation 5%. Mirrors forge/engine/score_engine.py
// (the Python prototype) so both implementations compute the same thing
// from equivalent inputs.
const MIN_EXCHANGES_FOR_FULL_CONFIDENCE = 3;

export function computeScore(state) {
  const { liquidityEngine, tradeBuffer } = state;
  const mid = liquidityEngine.midPrice();
  const connected = liquidityEngine.connectedExchanges.length;

  if (mid === null || connected === 0) {
    return {
      hasEnoughData: false,
      reason: 'no order book data received yet for this symbol',
    };
  }

  const { above, below } = liquidityEngine.concentrationAboveBelow(mid);
  const total = above + below;
  const concentrationScore = total === 0 ? 0 : (Math.abs(above - below) / total) * 100;

  const removalScore = computeRemovalScore(state.heatmapHistory);
  const { oiScore, oiChangePct } = computeOiScore(state.oiHistory);
  const { liquidationScore, liquidationNotionalUsd } = computeLiquidationScore(state.liquidations, mid);

  const imbalance = liquidityEngine.orderbookImbalance();
  const imbalanceScore = Math.abs(imbalance) * 100;

  // tradeBuffer.flowImbalance() is already a windowed (buy-sell)/total
  // over recent trades - exactly what the architecture doc calls CVD.
  const cvd = tradeBuffer.flowImbalance();
  const cvdScore = Math.abs(cvd) * 100;

  const { fundingScore, fundingRate } = computeFundingScore(state.fundingByExchange);
  const confirmationScore = Math.min(100, (connected / MIN_EXCHANGES_FOR_FULL_CONFIDENCE) * 100);

  const liquidityScore =
    concentrationScore * 0.25 +
    removalScore * 0.15 +
    oiScore * 0.15 +
    liquidationScore * 0.15 +
    imbalanceScore * 0.1 +
    cvdScore * 0.1 +
    fundingScore * 0.05 +
    confirmationScore * 0.05;

  let bias = 'NEUTRAL';
  if (above > below * 1.15) bias = 'BEARISH'; // more sell-side liquidity above price = resistance
  else if (below > above * 1.15) bias = 'BULLISH'; // more buy-side liquidity below price = support

  return {
    hasEnoughData: true,
    liquidityScore: Number(liquidityScore.toFixed(1)),
    bias,
    confidence: Number(confirmationScore.toFixed(1)),
    components: {
      concentrationScore: round1(concentrationScore),
      removalScore: round1(removalScore),
      oiScore: round1(oiScore),
      liquidationScore: round1(liquidationScore),
      imbalanceScore: round1(imbalanceScore),
      cvdScore: round1(cvdScore),
      fundingScore: round1(fundingScore),
      confirmationScore: round1(confirmationScore),
    },
    concentrationAboveUsd: Number(above.toFixed(2)),
    concentrationBelowUsd: Number(below.toFixed(2)),
    orderbookImbalance: Number(imbalance.toFixed(3)),
    cvd: Number(cvd.toFixed(3)),
    oiChangePct: Number(oiChangePct.toFixed(2)),
    fundingRate,
    liquidationNotionalUsd: Number(liquidationNotionalUsd.toFixed(2)),
    topLiquidityWalls: liquidityEngine.topWalls(),
    connectedExchanges: liquidityEngine.connectedExchanges,
  };
}

/** Fraction of the oldest 60s-window heatmap bucket total that has since
 * dropped by more than half - "liquidity pulled from the book". */
function computeRemovalScore(heatmapHistory) {
  if (heatmapHistory.length < 2) return 0;
  const oldTotals = heatmapHistory[0].totals;
  const newTotals = heatmapHistory[heatmapHistory.length - 1].totals;
  let oldTotal = 0;
  for (const v of oldTotals.values()) oldTotal += v;
  if (oldTotal === 0) return 0;
  let removed = 0;
  for (const [price, v] of oldTotals) {
    if ((newTotals.get(price) ?? 0) < v * 0.5) removed += v;
  }
  return Math.min(100, (removed / oldTotal) * 100);
}

/** % change in total open interest across exchanges over the 15-minute
 * window, scaled so a 20% move saturates the component. */
function computeOiScore(oiHistory) {
  if (oiHistory.length < 2) return { oiScore: 0, oiChangePct: 0 };
  const start = oiHistory[0].totalUsd;
  const latest = oiHistory[oiHistory.length - 1].totalUsd;
  if (start === 0) return { oiScore: 0, oiChangePct: 0 };
  const changePct = ((latest - start) / start) * 100;
  return { oiScore: Math.min(100, Math.abs(changePct) * 5), oiChangePct: changePct };
}

/** Liquidation notional over the 15-minute window, normalized against mid
 * price so it's comparable across symbols of very different price scale. */
function computeLiquidationScore(liquidations, mid) {
  const notional = liquidations.reduce((sum, l) => sum + l.notionalUsd, 0);
  const normalized = notional / ((mid || 1) * 100);
  return { liquidationScore: Math.min(100, normalized), liquidationNotionalUsd: notional };
}

/** Average funding rate across exchanges, scaled so an extreme (~0.5%)
 * rate saturates the component. */
function computeFundingScore(fundingByExchange) {
  if (fundingByExchange.size === 0) return { fundingScore: 0, fundingRate: 0 };
  const rates = [...fundingByExchange.values()];
  const avg = rates.reduce((sum, r) => sum + r, 0) / rates.length;
  return { fundingScore: Math.min(100, Math.abs(avg) * 100 * 20), fundingRate: avg };
}

function round1(n) {
  return Number(n.toFixed(1));
}
