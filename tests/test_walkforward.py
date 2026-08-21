"""Out-of-sample splitting: the window you may fit, and the one you may not.

The tests that matter here are about leakage and about honesty. A split that
lets a session into both windows is worse than no split, because it produces a
number that looks validated and is not.
"""

from datetime import date

import pytest

from quantdesk.walkforward import (
    Degradation, RevealLog, SplitResult, split_window, to_text,
)


# --- carving the window -------------------------------------------------------
def test_the_windows_do_not_overlap():
    """The leak the split exists to prevent.

    A shared session would let the fit window's open positions settle inside
    the holdout, so the holdout would be scoring decisions made with data it is
    supposed to be blind to.
    """
    fit_end, holdout_start = split_window(date(2017, 9, 1), date(2026, 8, 20))
    assert holdout_start > fit_end
    assert (holdout_start - fit_end).days == 1


def test_an_explicit_split_date_is_honoured():
    fit_end, holdout_start = split_window(date(2017, 1, 1), date(2026, 1, 1),
                                          at=date(2023, 8, 31))
    assert fit_end == date(2023, 8, 31)
    assert holdout_start == date(2023, 9, 1)


def test_the_default_leaves_two_thirds_to_fit():
    start, end = date(2020, 1, 1), date(2030, 1, 1)
    fit_end, _ = split_window(start, end)
    fitted = (fit_end - start).days / (end - start).days
    assert 0.66 <= fitted <= 0.68


@pytest.mark.parametrize("at", [date(2016, 1, 1), date(2027, 1, 1)])
def test_a_split_outside_the_window_is_refused(at):
    with pytest.raises(ValueError):
        split_window(date(2017, 1, 1), date(2026, 1, 1), at=at)


def test_a_split_leaving_no_holdout_is_refused():
    """Splitting on the final day gives a holdout of nothing at all."""
    with pytest.raises(ValueError):
        split_window(date(2020, 1, 1), date(2020, 12, 31), at=date(2020, 12, 31))


def test_a_backwards_window_is_refused():
    with pytest.raises(ValueError):
        split_window(date(2026, 1, 1), date(2020, 1, 1))


# --- reading the comparison ---------------------------------------------------
def test_a_shallower_drawdown_is_not_a_regression():
    """Drawdown is stored negative, so -0.9% beats -2.3%.

    Treating it as a cost to be minimised marked every improvement as "worse",
    which is the kind of wrong that teaches the reader to ignore the column.
    """
    d = Degradation("Max drawdown", -2.33, -0.94)
    assert d.change > 0
    assert not d.worse


def test_a_deeper_drawdown_is_a_regression():
    assert Degradation("Max drawdown", -2.33, -8.10).worse


def test_a_measure_where_less_is_better_still_reads_correctly():
    """Kept for measures like volatility, where the sign convention flips."""
    assert Degradation("Volatility", 9.0, 14.0, higher_is_better=False).worse
    assert not Degradation("Volatility", 14.0, 9.0, higher_is_better=False).worse


def test_retained_is_undefined_when_the_fit_window_lost_money():
    """"Kept 40% of a negative return" is not a sentence worth printing."""
    assert Degradation("CAGR", -4.0, -1.6).retained is None


def test_retained_is_the_share_of_the_fitted_edge_that_survived():
    assert Degradation("CAGR", 10.0, 3.0).retained == pytest.approx(0.3)


# --- the verdict --------------------------------------------------------------
class FakeMetrics:
    def __init__(self, cagr, sharpe=1.0, sortino=1.0, dd=-10.0, pf=1.5,
                 expectancy=50.0, win_rate=50.0, total=10.0, closed=100):
        self.cagr_pct, self.sharpe, self.sortino = cagr, sharpe, sortino
        self.max_drawdown_pct, self.profit_factor = dd, pf
        self.expectancy, self.win_rate = expectancy, win_rate
        self.total_return_pct, self.closed_trades = total, closed


class FakeRun:
    def __init__(self, metrics, benchmark=None):
        self.metrics, self.benchmark_metrics = metrics, benchmark


def make_split(fit_cagr, holdout_cagr, reveals=1, revealed=True,
               benchmark=None, closed=100,
               holdout_start=date(2023, 1, 1), holdout_end=date(2026, 1, 1)):
    return SplitResult(
        fit_start=date(2017, 1, 1), fit_end=holdout_start,
        holdout_start=holdout_start, holdout_end=holdout_end,
        fit=FakeRun(FakeMetrics(fit_cagr)),
        holdout=FakeRun(FakeMetrics(holdout_cagr, closed=closed), benchmark),
        reveals=reveals, revealed=revealed,
    )


def test_an_unrevealed_holdout_says_so_and_stops():
    lines = make_split(10.0, 3.0, revealed=False).verdict()
    assert len(lines) == 1
    assert "was not run" in lines[0]


def test_losing_most_of_the_edge_is_called_out():
    text = " ".join(make_split(10.0, 3.0).verdict())
    assert "kept 30%" in text and "shaped by this particular history" in text


def test_holding_up_out_of_sample_is_said_plainly():
    text = " ".join(make_split(10.0, 8.0).verdict())
    assert "kept 80%" in text and "might be real" in text


def test_a_sign_change_is_named_as_overfitting():
    text = " ".join(make_split(10.0, -4.0).verdict())
    assert "changed sign" in text


def test_a_fit_window_that_lost_money_is_the_real_finding():
    """No point discussing decay when there was nothing to decay from."""
    text = " ".join(make_split(-3.0, -5.0).verdict())
    assert "lost money" in text and "nothing here that worked" in text


def test_windows_that_agree_too_closely_are_treated_as_suspicious():
    text = " ".join(make_split(10.0, 10.1).verdict())
    assert "Check the split is real" in text


def test_repeated_reveals_are_reported():
    text = " ".join(make_split(10.0, 8.0, reveals=2).verdict())
    assert "revealed 2 times" in text


def test_a_spent_holdout_is_called_spent():
    text = " ".join(make_split(10.0, 8.0, reveals=4).verdict())
    assert "not really a holdout any more" in text


def test_a_short_holdout_is_discounted():
    text = " ".join(make_split(10.0, 8.0, holdout_start=date(2025, 1, 1),
                               holdout_end=date(2026, 1, 1)).verdict())
    assert "only 1.0 years" in text


def test_too_few_holdout_trades_is_flagged():
    text = " ".join(make_split(10.0, 8.0, closed=12).verdict())
    assert "Only 12 closed positions" in text


def test_losing_to_buy_and_hold_out_of_sample_outranks_the_split():
    """Surviving the holdout and still losing to the index is still losing."""
    text = " ".join(make_split(10.0, 8.0,
                               benchmark=FakeMetrics(20.0, total=60.0)).verdict())
    assert "still lost to buy-and-hold by 50.0 percentage points" in text


# --- rendering ----------------------------------------------------------------
def test_the_text_report_shows_both_windows():
    text = to_text(make_split(10.0, 3.0))
    assert "OUT-OF-SAMPLE SPLIT" in text
    assert "Fit window" in text and "Holdout" in text
    assert "CAGR" in text and "worse" in text


def test_the_text_report_hides_the_holdout_until_revealed():
    split = make_split(10.0, 3.0, revealed=False)
    split.holdout = None
    text = to_text(split)
    assert "has not been run" in text
    # The whole point: no holdout number appears anywhere on the page.
    assert "3.00" not in text


# --- the reveal log -----------------------------------------------------------
def test_reveals_are_counted_across_runs(tmp_path):
    log = RevealLog(tmp_path / "reveals.json")
    key = log.key(date(2023, 1, 1), date(2026, 1, 1), ["SPY", "QQQ"])
    assert log.count(key) == 0
    assert log.record(key, date(2026, 1, 2)) == 1
    assert RevealLog(tmp_path / "reveals.json").record(key, date(2026, 1, 3)) == 2
    assert RevealLog(tmp_path / "reveals.json").count(key) == 2


def test_the_key_is_stable_across_processes(tmp_path):
    """Python salts str hashing per process.

    Using the built-in hash() would give the same holdout a different key on
    every run, so the count could never rise above one and the erosion this
    log exists to show would be invisible.
    """
    import subprocess
    import sys

    script = (
        "from datetime import date;"
        "from quantdesk.walkforward import RevealLog;"
        "print(RevealLog('x').key(date(2023,1,1), date(2026,1,1), ['SPY','QQQ']))"
    )
    keys = {
        subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, cwd=".").stdout.strip()
        for _ in range(2)
    }
    assert len(keys) == 1 and keys != {""}


def test_a_different_universe_is_a_different_holdout(tmp_path):
    """The same dates over different symbols is a different test.

    Charging it against the same count would report a holdout as used up when
    it has not been looked at.
    """
    log = RevealLog(tmp_path / "reveals.json")
    a = log.key(date(2023, 1, 1), date(2026, 1, 1), ["SPY", "QQQ"])
    b = log.key(date(2023, 1, 1), date(2026, 1, 1), ["SPY", "IWM"])
    assert a != b


def test_symbol_order_does_not_change_the_key(tmp_path):
    log = RevealLog(tmp_path / "reveals.json")
    assert log.key(date(2023, 1, 1), date(2026, 1, 1), ["QQQ", "spy"]) == \
           log.key(date(2023, 1, 1), date(2026, 1, 1), ["SPY", "QQQ"])


def test_a_corrupt_log_does_not_stop_a_backtest(tmp_path):
    """Undercounting reveals is a smaller harm than refusing to run."""
    path = tmp_path / "reveals.json"
    path.write_text("{not json at all", encoding="utf-8")
    log = RevealLog(path)
    key = log.key(date(2023, 1, 1), date(2026, 1, 1), ["SPY"])
    assert log.count(key) == 0
    assert log.record(key, date(2026, 1, 2)) == 1


# --- running the split for real -----------------------------------------------
def test_the_two_runs_share_no_session_and_no_capital():
    """The property the whole module rests on.

    If the holdout inherited the fit window's ending equity or its open
    positions, it would be scoring the fit window as much as itself - and the
    resulting number would look validated while being nothing of the kind.
    """
    from datetime import timedelta

    from quantdesk.backtest import BacktestConfig
    from quantdesk.data import get_provider
    from quantdesk.walkforward import run_split

    end = date.today() - timedelta(days=5)
    config = BacktestConfig(symbols=["SPY", "QQQ", "AAPL"],
                            start=end - timedelta(days=600), end=end,
                            scan_every=10, starting_cash=100_000.0)

    split = run_split(get_provider("synthetic"), config, reveal=True)

    fit_days = [d for d, _ in split.fit.equity_curve]
    holdout_days = [d for d, _ in split.holdout.equity_curve]
    assert fit_days and holdout_days
    assert not set(fit_days) & set(holdout_days)
    assert max(fit_days) < min(holdout_days)

    # Each window starts from the same cash, not from where the other finished.
    assert split.holdout.equity_curve[0][1] == pytest.approx(100_000.0, rel=0.05)

    # And each is scored against its own benchmark, not the whole period's.
    assert split.holdout.benchmark_metrics is not None


def test_the_holdout_is_not_run_unless_revealed():
    from datetime import timedelta

    from quantdesk.backtest import BacktestConfig
    from quantdesk.data import get_provider
    from quantdesk.walkforward import run_split

    end = date.today() - timedelta(days=5)
    config = BacktestConfig(symbols=["SPY", "QQQ"], start=end - timedelta(days=500),
                            end=end, scan_every=10)

    split = run_split(get_provider("synthetic"), config, reveal=False)
    assert split.fit is not None
    assert split.holdout is None
    assert not split.revealed


def test_a_split_without_explicit_dates_is_refused():
    """Without both ends the window is whatever the provider returned.

    The same --split would then carve a different holdout next month, and
    comparing this month's number to that one would mean nothing.
    """
    from quantdesk.backtest import BacktestConfig
    from quantdesk.data import get_provider
    from quantdesk.walkforward import run_split

    with pytest.raises(ValueError, match="explicit start and end"):
        run_split(get_provider("synthetic"),
                  BacktestConfig(symbols=["SPY"], start=None, end=None))
