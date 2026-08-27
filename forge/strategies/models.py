from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StrategySource(str, Enum):
    OWN = "OWN"
    FINANCEX_NORMAL = "FINANCEX_NORMAL"
    FINANCEX_ELITE = "FINANCEX_ELITE"


class StrategyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass
class Strategy:
    strategy_id: str
    user_id: str
    source: StrategySource
    name: str
    description: str
    status: StrategyStatus
    created_at: float
    activated_at: float | None
