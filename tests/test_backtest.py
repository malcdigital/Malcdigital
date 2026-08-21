"""Backtesting.

The headline test here is look-ahead safety. A backtest that can see the future
reports returns nobody could have earned, and it fails silently - the numbers
just come out better. Everything else in this file is secondary to that.
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quantdesk.backtest import (
    BacktestConfig, Backtester, PrecomputedCache, ReplayProvider,
    buy_and_hold, compute_metrics, verdict,
)
from quantdesk.data import get_provider
from quantdesk.data.base import DataProvider, Instrument

SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]

#: Tests bound their window explicitly rather than inheriting whatever history
#: the provider happens to return. Otherwise a change to how much data a
#: provider serves silently changes how long the suite takes - which is exactly
#: how this file went from seconds to minutes once the backtester started
#: asking for full history.
WINDOW_START = date.today() - timedelta(days=900)


@pytest.fixture(scope="module")
def provider():
    return get_provider("synthetic")


# --- look-ahead safety --------------------------------------------------------
def test_replay_provider_never_serves_future_bars(provider):
    replay = ReplayProvider(provider, ["AAPL"])
    full = replay.full_history("AAPL")
    cutoff = full.index[len(full) // 2]

    replay.cutoff = cutoff
    served = replay.history("AAPL")
    assert served.index.max() <= cutoff
    assert len(served) < len(full)


def test_extending_the_end_date_cannot_change_earlier_results(provider):
    """The decisive property.

    If any signal could see the future, running to a later end date would
    change what happened before it. Running the same window twice with
    different ends must produce an identical overlapping equity curve.
    """
    common = dict(symbols=SYMBOLS, starting_cash=100_000.0,
                  risk_profile="moderate", max_new_ideas=3, scan_every=5,
                  start=WINDOW_START)

    replay = ReplayProvider(provider, SYMBOLS)
    sessions = [ts.date() for ts in replay.full_history("SPY").index]
    sessions = [d for d in sessions if d >= WINDOW_START]
    early_end = sessions[-120]

    short = Backtester(provider, BacktestConfig(end=early_end, **common)).run()
    long = Backtester(provider, BacktestConfig(**common)).run()

    assert short.equity_curve, "short run produced nothing"
    overlap = {d: v for d, v in long.equity_curve}
    compared = 0
    for day, value in short.equity_curve:
        assert day in overlap, f"{day} missing from the longer run"
        assert overlap[day] == pytest.approx(value, abs=0.01), (
            f"equity on {day} changed when the end date moved: "
            f"{value} then {overlap[day]} - that is look-ahead"
        )
        compared += 1
    assert compared > 100


def test_precomputed_frames_match_recomputed_ones(provider):
    """The speed optimisation must not change any answer.

    Every indicator involved is backward-looking, so a precomputed frame sliced
    to a window has to equal one computed from that window. If that ever stops
    holding, the backtest is quietly using future information.
    """
    from quantdesk.analysis import indicators as ind

    bars = provider.history("AAPL", 900)
    cache = PrecomputedCache()
    cache.prime("AAPL", bars)

    for cut in (400, 600, 800):
        window = bars.iloc[:cut]
        enriched, weekly, weekly_enriched = cache.get("AAPL", window)
        assert enriched is not None
        assert len(enriched) == len(window)

        fresh = ind.compute_all(window)
        for column in fresh.columns:
            a, b = enriched[column], fresh[column]
            both = a.notna() & b.notna()
            if both.sum() == 0:
                continue
            np.testing.assert_allclose(
                a[both].to_numpy(), b[both].to_numpy(), rtol=1e-9, atol=1e-9,
                err_msg=f"{column} differs at cut {cut}",
            )
        if weekly is not None:
            assert weekly.index.max() <= window.index.max()


def test_cache_declines_when_the_window_disagrees(provider):
    """Rather than silently returning a mismatched frame."""
    bars = provider.history("AAPL", 900)
    cache = PrecomputedCache()
    cache.prime("AAPL", bars)
    # A window with a gap punched in it: same end, fewer rows.
    holed = pd.concat([bars.iloc[:100], bars.iloc[200:400]])
    assert cache.get("AAPL", holed) == (None, None, None)


def test_unprimed_symbol_returns_nothing(provider):
    assert PrecomputedCache().get("NOPE", provider.history("AAPL", 300)) == (None, None, None)


# --- metrics ------------------------------------------------------------------
def test_metrics_on_a_known_curve():
    curve = [(date(2024, 1, 1), 100.0), (date(2025, 1, 1), 200.0)]
    metrics = compute_metrics(curve)
    assert metrics.total_return_pct == pytest.approx(100.0)
    # Doubling over ~1 year is ~100% CAGR.
    assert 95 < metrics.cagr_pct < 105


def test_max_drawdown_is_peak_to_trough():
    curve = [(date(2024, 1, i + 1), v) for i, v in enumerate([100, 120, 60, 80])]
    assert compute_metrics(curve).max_drawdown_pct == pytest.approx(-50.0)


def test_a_flat_curve_has_no_return_and_no_risk():
    curve = [(date(2024, 1, i + 1), 100.0) for i in range(30)]
    metrics = compute_metrics(curve)
    assert metrics.total_return_pct == pytest.approx(0.0)
    assert metrics.max_drawdown_pct == pytest.approx(0.0)
    assert metrics.sharpe == 0.0


def test_too_short_a_curve_is_handled():
    assert compute_metrics([]).total_return_pct == 0.0
    assert compute_metrics([(date(2024, 1, 1), 100.0)]).sharpe == 0.0


def test_trade_statistics():
    from quantdesk.portfolio.store import Trade

    trades = [
        Trade("A", "sell", 1, 10.0, date(2024, 1, 1), realized_pnl=p)
        for p in [100, -50, 200, -80, 300, -40, -60, 150]
    ]
    curve = [(date(2024, 1, i + 1), 100.0 + i) for i in range(10)]
    metrics = compute_metrics(curve, trades)
    assert metrics.closed_trades == 8
    assert metrics.win_rate == pytest.approx(50.0)
    assert metrics.profit_factor == pytest.approx(750 / 230, abs=0.01)
    assert metrics.expectancy == pytest.approx(65.0)
    assert metrics.best_trade == 300 and metrics.worst_trade == -80


def test_sortino_ignores_upside_volatility():
    rising = [(date(2024, 1, 1) , 100.0)]
    values = [100.0]
    for step in [1.0, 8.0, 1.0, 9.0, 1.0, 7.0]:      # all gains, no downside
        values.append(values[-1] + step)
    curve = [(date(2024, 1, i + 1), v) for i, v in enumerate(values)]
    metrics = compute_metrics(curve)
    assert metrics.sortino == 0.0, "no losing days means no downside deviation"


# --- benchmark ----------------------------------------------------------------
def test_buy_and_hold_tracks_the_benchmark(provider):
    bars = provider.history("SPY", 400)
    sessions = [ts.date() for ts in bars.index[-100:]]
    curve = buy_and_hold(bars, sessions, 100_000.0)

    assert len(curve) == len(sessions)
    assert curve[0][1] == pytest.approx(100_000.0, rel=1e-6)
    # Final value must track the price ratio over the window.
    first = float(bars["close"].loc[:pd.Timestamp(sessions[0])].iloc[-1])
    last = float(bars["close"].loc[:pd.Timestamp(sessions[-1])].iloc[-1])
    assert curve[-1][1] == pytest.approx(100_000.0 * last / first, rel=1e-6)


def test_buy_and_hold_handles_missing_data():
    assert buy_and_hold(pd.DataFrame(), [date(2024, 1, 1)], 100.0) == []
    assert buy_and_hold(None, [], 100.0) == []


# --- end to end ---------------------------------------------------------------
@pytest.fixture(scope="module")
def result(provider):
    config = BacktestConfig(symbols=SYMBOLS, starting_cash=100_000.0,
                            risk_profile="moderate", max_new_ideas=3,
                            scan_every=10, start=WINDOW_START)
    return Backtester(provider, config).run()


def test_backtest_produces_a_curve_and_metrics(result):
    assert result.sessions > 100
    assert len(result.equity_curve) == result.sessions
    assert result.metrics is not None
    assert all(v > 0 for _, v in result.equity_curve)


def test_equity_curve_is_chronological(result):
    days = [d for d, _ in result.equity_curve]
    assert days == sorted(days)
    assert len(set(days)) == len(days), "a session must not be recorded twice"


def test_benchmark_is_computed_over_the_same_window(result):
    assert result.benchmark_metrics is not None
    assert result.benchmark_curve[0][0] == result.equity_curve[0][0]
    assert result.benchmark_curve[-1][0] == result.equity_curve[-1][0]


def test_trades_reconcile_with_the_result(result):
    for trade in result.trades:
        if trade.action in ("sell", "cover"):
            assert trade.realized_pnl is not None


def test_verdict_always_compares_to_the_benchmark(result):
    text = " ".join(verdict(result))
    assert "buy-and-hold" in text.lower() or "benchmark" in text.lower()
    assert "Simulated results are not real results" in text


def test_verdict_names_underperformance_bluntly():
    """A losing strategy must not be described in neutral language."""
    config = BacktestConfig(symbols=["AAPL"])
    losing = Backtester.__new__(Backtester)
    from quantdesk.backtest import BacktestMetrics, BacktestResult

    result = BacktestResult(config=config)
    result.equity_curve = [(date(2020, 1, 1), 100_000.0), (date(2024, 1, 1), 105_000.0)]
    result.metrics = BacktestMetrics(5.0, 1.2, -8.0, 0.4, 0.6, 9.0, closed_trades=120)
    result.benchmark_metrics = BacktestMetrics(80.0, 15.0, -20.0, 0.9, 1.2, 18.0)
    text = " ".join(verdict(result))
    assert "LOST TO BUY-AND-HOLD" in text


def test_small_sample_is_called_out():
    from quantdesk.backtest import BacktestMetrics, BacktestResult

    result = BacktestResult(config=BacktestConfig(symbols=["AAPL"]))
    result.equity_curve = [(date(2024, 1, 1), 100_000.0), (date(2024, 3, 1), 101_000.0)]
    result.metrics = BacktestMetrics(1.0, 4.0, -2.0, 0.5, 0.7, 5.0, closed_trades=4)
    text = " ".join(verdict(result))
    assert "noise" in text.lower()
    assert "not a test" in text.lower() or "regime" in text.lower()


def test_missing_symbols_are_reported_not_silently_dropped(provider):
    config = BacktestConfig(symbols=["AAPL", "NOT_A_REAL_TICKER_XYZ"],
                            scan_every=25, start=WINDOW_START)

    class Partial(DataProvider):
        name = "partial"

        def history(self, symbol, lookback_days=400):
            if symbol.upper().startswith("NOT_A_REAL"):
                raise RuntimeError("no data")
            return provider.history(symbol, lookback_days)

        def instrument(self, symbol):
            return Instrument(symbol.upper())

    result = Backtester(Partial(), config).run()
    assert any("could not be loaded" in w for w in result.warnings)


def test_report_renders(result):
    from quantdesk.backtest_report import to_html, to_text

    text = to_text(result)
    assert "QUANTDESK BACKTEST" in text
    assert "BUY & HOLD" in text
    assert "Not financial advice" in text

    html = to_html(result)
    assert html.startswith("<!DOCTYPE html>") and "</html>" in html
    assert "<svg" in html
    assert "Buy &amp; hold" in html


def test_the_html_report_carries_the_trade_breakdown():
    """The HTML is the file most people open; the text report is not.

    Shipping the breakdown only in the text output meant the reader who clicks
    backtest.html saw the headline return without the section that explains it.
    """
    from datetime import date

    from quantdesk.backtest import BacktestMetrics, BacktestResult
    from quantdesk.backtest_report import to_html
    from quantdesk.portfolio.store import Trade

    trades = [
        Trade(symbol="X", action="buy", shares=100, price=100.0,
              trade_date=date(2024, 1, 1), position_id=1, setup="breakout"),
        Trade(symbol="X", action="sell", shares=100, price=120.0,
              trade_date=date(2024, 2, 1), position_id=1, setup="breakout",
              reason="target $120.00 reached", realized_pnl=2000.0,
              r_multiple=2.0, holding_days=31),
    ]
    metrics = BacktestMetrics(total_return_pct=2.0, cagr_pct=2.0,
                              max_drawdown_pct=-1.0, sharpe=0.5, sortino=0.6,
                              volatility_pct=10.0, closed_trades=1)
    html = to_html(BacktestResult(
        config=BacktestConfig(start=date(2024, 1, 1), end=date(2024, 3, 1),
                              symbols=["X"]),
        trades=trades, sessions=40, metrics=metrics,
        equity_curve=[(date(2024, 1, 1), 100000.0), (date(2024, 3, 1), 102000.0)],
    ))
    assert "How the trades ended" in html
    assert "Result distribution" in html
    assert "target reached" in html


def test_the_html_report_omits_the_breakdown_with_no_closed_trades():
    from datetime import date

    from quantdesk.backtest import BacktestMetrics, BacktestResult
    from quantdesk.backtest_report import to_html

    metrics = BacktestMetrics(total_return_pct=0.0, cagr_pct=0.0,
                              max_drawdown_pct=0.0, sharpe=0.0, sortino=0.0,
                              volatility_pct=0.0)
    html = to_html(BacktestResult(
        config=BacktestConfig(start=date(2024, 1, 1), end=date(2024, 3, 1),
                              symbols=["X"]),
        sessions=40, metrics=metrics,
        equity_curve=[(date(2024, 1, 1), 100000.0), (date(2024, 3, 1), 100000.0)],
    ))
    assert "How the trades ended" not in html


def test_the_html_report_survives_a_missing_benchmark():
    """A benchmark that failed to load must not take the report down with it."""
    from datetime import date

    from quantdesk.backtest import BacktestMetrics, BacktestResult
    from quantdesk.backtest_report import to_html

    metrics = BacktestMetrics(total_return_pct=5.0, cagr_pct=5.0,
                              max_drawdown_pct=-2.0, sharpe=0.4, sortino=0.5,
                              volatility_pct=9.0)
    html = to_html(BacktestResult(
        config=BacktestConfig(start=date(2024, 1, 1), end=date(2024, 3, 1),
                              symbols=["X"]),
        sessions=40, metrics=metrics, benchmark_metrics=None,
        equity_curve=[(date(2024, 1, 1), 100000.0), (date(2024, 3, 1), 105000.0)],
    ))
    assert "n/a" in html and "+5.0%" in html
