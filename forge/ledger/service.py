from __future__ import annotations

import uuid

from forge.accounts.service import AccountsService
from forge.ledger.db import StrategyTradesRepo, TradesRepo
from forge.ledger.models import MARKET_TYPE, VERIFICATION_STATUS_VERIFIED, Trade
from forge.strategies.db import StrategiesRepo


class LedgerService:
    """Pulls recent fills from a connection's exchange (via AccountsService,
    reusing its credential-decryption + private-client wiring) and stores
    them as normalized Trade rows. Each newly-stored trade is linked to
    whatever strategy is currently ACTIVE for the user, if any - see
    forge/strategies/service.py for activation."""

    def __init__(self, accounts_service: AccountsService, trades_repo: TradesRepo, strategy_trades_repo: StrategyTradesRepo, strategies_repo: StrategiesRepo):
        self._accounts_service = accounts_service
        self._trades_repo = trades_repo
        self._strategy_trades_repo = strategy_trades_repo
        self._strategies_repo = strategies_repo

    async def sync_trades(self, connection_id: str, user_id: str) -> int:
        fills = await self._accounts_service.get_recent_trades(connection_id, user_id)
        active_strategy = await self._strategies_repo.get_active_for_user(user_id)

        new_count = 0
        for fill in fills:
            gross_pnl = fill.realized_pnl
            net_pnl = fill.realized_pnl - fill.fee if fill.realized_pnl is not None else None
            trade = Trade(
                trade_id=str(uuid.uuid4()),
                user_id=user_id,
                exchange=fill.exchange,
                external_id=fill.external_id,
                symbol=fill.symbol,
                market_type=MARKET_TYPE,
                side=fill.side,
                quantity=fill.qty,
                price=fill.price,
                fee=fill.fee,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                funding=None,
                slippage=None,
                order_id=fill.order_id,
                opened_at=fill.timestamp,
                source=fill.exchange,
                verification_status=VERIFICATION_STATUS_VERIFIED,
            )
            inserted = await self._trades_repo.insert_if_new(trade)
            if not inserted:
                continue
            new_count += 1
            if active_strategy is not None:
                await self._strategy_trades_repo.create(
                    trade_id=trade.trade_id,
                    strategy_id=active_strategy.strategy_id,
                    origin=active_strategy.source.value,
                    classification="UNKNOWN",
                )
        return new_count

    async def list_trades(self, user_id: str) -> list[Trade]:
        return await self._trades_repo.list_for_user(user_id)
