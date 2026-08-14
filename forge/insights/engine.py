from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from forge.insights.models import MIN_SAMPLE_SIZE, Insight
from forge.ledger.models import StrategyTrade, Trade


def compute_insights(
    user_id: str, trades: list[Trade], strategy_trades_by_trade_id: dict[str, StrategyTrade]
) -> list[Insight]:
    """Pure computation, no I/O - forge/insights/service.py handles
    loading trades and persisting the result.

    Only two categories are computed, both honestly supportable by what
    forge/ledger actually stores today:
    - performance by strategy origin (needs a strategy_trades link)
    - consistency by UTC hour-of-day (needs only opened_at)

    "Aderência ao plano" and behavior-pattern insights (spec section 2.3
    bullets 2 and 4) are not computed here - they'd need the Adherence
    Engine and Trader DNA engine, neither of which exist yet, and
    fabricating them would violate the spec's own "never invent a
    pattern without enough data" rule (section 2.5).
    """
    now = time.time()
    insights: list[Insight] = []

    by_origin: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        st = strategy_trades_by_trade_id.get(t.trade_id)
        if st is None or t.net_pnl is None:
            continue
        by_origin[st.origin].append(t)

    for origin, group in by_origin.items():
        if len(group) < MIN_SAMPLE_SIZE:
            continue
        wins = sum(1 for t in group if t.net_pnl > 0)
        win_rate = wins / len(group)
        avg_pnl = sum(t.net_pnl for t in group) / len(group)
        insights.append(
            Insight(
                insight_id=str(uuid.uuid4()),
                user_id=user_id,
                category="performance_por_estrategia",
                text=(
                    f"Operando estratégia {origin}, sua taxa de acerto é {win_rate:.0%} "
                    f"em {len(group)} trades, com PnL líquido médio de {avg_pnl:.4f}."
                ),
                evidence={"origin": origin, "win_rate": win_rate, "avg_net_pnl": avg_pnl, "sample_size": len(group)},
                sample_size=len(group),
                generated_at=now,
            )
        )

    by_hour: dict[int, list[Trade]] = defaultdict(list)
    for t in trades:
        if t.net_pnl is None:
            continue
        hour = datetime.fromtimestamp(t.opened_at, tz=timezone.utc).hour
        by_hour[hour].append(t)

    eligible_hours = {h: g for h, g in by_hour.items() if len(g) >= MIN_SAMPLE_SIZE}
    if eligible_hours:
        best_hour = max(eligible_hours, key=lambda h: sum(t.net_pnl for t in eligible_hours[h]) / len(eligible_hours[h]))
        group = eligible_hours[best_hour]
        win_rate = sum(1 for t in group if t.net_pnl > 0) / len(group)
        avg_pnl = sum(t.net_pnl for t in group) / len(group)
        insights.append(
            Insight(
                insight_id=str(uuid.uuid4()),
                user_id=user_id,
                category="consistencia_horario",
                text=(
                    f"Seu melhor horário (UTC) é por volta das {best_hour}h, com taxa de acerto "
                    f"de {win_rate:.0%} em {len(group)} trades nesse horário."
                ),
                evidence={"hour_utc": best_hour, "win_rate": win_rate, "avg_net_pnl": avg_pnl, "sample_size": len(group)},
                sample_size=len(group),
                generated_at=now,
            )
        )

    if not insights:
        insights.append(
            Insight(
                insight_id=str(uuid.uuid4()),
                user_id=user_id,
                category="insufficient_data",
                text=(
                    f"Ainda não há trades suficientes para gerar um insight confiável "
                    f"(mínimo {MIN_SAMPLE_SIZE} por categoria; {len(trades)} trades sincronizados no total)."
                ),
                evidence={"trades_synced": len(trades), "min_sample_size": MIN_SAMPLE_SIZE},
                sample_size=len(trades),
                generated_at=now,
            )
        )

    return insights
