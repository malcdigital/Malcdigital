"""Trend classification and price structure.

"Is this thing trending?" is answered from four independent angles, because any
one of them alone is easy to fool:

* **Moving-average stack** - are price, the 20, 50 and 200 lined up in order?
* **ADX** - is there directional strength, or is it drifting sideways?
* **Regression slope** - which way is the 20-day best-fit line pointing?
* **Swing structure** - higher highs and higher lows, or lower ones?

Agreement across all four is a real trend. Disagreement is chop, and chop is
where breakout strategies bleed money.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantdesk.analysis import indicators as ind

STRONG_UPTREND = "strong_uptrend"
UPTREND = "uptrend"
SIDEWAYS = "sideways"
DOWNTREND = "downtrend"
STRONG_DOWNTREND = "strong_downtrend"

_LABELS = {
    STRONG_UPTREND: "Strong uptrend",
    UPTREND: "Uptrend",
    SIDEWAYS: "Sideways / range-bound",
    DOWNTREND: "Downtrend",
    STRONG_DOWNTREND: "Strong downtrend",
}


@dataclass
class SwingPoint:
    date: pd.Timestamp
    price: float
    kind: str  # "high" | "low"
    index: int


@dataclass
class Level:
    """A horizontal price level that has repeatedly mattered."""

    price: float
    kind: str  # "support" | "resistance"
    touches: int
    last_touch: pd.Timestamp

    def distance_pct(self, price: float) -> float:
        return (self.price - price) / price * 100.0


@dataclass
class TrendState:
    regime: str
    label: str
    score: float
    """-100 (max bearish) .. +100 (max bullish)."""

    adx: float
    slope20: float
    above_sma50: bool
    above_sma200: bool
    ma_stack_bullish: bool
    structure: str
    """higher_highs | lower_lows | mixed"""

    pct_from_52w_high: float
    pct_from_52w_low: float
    volatility: float
    atr_pct: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_bullish(self) -> bool:
        return self.regime in (UPTREND, STRONG_UPTREND)

    @property
    def is_bearish(self) -> bool:
        return self.regime in (DOWNTREND, STRONG_DOWNTREND)

    @property
    def is_choppy(self) -> bool:
        """True when there is no real directional strength behind the move.

        A random walk still prints local "trends"; ADX below 20 is the standard
        warning that the move has no persistence behind it. Breakout entries
        taken in this state are the classic way to bleed capital, so the trade
        engine treats it as a veto rather than a mild penalty.
        """
        import math

        return not math.isfinite(self.adx) or self.adx < 20.0


def find_swings(bars: pd.DataFrame, order: int = 5) -> list[SwingPoint]:
    """Locate pivot highs/lows: bars whose extreme beats ``order`` neighbours."""
    highs, lows = bars["high"].to_numpy(), bars["low"].to_numpy()
    n = len(bars)
    swings: list[SwingPoint] = []
    for i in range(order, n - order):
        window = slice(i - order, i + order + 1)
        if highs[i] == highs[window].max() and (highs[window] == highs[i]).sum() == 1:
            swings.append(SwingPoint(bars.index[i], float(highs[i]), "high", i))
        elif lows[i] == lows[window].min() and (lows[window] == lows[i]).sum() == 1:
            swings.append(SwingPoint(bars.index[i], float(lows[i]), "low", i))
    return swings


def find_levels(
    bars: pd.DataFrame, order: int = 5, tolerance_pct: float = 1.2, max_levels: int = 6
) -> list[Level]:
    """Cluster nearby swing points into support/resistance levels.

    A level touched three times is far more meaningful than one touched once, so
    the touch count is preserved for downstream weighting.
    """
    swings = find_swings(bars, order)
    if not swings:
        return []

    current = float(bars["close"].iloc[-1])
    clusters: list[dict] = []
    for sp in sorted(swings, key=lambda s: s.price):
        placed = False
        for cluster in clusters:
            if abs(sp.price - cluster["price"]) / cluster["price"] * 100 <= tolerance_pct:
                total = cluster["touches"]
                cluster["price"] = (cluster["price"] * total + sp.price) / (total + 1)
                cluster["touches"] = total + 1
                cluster["last"] = max(cluster["last"], sp.date)
                placed = True
                break
        if not placed:
            clusters.append({"price": sp.price, "touches": 1, "last": sp.date})

    levels = [
        Level(
            price=round(c["price"], 4),
            kind="resistance" if c["price"] > current else "support",
            touches=c["touches"],
            last_touch=c["last"],
        )
        for c in clusters
    ]
    # Prefer levels that are well-tested and close to where price actually is.
    levels.sort(
        key=lambda lv: (-lv.touches, abs(lv.price - current) / current)
    )
    return levels[:max_levels]


def nearest_levels(levels: list[Level], price: float) -> tuple[Level | None, Level | None]:
    """The closest support below and resistance above the given price."""
    below = [lv for lv in levels if lv.price < price]
    above = [lv for lv in levels if lv.price > price]
    support = max(below, key=lambda lv: lv.price) if below else None
    resistance = min(above, key=lambda lv: lv.price) if above else None
    return support, resistance


def _structure(bars: pd.DataFrame, order: int = 5) -> str:
    swings = find_swings(bars.tail(140), order)
    highs = [s.price for s in swings if s.kind == "high"][-3:]
    lows = [s.price for s in swings if s.kind == "low"][-3:]
    if len(highs) >= 2 and len(lows) >= 2:
        rising = highs[-1] > highs[-2] and lows[-1] > lows[-2]
        falling = highs[-1] < highs[-2] and lows[-1] < lows[-2]
        if rising:
            return "higher_highs"
        if falling:
            return "lower_lows"
    return "mixed"


def classify(bars: pd.DataFrame, enriched: pd.DataFrame | None = None) -> TrendState:
    """Produce a full trend read for the most recent bar."""
    df = enriched if enriched is not None else ind.compute_all(bars)
    last = df.iloc[-1]
    close = float(last["close"])

    def val(name: str, default: float = np.nan) -> float:
        v = last.get(name, default)
        return float(v) if pd.notna(v) else float("nan")

    sma20, sma50, sma200 = val("sma20"), val("sma50"), val("sma200")
    adx_val = val("adx_adx")
    plus_di, minus_di = val("adx_plus_di"), val("adx_minus_di")
    slope20 = val("slope20")
    macd_hist = val("macd_histogram")
    rsi14 = val("rsi14")

    above_50 = bool(np.isfinite(sma50) and close > sma50)
    above_200 = bool(np.isfinite(sma200) and close > sma200)
    stack_bull = bool(
        np.isfinite(sma20) and np.isfinite(sma50) and np.isfinite(sma200)
        and close > sma20 > sma50 > sma200
    )
    stack_bear = bool(
        np.isfinite(sma20) and np.isfinite(sma50) and np.isfinite(sma200)
        and close < sma20 < sma50 < sma200
    )
    structure = _structure(bars)

    # --- weighted vote, each component in -1..1 -----------------------------
    votes: list[tuple[float, float, str]] = []  # (value, weight, reason)

    ma_vote = 0.0
    if stack_bull:
        ma_vote, ma_reason = 1.0, "Price > 20 > 50 > 200-day MA: textbook bullish stack"
    elif stack_bear:
        ma_vote, ma_reason = -1.0, "Price < 20 < 50 < 200-day MA: textbook bearish stack"
    else:
        ma_vote = (0.5 if above_50 else -0.5) + (0.5 if above_200 else -0.5)
        ma_reason = (
            f"Price is {'above' if above_50 else 'below'} the 50-day and "
            f"{'above' if above_200 else 'below'} the 200-day MA"
        )
    votes.append((ma_vote, 0.30, ma_reason))

    if np.isfinite(adx_val):
        directional = 1.0 if plus_di > minus_di else -1.0
        strength = min(1.0, max(0.0, (adx_val - 15.0) / 25.0))
        votes.append((
            directional * strength, 0.25,
            f"ADX {adx_val:.0f} ({'trending' if adx_val >= 25 else 'weak/rangebound'}) "
            f"with {'+DI' if plus_di > minus_di else '-DI'} dominant",
        ))

    if np.isfinite(slope20):
        votes.append((
            float(np.clip(slope20 / 0.35, -1, 1)), 0.20,
            f"20-day regression slope {slope20:+.2f}%/day",
        ))

    struct_vote = {"higher_highs": 1.0, "lower_lows": -1.0, "mixed": 0.0}[structure]
    votes.append((
        struct_vote, 0.15,
        {
            "higher_highs": "Swing structure printing higher highs and higher lows",
            "lower_lows": "Swing structure printing lower highs and lower lows",
            "mixed": "Swing structure is mixed - no clean sequence of highs/lows",
        }[structure],
    ))

    if np.isfinite(macd_hist) and np.isfinite(close):
        votes.append((
            float(np.clip(macd_hist / (0.01 * close), -1, 1)), 0.10,
            f"MACD histogram {'positive' if macd_hist > 0 else 'negative'}",
        ))

    total_weight = sum(w for _, w, _ in votes)
    raw = sum(v * w for v, w, _ in votes) / total_weight if total_weight else 0.0
    score = float(np.clip(raw * 100.0, -100.0, 100.0))

    if score >= 55:
        regime = STRONG_UPTREND
    elif score >= 20:
        regime = UPTREND
    elif score <= -55:
        regime = STRONG_DOWNTREND
    elif score <= -20:
        regime = DOWNTREND
    else:
        regime = SIDEWAYS

    window = df.tail(252)
    high_52w = float(window["high"].max())
    low_52w = float(window["low"].min())

    reasons = [r for _, _, r in votes]
    if np.isfinite(rsi14):
        if rsi14 >= 70:
            reasons.append(f"RSI {rsi14:.0f} - extended, prone to a pullback")
        elif rsi14 <= 30:
            reasons.append(f"RSI {rsi14:.0f} - washed out, prone to a bounce")

    return TrendState(
        regime=regime,
        label=_LABELS[regime],
        score=round(score, 2),
        adx=round(adx_val, 2) if np.isfinite(adx_val) else float("nan"),
        slope20=round(slope20, 4) if np.isfinite(slope20) else float("nan"),
        above_sma50=above_50,
        above_sma200=above_200,
        ma_stack_bullish=stack_bull,
        structure=structure,
        pct_from_52w_high=round((close / high_52w - 1.0) * 100.0, 2) if high_52w else 0.0,
        pct_from_52w_low=round((close / low_52w - 1.0) * 100.0, 2) if low_52w else 0.0,
        volatility=round(val("volatility20"), 4) if np.isfinite(val("volatility20")) else float("nan"),
        atr_pct=round(val("atr_pct"), 3) if np.isfinite(val("atr_pct")) else float("nan"),
        reasons=reasons,
    )
