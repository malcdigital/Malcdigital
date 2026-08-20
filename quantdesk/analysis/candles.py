"""Candlestick pattern recognition.

Two principles drive this module:

1. **Geometry is measured, not eyeballed.** Every pattern is expressed in terms
   of body size, shadow length and overlap, each normalised by the bar's range
   or by recent ATR, so the same rules work on a $9 stock and a $600 one.

2. **Context decides meaning.** The identical shape is a bullish hammer after a
   decline and a bearish hanging man after a rally. Detectors therefore receive
   the prevailing short-term trend and refuse to fire in the wrong context.

Each detection carries a ``strength`` in 0-1 reflecting how textbook the example
is (body/shadow proportions, gap quality, volume confirmation), so downstream
scoring can weight a picture-perfect engulfing above a marginal one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class Pattern:
    """A single pattern occurrence."""

    name: str
    direction: str
    date: pd.Timestamp
    index: int
    strength: float
    bars: int
    explanation: str

    @property
    def signed_strength(self) -> float:
        if self.direction == BULLISH:
            return self.strength
        if self.direction == BEARISH:
            return -self.strength
        return 0.0


@dataclass
class _BarGeometry:
    """Normalised measurements for one candle."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    atr: float

    @property
    def range(self) -> float:
        return max(self.high - self.low, 1e-9)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def body_pct(self) -> float:
        return self.body / self.range

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    @property
    def upper_shadow(self) -> float:
        return self.high - self.body_top

    @property
    def lower_shadow(self) -> float:
        return self.body_bottom - self.low

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open

    @property
    def midpoint(self) -> float:
        return (self.open + self.close) / 2.0

    @property
    def is_significant(self) -> bool:
        """Is this bar large enough relative to recent volatility to matter?"""
        return self.atr > 0 and self.range >= 0.5 * self.atr


def _geometry(bars: pd.DataFrame, i: int, atr_series: pd.Series) -> _BarGeometry:
    row = bars.iloc[i]
    atr_val = atr_series.iloc[i]
    return _BarGeometry(
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        atr=float(atr_val) if pd.notna(atr_val) else float(row["high"] - row["low"]),
    )


def _build_geometries(
    bars: pd.DataFrame, atr_series: pd.Series, start: int, end: int
) -> dict[int, _BarGeometry]:
    """Measure each bar in the window once.

    Eighteen detectors each looking at up to three bars means the same rows were
    being pulled out of the frame hundreds of times per scan, and a pandas row
    lookup is not cheap. Reading the columns into arrays once and building the
    geometries in a single pass turns that into a handful of operations - which
    matters most in a backtest, where a symbol is re-scanned on every session.
    """
    lo = max(0, start)
    hi = min(len(bars), end)
    if hi <= lo:
        return {}

    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    volumes = bars["volume"].to_numpy(dtype=float)
    atrs = atr_series.to_numpy(dtype=float)

    out: dict[int, _BarGeometry] = {}
    for i in range(lo, hi):
        atr_val = atrs[i]
        out[i] = _BarGeometry(
            open=opens[i], high=highs[i], low=lows[i], close=closes[i],
            volume=volumes[i],
            atr=float(atr_val) if atr_val == atr_val else highs[i] - lows[i],
        )
    return out


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(hi, max(lo, x)))


class CandlestickScanner:
    """Detects candlestick patterns across a bar series."""

    #: Patterns that need a prior downtrend to be read as bullish reversals,
    #: and vice versa. Continuation patterns are exempt.
    def __init__(self, trend_lookback: int = 8, atr_window: int = 14) -> None:
        self.trend_lookback = trend_lookback
        self.atr_window = atr_window

    # -- context -------------------------------------------------------------
    def _trend_context(
        self, bars: pd.DataFrame, atr_series: pd.Series | None = None
    ) -> pd.Series:
        """Short-term drift preceding each bar, in ATR units.

        Positive means the market rallied into this bar, negative means it fell.
        Measured to the *previous* bar so a pattern never uses its own outcome.
        """
        from quantdesk.analysis.indicators import atr as _atr

        close = bars["close"]
        if atr_series is None:
            atr_series = _atr(bars["high"], bars["low"], close, self.atr_window)
        prior_close = close.shift(1)
        drift = prior_close - prior_close.shift(self.trend_lookback)
        return (drift / atr_series.replace(0.0, np.nan)).fillna(0.0)

    def _volume_confirmation(self, bars: pd.DataFrame) -> pd.Series:
        avg = bars["volume"].rolling(20, min_periods=5).mean()
        return (bars["volume"] / avg.replace(0.0, np.nan)).fillna(1.0)

    # -- entry point ---------------------------------------------------------
    def scan(
        self,
        bars: pd.DataFrame,
        lookback: int = 10,
        atr_series: pd.Series | None = None,
    ) -> list[Pattern]:
        """Return patterns completing within the last ``lookback`` bars.

        ``atr_series`` may be supplied by a caller that has already computed it -
        a backtest re-scans the same symbol hundreds of times, and recomputing
        ATR over the full history each time dominates the cost of the scan
        itself. ATR is strictly backward-looking, so a precomputed series sliced
        to the same window is identical to one computed from the slice.
        """
        from quantdesk.analysis.indicators import atr as _atr

        if len(bars) < 30:
            return []

        if atr_series is None:
            atr_series = _atr(bars["high"], bars["low"], bars["close"], self.atr_window)
        trend = self._trend_context(bars, atr_series)
        vol_ratio = self._volume_confirmation(bars)

        detectors: list[Callable[..., Pattern | None]] = [
            self._bullish_engulfing,
            self._bearish_engulfing,
            self._hammer,
            self._hanging_man,
            self._inverted_hammer,
            self._shooting_star,
            self._morning_star,
            self._evening_star,
            self._piercing_line,
            self._dark_cloud_cover,
            self._three_white_soldiers,
            self._three_black_crows,
            self._bullish_harami,
            self._bearish_harami,
            self._doji,
            self._marubozu,
            self._tweezer_bottom,
            self._tweezer_top,
        ]

        start = max(3, len(bars) - lookback)
        # Two bars of headroom: three-bar patterns reach back from `start`.
        geometries = _build_geometries(bars, atr_series, start - 2, len(bars))
        dates = list(bars.index)
        trend_values = trend.to_numpy(dtype=float)
        vol_values = vol_ratio.to_numpy(dtype=float)

        found: list[Pattern] = []
        for i in range(start, len(bars)):
            ctx = float(trend_values[i])
            vol = float(vol_values[i])
            for detect in detectors:
                try:
                    hit = detect(geometries, dates, i, ctx, vol)
                except (IndexError, KeyError, ValueError):
                    continue
                if hit is not None:
                    found.append(hit)
        return found

    # -- single-bar patterns -------------------------------------------------
    def _hammer(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if ctx > -0.6:  # needs a decline into it
            return None
        if c.body_pct > 0.34:
            return None
        if c.lower_shadow < 2.0 * c.body or c.lower_shadow <= 0:
            return None
        if c.upper_shadow > 0.9 * c.body and c.upper_shadow > 0.15 * c.range:
            return None
        if not c.is_significant:
            return None
        strength = _clamp(
            0.40
            + 0.20 * _clamp(c.lower_shadow / c.range - 0.5, 0, 0.5) / 0.5
            + 0.15 * _clamp(-ctx / 3.0)
            + 0.15 * _clamp((vol - 1.0) / 1.5)
            + (0.10 if c.is_bull else 0.0)
        )
        return Pattern(
            "Hammer", BULLISH, dates[i], i, strength, 1,
            f"Long lower shadow ({c.lower_shadow / c.range:.0%} of range) after a "
            f"{abs(ctx):.1f}-ATR decline: sellers pushed price down and were rejected.",
        )

    def _hanging_man(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if ctx < 0.6:  # same shape, but it must follow a rally
            return None
        if c.body_pct > 0.34 or c.lower_shadow < 2.0 * c.body or c.lower_shadow <= 0:
            return None
        if c.upper_shadow > 0.9 * c.body and c.upper_shadow > 0.15 * c.range:
            return None
        if not c.is_significant:
            return None
        strength = _clamp(
            0.35 + 0.20 * _clamp(ctx / 3.0) + 0.15 * _clamp((vol - 1.0) / 1.5)
            + (0.10 if c.is_bear else 0.0)
        )
        return Pattern(
            "Hanging Man", BEARISH, dates[i], i, strength, 1,
            f"Hammer shape after a {ctx:.1f}-ATR advance: selling pressure appearing "
            "inside an uptrend.",
        )

    def _inverted_hammer(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if ctx > -0.6 or c.body_pct > 0.34:
            return None
        if c.upper_shadow < 2.0 * c.body or c.upper_shadow <= 0:
            return None
        if c.lower_shadow > 0.9 * c.body and c.lower_shadow > 0.15 * c.range:
            return None
        if not c.is_significant:
            return None
        strength = _clamp(0.32 + 0.18 * _clamp(-ctx / 3.0) + 0.15 * _clamp((vol - 1.0) / 1.5))
        return Pattern(
            "Inverted Hammer", BULLISH, dates[i], i, strength, 1,
            "Long upper shadow after a decline: buyers probed higher. Needs an "
            "up-close next session to confirm.",
        )

    def _shooting_star(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if ctx < 0.6 or c.body_pct > 0.34:
            return None
        if c.upper_shadow < 2.0 * c.body or c.upper_shadow <= 0:
            return None
        if c.lower_shadow > 0.9 * c.body and c.lower_shadow > 0.15 * c.range:
            return None
        if not c.is_significant:
            return None
        strength = _clamp(
            0.42 + 0.20 * _clamp(ctx / 3.0)
            + 0.18 * _clamp(c.upper_shadow / c.range - 0.5, 0, 0.5) / 0.5
            + 0.12 * _clamp((vol - 1.0) / 1.5)
        )
        return Pattern(
            "Shooting Star", BEARISH, dates[i], i, strength, 1,
            f"Rally to a new high rejected, closing near the low ({c.upper_shadow / c.range:.0%} "
            "upper shadow): buyers lost control intraday.",
        )

    def _doji(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if c.body_pct > 0.08 or not c.is_significant:
            return None
        # A doji only carries information after a directional move.
        if abs(ctx) < 1.0:
            return None
        direction = BEARISH if ctx > 0 else BULLISH
        strength = _clamp(0.22 + 0.15 * _clamp(abs(ctx) / 3.0))
        which = "uptrend" if ctx > 0 else "downtrend"
        return Pattern(
            "Doji", direction, dates[i], i, strength, 1,
            f"Open and close nearly equal after a {which}: the prevailing move has "
            "stalled into indecision.",
        )

    def _marubozu(self, g, dates, i, ctx, vol) -> Pattern | None:
        c = g[i]
        if c.body_pct < 0.92 or not c.is_significant:
            return None
        if c.range < 0.9 * c.atr:
            return None
        direction = BULLISH if c.is_bull else BEARISH
        strength = _clamp(0.30 + 0.20 * _clamp((c.range / max(c.atr, 1e-9)) - 1.0)
                          + 0.15 * _clamp((vol - 1.0) / 1.5))
        side = "buyers" if c.is_bull else "sellers"
        return Pattern(
            "Marubozu", direction, dates[i], i, strength, 1,
            f"Full-bodied bar with almost no shadows: {side} controlled the entire "
            "session open to close.",
        )

    # -- two-bar patterns ----------------------------------------------------
    def _bullish_engulfing(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not (prev.is_bear and cur.is_bull):
            return None
        if not (cur.close > prev.open and cur.open < prev.close):
            return None
        if ctx > -0.4 or not cur.is_significant:
            return None
        engulf_ratio = cur.body / max(prev.body, 1e-9)
        if engulf_ratio < 1.05:
            return None
        strength = _clamp(
            0.45 + 0.20 * _clamp((engulf_ratio - 1.0) / 1.5)
            + 0.20 * _clamp((vol - 1.0) / 1.5) + 0.15 * _clamp(-ctx / 3.0)
        )
        return Pattern(
            "Bullish Engulfing", BULLISH, dates[i], i, strength, 2,
            f"Today's up-bar fully engulfs yesterday's down-bar ({engulf_ratio:.1f}x the "
            f"body) on {vol:.1f}x average volume: demand overwhelmed supply.",
        )

    def _bearish_engulfing(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not (prev.is_bull and cur.is_bear):
            return None
        if not (cur.close < prev.open and cur.open > prev.close):
            return None
        if ctx < 0.4 or not cur.is_significant:
            return None
        engulf_ratio = cur.body / max(prev.body, 1e-9)
        if engulf_ratio < 1.05:
            return None
        strength = _clamp(
            0.45 + 0.20 * _clamp((engulf_ratio - 1.0) / 1.5)
            + 0.20 * _clamp((vol - 1.0) / 1.5) + 0.15 * _clamp(ctx / 3.0)
        )
        return Pattern(
            "Bearish Engulfing", BEARISH, dates[i], i, strength, 2,
            f"Today's down-bar fully engulfs yesterday's up-bar ({engulf_ratio:.1f}x the "
            "body): supply overwhelmed demand at the highs.",
        )

    def _piercing_line(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not (prev.is_bear and cur.is_bull) or ctx > -0.4:
            return None
        if cur.open >= prev.close:  # must gap down below the prior close
            return None
        if not (prev.midpoint < cur.close < prev.open):
            return None
        penetration = (cur.close - prev.close) / max(prev.body, 1e-9)
        strength = _clamp(0.38 + 0.25 * _clamp((penetration - 0.5) / 0.5)
                          + 0.15 * _clamp((vol - 1.0) / 1.5))
        return Pattern(
            "Piercing Line", BULLISH, dates[i], i, strength, 2,
            f"Gapped down then closed {penetration:.0%} back into the prior red body: "
            "the gap was bought.",
        )

    def _dark_cloud_cover(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not (prev.is_bull and cur.is_bear) or ctx < 0.4:
            return None
        if cur.open <= prev.close:  # must gap up above the prior close
            return None
        if not (prev.open < cur.close < prev.midpoint):
            return None
        penetration = (prev.close - cur.close) / max(prev.body, 1e-9)
        strength = _clamp(0.38 + 0.25 * _clamp((penetration - 0.5) / 0.5)
                          + 0.15 * _clamp((vol - 1.0) / 1.5))
        return Pattern(
            "Dark Cloud Cover", BEARISH, dates[i], i, strength, 2,
            f"Gapped up then closed {penetration:.0%} back into the prior green body: "
            "the breakout failed intraday.",
        )

    def _bullish_harami(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not prev.is_bear or ctx > -0.5:
            return None
        if prev.body < 0.8 * prev.atr:  # the mother bar must be a big one
            return None
        if not (cur.body_top < prev.open and cur.body_bottom > prev.close):
            return None
        if cur.body > 0.6 * prev.body:
            return None
        strength = _clamp(0.30 + 0.20 * _clamp(1.0 - cur.body / max(prev.body, 1e-9))
                          + 0.15 * _clamp(-ctx / 3.0))
        return Pattern(
            "Bullish Harami", BULLISH, dates[i], i, strength, 2,
            "A small body sits inside the prior large red body: selling momentum has "
            "contracted sharply.",
        )

    def _bearish_harami(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if not prev.is_bull or ctx < 0.5:
            return None
        if prev.body < 0.8 * prev.atr:
            return None
        if not (cur.body_top < prev.close and cur.body_bottom > prev.open):
            return None
        if cur.body > 0.6 * prev.body:
            return None
        strength = _clamp(0.30 + 0.20 * _clamp(1.0 - cur.body / max(prev.body, 1e-9))
                          + 0.15 * _clamp(ctx / 3.0))
        return Pattern(
            "Bearish Harami", BEARISH, dates[i], i, strength, 2,
            "A small body sits inside the prior large green body: buying momentum has "
            "contracted sharply.",
        )

    def _tweezer_bottom(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if ctx > -0.6 or not (prev.is_bear and cur.is_bull):
            return None
        tolerance = 0.12 * max(cur.atr, 1e-9)
        if abs(cur.low - prev.low) > tolerance:
            return None
        strength = _clamp(0.28 + 0.18 * _clamp(-ctx / 3.0) + 0.12 * _clamp((vol - 1.0) / 1.5))
        return Pattern(
            "Tweezer Bottom", BULLISH, dates[i], i, strength, 2,
            "Two sessions rejected from an identical low: a precise level buyers are "
            "defending.",
        )

    def _tweezer_top(self, g, dates, i, ctx, vol) -> Pattern | None:
        prev, cur = g[i - 1], g[i]
        if ctx < 0.6 or not (prev.is_bull and cur.is_bear):
            return None
        tolerance = 0.12 * max(cur.atr, 1e-9)
        if abs(cur.high - prev.high) > tolerance:
            return None
        strength = _clamp(0.28 + 0.18 * _clamp(ctx / 3.0) + 0.12 * _clamp((vol - 1.0) / 1.5))
        return Pattern(
            "Tweezer Top", BEARISH, dates[i], i, strength, 2,
            "Two sessions rejected from an identical high: a ceiling sellers are "
            "defending.",
        )

    # -- three-bar patterns --------------------------------------------------
    def _morning_star(self, g, dates, i, ctx, vol) -> Pattern | None:
        a, b, c = (g[i - 2], g[i - 1],
                   g[i])
        if not (a.is_bear and c.is_bull) or ctx > -0.5:
            return None
        if a.body < 0.7 * a.atr:
            return None
        if b.body > 0.45 * a.body:  # the star must be a small body
            return None
        if b.body_top >= a.close:  # star gaps below the first body
            return None
        if c.close <= a.midpoint or c.close >= a.open:
            return None
        recovery = (c.close - a.close) / max(a.body, 1e-9)
        strength = _clamp(0.52 + 0.22 * _clamp((recovery - 0.5) / 0.5)
                          + 0.16 * _clamp((vol - 1.0) / 1.5) + 0.10 * _clamp(-ctx / 3.0))
        return Pattern(
            "Morning Star", BULLISH, dates[i], i, strength, 3,
            f"Capitulation bar, an indecisive gap-down star, then a strong up-bar "
            f"recovering {recovery:.0%} of the decline: a three-session bottom.",
        )

    def _evening_star(self, g, dates, i, ctx, vol) -> Pattern | None:
        a, b, c = (g[i - 2], g[i - 1],
                   g[i])
        if not (a.is_bull and c.is_bear) or ctx < 0.5:
            return None
        if a.body < 0.7 * a.atr or b.body > 0.45 * a.body:
            return None
        if b.body_bottom <= a.close:  # star gaps above the first body
            return None
        if c.close >= a.midpoint or c.close <= a.open:
            return None
        giveback = (a.close - c.close) / max(a.body, 1e-9)
        strength = _clamp(0.52 + 0.22 * _clamp((giveback - 0.5) / 0.5)
                          + 0.16 * _clamp((vol - 1.0) / 1.5) + 0.10 * _clamp(ctx / 3.0))
        return Pattern(
            "Evening Star", BEARISH, dates[i], i, strength, 3,
            f"Strong up-bar, an exhausted gap-up star, then a decline giving back "
            f"{giveback:.0%} of the advance: a three-session top.",
        )

    def _three_white_soldiers(self, g, dates, i, ctx, vol) -> Pattern | None:
        g = [g[i - k] for k in (2, 1, 0)]
        if not all(x.is_bull for x in g):
            return None
        if not all(x.body > 0.55 * x.atr for x in g):
            return None
        if not (g[1].close > g[0].close and g[2].close > g[1].close):
            return None
        # Each open should sit inside the previous body: a steady advance, not gaps.
        if not (g[0].body_bottom < g[1].open < g[0].body_top):
            return None
        if not (g[1].body_bottom < g[2].open < g[1].body_top):
            return None
        # Long upper shadows would signal the advance is being sold into.
        if any(x.upper_shadow > 0.35 * x.range for x in g):
            return None
        strength = _clamp(0.55 + 0.20 * _clamp((vol - 1.0) / 1.5)
                          + 0.15 * _clamp(sum(x.body / max(x.atr, 1e-9) for x in g) / 3 - 0.6))
        return Pattern(
            "Three White Soldiers", BULLISH, dates[i], i, strength, 3,
            "Three consecutive strong up-bars, each opening within the prior body and "
            "closing near its high: persistent, orderly accumulation.",
        )

    def _three_black_crows(self, g, dates, i, ctx, vol) -> Pattern | None:
        g = [g[i - k] for k in (2, 1, 0)]
        if not all(x.is_bear for x in g):
            return None
        if not all(x.body > 0.55 * x.atr for x in g):
            return None
        if not (g[1].close < g[0].close and g[2].close < g[1].close):
            return None
        if not (g[0].body_bottom < g[1].open < g[0].body_top):
            return None
        if not (g[1].body_bottom < g[2].open < g[1].body_top):
            return None
        if any(x.lower_shadow > 0.35 * x.range for x in g):
            return None
        strength = _clamp(0.55 + 0.20 * _clamp((vol - 1.0) / 1.5)
                          + 0.15 * _clamp(sum(x.body / max(x.atr, 1e-9) for x in g) / 3 - 0.6))
        return Pattern(
            "Three Black Crows", BEARISH, dates[i], i, strength, 3,
            "Three consecutive strong down-bars closing near their lows: persistent "
            "distribution.",
        )


def summarise_patterns(patterns: list[Pattern], half_life_bars: float = 4.0,
                       latest_index: int | None = None) -> dict:
    """Collapse detections into one bias score in -1..1.

    Recent patterns matter more, so each contribution decays exponentially with
    how many bars ago it completed.
    """
    if not patterns:
        return {"score": 0.0, "bias": NEUTRAL, "patterns": [], "count": 0}

    newest = latest_index if latest_index is not None else max(p.index for p in patterns)
    weighted = 0.0
    total_weight = 0.0
    for p in patterns:
        age = max(0, newest - p.index)
        weight = 0.5 ** (age / half_life_bars)
        weighted += p.signed_strength * weight
        total_weight += weight

    score = weighted / total_weight if total_weight else 0.0
    # Several agreeing patterns should read stronger than a lone one.
    conviction = min(1.0, 0.65 + 0.12 * len(patterns))
    score = _clamp(score * conviction, -1.0, 1.0)

    bias = NEUTRAL
    if score > 0.12:
        bias = BULLISH
    elif score < -0.12:
        bias = BEARISH

    return {
        "score": round(score, 4),
        "bias": bias,
        "count": len(patterns),
        "patterns": sorted(patterns, key=lambda p: (-p.index, -p.strength)),
    }
