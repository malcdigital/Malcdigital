"""Scoring the strategy against the index's own bad stretches.

The bug this module exists to prevent is a comfortable one: a max drawdown
column showing the strategy fell less than the index, read as evidence that it
protects capital, when it fell less because it held less and gave the
difference back on the recovery. Every test here is about keeping both legs of
the episode in view.
"""

from datetime import date, timedelta

import pytest

from quantdesk.stress import Episode, drawdown_episodes, to_text, verdict


def curve(values, start=date(2020, 1, 1), step=1):
    return [(start + timedelta(days=i * step), float(v))
            for i, v in enumerate(values)]


# --- finding the episodes -----------------------------------------------------
def test_a_deep_fall_and_its_recovery_is_one_episode():
    episodes = drawdown_episodes(curve([100, 90, 80, 90, 100, 110]),
                                 curve([100, 95, 92, 96, 103, 105]))
    assert len(episodes) == 1
    e = episodes[0]
    assert e.peak == date(2020, 1, 1)
    assert e.trough == date(2020, 1, 3)
    assert e.recovered == date(2020, 1, 5)
    assert e.benchmark_fall_pct == pytest.approx(-20.0)
    assert e.strategy_fall_pct == pytest.approx(-8.0)


def test_a_shallow_dip_is_not_an_episode():
    """Reporting every 3% wobble as a regime buries the two that matter."""
    assert drawdown_episodes(curve([100, 97, 100, 103]),
                             curve([100, 99, 101, 102])) == []


def test_the_floor_can_be_lowered():
    episodes = drawdown_episodes(curve([100, 97, 100, 103]),
                                 curve([100, 99, 101, 102]),
                                 min_depth_pct=2.0)
    assert len(episodes) == 1


def test_episodes_run_peak_to_peak_and_do_not_overlap():
    episodes = drawdown_episodes(
        curve([100, 80, 100, 105, 84, 105, 120]),
        curve([100, 90, 100, 102, 92, 101, 110]))
    assert len(episodes) == 2
    assert episodes[0].recovered <= episodes[1].peak


def test_a_decline_still_running_at_the_end_is_reported_not_dropped():
    """An unrecovered fall is a real thing that happened."""
    episodes = drawdown_episodes(curve([100, 105, 90, 78]),
                                 curve([100, 103, 95, 88]))
    assert len(episodes) == 1
    e = episodes[0]
    assert e.recovered is None
    assert e.strategy_round_trip_pct is None
    assert e.episode_days is None


def test_an_unfinished_episode_is_not_judged():
    """Scoring it now would score only the half that has happened."""
    episodes = drawdown_episodes(curve([100, 90, 75]), curve([100, 96, 90]))
    assert episodes[0].helped is None


# --- the measure that decides it ----------------------------------------------
def test_the_round_trip_is_the_strategy_across_the_whole_cycle():
    e = drawdown_episodes(curve([100, 80, 100]), curve([100, 90, 107]))[0]
    assert e.strategy_round_trip_pct == pytest.approx(7.0)
    assert e.helped


def test_falling_less_and_finishing_down_is_not_defence():
    """The case the drawdown column cannot show.

    Down 10% against the index's 20%, so it "protected" you - and then it came
    out of the round trip 4% poorer over a stretch where holding the index
    left you flat.
    """
    e = drawdown_episodes(curve([100, 80, 100]), curve([100, 90, 96]))[0]
    assert e.spared_pct == pytest.approx(10.0)
    assert e.strategy_round_trip_pct == pytest.approx(-4.0)
    assert not e.helped


def test_the_index_earns_nothing_across_its_own_round_trip():
    """Which is what makes the strategy's figure readable on its own."""
    bench = curve([100, 80, 100])
    e = drawdown_episodes(bench, curve([100, 90, 100]))[0]
    peak = dict(bench)[e.peak]
    assert dict(bench)[e.recovered] == pytest.approx(peak)
    assert e.strategy_round_trip_pct == pytest.approx(0.0)


# --- curves that do not line up -----------------------------------------------
def test_a_missing_session_carries_the_previous_value_forward():
    bench = curve([100, 80, 100])
    strategy = [(date(2020, 1, 1), 100.0), (date(2020, 1, 3), 104.0)]
    e = drawdown_episodes(bench, strategy)[0]
    assert e.strategy_fall_pct == pytest.approx(0.0)  # 2 Jan unknown, holds 100
    assert e.strategy_round_trip_pct == pytest.approx(4.0)


def test_an_episode_beginning_before_the_strategy_exists_is_skipped():
    """Better to drop the row than to invent a starting equity for it."""
    bench = curve([100, 80, 100])
    strategy = [(date(2020, 1, 2), 90.0), (date(2020, 1, 3), 100.0)]
    assert drawdown_episodes(bench, strategy) == []


def test_no_curve_at_all_is_not_an_error():
    assert drawdown_episodes([], curve([100, 90])) == []
    assert drawdown_episodes(curve([100, 90]), []) == []


# --- what it says -------------------------------------------------------------
def test_a_window_with_no_drawdowns_says_it_proves_nothing():
    text = " ".join(verdict([]))
    assert "never fell more than 10%" in text
    assert "is not evidence" in text


def test_coming_through_every_episode_ahead_is_said_plainly():
    text = " ".join(verdict(drawdown_episodes(
        curve([100, 80, 100, 120, 95, 120]),
        curve([100, 90, 110, 118, 108, 125]))))
    assert "ahead in 2 of them" in text
    assert "genuinely defensive design" in text


def test_losing_through_all_of_them_is_named_as_a_smaller_position():
    text = " ".join(verdict(drawdown_episodes(
        curve([100, 80, 100, 120, 95, 120]),
        curve([100, 90, 96, 100, 94, 97]))))
    assert "lost money through all of them" in text
    assert "a smaller position in the same trade" in text


def test_giving_the_protection_back_is_called_out_separately():
    text = " ".join(verdict(drawdown_episodes(curve([100, 80, 100]),
                                              curve([100, 90, 96]))))
    assert "fell less than the index and still finished the episode down" in text
    assert "handed back on the way up" in text


def test_a_mixed_record_is_not_dressed_up_as_a_finding():
    text = " ".join(verdict(drawdown_episodes(
        curve([100, 80, 100, 120, 95, 120]),
        curve([100, 90, 105, 115, 108, 112]))))
    assert "Mixed" in text and "direction rather than a finding" in text


def test_an_open_episode_is_flagged_as_unscorable():
    text = " ".join(verdict(drawdown_episodes(curve([100, 80, 100, 120, 90]),
                                              curve([100, 90, 105, 115, 100]))))
    assert "still open" in text and "cannot be scored" in text


# --- rendering ----------------------------------------------------------------
def test_the_table_leads_with_the_round_trip():
    text = to_text(drawdown_episodes(curve([100, 80, 100]),
                                     curve([100, 90, 96])))
    assert "WHEN THE INDEX FELL" in text
    assert "ROUND TRIP" in text and "-4.0%" in text
    assert "earns 0% by definition" in text


def test_an_open_episode_renders_as_open_not_as_zero():
    text = to_text(drawdown_episodes(curve([100, 90, 75]), curve([100, 96, 90])))
    assert "open" in text


def test_an_empty_table_still_explains_itself():
    text = to_text([])
    assert "WHEN THE INDEX FELL" in text
    assert "nothing here to test" in text


def test_the_heading_reflects_the_floor_that_was_used():
    """Selecting on 5% and captioning it 10% is how a reader is misled."""
    episodes = drawdown_episodes(curve([100, 93, 100]), curve([100, 97, 101]),
                                 min_depth_pct=5.0)
    assert "never fell more than 5%" in to_text([], min_depth_pct=5.0)
    assert len(episodes) == 1
