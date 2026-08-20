"""Composite signal scoring.

No single indicator is reliable on its own, so the desk scores each candidate
across six independent dimensions and requires broad agreement before calling
something actionable. The components are deliberately weighted rather than
averaged, and every one contributes a written reason, so a recommendation can
always be explained in plain English rather than "the model liked it".

Scores run 0-100 where 50 is neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantdesk.analysis import indicators as ind
from quantdesk.analysis.candles import CandlestickScanner, summarise_patterns
from quantdesk.analysis.trend import TrendState, classify, find_levels, nearest_levels
from quantdesk.config import RiskProfile


@dataclass
class Component:
    name: str
    value: float
    """-1..1"""
    weight: float
    reason: str

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class SignalReport:
    """Everything the desk concluded about one symbol."""

    symbol: str
    price: float
    score: float
    setup: str
    trend: TrendState
    components: list[Component] = field(default_factory=list)
    patterns: dict = field(default_factory=dict)
    news_score: float = 0.0
    news_summary: str = ""
    relative_strength: float = 0.0
    liquidity: float = 0.0
    volatility: float = 0.0
    vetoes: list[str] = field(default_factory=list)
    support: float | None = None
    resistance: float | None = None
    enriched: pd.DataFrame | None = None
    """Indicator frame, kept so downstream consumers need not recompute it."""

    @property
    def is_actionable(self) -> bool:
        return not self.vetoes

    @property
    def reasons(self) -> list[str]:
        ordered = sorted(self.components, key=lambda c: -abs(c.contribution))
        return [c.reason for c in ordered]


def relative_strength(bars: pd.DataFrame, benchmark: pd.DataFrame, window: int = 63) -> float:
    """Excess return versus the benchmark over ``window`` sessions, as a fraction.

    Leaders keep leading more often than laggards mean-revert, so this is a real
    edge - but it is measured over a quarter, not a week, to avoid chasing noise.
    """
    if len(bars) < window + 1 or len(benchmark) < window + 1:
        return 0.0
    aligned = bars["close"].reindex(benchmark.index).ffill().dropna()
    bench = benchmark["close"].reindex(aligned.index).ffill().dropna()
    aligned = aligned.reindex(bench.index).dropna()
    if len(aligned) < window + 1:
        return 0.0
    sym_ret = float(aligned.iloc[-1] / aligned.iloc[-window - 1] - 1.0)
    ben_ret = float(bench.iloc[-1] / bench.iloc[-window - 1] - 1.0)
    return sym_ret - ben_ret


def detect_setup(enriched: pd.DataFrame, trend: TrendState, pattern_summary: dict) -> str:
    """Classify which kind of trade this is, which decides the entry style."""
    last = enriched.iloc[-1]
    close = float(last["close"])

    def f(name: str, default: float = np.nan) -> float:
        v = last.get(name, default)
        return float(v) if pd.notna(v) else float("nan")

    dc_upper = f("dc20_upper")
    ema21 = f("ema21")
    sma50 = f("sma50")
    rsi = f("rsi14")

    near_breakout = np.isfinite(dc_upper) and close >= dc_upper * 0.985

    if trend.is_bullish and near_breakout:
        return "breakout"
    if (
        trend.is_bullish
        and np.isfinite(ema21)
        and np.isfinite(sma50)
        and close < ema21 * 1.02
        and close > sma50
        and (not np.isfinite(rsi) or rsi < 62)
    ):
        return "pullback"
    if pattern_summary.get("bias") == "bullish" and not trend.is_bullish:
        return "reversal"
    if trend.is_bullish:
        return "pullback"
    return "reversal"


def score_symbol(
    symbol: str,
    bars: pd.DataFrame,
    profile: RiskProfile,
    benchmark_bars: pd.DataFrame | None = None,
    news_score: float = 0.0,
    news_coverage: float = 0.0,
    news_summary: str = "",
    asset_type: str = "stock",
) -> SignalReport:
    """Score one candidate across all dimensions and apply hard vetoes."""
    enriched = ind.compute_all(bars)
    trend = classify(bars, enriched)
    last = enriched.iloc[-1]
    close = float(last["close"])

    def f(name: str, default: float = np.nan) -> float:
        v = last.get(name, default)
        return float(v) if pd.notna(v) else float("nan")

    scanner = CandlestickScanner()
    patterns = scanner.scan(bars, lookback=10)
    pattern_summary = summarise_patterns(patterns, latest_index=len(bars) - 1)

    rs = relative_strength(bars, benchmark_bars) if benchmark_bars is not None else 0.0
    volatility = f("volatility20")
    liquidity = f("dollar_volume20")

    components: list[Component] = []

    # 1. Trend (the dominant term - trade with the tide).
    components.append(Component(
        "trend", float(np.clip(trend.score / 100.0, -1, 1)), 0.30,
        f"Trend: {trend.label.lower()} (score {trend.score:+.0f}, ADX {trend.adx:.0f}).",
    ))

    # 2. Candlestick evidence.
    p_score = float(pattern_summary.get("score", 0.0))
    if pattern_summary.get("count"):
        top = pattern_summary["patterns"][0]
        p_reason = (
            f"Candles: {pattern_summary['count']} pattern(s), most recent "
            f"{top.name} ({top.direction}, strength {top.strength:.2f})."
        )
    else:
        p_reason = "Candles: no significant patterns in the last 10 sessions."
    components.append(Component("candles", p_score, 0.15, p_reason))

    # 3. Momentum.
    rsi = f("rsi14")
    macd_hist = f("macd_histogram")
    mom = 0.0
    if np.isfinite(rsi):
        # Reward strength, but fade genuinely overbought readings.
        mom += float(np.clip((rsi - 50.0) / 25.0, -1, 1)) * 0.6
        if rsi > 78:
            mom -= 0.45
    if np.isfinite(macd_hist) and close:
        mom += float(np.clip(macd_hist / (0.012 * close), -1, 1)) * 0.4
    mom = float(np.clip(mom, -1, 1))
    components.append(Component(
        "momentum", mom, 0.15,
        f"Momentum: RSI {rsi:.0f}, MACD histogram {'positive' if macd_hist > 0 else 'negative'}."
        if np.isfinite(rsi) and np.isfinite(macd_hist) else "Momentum: insufficient history.",
    ))

    # 4. News sentiment, scaled by how much coverage actually exists.
    news_component = float(np.clip(news_score, -1, 1)) * min(1.0, max(0.0, news_coverage))
    components.append(Component(
        "news", news_component, 0.15,
        f"News: {news_summary}" if news_summary else "News: no meaningful coverage.",
    ))

    # 5. Relative strength versus the benchmark.
    rs_component = float(np.clip(rs / 0.15, -1, 1))
    components.append(Component(
        "relative_strength", rs_component, 0.15,
        f"Relative strength: {rs * 100:+.1f}% versus the benchmark over ~3 months.",
    ))

    # 6. Volume confirmation via OBV.
    obv_slope = f("obv_slope")
    vol_component = float(np.clip(obv_slope / 0.5, -1, 1)) if np.isfinite(obv_slope) else 0.0
    components.append(Component(
        "volume", vol_component, 0.10,
        f"Volume: OBV trend {'confirms' if vol_component > 0.1 else 'does not confirm'} "
        "the price move.",
    ))

    total_weight = sum(c.weight for c in components)
    raw = sum(c.contribution for c in components) / total_weight
    score = float(np.clip(50.0 + raw * 50.0, 0.0, 100.0))

    setup = detect_setup(enriched, trend, pattern_summary)
    levels = find_levels(bars)
    support, resistance = nearest_levels(levels, close)

    # --- hard vetoes --------------------------------------------------------
    # These are not penalties. A candidate failing any of them is not traded,
    # regardless of how attractive the rest of the picture looks.
    vetoes: list[str] = []
    if asset_type not in profile.allowed_asset_types:
        vetoes.append(f"{asset_type} is outside the {profile.name} mandate")
    if np.isfinite(volatility) and volatility > profile.max_annual_volatility:
        vetoes.append(
            f"annualised volatility {volatility:.0%} exceeds the "
            f"{profile.max_annual_volatility:.0%} ceiling for this risk level"
        )
    if np.isfinite(liquidity) and liquidity < profile.min_avg_dollar_volume:
        vetoes.append(
            f"average dollar volume ${liquidity / 1e6:.1f}M is below the "
            f"${profile.min_avg_dollar_volume / 1e6:.0f}M liquidity floor"
        )
    if trend.is_bearish:
        vetoes.append("the trend is down - the desk does not buy falling markets")
    if trend.is_choppy and setup == "breakout":
        vetoes.append("ADX below 20: breakouts fail in directionless markets")
    if score < profile.min_score:
        vetoes.append(
            f"composite score {score:.0f} is below the {profile.min_score:.0f} "
            f"threshold for {profile.name}"
        )

    return SignalReport(
        symbol=symbol.upper(),
        price=close,
        score=round(score, 2),
        setup=setup,
        trend=trend,
        components=components,
        patterns=pattern_summary,
        news_score=news_score,
        news_summary=news_summary,
        relative_strength=round(rs, 4),
        liquidity=liquidity if np.isfinite(liquidity) else 0.0,
        volatility=volatility if np.isfinite(volatility) else 0.0,
        vetoes=vetoes,
        support=support.price if support else None,
        resistance=resistance.price if resistance else None,
        enriched=enriched,
    )
