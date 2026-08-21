"""Post-trade breakdown: classifying how trades ended and what they returned."""

from datetime import date

import pytest

from quantdesk.analysis.trades import (
    GAP_STOP, GAP_TRAILED, STOP, TARGET, TIME_STOP, TRAILING,
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
        exit_trade("stop loss hit", -1.4),
        exit_trade("stop loss hit", -1.03),
        exit_trade("stop loss hit", -0.3),
        exit_trade("stop loss hit", 0.0, pnl=-2.0),
        exit_trade("time stop", 0.5),
        exit_trade("target $1 reached", 2.5),
        exit_trade("target $1 reached", 5.0),
    ])
    histogram = analysis.r_histogram
    assert histogram["< -2R (gapped badly)"] == 1
    assert histogram["-2R to -1.25R (worse than planned)"] == 1
    assert histogram["-1.25R to -0.75R (stop, as planned)"] == 1
    assert histogram["-0.75R to -0.05R"] == 1
    assert histogram["breakeven (-0.05R to +0.05R)"] == 1
    assert histogram["+0.05R to +1R"] == 1
    assert histogram["+2R to +4R"] == 1
    assert histogram["> +4R"] == 1


def test_an_ordinary_stop_is_not_filed_as_worse_than_planned():
    """Stops fill slightly past their price; -1.03R is a stop working.

    A boundary drawn exactly at -1R files almost every normal stop under
    "worse than planned" and buries the genuinely bad gap fills beside them.
    """
    analysis = analyze_trades([exit_trade("stop loss hit", -1.03) for _ in range(20)])
    assert analysis.r_histogram["-1.25R to -0.75R (stop, as planned)"] == 20
    assert analysis.r_histogram["< -2R (gapped badly)"] == 0
    assert analysis.r_histogram["-2R to -1.25R (worse than planned)"] == 0


def test_a_breakeven_scratch_is_not_a_loss():
    from quantdesk.analysis.trades import BREAKEVEN

    analysis = analyze_trades([
        exit_trade("stop loss hit", 0.0, pnl=-1.0),
        exit_trade("target $1 reached", 2.0),
        exit_trade("stop loss hit", -1.0),
    ])
    assert analysis.buckets[BREAKEVEN].count == 1
    # The scratch must not drag either average.
    assert analysis.avg_win_r == pytest.approx(2.0)
    assert analysis.avg_loss_r == pytest.approx(-1.0)


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


# --- round trips: the distortion this module was rebuilt to remove -----------
def entry(pid, shares=100, direction="long", setup="breakout"):
    return Trade(symbol="X", action="short" if direction == "short" else "buy",
                 shares=shares, price=100.0, trade_date=date(2024, 1, 1),
                 position_id=pid, direction=direction, setup=setup)


def leg(pid, reason, r, shares, pnl, day=2, trailed=False,
        direction="long", setup="breakout"):
    return Trade(symbol="X", action="cover" if direction == "short" else "sell",
                 shares=shares, price=100.0, trade_date=date(2024, 1, day),
                 reason=reason, realized_pnl=pnl, r_multiple=r,
                 holding_days=day * 5, stop_trailed=trailed,
                 position_id=pid, direction=direction, setup=setup)


def test_a_staged_exit_is_one_trade_not_two():
    """The bug that made a working design look broken.

    Half off at +2R and the remainder stopped at -1R is a single position that
    returned +0.5R. Counted per exit event it becomes a +2R win measured on half
    a position and a -1R loss measured on the other half, which are then
    averaged against each other as if they were separate trades.
    """
    trades = [
        entry(1, shares=100),
        leg(1, "target $120.00 reached", 2.0, 50, +1000.0, day=2),
        leg(1, "stop loss hit", -1.0, 50, -500.0, day=4),
    ]
    analysis = analyze_trades(trades)

    assert analysis.closed == 1, "one position, one trade"
    assert analysis.multi_exit == 1
    assert analysis.partial_profit == 1
    # R weighted by the share of the position each leg closed: (2.0+-1.0)/2
    trip_r = analysis.r_histogram
    assert trip_r["+0.05R to +1R"] == 1
    assert analysis.avg_win_r == pytest.approx(0.5)
    assert analysis.avg_loss_r == 0.0, "there is no losing trade here"


def test_the_outcome_is_recorded_against_the_final_exit():
    trades = [
        entry(1),
        leg(1, "target $120.00 reached", 2.0, 50, +1000.0, day=2),
        leg(1, "stop loss hit", -1.0, 50, -500.0, day=4),
    ]
    analysis = analyze_trades(trades)
    assert analysis.buckets[STOP].count == 1
    assert analysis.buckets[STOP].total_pnl == pytest.approx(500.0)


def test_r_is_weighted_by_the_size_each_leg_closed():
    """An 80/20 split must not average as if it were 50/50."""
    trades = [
        entry(1, shares=100),
        leg(1, "target $120.00 reached", 3.0, 80, +2400.0, day=2),
        leg(1, "stop loss hit", -1.0, 20, -200.0, day=3),
    ]
    analysis = analyze_trades(trades)
    # (3.0*80 + -1.0*20) / 100 = 2.2
    assert analysis.avg_win_r == pytest.approx(2.2)


def test_a_position_still_open_is_not_counted_as_a_result():
    """Booking the realised half while ignoring the open remainder is fiction."""
    trades = [
        entry(1, shares=100),
        leg(1, "target $120.00 reached", 2.0, 50, +1000.0, day=2),
        # the other 50 shares are still held
    ]
    analysis = analyze_trades(trades)
    assert analysis.closed == 0
    assert analysis.open_at_end == 1


def test_separate_positions_stay_separate():
    trades = [
        entry(1), leg(1, "target $1 reached", 2.0, 100, +1000.0),
        entry(2), leg(2, "stop loss hit", -1.0, 100, -500.0),
    ]
    analysis = analyze_trades(trades)
    assert analysis.closed == 2
    assert analysis.multi_exit == 0
    assert analysis.win_rate == pytest.approx(50.0)


def test_dollar_averages_are_now_position_level():
    trades = [
        entry(1), leg(1, "target $1 reached", 2.0, 100, +1000.0),
        entry(2), leg(2, "stop loss hit", -1.0, 100, -400.0),
    ]
    analysis = analyze_trades(trades)
    assert analysis.avg_win_dollars == pytest.approx(1000.0)
    assert analysis.avg_loss_dollars == pytest.approx(400.0)


# --- gap classification -------------------------------------------------------
def test_a_gap_through_a_trailed_stop_is_not_a_disaster():
    """It gives back profit; gapping through the original stop exceeds the loss."""
    from quantdesk.analysis.trades import GAP_TRAILED

    assert classify_exit("gapped through the stop", 0.8, stop_trailed=True) == GAP_TRAILED
    assert classify_exit("gapped through the stop", -2.4, stop_trailed=False) == GAP_STOP


def test_the_two_gap_kinds_are_reported_separately():
    from quantdesk.analysis.trades import GAP_TRAILED

    trades = []
    for i in range(1, 11):
        trades += [entry(i), leg(i, "gapped through the stop", -2.2, 100, -1100.0)]
    for i in range(11, 16):
        trades += [entry(i),
                   leg(i, "gapped through the stop", 0.9, 100, +450.0, trailed=True)]

    analysis = analyze_trades(trades)
    assert analysis.buckets[GAP_STOP].count == 10
    assert analysis.buckets[GAP_TRAILED].count == 5
    assert analysis.buckets[GAP_STOP].avg_r < -1
    assert analysis.buckets[GAP_TRAILED].avg_r > 0


def test_staged_exits_are_explained_in_the_findings():
    trades = []
    for i in range(1, 41):
        trades += [
            entry(i),
            leg(i, "target $1 reached", 2.0, 50, +1000.0, day=2),
            leg(i, "stop loss hit", -1.0, 50, -500.0, day=4),
        ]
    text = " ".join(analyze_trades(trades).findings())
    assert "closed in stages" in text
    assert "part-positions against whole ones" in text


def test_long_labels_do_not_break_the_columns():
    """A misaligned table is easy to misread, and labels get renamed.

    "gapped through trailed stop" is longer than the width the columns were
    originally hard-coded to, which pushed every number on that row one place
    right of its heading.
    """
    trades = [leg(1, "gapped through the stop - filled at the open", 0.8, 100,
                  80.0, trailed=True), entry(1)]
    lines = to_text(analyze_trades(trades)).splitlines()
    header = next(x for x in lines if "HOW IT ENDED" in x)
    row = next(x for x in lines if GAP_TRAILED in x and "%" in x)
    count_col = slice(header.index("COUNT"), header.index("COUNT") + len("COUNT"))
    assert row[count_col].strip() == "1"

    dist = next(x for x in lines if "stop, as planned" in x)
    widest = next(x for x in lines if "worse than planned" in x)
    assert dist.index("%") == widest.index("%")
