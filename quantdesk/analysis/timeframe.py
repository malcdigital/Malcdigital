"""Multi-timeframe confirmation.

A daily chart shows a clean breakout roughly as often in a market that is
grinding lower on the weekly as in one that is genuinely advancing. Requiring
the higher timeframe to agree is the cheapest available filter on that: it does
not improve any single signal, it removes a whole class of signals that were
never worth taking.

The cost is real and worth stating plainly - fewer trades, and entries slightly
later, because the weekly bar confirms after the daily one does. That trade is
usually worth making, but it is a trade, not a free improvement.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantdesk.analysis import indicators as ind
from quantdesk.analysis.trend import TrendState, classify

AGREES = "agrees"
CONFLICTS = "conflicts"
NEUTRAL = "neutral"


@dataclass
class TimeframeCheck:
    """Whether the weekly picture supports a daily signal."""

    verdict: str
    weekly_trend: TrendState | None
    weekly_bars: int
    reason: str

    @property
    def confirms(self) -> bool:
        return self.verdict == AGREES

    @property
    def contradicts(self) -> bool:
        return self.verdict == CONFLICTS

    @property
    def score_adjustment(self) -> float:
        """Contribution in -1..1 for the composite score."""
        if self.verdict == AGREES:
            return 1.0
        if self.verdict == CONFLICTS:
            return -1.0
        return 0.0


def to_weekly(bars: pd.DataFrame) -> pd.DataFrame:
    """Resample daily bars into weekly ones ending Friday.

    Open is the week's first open, close its last close, high and low the
    extremes, volume the sum - the only aggregation that yields a real bar.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    weekly = bars.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    )
    return weekly.dropna(subset=["open", "high", "low", "close"])


def confirm(bars: pd.DataFrame, direction: str, min_weeks: int = 60) -> TimeframeCheck:
    """Check whether the weekly trend supports a ``direction`` trade.

    With too little history to classify a weekly trend the verdict is neutral
    rather than a rejection: absence of evidence should not read as evidence
    against, or every recently listed instrument becomes permanently untradeable.
    """
    weekly = to_weekly(bars)
    if len(weekly) < min_weeks:
        return TimeframeCheck(
            NEUTRAL, None, len(weekly),
            f"only {len(weekly)} weekly bars - too little history to confirm",
        )

    try:
        weekly_trend = classify(weekly, ind.compute_all(weekly))
    except Exception:
        return TimeframeCheck(
            NEUTRAL, None, len(weekly), "weekly trend could not be classified"
        )

    if direction == "long":
        if weekly_trend.is_bullish:
            verdict = AGREES
            reason = f"weekly trend is {weekly_trend.label.lower()} - supports a long"
        elif weekly_trend.is_bearish:
            verdict = CONFLICTS
            reason = (
                f"weekly trend is {weekly_trend.label.lower()} - buying against the "
                "higher timeframe"
            )
        else:
            verdict = NEUTRAL
            reason = "weekly trend is sideways - no higher-timeframe support"
    else:
        if weekly_trend.is_bearish:
            verdict = AGREES
            reason = f"weekly trend is {weekly_trend.label.lower()} - supports a short"
        elif weekly_trend.is_bullish:
            verdict = CONFLICTS
            reason = (
                f"weekly trend is {weekly_trend.label.lower()} - shorting against the "
                "higher timeframe"
            )
        else:
            verdict = NEUTRAL
            reason = "weekly trend is sideways - no higher-timeframe support"

    return TimeframeCheck(verdict, weekly_trend, len(weekly), reason)
