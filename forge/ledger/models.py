from __future__ import annotations

from dataclasses import dataclass

# All four exchange adapters/private clients in this repo are USDT-M
# perpetual futures only - see forge/adapters/. Revisit if spot or other
# market types are ever added.
MARKET_TYPE = "PERPETUAL_FUTURES"

# Pulled directly from the exchange's authenticated API (not user-entered
# or inferred) - "verified" in the blueprint section 62 sense of the word.
VERIFICATION_STATUS_VERIFIED = "VERIFIED"


@dataclass
class Trade:
    """Normalized trade record, blueprint section 9. funding and slippage
    are None in this round - funding needs position-level tracking and
    slippage needs a strategy's expected entry price, neither of which
    exist yet (see forge/strategies and the Adherence Engine, blueprint
    section 20, which isn't built)."""

    trade_id: str
    user_id: str
    exchange: str
    external_id: str
    symbol: str
    market_type: str
    side: str
    quantity: float
    price: float
    fee: float
    gross_pnl: float | None
    net_pnl: float | None
    funding: float | None
    slippage: float | None
    order_id: str
    opened_at: float
    source: str
    verification_status: str


@dataclass
class StrategyTrade:
    """Links a Trade to whichever strategy was ACTIVE for the user at
    sync time. classification is always UNKNOWN in this round - the
    Adherence Engine that would evaluate PASS/FAIL (blueprint section 20)
    isn't built yet."""

    strategy_trade_id: str
    trade_id: str
    strategy_id: str
    origin: str
    classification: str
