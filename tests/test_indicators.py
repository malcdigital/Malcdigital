"""Indicators are checked against values that can be derived by hand."""

import numpy as np
import pandas as pd
import pytest

from quantdesk.analysis.indicators import (
    atr, max_drawdown, rsi, sma, slope_pct_per_day, adx, bollinger, compute_all,
)


def test_rsi_is_100_when_every_bar_gains():
    assert rsi(pd.Series(np.arange(1, 60, dtype=float))).iloc[-1] == pytest.approx(100.0)


def test_rsi_is_0_when_every_bar_loses():
    assert rsi(pd.Series(np.arange(60, 1, -1, dtype=float))).iloc[-1] == pytest.approx(0.0)


def test_rsi_midrange_for_alternating_moves():
    values = pd.Series([100 + (1 if i % 2 else -1) for i in range(80)], dtype=float)
    assert 30 < rsi(values).iloc[-1] < 70


def test_sma_matches_hand_calculation():
    assert sma(pd.Series([1, 2, 3, 4, 5], dtype=float), 3).iloc[-1] == pytest.approx(4.0)


def test_atr_of_constant_range_equals_that_range():
    n = 40
    high = pd.Series([12.0] * n)
    low = pd.Series([10.0] * n)
    close = pd.Series([11.0] * n)
    assert atr(high, low, close).iloc[-1] == pytest.approx(2.0)


def test_max_drawdown_is_peak_to_trough():
    assert max_drawdown(pd.Series([100.0, 120.0, 60.0, 80.0])) == pytest.approx(-0.5)


def test_adx_is_strong_and_positive_in_a_clean_uptrend():
    base = np.linspace(100, 200, 120)
    frame = adx(pd.Series(base + 1), pd.Series(base - 1), pd.Series(base))
    assert frame["adx"].iloc[-1] > 40
    assert frame["plus_di"].iloc[-1] > frame["minus_di"].iloc[-1]


def test_bollinger_bands_straddle_the_middle():
    close = pd.Series(np.random.default_rng(0).normal(100, 2, 100))
    bands = bollinger(close)
    last = bands.iloc[-1]
    assert last["lower"] < last["middle"] < last["upper"]


@pytest.mark.parametrize("series_name,series", [
    ("random_walk", pd.Series(
        100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 400))))),
    ("linear", pd.Series(np.linspace(50, 150, 300))),
])
def test_vectorised_slope_matches_rolling_polyfit(series_name, series):
    """The closed-form slope must equal the polyfit it replaced."""

    def reference(s, window=20):
        def fit(v):
            if np.isnan(v).any():
                return np.nan
            slope = np.polyfit(np.arange(len(v), dtype=float), v, 1)[0]
            mean = v.mean()
            return float(slope / mean * 100.0) if mean else np.nan

        return s.rolling(window, min_periods=window).apply(fit, raw=True)

    fast, slow = slope_pct_per_day(series, 20), reference(series, 20)
    assert (fast.isna() == slow.isna()).all()
    np.testing.assert_allclose(
        fast.dropna().to_numpy(), slow.dropna().to_numpy(), rtol=1e-9, atol=1e-9
    )


def test_slope_sign_follows_direction():
    assert slope_pct_per_day(pd.Series(np.linspace(10, 20, 60)), 20).iloc[-1] > 0
    assert slope_pct_per_day(pd.Series(np.linspace(20, 10, 60)), 20).iloc[-1] < 0


def test_compute_all_adds_expected_columns(bar_frame):
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 1, 300))
    rows = [(c, c + 1, c - 1, c, 1e6) for c in close]
    enriched = compute_all(bar_frame(rows))
    for column in ("sma50", "rsi14", "atr14", "macd_histogram", "adx_adx", "bb_upper"):
        assert column in enriched.columns
    assert not np.isnan(enriched["rsi14"].iloc[-1])
