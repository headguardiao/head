from __future__ import annotations

from dataclasses import dataclass, field

# Spec section 2.5 / blueprint section 46: never present a pattern as
# real without enough samples behind it. 15 is the low end of the spec's
# own suggested 15-20 range.
MIN_SAMPLE_SIZE = 15


@dataclass
class Insight:
    insight_id: str
    user_id: str
    category: str
    text: str
    evidence: dict = field(default_factory=dict)
    sample_size: int = 0
    generated_at: float = 0.0
