// Only Binance + OKX are wired up in this test phase, so this is a
// deliberately reduced/provisional score: it uses order-book
// concentration, top-of-book imbalance, recent trade flow and
// cross-exchange confirmation. Open interest, funding and liquidations
// are NOT part of this phase's data collection, so they are not part of
// this score yet - it is not the full weighted LIQUIDITY_SCORE from the
// architecture doc.
const EXPECTED_EXCHANGES = 2;

export function computeProvisionalScore(liquidityEngine, tradeBuffer) {
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

  const imbalance = liquidityEngine.orderbookImbalance();
  const imbalanceScore = Math.abs(imbalance) * 100;

  const flow = tradeBuffer.flowImbalance();
  const flowScore = Math.abs(flow) * 100;

  const confirmationScore = Math.min(100, (connected / EXPECTED_EXCHANGES) * 100);

  const liquidityScore =
    concentrationScore * 0.35 + imbalanceScore * 0.3 + flowScore * 0.2 + confirmationScore * 0.15;

  let bias = 'NEUTRAL';
  if (above > below * 1.15) bias = 'BEARISH'; // more sell-side liquidity above price = resistance
  else if (below > above * 1.15) bias = 'BULLISH'; // more buy-side liquidity below price = support

  return {
    hasEnoughData: true,
    provisional: true,
    liquidityScore: Number(liquidityScore.toFixed(1)),
    bias,
    confidence: Number(confirmationScore.toFixed(1)),
    components: {
      concentrationScore: Number(concentrationScore.toFixed(1)),
      imbalanceScore: Number(imbalanceScore.toFixed(1)),
      tradeFlowScore: Number(flowScore.toFixed(1)),
      confirmationScore: Number(confirmationScore.toFixed(1)),
    },
    concentrationAboveUsd: Number(above.toFixed(2)),
    concentrationBelowUsd: Number(below.toFixed(2)),
    orderbookImbalance: Number(imbalance.toFixed(3)),
    tradeFlowImbalance: Number(flow.toFixed(3)),
    topLiquidityWalls: liquidityEngine.topWalls(),
    connectedExchanges: liquidityEngine.connectedExchanges,
    note: 'Provisional score for the Binance+OKX test phase - does not yet include open interest, funding or liquidations.',
  };
}
