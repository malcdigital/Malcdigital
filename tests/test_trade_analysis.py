"""Post-trade breakdown: classifying how trades ended and what they returned."""

from datetime import date

import pytest

from quantdesk.analysis.trades import (
    GAP_STOP, STOP, TARGET, TIME_STOP, TRAILING,
    analyze_trades, classify_exit, to_text,
)
from quantdesk.portfolio.store import Trade


def exit_trade(reason, r, pnl=None, days=10, setup="breakout", direction="long"):
    return Trade(
        symbol="X", action="sell", shares=10, price=100.0,
        trade_date=date(2024, 1, 1), reason=reason,
        realized_pnl=pnl if pnl is not None else r * 100.0,
        r_multiple=r, holding_days=days, setup=setup, direction=direction,
    )


# --- classification -----------------------------------------------------------
@pytest.mark.parametrize("reason,r,expected", [
    ("target $170.00 reached", 2.0, TARGET),
    ("time stop - held 61 days without reaching target", 0.3, TIME_STOP),
    ("gapped through the stop - filled at the open", -2.4, GAP_STOP),
    ("stop loss hit", -1.0, STOP),
])
def test_exit_classification(reason, r, expected):
    assert classify_exit(reason, r) == expected


def test_a_stop_hit_in_profit_is_a_trailing_stop():
    """Both record "stop loss hit" - trailing works by moving the stop.

    Counting a profitable trail alongside a loss at the original stop would
    hide the difference between protecting a gain and being wrong.
    """
    assert classify_exit("stop loss hit", 1.4) == TRAILING
    assert classify_exit("stop loss hit", -1.0) == STOP


def test_unknown_reason_does_not_crash():
    from quantdesk.analysis.trades import OTHER

    assert classify_exit("", None) == OTHER
    assert classify_exit("manually closed", None) == OTHER


# --- aggregation --------------------------------------------------------------
def test_buckets_count_and_average_correctly():
    trades = [
        exit_trade("target $1 reached", 2.0),
        exit_trade("target $1 reached", 4.0),
        exit_trade("stop loss hit", -1.0),
        exit_trade("stop loss hit", -1.0),
        exit_trade("stop loss hit", -1.0),
    ]
    analysis = analyze_trades(trades)
    assert analysis.closed == 5
    assert analysis.buckets[TARGET].count == 2
    assert analysis.buckets[TARGET].avg_r == pytest.approx(3.0)
    assert analysis.buckets[STOP].count == 3
    assert analysis.buckets[STOP].avg_r == pytest.approx(-1.0)
    assert analysis.share(TARGET) == pytest.approx(40.0)


def test_entries_are_ignored():
    trades = [
        Trade("X", "buy", 10, 100.0, date(2024, 1, 1)),
        exit_trade("target $1 reached", 2.0),
    ]
    assert analyze_trades(trades).closed == 1


def test_short_covers_are_counted():
    cover = Trade("X", "cover", 10, 100.0, date(2024, 1, 1),
                  realized_pnl=500.0, r_multiple=2.0, holding_days=5,
                  direction="short", setup="breakdown")
    analysis = analyze_trades([cover])
    assert analysis.closed == 1
    assert analysis.by_direction["short"].count == 1


def test_win_and_loss_r_are_separated():
    analysis = analyze_trades([
        exit_trade("target $1 reached", 3.0),
        exit_trade("target $1 reached", 1.0),
        exit_trade("stop loss hit", -1.0),
        exit_trade("stop loss hit", -2.0),
    ])
    assert analysis.avg_win_r == pytest.approx(2.0)
    assert analysis.avg_loss_r == pytest.approx(-1.5)
    assert analysis.best_r == pytest.approx(3.0)
    assert analysis.worst_r == pytest.approx(-2.0)


def test_holding_periods_split_by_outcome():
    analysis = analyze_trades([
        exit_trade("target $1 reached", 2.0, days=30),
        exit_trade("stop loss hit", -1.0, days=6),
    ])
    assert analysis.winner_days == pytest.approx(30.0)
    assert analysis.loser_days == pytest.approx(6.0)


def test_histogram_bins_by_r():
    analysis = analyze_trades([
        exit_trade("gapped through the stop", -2.5),
        exit_trade("stop loss hit", -1.0),
        exit_trade("stop loss hit", -0.2),
        exit_trade("time stop", 0.5),
        exit_trade("target $1 reached", 2.5),
        exit_trade("target $1 reached", 5.0),
    ])
    histogram = analysis.r_histogram
    assert histogram["< -1R (worse than planned)"] == 1
    assert histogram["-1R to -0.5R"] == 1
    assert histogram["-0.5R to 0"] == 1
    assert histogram["0 to +1R"] == 1
    assert histogram["+2R to +4R"] == 1
    assert histogram["> +4R"] == 1


def test_missing_r_is_counted_not_dropped():
    analysis = analyze_trades([exit_trade("stop loss hit", None, pnl=-100.0)])
    assert analysis.closed == 1
    assert analysis.missing_r == 1


def test_empty_input():
    analysis = analyze_trades([])
    assert analysis.closed == 0
    assert "No closed trades" in to_text(analysis)


# --- findings -----------------------------------------------------------------
def test_small_sample_refuses_to_diagnose():
    analysis = analyze_trades([exit_trade("stop loss hit", -1.0) for _ in range(5)])
    findings = analysis.findings()
    assert len(findings) == 1 and "too few" in findings[0]


def test_cut_winners_are_named():
    """The signature this whole module exists to detect."""
    trades = (
        [exit_trade("time stop - held 61 days", 0.3) for _ in range(40)]
        + [exit_trade("stop loss hit", -1.0) for _ in range(40)]
    )
    text = " ".join(analyze_trades(trades).findings())
    assert "time stop" in text.lower()
    assert "cut early" in text.lower() or "before trades resolve" in text.lower()


def test_healthy_shape_is_also_named():
    """It must be able to say the design is working, not only that it is not."""
    trades = (
        [exit_trade("target $1 reached", 3.0) for _ in range(50)]
        + [exit_trade("stop loss hit", -1.0) for _ in range(50)]
    )
    text = " ".join(analyze_trades(trades).findings())
    assert "the shape the design intends" in text


def test_gaps_through_stops_are_called_out():
    trades = (
        [exit_trade("gapped through the stop", -2.5) for _ in range(10)]
        + [exit_trade("stop loss hit", -1.0) for _ in range(40)]
    )
    text = " ".join(analyze_trades(trades).findings())
    assert "gapped" in text.lower()


def test_holding_losers_longer_is_flagged():
    trades = (
        [exit_trade("target $1 reached", 2.0, days=5) for _ in range(30)]
        + [exit_trade("stop loss hit", -1.0, days=40) for _ in range(30)]
    )
    text = " ".join(analyze_trades(trades).findings())
    assert "opposite of the intended discipline" in text


# --- rendering ----------------------------------------------------------------
def test_text_report_renders():
    trades = (
        [exit_trade("target $1 reached", 2.0, setup="breakout") for _ in range(20)]
        + [exit_trade("stop loss hit", -1.0, setup="pullback",
                      direction="short") for _ in range(30)]
    )
    text = to_text(analyze_trades(trades))
    assert "TRADE BREAKDOWN" in text
    assert "RESULT DISTRIBUTION" in text
    assert "BY SETUP" in text and "BY DIRECTION" in text
    assert "WHAT THIS SAYS" in text
