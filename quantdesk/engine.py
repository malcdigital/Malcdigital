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

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from quantdesk.broker.paper import ExecutionEvent, PaperBroker
from quantdesk.config import Settings
from quantdesk.data import get_provider
from quantdesk.data.base import DataProvider
from quantdesk.news.fetch import NewsFetcher
from quantdesk.portfolio.metrics import compute_performance
from quantdesk.portfolio.report import DailyReport
from quantdesk.portfolio.store import PortfolioStore, Proposal
from quantdesk.broker.paper import ORDER_LIFETIME_DAYS
from quantdesk.strategy.recommend import Recommender, ScanResult
from quantdesk.strategy.risk import Target, TradePlan


@dataclass
class RunOutcome:
    report: DailyReport
    scan: ScanResult
    text_path: Path | None = None
    html_path: Path | None = None
    proposals: list = field(default_factory=list)
    """Ideas queued for approval, when running in manual mode."""


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

    # --- approval workflow --------------------------------------------------
    def _proposal_from(self, rec, as_of: date) -> Proposal:
        """Freeze a recommendation into a reviewable proposal.

        The full plan is captured rather than a reference to it, so approving
        tomorrow acts on exactly what was reviewed today.
        """
        plan = rec.plan
        return Proposal(
            symbol=plan.symbol,
            direction=plan.direction,
            proxy_for=plan.proxy_for,
            setup=plan.setup,
            entry_style=plan.entry_style,
            entry_price=plan.entry_price,
            stop_price=plan.stop_price,
            targets=[(t.price, t.take_pct) for t in plan.targets],
            shares=plan.shares,
            risk_dollars=plan.risk_dollars,
            position_value=plan.position_value,
            score=rec.score,
            time_stop_days=plan.time_stop_days,
            rationale=" | ".join(rec.signal.reasons[:4]),
            instructions="\n".join(plan.instructions()),
            created_date=as_of,
            expires_date=as_of + timedelta(days=self.settings.proposal_lifetime_days),
        )

    def approve_proposal(self, proposal_id: int, as_of: date | None = None):
        """Approve a queued idea and place it as a working order.

        Returns (proposal, event) or (None, None) if it was not pending - an
        already-decided proposal must not be actionable a second time.
        """
        as_of = as_of or date.today()
        proposal = self.store.decide_proposal(proposal_id, "approved")
        if proposal is None:
            return None, None

        plan = TradePlan(
            symbol=proposal.symbol,
            setup=proposal.setup,
            entry_style=proposal.entry_style,
            entry_price=proposal.entry_price,
            entry_condition="approved from the review queue",
            stop_price=proposal.stop_price,
            stop_reason="",
            targets=[Target(price=p, r_multiple=0.0, take_pct=f)
                     for p, f in proposal.targets],
            shares=proposal.shares,
            sizing_note="",
            risk_dollars=proposal.risk_dollars,
            position_value=proposal.position_value,
            equity_pct=0.0,
            trail_rule="",
            time_stop_days=proposal.time_stop_days,
            direction=proposal.direction,
            proxy_for=proposal.proxy_for,
        )
        event = self.broker.place_from_plan(plan, as_of)
        return proposal, event

    def reject_proposal(self, proposal_id: int):
        return self.store.decide_proposal(proposal_id, "rejected")

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

        # 5. Either place working orders, or queue the ideas for approval.
        queued: list[Proposal] = []
        if execute:
            self.store.expire_proposals(as_of)
            if self.settings.execution_mode == "manual":
                pending = {p.symbol for p in self.store.proposals("pending")}
                for rec in scan.recommendations:
                    if rec.symbol in pending:
                        continue
                    proposal = self._proposal_from(rec, as_of)
                    proposal.id = self.store.add_proposal(proposal)
                    queued.append(proposal)
                    summary.events.append(ExecutionEvent(
                        "queued", rec.symbol,
                        f"queued for approval: {rec.plan.direction} "
                        f"{rec.plan.shares} @ ${rec.plan.entry_price:,.2f}, "
                        f"stop ${rec.plan.stop_price:,.2f}",
                        shares=rec.plan.shares, price=rec.plan.entry_price,
                    ))
            else:
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

        return RunOutcome(report, scan, text_path, html_path, queued)
