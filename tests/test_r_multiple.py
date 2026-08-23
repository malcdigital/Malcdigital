"""R multiples, and the denominator they are measured against.

R only means anything if it is measured against the risk the position was
*sized on*. Measuring against the distance from the fill to the stop looks
identical almost always, and then one gapped fill produces a -98R on a trade
that lost $1,642 - a number that goes on to poison every average containing it.
"""

from datetime import date

import pytest

from quantdesk.portfolio.store import Position


def long_position(entry, stop, shares=100, risk_dollars=None, entry_shares=None):
    return Position(
        symbol="X", shares=shares, entry_price=entry, entry_date=date(2024, 1, 1),
        stop_price=stop, initial_stop=stop, targets=[],
        risk_dollars=(shares * (entry - stop)) if risk_dollars is None
        else risk_dollars,
        entry_shares=shares if entry_shares is None else entry_shares,
    )


def short_position(entry, stop, shares=100):
    return Position(
        symbol="X", shares=shares, entry_price=entry, entry_date=date(2024, 1, 1),
        stop_price=stop, initial_stop=stop, targets=[], direction="short",
        risk_dollars=shares * (stop - entry), entry_shares=shares,
    )


# --- the ordinary case, which must not have changed ---------------------------
def test_a_long_at_its_stop_is_minus_one_r():
    assert long_position(100.0, 97.0).r_multiple(97.0) == pytest.approx(-1.0)


def test_a_long_at_twice_its_risk_is_plus_two_r():
    assert long_position(100.0, 97.0).r_multiple(106.0) == pytest.approx(2.0)


def test_a_short_at_its_stop_is_minus_one_r():
    assert short_position(100.0, 103.0).r_multiple(103.0) == pytest.approx(-1.0)


def test_a_short_moving_in_your_favour_is_positive():
    assert short_position(100.0, 103.0).r_multiple(94.0) == pytest.approx(2.0)


# --- the bug --------------------------------------------------------------
def test_a_fill_that_lands_beside_the_stop_does_not_explode():
    """The -98.43R.

    A limit order gapped through fills at the open, below where the order sat.
    Planned: buy at $100, stop $97, so $3/share of risk over 100 shares. The
    open gapped to $97.01, so the realised distance to the stop is one cent.
    Dividing by that cent turns an ordinary loss into a 300R catastrophe.
    """
    position = Position(
        symbol="X", shares=100, entry_price=97.01, entry_date=date(2024, 1, 1),
        stop_price=97.0, initial_stop=97.0, targets=[],
        risk_dollars=300.0, entry_shares=100,   # planned: 100 x $3
    )
    r = position.r_multiple(94.0)
    assert r == pytest.approx(-1.0033, abs=1e-3)
    assert r > -2.0, "measured against the fill this would be about -300R"


def test_the_old_denominator_is_what_produced_the_absurd_number():
    """Kept as the counter-example, so the regression is unambiguous."""
    entry, stop = 97.01, 97.0
    naive = (94.0 - entry) / (entry - stop)
    assert naive < -300  # what the report printed a version of


def test_no_usable_risk_figure_reports_none_rather_than_zero():
    """0.0R would file the position among genuine break-even scratches."""
    position = Position(
        symbol="X", shares=10, entry_price=100.0, entry_date=date(2024, 1, 1),
        stop_price=100.0, initial_stop=100.0, targets=[],
        risk_dollars=0.0, entry_shares=0,
    )
    assert position.r_multiple(90.0) is None


def test_a_stop_a_hair_from_entry_is_treated_as_no_risk_figure():
    """The fallback path needs the same protection as the primary one.

    Positions predating entry_shares have no planned figure to fall back on, so
    a stop within a tenth of a percent of the fill is reported as unknown
    rather than used as a denominator.
    """
    position = Position(
        symbol="X", shares=100, entry_price=97.01, entry_date=date(2024, 1, 1),
        stop_price=97.0, initial_stop=97.0, targets=[],
        risk_dollars=0.0, entry_shares=0,
    )
    assert position.r_multiple(94.0) is None


# --- scaling out --------------------------------------------------------------
def test_r_does_not_change_as_the_position_is_scaled_out():
    """The trap in measuring against a per-position budget.

    `shares` shrinks on a partial exit while risk_dollars does not, so dividing
    the budget by the *current* count would double the reported R on the second
    leg of a staged exit.
    """
    position = long_position(100.0, 97.0, shares=100)
    first = position.r_multiple(106.0)

    position.shares -= 50          # half taken off at the target
    second = position.r_multiple(106.0)

    assert first == pytest.approx(2.0)
    assert second == pytest.approx(first)


def test_the_planned_risk_wins_over_the_fill_distance():
    """When they disagree, the plan is the one the share count came from."""
    position = Position(
        symbol="X", shares=100, entry_price=101.0, entry_date=date(2024, 1, 1),
        stop_price=97.0, initial_stop=97.0, targets=[],
        risk_dollars=300.0, entry_shares=100,   # planned $3/share, filled $4 away
    )
    # Planned risk says 100 shares x $3; the fill distance would say $4.
    assert position.r_multiple(104.0) == pytest.approx(1.0)


def test_positions_without_a_planned_figure_still_work():
    """Rows written before entry_shares existed migrate to 0, not to broken."""
    position = Position(
        symbol="X", shares=100, entry_price=100.0, entry_date=date(2024, 1, 1),
        stop_price=97.0, initial_stop=97.0, targets=[],
        risk_dollars=0.0, entry_shares=0,
    )
    assert position.r_multiple(103.0) == pytest.approx(1.0)


# --- persistence --------------------------------------------------------------
def test_the_entry_size_survives_a_round_trip(tmp_path):
    """R is computed from stored positions, so the size has to persist."""
    from quantdesk.portfolio.store import PortfolioStore

    store = PortfolioStore(tmp_path / "p.db")
    store.initialise(100_000)
    pid = store.add_position(long_position(100.0, 97.0, shares=100))

    reloaded = next(p for p in store.open_positions() if p.id == pid)
    assert reloaded.entry_shares == 100
    assert reloaded.r_multiple(106.0) == pytest.approx(2.0)


def test_scaling_out_does_not_overwrite_the_entry_size(tmp_path):
    from quantdesk.portfolio.store import PortfolioStore

    store = PortfolioStore(tmp_path / "p.db")
    store.initialise(100_000)
    position = long_position(100.0, 97.0, shares=100)
    position.id = store.add_position(position)

    position.shares = 50
    store.update_position(position)

    reloaded = next(p for p in store.open_positions() if p.id == position.id)
    assert reloaded.shares == 50
    assert reloaded.entry_shares == 100
    assert reloaded.r_multiple(106.0) == pytest.approx(2.0)


def test_an_older_database_migrates_without_losing_positions(tmp_path):
    """The column is added in place; existing rows get 0 and use the fallback."""
    import sqlite3

    from quantdesk.portfolio.store import PortfolioStore

    path = tmp_path / "old.db"
    store = PortfolioStore(path)
    store.initialise(100_000)
    store.add_position(long_position(100.0, 97.0, shares=100))

    # Simulate a database written before the column existed.
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE positions RENAME TO positions_old")
        conn.execute(
            "CREATE TABLE positions AS SELECT id, symbol, shares, entry_price, "
            "entry_date, stop_price, initial_stop, targets, setup, risk_dollars, "
            "highest_close, time_stop_days, status, notes, direction, "
            "lowest_close, proxy_for FROM positions_old"
        )
        conn.execute("DROP TABLE positions_old")

    reopened = PortfolioStore(path)
    positions = reopened.open_positions()
    assert len(positions) == 1
    assert positions[0].entry_shares == 0
    # Falls back to the fill-to-stop distance, which for this position is sound.
    assert positions[0].r_multiple(106.0) == pytest.approx(2.0)
