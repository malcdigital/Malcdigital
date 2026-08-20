"""Weekly-timeframe confirmation and its effect on scoring."""

import numpy as np
import pandas as pd
import pytest

from quantdesk.analysis.timeframe import AGREES, CONFLICTS, NEUTRAL, confirm, to_weekly
from quantdesk.config import get_profile
from quantdesk.strategy.signals import score_symbol


def ramp(a, b, n=700, seed=1):
    rng = np.random.default_rng(seed)
    base = np.linspace(a, b, n)
    close = base + rng.normal(0, abs(b - a) * 0.01, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.006,
         "low": np.minimum(open_, close) * 0.994, "close": close,
         "volume": np.full(n, 5e7)},
        index=pd.bdate_range(end="2026-01-01", periods=n),
    )


# --- resampling ---------------------------------------------------------------
def test_weekly_resample_produces_real_bars():
    daily = ramp(100, 200)
    weekly = to_weekly(daily)
    assert 4.5 < len(daily) / len(weekly) < 5.5, "roughly five sessions per week"

    week = weekly.iloc[-2]
    span = daily[(daily.index > weekly.index[-3]) & (daily.index <= weekly.index[-2])]
    assert week["open"] == pytest.approx(span["open"].iloc[0])
    assert week["close"] == pytest.approx(span["close"].iloc[-1])
    assert week["high"] == pytest.approx(span["high"].max())
    assert week["low"] == pytest.approx(span["low"].min())
    assert week["volume"] == pytest.approx(span["volume"].sum())


def test_weekly_bars_keep_ohlc_sane():
    weekly = to_weekly(ramp(100, 200))
    assert (weekly["high"] >= weekly["low"]).all()
    assert (weekly["high"] >= weekly[["open", "close"]].max(axis=1)).all()
    assert (weekly["low"] <= weekly[["open", "close"]].min(axis=1)).all()


def test_empty_input_is_handled():
    assert to_weekly(pd.DataFrame()).empty


# --- confirmation -------------------------------------------------------------
@pytest.mark.parametrize("a,b,direction,expected", [
    (100, 200, "long", AGREES),
    (100, 200, "short", CONFLICTS),
    (200, 100, "short", AGREES),
    (200, 100, "long", CONFLICTS),
])
def test_confirmation_verdicts(a, b, direction, expected):
    assert confirm(ramp(a, b), direction).verdict == expected


def test_thin_history_is_neutral_not_a_rejection():
    """Absence of evidence must not read as evidence against.

    Otherwise every recently listed instrument is permanently untradeable.
    """
    check = confirm(ramp(100, 120, n=100), "long")
    assert check.verdict == NEUTRAL
    assert check.score_adjustment == 0.0


def test_score_adjustment_signs():
    assert confirm(ramp(100, 200), "long").score_adjustment == 1.0
    assert confirm(ramp(100, 200), "short").score_adjustment == -1.0


# --- effect on scoring --------------------------------------------------------
def test_conflicting_weekly_trend_vetoes_the_trade():
    """A daily signal against the weekly trend is not merely penalised."""
    profile = get_profile("conservative")   # long-only, so direction is forced
    report = score_symbol("X", ramp(200, 100), profile, multi_timeframe=True)
    assert not report.is_actionable
    assert any("higher timeframe disagrees" in v for v in report.vetoes)


def test_weekly_component_is_recorded_for_the_reader():
    report = score_symbol("X", ramp(100, 220), get_profile("moderate"),
                          ramp(100, 140, seed=9))
    weekly = [c for c in report.components if c.name == "weekly"]
    assert weekly and "Weekly:" in weekly[0].reason


def test_score_equals_the_weighted_mean_of_its_components():
    """Guards the fold-in arithmetic.

    Every component except the weekly one is expressed as a bullish reading and
    flips sign for a short; the weekly one is already relative to the trade's
    direction and must not be flipped again.
    """
    for bars in (ramp(100, 220), ramp(220, 100)):
        report = score_symbol("X", bars, get_profile("moderate"),
                              ramp(100, 140, seed=9))
        total_weight = sum(c.weight for c in report.components)
        weighted = 0.0
        for component in report.components:
            value = (
                component.value
                if component.name == "weekly" or report.direction == "long"
                else -component.value
            )
            weighted += value * component.weight
        assert report.score == pytest.approx(50 + (weighted / total_weight) * 50, abs=0.01)


def test_multi_timeframe_can_be_disabled():
    report = score_symbol("X", ramp(200, 100), get_profile("conservative"),
                          multi_timeframe=False)
    assert report.timeframe is None
    assert not any("higher timeframe" in v for v in report.vetoes)
