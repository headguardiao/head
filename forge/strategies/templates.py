from __future__ import annotations

from forge.strategies.models import StrategySource

# Predefined FinanceX strategies - selection-only, no free text (spec
# section 4.1). Rule sets as documented in the spec handoff; not yet
# encoded as a Strategy DSL (blueprint section 18) since backtest/
# validation of these isn't in scope yet either.
FINANCEX_TEMPLATES: dict[StrategySource, dict[str, str]] = {
    StrategySource.FINANCEX_NORMAL: {
        "name": "FinanceX Normal",
        "description": "SMA21 + SMA8 + Pivot Point SuperTrend + volume",
    },
    StrategySource.FINANCEX_ELITE: {
        "name": "FinanceX Elite",
        "description": "Pullback + volume",
    },
}
