"""Market regime and sector rotation.

Individual signals are graded in isolation, which is how a desk ends up fully
invested at a top: every name still looks fine on its own chart while the market
underneath them rolls over. Two portfolio-level filters sit above the per-symbol
scoring:

* **Regime** - what the broad market is doing. Longs are cheap in an uptrend and
  expensive in a downtrend, so exposure is scaled to the market rather than the
  desk being equally aggressive in both.

* **Sector rotation** - money is not spread evenly across sectors. Buying a
  decent name in the weakest sector is fighting a current, so candidates in
  lagging sectors are penalised and leaders are favoured.

Neither filter tries to predict. Both react to what has already happened, which
is the only thing that can actually be measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantdesk.analysis import indicators as ind

BULL = "bull"
CORRECTION = "correction"
BEAR = "bear"

_LABELS = {
    BULL: "Bull market",
    CORRECTION: "Correction / choppy",
    BEAR: "Bear market",
}

#: Sector ETFs ranked against each other for rotation.
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


@dataclass
class MarketRegime:
    """What the broad market is doing, and what that means for exposure."""

    state: str
    label: str
    score: float
    """-100 (deep bear) .. +100 (strong bull)."""

    above_200dma: bool
    above_50dma: bool
    pct_from_high: float
    volatility: float
    long_exposure: float
    """Multiplier applied to long position sizes, 0..1."""

    short_exposure: float
    """Multiplier applied to short position sizes, 0..1."""

    reasons: list[str] = field(default_factory=list)

    @property
    def allows_longs(self) -> bool:
        return self.long_exposure > 0.0

    @property
    def allows_shorts(self) -> bool:
        return self.short_exposure > 0.0

    def summary(self) -> str:
        return (
            f"{self.label} (score {self.score:+.0f}). "
            f"Long exposure {self.long_exposure:.0%}, "
            f"short exposure {self.short_exposure:.0%}."
        )


def assess_regime(benchmark_bars: pd.DataFrame) -> MarketRegime:
    """Classify the market from the benchmark's own price action.

    The 200-day moving average is the single most durable regime line in equity
    markets - not because it predicts anything, but because sustained declines
    almost always happen below it. It is used as the primary gate, with drawdown
    from the high and realised volatility refining the exposure.
    """
    enriched = ind.compute_all(benchmark_bars)
    last = enriched.iloc[-1]
    close = float(last["close"])

    def val(name: str) -> float:
        v = last.get(name, np.nan)
        return float(v) if pd.notna(v) else float("nan")

    sma50, sma200 = val("sma50"), val("sma200")
    above_200 = bool(np.isfinite(sma200) and close > sma200)
    above_50 = bool(np.isfinite(sma50) and close > sma50)

    window = enriched.tail(252)
    high_252 = float(window["high"].max())
    pct_from_high = (close / high_252 - 1.0) * 100.0 if high_252 else 0.0
    volatility = val("volatility20")
    slope200 = float(
        ind.slope_pct_per_day(enriched["close"], 60).iloc[-1]
    ) if len(enriched) > 60 else 0.0

    reasons: list[str] = []
    score = 0.0

    if above_200:
        score += 45
        reasons.append("Benchmark is above its 200-day moving average")
    else:
        score -= 45
        reasons.append("Benchmark is below its 200-day moving average")

    if above_50:
        score += 20
        reasons.append("Benchmark is above its 50-day moving average")
    else:
        score -= 20
        reasons.append("Benchmark is below its 50-day moving average")

    if np.isfinite(slope200):
        score += float(np.clip(slope200 / 0.20, -1, 1)) * 20
        reasons.append(f"60-day trend slope {slope200:+.2f}%/day")

    # Drawdown from the 52-week high: shallow dips are normal, deep ones are not.
    score += float(np.clip(pct_from_high / 12.0, -1, 0)) * 15
    reasons.append(f"{pct_from_high:+.1f}% from the 52-week high")

    if np.isfinite(volatility):
        if volatility > 0.30:
            score -= 10
            reasons.append(f"Elevated volatility ({volatility:.0%} annualised)")
        elif volatility < 0.14:
            reasons.append(f"Calm volatility ({volatility:.0%} annualised)")

    score = float(np.clip(score, -100.0, 100.0))

    if score >= 35:
        state = BULL
    elif score <= -30:
        state = BEAR
    else:
        state = CORRECTION

    # Exposure is scaled, not switched. A binary on/off whipsaws around the line;
    # scaling reduces risk while a regime is deteriorating without forcing an
    # all-or-nothing call on a single day's close.
    if state == BULL:
        long_exposure, short_exposure = 1.0, 0.25
    elif state == CORRECTION:
        long_exposure, short_exposure = 0.55, 0.75
    else:
        long_exposure, short_exposure = 0.20, 1.0

    return MarketRegime(
        state=state,
        label=_LABELS[state],
        score=round(score, 2),
        above_200dma=above_200,
        above_50dma=above_50,
        pct_from_high=round(pct_from_high, 2),
        volatility=round(volatility, 4) if np.isfinite(volatility) else float("nan"),
        long_exposure=long_exposure,
        short_exposure=short_exposure,
        reasons=reasons,
    )


@dataclass
class SectorRanking:
    """Sector ETFs ordered by relative strength against the benchmark."""

    ranked: list[tuple[str, str, float]] = field(default_factory=list)
    """(symbol, sector name, excess return) strongest first."""

    leaders: set[str] = field(default_factory=set)
    laggards: set[str] = field(default_factory=set)

    def position_of(self, sector: str) -> int | None:
        for index, (_, name, _) in enumerate(self.ranked):
            if name == sector:
                return index
        return None

    def bias_for(self, sector: str) -> float:
        """Score adjustment in -1..1 for a candidate in this sector."""
        if not self.ranked or sector in ("ETF", "Unknown", ""):
            return 0.0
        position = self.position_of(sector)
        if position is None:
            return 0.0
        # Linear from +1 (strongest) to -1 (weakest).
        span = max(1, len(self.ranked) - 1)
        return 1.0 - 2.0 * (position / span)

    def describe(self, top: int = 3) -> str:
        if not self.ranked:
            return "sector ranking unavailable"
        best = ", ".join(f"{name} ({rs * 100:+.1f}%)" for _, name, rs in self.ranked[:top])
        worst = self.ranked[-1]
        return f"leading: {best}; lagging: {worst[1]} ({worst[2] * 100:+.1f}%)"


def rank_sectors(
    sector_bars: dict[str, pd.DataFrame],
    benchmark_bars: pd.DataFrame,
    window: int = 63,
    leader_count: int = 3,
) -> SectorRanking:
    """Rank sectors by excess return over the benchmark across ``window`` days."""
    from quantdesk.strategy.signals import relative_strength

    scored: list[tuple[str, str, float]] = []
    for symbol, bars in sector_bars.items():
        name = SECTOR_ETFS.get(symbol.upper())
        if name is None or bars is None or len(bars) < window + 1:
            continue
        try:
            excess = relative_strength(bars, benchmark_bars, window)
        except Exception:
            continue
        scored.append((symbol.upper(), name, round(excess, 4)))

    scored.sort(key=lambda row: -row[2])
    leaders = {name for _, name, _ in scored[:leader_count]}
    laggards = {name for _, name, _ in scored[-leader_count:]} if len(scored) > leader_count else set()
    return SectorRanking(ranked=scored, leaders=leaders, laggards=laggards)
