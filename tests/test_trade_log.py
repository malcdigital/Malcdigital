"""The trade log a backtest leaves behind, and reading it back.

A backtest runs against a throwaway database, so without a written log the
per-trade detail dies with the run and re-examining a result means replaying
the whole thing. What matters is that the log round-trips: the breakdown read
from the file has to match the breakdown produced in the run.
"""

from datetime import date

from quantdesk.analysis.trades import analyze_trades
from quantdesk.cli import _read_trade_log, _write_trade_log
from quantdesk.portfolio.store import Trade


def sample_trades():
    return [
        Trade(symbol="AAPL", action="buy", shares=100, price=190.25,
              trade_date=date(2024, 1, 2), position_id=1, direction="long",
              setup="breakout", reason="breakout long entry"),
        Trade(symbol="AAPL", action="sell", shares=50, price=210.5,
              trade_date=date(2024, 2, 1), position_id=1, direction="long",
              setup="breakout", reason="target $210.00 reached",
              realized_pnl=1012.5, r_multiple=2.0, holding_days=30,
              commission=1.25),
        Trade(symbol="AAPL", action="sell", shares=50, price=200.0,
              trade_date=date(2024, 2, 20), position_id=1, direction="long",
              setup="breakout", reason="stop loss hit", realized_pnl=487.5,
              r_multiple=0.96, holding_days=49, stop_trailed=True),
        Trade(symbol="SPY", action="short", shares=20, price=480.0,
              trade_date=date(2024, 3, 1), position_id=2, direction="short",
              setup="breakdown", reason="breakdown short entry"),
        Trade(symbol="SPY", action="cover", shares=20, price=492.0,
              trade_date=date(2024, 3, 5), position_id=2, direction="short",
              setup="breakdown", reason="gapped through the stop",
              realized_pnl=-240.0, r_multiple=-1.8, holding_days=4),
    ]


def test_the_log_round_trips(tmp_path):
    path = tmp_path / "trades.csv"
    original = sample_trades()
    _write_trade_log(original, path)
    restored = _read_trade_log(path)

    assert len(restored) == len(original)
    for before, after in zip(original, restored):
        assert after.symbol == before.symbol
        assert after.action == before.action
        assert after.shares == before.shares
        assert after.price == round(before.price, 4)
        assert after.trade_date == before.trade_date
        assert after.reason == before.reason
        assert after.position_id == before.position_id
        assert after.direction == before.direction
        assert after.setup == before.setup
        assert after.r_multiple == before.r_multiple
        assert after.holding_days == before.holding_days
        assert after.stop_trailed == before.stop_trailed


def test_the_breakdown_survives_the_round_trip(tmp_path):
    """The point of the log - the same conclusions, read back from disk."""
    path = tmp_path / "trades.csv"
    _write_trade_log(sample_trades(), path)

    live = analyze_trades(sample_trades())
    from_file = analyze_trades(_read_trade_log(path))

    assert from_file.closed == live.closed == 2
    assert from_file.multi_exit == live.multi_exit == 1
    assert from_file.avg_win_r == live.avg_win_r
    assert from_file.avg_loss_dollars == live.avg_loss_dollars
    assert [b.reason for b in from_file.ordered_buckets] == \
           [b.reason for b in live.ordered_buckets]


def test_an_entry_without_a_position_still_writes(tmp_path):
    """Blank optional fields must not turn into the string "None" on the way
    back, which would make a missing P&L look like a recorded one."""
    path = tmp_path / "trades.csv"
    _write_trade_log([Trade(symbol="X", action="buy", shares=1, price=1.0,
                            trade_date=date(2024, 1, 1))], path)
    restored = _read_trade_log(path)
    assert restored[0].position_id is None
    assert restored[0].realized_pnl is None
    assert restored[0].r_multiple is None
    assert restored[0].holding_days is None
    assert restored[0].stop_trailed is False
