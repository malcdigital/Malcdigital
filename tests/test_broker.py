"""Execution semantics.

These are the tests that keep the simulator honest: gaps must hurt, stops must
win ties, slippage must always work against you, and cash must reconcile.
"""

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.broker.paper import PaperBroker
from quantdesk.config import Settings
from quantdesk.portfolio.store import Order, PortfolioStore, Position


@pytest.fixture
def desk(tmp_path):
    def _make(cash=100_000.0, slippage_bps=0.0, commission=0.0, risk="moderate"):
        store = PortfolioStore(tmp_path / f"{slippage_bps}-{cash}-{risk}.db")
        store.initialise(cash, force=True)
        settings = Settings(home=tmp_path, risk_profile=risk)
        settings.slippage_bps = slippage_bps
        settings.commission_per_share = commission
        return store, PaperBroker(store, settings)

    return _make


def one_bar(o, h, l, c, v=1_000_000):
    return pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c, "volume": v}],
        index=pd.to_datetime(["2026-01-05"]),
    )


def buy_order(order_type="stop", trigger=155.0, shares=100, stop=145.0,
              targets=((170.0, 1.0),), expires=date(2026, 1, 10)):
    return Order("AAPL", "buy", order_type, shares, trigger, stop, list(targets),
                 "breakout", 1000.0, 60, date(2026, 1, 5), expires)


def long_position(entry=150.0, stop=145.0, shares=100, targets=((170.0, 1.0),),
                  entry_date=date(2026, 1, 1), highest=150.0, time_stop=60):
    return Position("AAPL", shares, entry, entry_date, stop, stop, list(targets),
                    "x", 500.0, highest, time_stop)


# --- entries ----------------------------------------------------------------
def test_buy_stop_does_not_fill_below_its_trigger(desk):
    store, broker = desk()
    store.add_order(buy_order())
    summary = broker.process_day({"AAPL": one_bar(150, 154.9, 149, 152)}, date(2026, 1, 5))
    assert summary.fills == 0
    assert store.open_positions() == []


def test_buy_stop_fills_at_trigger_when_crossed(desk):
    store, broker = desk()
    store.add_order(buy_order())
    broker.process_day({"AAPL": one_bar(150, 158, 149, 157)}, date(2026, 1, 5))
    assert store.open_positions()[0].entry_price == pytest.approx(155.0)


def test_gap_above_a_buy_stop_fills_at_the_open_not_the_trigger(desk):
    """A gap up costs you money; pretending otherwise inflates every backtest."""
    store, broker = desk()
    store.add_order(buy_order())
    broker.process_day({"AAPL": one_bar(162, 165, 161, 164)}, date(2026, 1, 5))
    assert store.open_positions()[0].entry_price == pytest.approx(162.0)


def test_buy_limit_fills_better_on_a_gap_down(desk):
    store, broker = desk()
    store.add_order(buy_order("limit", trigger=150.0, stop=140.0))
    broker.process_day({"AAPL": one_bar(146, 151, 145, 149)}, date(2026, 1, 5))
    assert store.open_positions()[0].entry_price == pytest.approx(146.0)


def test_stale_orders_expire(desk):
    store, broker = desk()
    store.add_order(buy_order(trigger=999.0, expires=date(2026, 1, 4)))
    summary = broker.process_day({"AAPL": one_bar(150, 160, 149, 155)}, date(2026, 1, 5))
    assert any(e.kind == "expired" for e in summary.events)
    assert store.pending_orders() == []


def test_position_limit_blocks_new_fills(desk):
    store, broker = desk()
    for i in range(10):  # moderate profile allows 10
        store.add_position(Position(f"S{i}", 1, 10.0, date(2026, 1, 1), 9.0, 9.0,
                                    [(12.0, 1.0)], "x", 1.0, 10.0, 60))
    store.add_order(buy_order("market", trigger=None, shares=10))
    summary = broker.process_day({"AAPL": one_bar(150, 155, 149, 154)}, date(2026, 1, 5))
    assert any("position limit" in e.detail for e in summary.events)


def test_trimming_an_order_trims_its_risk_budget_with_it(desk):
    """The budget belongs to the size it was derived from.

    An order cut back to fit the cash reserve keeps the same per-share distance
    to its stop, so its risk budget has to shrink in step. Leaving the whole
    budget on a smaller position inflates planned risk per share, which halves
    the R the position reports and pushes its rebased targets out past where
    the plan put them.
    """
    store, broker = desk(cash=100_000.0)
    order = buy_order("market", trigger=None, shares=1000, stop=145.0)
    order.risk_dollars = 5000.0  # $5/share over 1000 shares
    store.add_order(order)
    summary = broker.process_day({"AAPL": one_bar(150, 155, 149, 154)}, date(2026, 1, 5))

    assert any("trimmed to" in e.detail for e in summary.events)
    position = store.open_positions()[0]
    assert position.entry_shares < 1000
    assert position.planned_risk_per_share() == pytest.approx(5.0, abs=0.01)


# --- exits ------------------------------------------------------------------
def test_stop_loss_fills_at_the_stop(desk):
    store, broker = desk()
    store.add_position(long_position())
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(148, 149, 143, 144)}, date(2026, 1, 5))
    assert store.trades()[0].price == pytest.approx(145.0)


def test_gap_through_the_stop_fills_at_the_open(desk):
    store, broker = desk()
    store.add_position(long_position())
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(138, 140, 136, 139)}, date(2026, 1, 5))
    trade = store.trades()[0]
    assert trade.price == pytest.approx(138.0), "must not pretend the stop held"
    assert trade.realized_pnl < 0


def test_stop_is_assumed_to_fill_before_a_target_in_the_same_bar(desk):
    """Daily bars cannot resolve intraday order; assume the pessimistic case."""
    store, broker = desk()
    store.add_position(long_position())
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(150, 175, 143, 160)}, date(2026, 1, 5))
    trade = store.trades()[0]
    assert trade.price == pytest.approx(145.0)
    assert trade.realized_pnl < 0


def test_partial_target_sells_a_tranche_and_keeps_the_rest(desk):
    store, broker = desk()
    store.add_position(long_position(targets=((170.0, 0.5), (190.0, 0.5))))
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(160, 172, 159, 171)}, date(2026, 1, 5))
    positions = store.open_positions()
    assert len(positions) == 1 and positions[0].shares == 50
    assert store.trades()[0].price == pytest.approx(170.0)


def test_time_stop_closes_a_stale_position(desk):
    store, broker = desk()
    store.add_position(long_position(entry_date=date(2025, 1, 1), stop=100.0,
                                     targets=((400.0, 1.0),)))
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(151, 152, 150, 151)}, date(2026, 1, 5))
    assert store.open_positions() == []
    assert "time stop" in store.trades()[0].reason


def test_trailing_stop_rises_but_never_falls(desk):
    store, broker = desk()
    store.add_position(long_position(targets=((400.0, 1.0),)))
    store.cash = 85_000
    rising = pd.DataFrame(
        {"open": [150] * 20, "high": [200] * 20, "low": [151] * 20,
         "close": [199] * 20, "volume": [1e6] * 20},
        index=pd.bdate_range("2026-01-01", periods=20),
    )
    broker.process_day({"AAPL": rising}, date(2026, 1, 5))
    first = store.open_positions()[0].stop_price
    assert first >= 150.0, "stop should be at least breakeven once trailing starts"

    higher = rising.assign(open=195, high=205, low=194, close=204)
    broker.process_day({"AAPL": higher}, date(2026, 1, 6))
    assert store.open_positions()[0].stop_price >= first


def test_a_raised_stop_is_actually_enforced(desk):
    store, broker = desk()
    store.add_position(long_position(entry=150.0, stop=150.0, highest=199.0,
                                     targets=((400.0, 1.0),)))
    store.cash = 85_000
    broker.process_day({"AAPL": one_bar(151, 152, 149, 150)}, date(2026, 1, 7))
    assert store.open_positions() == []


# --- costs and accounting ---------------------------------------------------
def test_slippage_always_works_against_you(desk):
    store, broker = desk(slippage_bps=50.0)
    store.add_order(buy_order("market", trigger=None, stop=140.0, targets=((200.0, 1.0),)))
    broker.process_day({"AAPL": one_bar(150, 155, 149, 154)}, date(2026, 1, 5))
    assert store.open_positions()[0].entry_price > 150.0


def test_cash_reconciles_across_a_round_trip(desk):
    store, broker = desk()
    start = store.cash
    store.add_order(buy_order("market", trigger=None, stop=140.0, targets=((160.0, 1.0),)))
    broker.process_day({"AAPL": one_bar(150, 151, 149, 150)}, date(2026, 1, 5))
    assert store.cash == pytest.approx(start - 15_000)

    broker.process_day({"AAPL": one_bar(158, 165, 157, 164)}, date(2026, 1, 6))
    assert store.cash == pytest.approx(start + 1_000)
    assert store.open_positions() == []
