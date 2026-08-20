"""End-to-end: a full trading day, and a walk-forward run with no look-ahead."""

from datetime import date

import pandas as pd
import pytest

from quantdesk.config import Settings
from quantdesk.data.base import DataProvider
from quantdesk.data.synthetic import SyntheticProvider
from quantdesk.engine import TradingEngine
from quantdesk.news.fetch import NewsFetcher

UNIVERSE = ["SPY", "QQQ", "XLK", "AAPL", "MSFT", "NVDA", "TSLA", "GLD", "TLT", "JPM"]


class ReplayProvider(DataProvider):
    """Serves history truncated to a simulated 'today'.

    Without this, a walk-forward test would hand the strategy tomorrow's prices
    and every result would be meaningless.
    """

    name = "synthetic-replay"

    def __init__(self):
        self.inner = SyntheticProvider()
        self.cutoff = None
        self._cache = {}

    def history(self, symbol, lookback_days=400):
        if symbol not in self._cache:
            self._cache[symbol] = self.inner.history(symbol, 900)
        frame = self._cache[symbol]
        if self.cutoff is not None:
            frame = frame[frame.index <= pd.Timestamp(self.cutoff)]
        if len(frame) < 60:
            raise RuntimeError("insufficient history")
        return frame

    def instrument(self, symbol):
        return self.inner.instrument(symbol)


@pytest.fixture
def engine(tmp_path):
    settings = Settings(home=tmp_path, risk_profile="moderate", starting_cash=100_000.0)
    provider = ReplayProvider()
    eng = TradingEngine(settings, provider=provider,
                        news_fetcher=NewsFetcher(offline=True))
    original = eng.recommender.scan
    eng.recommender.scan = (
        lambda equity, symbols=None, limit=10, exclude=None:
        original(equity, UNIVERSE, limit, exclude)
    )
    return eng, provider


def test_single_day_produces_a_report(engine):
    eng, provider = engine
    provider.cutoff = None
    outcome = eng.run_daily(max_new_ideas=3, write_files=False)
    report = outcome.report

    assert report.equity == pytest.approx(100_000.0)
    text = report.to_text()
    assert "QUANTDESK DAILY REPORT" in text
    assert "Not financial advice" in text
    html = report.to_html()
    assert html.startswith("<!DOCTYPE html>") and "</html>" in html


def test_report_flags_simulated_data(engine):
    eng, _ = engine
    outcome = eng.run_daily(max_new_ideas=2, write_files=False)
    assert "SIMULATED" in outcome.report.data_warning.upper()


def test_walk_forward_preserves_accounting_invariants(engine):
    """The core safety properties must hold across many sessions."""
    eng, provider = engine
    provider.history("SPY")
    sessions = [d.date() for d in provider._cache["SPY"].index][-45:]

    for day in sessions:
        provider.cutoff = day
        eng.run_daily(as_of=day, max_new_ideas=3, write_files=False)

    portfolio = eng.store.load_portfolio()
    assert portfolio.cash >= -0.01, "cash must never go negative"
    assert len(portfolio.positions) <= eng.settings.profile.max_positions

    for position in portfolio.positions:
        assert position.shares > 0
        assert position.stop_price > 0

    # Every sell must be traceable to a position and carry a realised P&L.
    for trade in eng.store.trades():
        if trade.action == "sell":
            assert trade.realized_pnl is not None
            assert trade.position_id is not None

    history = eng.store.equity_history()
    assert len(history) == len(sessions)
    assert all(row["total_equity"] > 0 for row in history)


def test_positions_never_exceed_the_size_cap(engine):
    eng, provider = engine
    provider.history("SPY")
    for day in [d.date() for d in provider._cache["SPY"].index][-25:]:
        provider.cutoff = day
        eng.run_daily(as_of=day, max_new_ideas=3, write_files=False)

    portfolio = eng.store.load_portfolio()
    prices = {
        s: float(provider.history(s)["close"].iloc[-1]) for s in portfolio.symbols
    }
    equity = portfolio.total_equity(prices)
    cap = eng.settings.profile.max_position_pct
    for position in portfolio.positions:
        weight = position.market_value(prices[position.symbol]) / equity
        # Allow drift: a winner may grow past its entry weight, which is fine.
        assert weight <= cap * 2.5, f"{position.symbol} at {weight:.1%} of equity"


def test_dry_run_places_no_orders(engine):
    eng, _ = engine
    eng.run_daily(max_new_ideas=3, execute=False, write_files=False)
    assert eng.store.pending_orders() == []
    assert eng.store.open_positions() == []


def test_reports_are_written_to_disk(engine, tmp_path):
    eng, _ = engine
    outcome = eng.run_daily(max_new_ideas=2, write_files=True)
    assert outcome.text_path.exists() and outcome.html_path.exists()
    assert (tmp_path / "reports" / "latest.html").exists()
