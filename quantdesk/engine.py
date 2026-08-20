"""The daily cycle that ties every component together.

One run of :meth:`TradingEngine.run_daily` is a complete trading day:

1. Refresh prices for everything held or on order.
2. Let the broker manage open positions - stops, targets, trailing, time stops.
3. Fill or expire working orders against today's bar.
4. Re-scan the universe for new ideas, sized to current equity.
5. Place working orders for tomorrow.
6. Snapshot equity and write the report.

Steps 2 and 3 run before 4 so that capital freed by an exit is available to the
same day's new ideas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from quantdesk.broker.paper import PaperBroker
from quantdesk.config import Settings
from quantdesk.data import get_provider
from quantdesk.data.base import DataProvider
from quantdesk.news.fetch import NewsFetcher
from quantdesk.portfolio.metrics import compute_performance
from quantdesk.portfolio.report import DailyReport
from quantdesk.portfolio.store import PortfolioStore
from quantdesk.strategy.recommend import Recommender, ScanResult


@dataclass
class RunOutcome:
    report: DailyReport
    scan: ScanResult
    text_path: Path | None = None
    html_path: Path | None = None


class TradingEngine:
    def __init__(
        self,
        settings: Settings,
        provider: DataProvider | None = None,
        news_fetcher: NewsFetcher | None = None,
    ) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.provider = provider or get_provider(
            settings.data_provider, settings.cache_dir
        )
        self.store = PortfolioStore(settings.db_path)
        self.store.initialise(settings.starting_cash)
        self.broker = PaperBroker(self.store, settings)
        self.news = news_fetcher or NewsFetcher()
        self.recommender = Recommender(self.provider, settings, self.news)

    # --- helpers ------------------------------------------------------------
    def _bars_for(self, symbols: set[str]) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                out[symbol] = self.provider.history(symbol, 400)
            except Exception:
                continue
        return out

    def _latest_prices(self, bars: dict[str, pd.DataFrame]) -> dict[str, float]:
        return {
            sym: float(df["close"].iloc[-1])
            for sym, df in bars.items()
            if df is not None and not df.empty
        }

    def current_equity(self) -> float:
        portfolio = self.store.load_portfolio()
        if not portfolio.positions:
            return portfolio.cash
        bars = self._bars_for(portfolio.symbols)
        return portfolio.total_equity(self._latest_prices(bars))

    # --- the daily cycle ----------------------------------------------------
    def run_daily(
        self,
        as_of: date | None = None,
        max_new_ideas: int = 5,
        execute: bool = True,
        write_files: bool = True,
    ) -> RunOutcome:
        as_of = as_of or date.today()

        # 1-3. Manage what is already on the book.
        portfolio = self.store.load_portfolio()
        watched = portfolio.symbols | {o.symbol for o in self.store.pending_orders()}
        bars = self._bars_for(watched)
        summary = (
            self.broker.process_day(bars, as_of)
            if execute
            else type("Empty", (), {"events": []})()
        )

        # 4. Look for new ideas, sized against equity after today's activity.
        portfolio = self.store.load_portfolio()
        bars.update(self._bars_for(portfolio.symbols - set(bars)))
        prices = self._latest_prices(bars)
        equity = portfolio.total_equity(prices)

        room = max(0, self.settings.profile.max_positions - len(portfolio.positions))
        pending = {o.symbol for o in self.store.pending_orders()}
        scan = ScanResult()
        if room > 0:
            scan = self.recommender.scan(
                equity=equity,
                limit=min(max_new_ideas, room),
                exclude=portfolio.symbols | pending,
            )

        # 5. Place working orders for the next session.
        if execute:
            for rec in scan.recommendations:
                event = self.broker.place_from_plan(rec.plan, as_of)
                summary.events.append(event)

        # 6. Snapshot and report.
        portfolio = self.store.load_portfolio()
        missing = portfolio.symbols - set(prices)
        if missing:
            bars.update(self._bars_for(missing))
            prices = self._latest_prices(bars)
        positions_value = portfolio.positions_value(prices)
        equity = portfolio.cash + positions_value

        self.store.snapshot_equity(
            as_of, portfolio.cash, positions_value, len(portfolio.positions)
        )

        history = [row["total_equity"] for row in self.store.equity_history()]
        unrealized = sum(
            p.unrealized_pnl(prices.get(p.symbol, p.entry_price))
            for p in portfolio.positions
        )
        performance = compute_performance(
            trades=self.store.trades(),
            equity_curve=history,
            starting_cash=self.store.starting_cash,
            current_equity=equity,
            unrealized_pnl=unrealized,
        )

        warning = ""
        if scan.used_synthetic_data:
            warning = (
                "SIMULATED PRICE DATA - live market data was unavailable, so this "
                "run used generated prices. Figures here do not reflect the real "
                "market."
            )
        elif scan.used_synthetic_news:
            warning = (
                "Live news was unavailable; sentiment used placeholder headlines "
                "for some symbols."
            )

        report = DailyReport(
            as_of=as_of,
            portfolio=portfolio,
            prices=prices,
            performance=performance,
            events=list(summary.events),
            recommendations=scan.recommendations,
            equity=equity,
            positions_value=positions_value,
            risk_profile=self.settings.profile.label,
            data_warning=warning,
        )

        text_path = html_path = None
        if write_files:
            reports = self.settings.reports_dir
            reports.mkdir(parents=True, exist_ok=True)
            text_path = reports / f"{as_of.isoformat()}.txt"
            html_path = reports / f"{as_of.isoformat()}.html"
            text_path.write_text(report.to_text(), encoding="utf-8")
            html_path.write_text(report.to_html(), encoding="utf-8")
            (reports / "latest.html").write_text(report.to_html(), encoding="utf-8")

        return RunOutcome(report, scan, text_path, html_path)
