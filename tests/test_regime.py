"""Market regime, sector rotation, and the OBV sign bug they exposed."""

import numpy as np
import pandas as pd
import pytest

from quantdesk.analysis.indicators import compute_all, slope_per_day, slope_pct_per_day
from quantdesk.strategy.regime import (
    BEAR, BULL, assess_regime, rank_sectors,
)


def ramp(a, b, n=340, seed=1, volume=5e7):
    rng = np.random.default_rng(seed)
    base = np.linspace(a, b, n)
    close = base + rng.normal(0, abs(b - a) * 0.012, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.006,
         "low": np.minimum(open_, close) * 0.994, "close": close,
         "volume": np.full(n, volume)},
        index=pd.bdate_range(end="2026-01-01", periods=n),
    )


# --- the OBV sign bug ---------------------------------------------------------
@pytest.mark.parametrize("a,b,expect_positive", [(100, 200, True), (200, 100, False)])
def test_obv_slope_sign_follows_price(a, b, expect_positive):
    """OBV is a signed cumulative total.

    Normalising it by its own level - as the price-oriented slope helper does -
    divides a negative slope by a negative mean and reports distribution as
    accumulation. This is the regression test for that.
    """
    enriched = compute_all(ramp(a, b))
    slope = float(enriched["obv_slope"].iloc[-1])
    assert (slope > 0) is expect_positive, f"obv_slope {slope:+.2f} has the wrong sign"


def test_obv_level_really_does_go_negative():
    """Guards the premise of the test above - otherwise it proves nothing."""
    assert float(compute_all(ramp(200, 100))["obv"].iloc[-1]) < 0


def test_raw_slope_is_not_level_normalised():
    falling = pd.Series(np.linspace(100, -100, 60))
    assert slope_per_day(falling, 20).iloc[-1] < 0
    # The level-normalised version is the one that cannot handle sign changes,
    # which is exactly why OBV must not use it.
    assert slope_per_day(pd.Series(np.linspace(10, 20, 60)), 20).iloc[-1] > 0


# --- regime -------------------------------------------------------------------
def test_rising_market_is_a_bull_regime():
    regime = assess_regime(ramp(300, 460))
    assert regime.state == BULL
    assert regime.long_exposure == 1.0
    assert regime.short_exposure < regime.long_exposure


def test_falling_market_is_a_bear_regime_and_cuts_long_exposure():
    regime = assess_regime(ramp(460, 300))
    assert regime.state == BEAR
    assert regime.long_exposure < 0.5, "longs must be throttled in a bear market"
    assert regime.short_exposure == 1.0


def test_exposure_is_scaled_not_switched():
    """A binary gate whipsaws around the 200-day line; scaling must not zero out."""
    for regime in (assess_regime(ramp(300, 460)), assess_regime(ramp(460, 300))):
        assert 0.0 < regime.long_exposure <= 1.0
        assert 0.0 < regime.short_exposure <= 1.0


def test_regime_explains_itself():
    regime = assess_regime(ramp(300, 460))
    assert regime.reasons
    assert "200-day" in " ".join(regime.reasons)
    assert "%" in regime.summary()


# --- sector rotation ----------------------------------------------------------
def test_sectors_rank_by_relative_strength():
    benchmark = ramp(300, 330, seed=9)
    sectors = {
        "XLK": ramp(100, 170, seed=2),   # strongest
        "XLV": ramp(100, 125, seed=6),
        "XLF": ramp(100, 108, seed=3),
        "XLE": ramp(100, 70, seed=4),    # weakest
    }
    ranking = rank_sectors(sectors, benchmark)
    names = [name for _, name, _ in ranking.ranked]
    assert names[0] == "Technology"
    assert names[-1] == "Energy"
    assert ranking.bias_for("Technology") > ranking.bias_for("Energy")
    assert ranking.bias_for("Technology") == pytest.approx(1.0)
    assert ranking.bias_for("Energy") == pytest.approx(-1.0)


def test_unknown_sector_gets_no_bias():
    ranking = rank_sectors({"XLK": ramp(100, 170)}, ramp(300, 330))
    assert ranking.bias_for("Unknown") == 0.0
    assert ranking.bias_for("ETF") == 0.0


def test_empty_ranking_is_harmless():
    ranking = rank_sectors({}, ramp(300, 330))
    assert ranking.ranked == []
    assert ranking.bias_for("Technology") == 0.0
