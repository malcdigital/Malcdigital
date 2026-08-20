"""Risk sizing, trade-plan invariants, trend classification and scoring."""

import numpy as np
import pandas as pd
import pytest

from quantdesk.analysis import indicators as ind
from quantdesk.analysis.trend import (
    STRONG_DOWNTREND, STRONG_UPTREND, classify, find_levels, nearest_levels,
)
from quantdesk.config import get_profile
from quantdesk.data.synthetic import SyntheticProvider
from quantdesk.strategy.risk import build_trade_plan
from quantdesk.strategy.signals import score_symbol


def ramp(direction, n=320, noise=0.6, seed=7):
    rng = np.random.default_rng(seed)
    base = np.linspace(100, 220, n) if direction == "up" else np.linspace(220, 100, n)
    close = base + rng.normal(0, noise, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + 0.7,
         "low": np.minimum(open_, close) - 0.7, "close": close,
         "volume": np.full(n, 1e6)},
        index=pd.bdate_range(end="2026-01-01", periods=n),
    )


# --- position sizing --------------------------------------------------------
def test_risk_budget_binds_when_the_stop_is_close():
    profile = get_profile("moderate")
    shares, note = profile.size_position(100_000, 50.0, 46.0)
    assert shares == 187  # 0.75% of 100k = $750 risk / $4 per share
    assert "risk budget" in note


def test_exposure_cap_binds_when_the_stop_is_tight():
    profile = get_profile("moderate")
    shares, note = profile.size_position(100_000, 500.0, 495.0)
    assert shares * 500.0 <= 100_000 * profile.max_position_pct
    assert "position-size cap" in note


def test_sizing_refuses_a_stop_above_entry():
    shares, note = get_profile("moderate").size_position(100_000, 50.0, 55.0)
    assert shares == 0
    assert "stop must sit below entry" in note


def test_riskier_profiles_take_larger_positions():
    sizes = [
        get_profile(name).size_position(100_000, 50.0, 46.0)[0]
        for name in ("conservative", "moderate", "aggressive")
    ]
    assert sizes == sorted(sizes)


# --- trend ------------------------------------------------------------------
def test_persistent_advance_is_a_strong_uptrend():
    state = classify(ramp("up"))
    assert state.regime == STRONG_UPTREND
    assert state.is_bullish and not state.is_choppy


def test_persistent_decline_is_a_strong_downtrend():
    state = classify(ramp("down"))
    assert state.regime == STRONG_DOWNTREND
    assert state.is_bearish


def test_trend_classifier_has_no_directional_bias_on_random_data():
    """A driftless series must not systematically read as bullish or bearish."""
    scores = []
    for seed in range(60):
        rng = np.random.default_rng(1000 + seed)
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.011, 320)))
        open_ = np.concatenate([[close[0]], close[:-1]])
        frame = pd.DataFrame(
            {"open": open_, "high": np.maximum(open_, close) + 0.7,
             "low": np.minimum(open_, close) - 0.7, "close": close,
             "volume": np.full(len(close), 1e6)},
            index=pd.bdate_range(end="2026-01-01", periods=len(close)),
        )
        scores.append(classify(frame).score)
    mean = float(np.mean(scores))
    standard_error = float(np.std(scores) / np.sqrt(len(scores)))
    assert abs(mean) < 3 * standard_error + 5, f"biased: mean score {mean:+.1f}"


def test_levels_are_ordered_around_the_current_price():
    bars = SyntheticProvider().history("NVDA", 400)
    price = float(bars["close"].iloc[-1])
    support, resistance = nearest_levels(find_levels(bars), price)
    if support:
        assert support.price < price
    if resistance:
        assert resistance.price > price


# --- trade plans ------------------------------------------------------------
@pytest.mark.parametrize("setup", ["breakout", "pullback", "reversal"])
def test_trade_plan_invariants_hold(setup):
    bars = SyntheticProvider().history("MSFT", 400)
    enriched = ind.compute_all(bars)
    state = classify(bars, enriched)
    support, resistance = nearest_levels(find_levels(bars), float(bars["close"].iloc[-1]))

    plan = build_trade_plan(
        "MSFT", bars, enriched, state, get_profile("moderate"), 100_000, setup,
        support.price if support else None, resistance.price if resistance else None,
    )

    assert plan.stop_price < plan.entry_price, "stop must sit below entry"
    assert all(t.price > plan.entry_price for t in plan.targets), "targets above entry"
    assert plan.per_share_risk > 0
    assert plan.reward_risk > 1.0, "never plan a trade risking more than it can make"
    assert plan.position_value <= 100_000 * get_profile("moderate").max_position_pct + 1
    assert len(plan.instructions()) >= 5


def test_risk_dollars_respects_the_profile_budget():
    bars = SyntheticProvider().history("MSFT", 400)
    enriched = ind.compute_all(bars)
    profile = get_profile("conservative")
    plan = build_trade_plan("MSFT", bars, enriched, classify(bars, enriched),
                            profile, 100_000, "breakout")
    assert plan.risk_dollars <= 100_000 * profile.risk_per_trade_pct * 1.01


def test_instructions_name_entry_stop_and_target():
    bars = SyntheticProvider().history("AAPL", 400)
    enriched = ind.compute_all(bars)
    plan = build_trade_plan("AAPL", bars, enriched, classify(bars, enriched),
                            get_profile("moderate"), 100_000, "breakout")
    text = " ".join(plan.instructions()).upper()
    for word in ("ENTRY", "STOP LOSS", "TARGET", "TRAIL", "TIME STOP"):
        assert word in text


# --- scoring ----------------------------------------------------------------
def test_downtrends_are_vetoed():
    report = score_symbol("TEST", ramp("down"), get_profile("moderate"))
    assert not report.is_actionable
    assert any("trend is down" in v for v in report.vetoes)


def test_score_stays_in_range():
    for direction in ("up", "down"):
        report = score_symbol("TEST", ramp(direction), get_profile("moderate"))
        assert 0.0 <= report.score <= 100.0


def test_volatility_ceiling_vetoes_wild_instruments():
    rng = np.random.default_rng(5)
    close = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.09, 320)))  # ~140% annualised
    open_ = np.concatenate([[close[0]], close[:-1]])
    frame = pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.02,
         "low": np.minimum(open_, close) * 0.98, "close": close,
         "volume": np.full(len(close), 1e7)},
        index=pd.bdate_range(end="2026-01-01", periods=len(close)),
    )
    report = score_symbol("WILD", frame, get_profile("conservative"))
    assert any("volatility" in v for v in report.vetoes)
