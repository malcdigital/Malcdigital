"""Targets, and the price they are measured from.

A trade is written as "buy at X, stop at Y, take profit at X + 2(X-Y)". The
fill is often not X. Leaving the targets where the plan put them means a
cheap fill lands with its first target nearly touched, and the position exits
for a rounding error rather than the 2R it was aiming at.
"""

import pytest

from quantdesk.broker.paper import rebase_targets


# --- longs --------------------------------------------------------------------
def test_a_fill_at_the_planned_entry_leaves_targets_alone():
    """The common case must be a no-op, or this changes far more than intended."""
    # planned entry 100, stop 97, risk 3 -> targets at 2R and 4R
    targets = [(106.0, 0.5), (112.0, 0.5)]
    assert rebase_targets(targets, 97.0, 3.0, 100.0) == [(106.0, 0.5), (112.0, 0.5)]


def test_a_cheap_fill_moves_the_targets_down_with_it():
    """The bug. A limit gapped through fills below where the order sat.

    Filled at 98 instead of 100, the 2R target at 106 is 8 away - nearly 3R of
    the risk actually carried. It should sit 6 above the fill, at 104.
    """
    moved = rebase_targets([(106.0, 0.5), (112.0, 0.5)], 97.0, 3.0, 98.0)
    assert moved == [(104.0, 0.5), (110.0, 0.5)]


def test_the_worst_case_no_longer_exits_for_nothing():
    """Filled a hair above the stop, the old first target was already behind."""
    # Planned 100/97. The open gapped to 97.10.
    moved = rebase_targets([(106.0, 0.5), (112.0, 0.5)], 97.0, 3.0, 97.10)
    assert moved[0][0] == pytest.approx(103.10)
    # Before: the target sat at 106, only 8.90 above a fill carrying 0.10 of
    # risk. Now it is a genuine 2R of the planned risk away.
    assert moved[0][0] - 97.10 == pytest.approx(6.0)


def test_an_expensive_fill_moves_the_targets_up():
    """Symmetry. Filling worse should not hand you a nearer target."""
    moved = rebase_targets([(106.0, 0.5), (112.0, 0.5)], 97.0, 3.0, 102.0)
    assert moved == [(108.0, 0.5), (114.0, 0.5)]


def test_the_take_fractions_are_untouched():
    moved = rebase_targets([(106.0, 0.4), (112.0, 0.35), (118.0, 0.25)],
                           97.0, 3.0, 98.0)
    assert [take for _, take in moved] == [0.4, 0.35, 0.25]


# --- shorts -------------------------------------------------------------------
def test_a_short_rebases_in_the_other_direction():
    # planned entry 100, stop 103, risk 3 -> targets at 94 (2R) and 88 (4R)
    moved = rebase_targets([(94.0, 0.5), (88.0, 0.5)], 103.0, 3.0, 102.0,
                           is_short=True)
    assert moved == [(96.0, 0.5), (90.0, 0.5)]


def test_a_short_filled_at_its_plan_is_a_no_op():
    targets = [(94.0, 0.5), (88.0, 0.5)]
    assert rebase_targets(targets, 103.0, 3.0, 100.0, is_short=True) == targets


# --- refusals -----------------------------------------------------------------
def test_no_risk_figure_leaves_everything_alone():
    targets = [(106.0, 0.5)]
    assert rebase_targets(targets, 97.0, 0.0, 98.0) == targets


def test_an_empty_target_list_is_returned_unchanged():
    assert rebase_targets([], 97.0, 3.0, 98.0) == []


def test_a_target_on_the_wrong_side_of_the_stop_is_left_alone():
    """Not a profit target as laid out. Reflecting it would invent a trade."""
    targets = [(96.0, 0.5)]   # below the stop on a long
    assert rebase_targets(targets, 97.0, 3.0, 98.0) == targets


# --- the property that matters ------------------------------------------------
@pytest.mark.parametrize("fill", [97.10, 98.0, 99.5, 100.0, 101.0, 104.0])
def test_every_target_stays_the_same_r_from_the_fill(fill):
    """The whole point: a "2R target" is 2R above what you actually paid."""
    risk = 3.0
    moved = rebase_targets([(106.0, 0.5), (112.0, 0.5)], 97.0, risk, fill)
    assert (moved[0][0] - fill) / risk == pytest.approx(2.0)
    assert (moved[1][0] - fill) / risk == pytest.approx(4.0)


# --- through the broker -------------------------------------------------------
def test_a_gapped_limit_fill_produces_rebased_targets(tmp_path):
    """End to end: the order fills below its limit and the position adjusts."""
    from datetime import date

    import pandas as pd

    from quantdesk.broker.paper import PaperBroker
    from quantdesk.config import Settings
    from quantdesk.portfolio.store import Order, PortfolioStore

    settings = Settings(home=tmp_path)
    store = PortfolioStore(tmp_path / "p.db")
    store.initialise(100_000)
    broker = PaperBroker(store, settings)

    store.add_order(Order(
        symbol="X", side="buy", order_type="limit", shares=100,
        trigger_price=100.0, stop_loss=97.0,
        targets=[(106.0, 0.5), (112.0, 0.5)],
        risk_dollars=300.0, created_date=date(2024, 1, 1),
        expires_date=date(2024, 12, 31),
    ))

    # The session gaps down through the limit: the fill is the open, not 100.
    bars = pd.DataFrame(
        {"open": [98.0], "high": [99.0], "low": [97.5], "close": [98.5],
         "volume": [5_000_000]},
        index=pd.to_datetime([date(2024, 1, 2)]),
    )
    broker.process_day({"X": bars}, as_of=date(2024, 1, 2))

    position = store.open_positions()[0]
    assert position.entry_price == pytest.approx(98.0, abs=0.5)
    first_target = position.targets[0][0]
    # 2R above the fill, not the 106 the plan wrote against a 100 entry.
    assert first_target < 106.0
    assert (first_target - position.entry_price) == pytest.approx(6.0, abs=0.4)
