"""Walk-forward backtesting.

A backtest is the only way to find out whether the rules in this repository do
anything useful, and it is also the easiest thing in quantitative finance to get
flatteringly wrong. Three commitments keep this one honest:

**No look-ahead.** Each simulated session sees only bars dated on or before that
day. The provider truncates, so there is no way for a signal to consult a price
that had not printed yet - the single most common way a backtest reports returns
that cannot be earned.

**The same code as live.** Scoring, sizing, plan construction and execution all
run through the production path. A backtest with its own simplified fill logic
measures the simplified logic, not the strategy you would actually run.

**A benchmark.** Absolute return means nothing on its own. Beating cash while
losing to buy-and-hold is a losing strategy that looks like a winning one, so
the benchmark is computed on the same window and reported alongside - including
when it wins.

Precomputed indicator frames are reused across sessions. Every indicator
involved is backward-looking, so a frame sliced to a window is identical to one
computed from that window; this is a speed optimisation with no effect on the
result, which the tests pin down.
"""

from __future__ import annotations

import math
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from quantdesk.analysis import indicators as ind
from quantdesk.analysis.timeframe import to_weekly
from quantdesk.broker.paper import PaperBroker
from quantdesk.config import Settings
from quantdesk.data.base import DataProvider, Instrument
from quantdesk.news.fetch import NewsFetcher
from quantdesk.portfolio.store import PortfolioStore
from quantdesk.strategy.recommend import Recommender
from quantdesk.strategy.universe import BENCHMARK

TRADING_DAYS = 252


# --- precomputation -----------------------------------------------------------
class PrecomputedCache:
    """Backward-looking frames computed once per symbol and sliced per session."""

    def __init__(self) -> None:
        self._daily: dict[str, pd.DataFrame] = {}
        self._weekly: dict[str, pd.DataFrame] = {}
        self._weekly_enriched: dict[str, pd.DataFrame] = {}

    def prime(self, symbol: str, full_bars: pd.DataFrame) -> None:
        symbol = symbol.upper()
        try:
            self._daily[symbol] = ind.compute_all(full_bars)
            weekly = to_weekly(full_bars)
            self._weekly[symbol] = weekly
            if len(weekly) >= 30:
                self._weekly_enriched[symbol] = ind.compute_all(weekly)
        except Exception:
            # A symbol that cannot be primed simply falls back to computing per
            # session; correctness does not depend on the cache.
            self._daily.pop(symbol, None)

    def get(self, symbol: str, bars: pd.DataFrame):
        """Return frames sliced to exactly the window ``bars`` covers."""
        symbol = symbol.upper()
        daily = self._daily.get(symbol)
        if daily is None or bars is None or bars.empty:
            return None, None, None

        cutoff = bars.index[-1]
        enriched = daily.loc[:cutoff]
        if len(enriched) != len(bars):
            return None, None, None  # windows disagree; recompute rather than guess

        weekly = self._weekly.get(symbol)
        weekly_enriched = self._weekly_enriched.get(symbol)
        if weekly is not None:
            weekly = weekly.loc[:cutoff]
            if weekly_enriched is not None:
                weekly_enriched = weekly_enriched.loc[:cutoff]
                if len(weekly_enriched) != len(weekly):
                    weekly_enriched = None
        return enriched, weekly, weekly_enriched


class ReplayProvider(DataProvider):
    """Serves history truncated to the simulated 'today'."""

    name = "replay"

    #: Effectively "everything the source has" - about twenty-four years, more
    #: than any free feed serves. A backtest that silently truncated to a few
    #: years would discard history the user deliberately fetched, and would do
    #: it without saying so. Providers that generate rather than retrieve cap
    #: themselves, so this cannot be turned into a request to fabricate.
    FULL_HISTORY = 6_000

    def __init__(self, source: DataProvider, symbols: list[str], lookback: int = FULL_HISTORY):
        self.source = source
        self.cutoff: pd.Timestamp | None = None
        self._full: dict[str, pd.DataFrame] = {}
        self._instruments: dict[str, Instrument] = {}
        for symbol in symbols:
            try:
                self._full[symbol.upper()] = source.history(symbol, lookback)
            except Exception:
                continue

    @property
    def loaded(self) -> list[str]:
        return sorted(self._full)

    def full_history(self, symbol: str) -> pd.DataFrame | None:
        return self._full.get(symbol.upper())

    def history(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        frame = self._full.get(symbol.upper())
        if frame is None:
            raise RuntimeError(f"{symbol} not loaded")
        if self.cutoff is not None:
            frame = frame.loc[:self.cutoff]
        if len(frame) < 60:
            raise RuntimeError(f"{symbol} has too little history at {self.cutoff}")
        return frame

    def instrument(self, symbol: str) -> Instrument:
        key = symbol.upper()
        if key not in self._instruments:
            try:
                self._instruments[key] = self.source.instrument(key)
            except Exception:
                self._instruments[key] = Instrument(symbol=key)
        return self._instruments[key]


# --- configuration and results ------------------------------------------------
@dataclass
class BacktestConfig:
    symbols: list[str]
    start: date | None = None
    end: date | None = None
    starting_cash: float = 100_000.0
    risk_profile: str = "moderate"
    max_new_ideas: int = 4
    scan_every: int = 1
    """Sessions between idea scans. Positions are still managed every session."""

    benchmark: str = BENCHMARK
    news: bool = False
    """Historical news is not available from the free feeds, and scoring today's
    headlines against a 2019 bar would be look-ahead of the worst kind. Off by
    default and documented rather than quietly faked."""


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    benchmark_curve: list[tuple[date, float]] = field(default_factory=list)
    trades: list = field(default_factory=list)
    sessions: int = 0
    elapsed_seconds: float = 0.0
    metrics: "BacktestMetrics | None" = None
    benchmark_metrics: "BacktestMetrics | None" = None
    scanned_sessions: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else 0.0


@dataclass
class BacktestMetrics:
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    volatility_pct: float
    closed_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    exposure_pct: float = 0.0
    """Share of sessions with at least one position open."""


def _returns(values: list[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if len(array) < 2:
        return np.array([])
    prior = array[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(prior > 0, array[1:] / prior - 1.0, 0.0)
    return out[np.isfinite(out)]


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst * 100.0


def compute_metrics(
    curve: list[tuple[date, float]],
    trades: list | None = None,
    exposure_sessions: int = 0,
) -> BacktestMetrics:
    """Summarise an equity curve, and the trade log when there is one."""
    values = [v for _, v in curve]
    if len(values) < 2:
        return BacktestMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    total_return = (values[-1] / values[0] - 1.0) * 100.0 if values[0] > 0 else 0.0
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1e-9)
    cagr = (
        ((values[-1] / values[0]) ** (1 / years) - 1.0) * 100.0
        if values[0] > 0 and values[-1] > 0 else 0.0
    )

    returns = _returns(values)
    volatility = float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS) * 100.0) if len(returns) > 1 else 0.0
    mean = float(returns.mean()) if len(returns) else 0.0
    sd = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = (mean / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0

    # Sortino punishes only downside deviation - upside volatility is not risk.
    downside = returns[returns < 0]
    dd = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mean / dd * math.sqrt(TRADING_DAYS)) if dd > 0 else 0.0

    metrics = BacktestMetrics(
        total_return_pct=round(total_return, 2),
        cagr_pct=round(cagr, 2),
        max_drawdown_pct=round(_max_drawdown(values), 2),
        sharpe=round(sharpe, 2),
        sortino=round(sortino, 2),
        volatility_pct=round(volatility, 2),
        exposure_pct=round(exposure_sessions / max(1, len(values)) * 100.0, 1),
    )

    # Per position, not per exit. Winners get scaled out of and losers get
    # closed in one go, so counting exit events measures every win on a
    # part-position and every loss on a whole one - which inverted the win/loss
    # ratio on a nine-year run and made a working exit design look broken.
    from quantdesk.analysis.trades import build_round_trips

    closed = [t for t in build_round_trips(trades or []) if t.fully_closed]
    if closed:
        pnls = [t.pnl for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_win, gross_loss = sum(wins), abs(sum(losses))
        metrics.closed_trades = len(pnls)
        metrics.win_rate = round(len(wins) / len(pnls) * 100.0, 1)
        metrics.avg_win = round(gross_win / len(wins), 2) if wins else 0.0
        metrics.avg_loss = round(gross_loss / len(losses), 2) if losses else 0.0
        metrics.profit_factor = (
            round(gross_win / gross_loss, 2) if gross_loss > 0
            else (float("inf") if gross_win > 0 else 0.0)
        )
        metrics.expectancy = round(sum(pnls) / len(pnls), 2)
        metrics.best_trade = round(max(pnls), 2)
        metrics.worst_trade = round(min(pnls), 2)
    return metrics


def buy_and_hold(bars: pd.DataFrame, sessions: list[date], cash: float) -> list[tuple[date, float]]:
    """The benchmark: buy at the first session and hold to the last."""
    if bars is None or bars.empty or not sessions:
        return []
    closes = bars["close"]
    first = closes.loc[:pd.Timestamp(sessions[0])]
    if first.empty:
        return []
    shares = cash / float(first.iloc[-1])

    curve: list[tuple[date, float]] = []
    for session in sessions:
        window = closes.loc[:pd.Timestamp(session)]
        if window.empty:
            continue
        curve.append((session, shares * float(window.iloc[-1])))
    return curve


class Backtester:
    """Replays the strategy session by session over historical bars."""

    def __init__(
        self,
        provider: DataProvider,
        config: BacktestConfig,
        settings: Settings | None = None,
    ) -> None:
        self.config = config
        self.settings = settings or Settings(risk_profile=config.risk_profile)
        self.settings.risk_profile = config.risk_profile
        self.settings.starting_cash = config.starting_cash
        self.settings.news_enabled = config.news
        # Ideas are executed directly: an approval queue has no meaning when
        # there is nobody to approve.
        self.settings.execution_mode = "auto"
        self.source = provider

    def run(self, progress=None) -> BacktestResult:
        started = time.monotonic()
        config = self.config
        result = BacktestResult(config=config)

        symbols = [s.upper() for s in dict.fromkeys(config.symbols)]
        needed = list(dict.fromkeys(symbols + [config.benchmark]))
        replay = ReplayProvider(self.source, needed)

        missing = [s for s in symbols if s not in replay.loaded]
        if missing:
            result.warnings.append(
                f"{len(missing)} symbol(s) could not be loaded and were skipped: "
                + ", ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
            )
        tradable = [s for s in symbols if s in replay.loaded]
        if not tradable:
            result.warnings.append("no symbols could be loaded - nothing to test")
            result.elapsed_seconds = round(time.monotonic() - started, 2)
            return result

        cache = PrecomputedCache()
        for symbol in replay.loaded:
            cache.prime(symbol, replay.full_history(symbol))

        sessions = self._sessions(replay, tradable)
        if len(sessions) < 30:
            result.warnings.append(
                f"only {len(sessions)} sessions in range - far too short to mean anything"
            )
        if not sessions:
            result.elapsed_seconds = round(time.monotonic() - started, 2)
            return result

        db = Path(tempfile.mkdtemp()) / "backtest.db"
        store = PortfolioStore(db)
        store.initialise(config.starting_cash, force=True)
        broker = PaperBroker(store, self.settings)
        recommender = Recommender(
            replay, self.settings, NewsFetcher(offline=True), precomputer=cache
        )

        exposure_sessions = 0
        scanned = 0

        for index, session in enumerate(sessions):
            replay.cutoff = pd.Timestamp(session)

            portfolio = store.load_portfolio()
            watched = portfolio.symbols | {o.symbol for o in store.pending_orders()}
            bars = self._bars_for(replay, watched)
            broker.process_day(bars, session)

            do_scan = (index % max(1, config.scan_every)) == 0
            portfolio = store.load_portfolio()
            prices = self._prices(replay, portfolio.symbols)
            equity = portfolio.total_equity(prices)

            if do_scan:
                room = max(0, self.settings.profile.max_positions - len(portfolio.positions))
                if room > 0:
                    pending = {o.symbol for o in store.pending_orders()}
                    scan = recommender.scan(
                        equity=equity,
                        symbols=tradable,
                        limit=min(config.max_new_ideas, room),
                        exclude=portfolio.symbols | pending,
                    )
                    for rec in scan.recommendations:
                        broker.place_from_plan(rec.plan, session)
                scanned += 1

            portfolio = store.load_portfolio()
            prices = self._prices(replay, portfolio.symbols)
            equity = portfolio.total_equity(prices)
            result.equity_curve.append((session, round(equity, 2)))
            if portfolio.positions:
                exposure_sessions += 1

            if progress is not None and (index % 20 == 0 or index == len(sessions) - 1):
                progress(index + 1, len(sessions), equity)

        result.sessions = len(sessions)
        result.scanned_sessions = scanned
        result.trades = store.trades(limit=100_000)
        result.metrics = compute_metrics(
            result.equity_curve, result.trades, exposure_sessions
        )

        benchmark_bars = replay.full_history(config.benchmark)
        if benchmark_bars is not None:
            result.benchmark_curve = buy_and_hold(
                benchmark_bars, sessions, config.starting_cash
            )
            result.benchmark_metrics = compute_metrics(result.benchmark_curve)
        else:
            result.warnings.append(
                f"benchmark {config.benchmark} unavailable - no comparison possible"
            )

        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    # --- helpers ----------------------------------------------------------
    def _sessions(self, replay: ReplayProvider, symbols: list[str]) -> list[date]:
        """Trading sessions common to the loaded data, within the configured range.

        The first year of history is reserved as warm-up: a 200-day average does
        not exist before then, and starting earlier would test the indicators'
        NaN handling rather than the strategy.
        """
        frames = [replay.full_history(s) for s in symbols]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return []

        index = frames[0].index
        for frame in frames[1:]:
            index = index.union(frame.index)

        warmup = 260
        usable = index[warmup:] if len(index) > warmup else index[len(index) // 2:]
        sessions = [ts.date() for ts in usable]
        if self.config.start:
            sessions = [d for d in sessions if d >= self.config.start]
        if self.config.end:
            sessions = [d for d in sessions if d <= self.config.end]
        return sessions

    @staticmethod
    def _bars_for(replay: ReplayProvider, symbols) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                out[symbol] = replay.history(symbol, 400)
            except Exception:
                continue
        return out

    @classmethod
    def _prices(cls, replay: ReplayProvider, symbols) -> dict[str, float]:
        return {
            sym: float(frame["close"].iloc[-1])
            for sym, frame in cls._bars_for(replay, symbols).items()
        }


# --- verdict ------------------------------------------------------------------
def verdict(result: BacktestResult) -> list[str]:
    """A plain-English read on the result, written to disappoint where warranted.

    A backtest's job is to talk you out of things. Every branch that could
    flatter the strategy is paired with the reason it might be wrong, because
    the failure mode here is not a bad number - it is a good number believed.
    """
    lines: list[str] = []
    metrics = result.metrics
    benchmark = result.benchmark_metrics
    if metrics is None:
        return ["No result to judge."]

    # 1. Sample size, before anything else.
    if metrics.closed_trades < 30:
        lines.append(
            f"Only {metrics.closed_trades} closed trades. That is noise, not "
            "evidence - a run this short can look like anything. Nothing below "
            "means much until there are several hundred."
        )
    years = 0.0
    if result.equity_curve:
        years = (result.equity_curve[-1][0] - result.equity_curve[0][0]).days / 365.25
    if years < 3:
        lines.append(
            f"The window is {years:.1f} years. One market regime is not a test - "
            "a trend-following strategy tested only in a bull market will always "
            "look good."
        )

    # 2. The comparison that actually decides it.
    if benchmark is not None:
        gap = metrics.total_return_pct - benchmark.total_return_pct
        if gap < -1:
            lines.append(
                f"LOST TO BUY-AND-HOLD by {abs(gap):.1f} percentage points "
                f"({metrics.total_return_pct:+.1f}% versus {benchmark.total_return_pct:+.1f}%). "
                "All the machinery in this repository did worse than buying the "
                "index and doing nothing. That is the result, however good the "
                "other numbers look."
            )
            if metrics.max_drawdown_pct > benchmark.max_drawdown_pct + 5:
                lines.append(
                    f"It did take materially less risk on the way "
                    f"({metrics.max_drawdown_pct:.1f}% worst drawdown versus "
                    f"{benchmark.max_drawdown_pct:.1f}%), which is worth something "
                    "if you would not have held through the benchmark's decline. "
                    "Most people believe they would have, and most did not."
                )
        elif gap > 1:
            lines.append(
                f"Beat buy-and-hold by {gap:.1f} percentage points "
                f"({metrics.total_return_pct:+.1f}% versus {benchmark.total_return_pct:+.1f}%). "
                "Treat that as a hypothesis, not a finding: these rules were "
                "written and tuned with this data available, so some of the edge "
                "is hindsight."
            )
        else:
            lines.append(
                "Finished level with buy-and-hold, which means the strategy added "
                "activity and cost without adding return."
            )

    # 3. Risk-adjusted reading.
    if metrics.sharpe >= 1.0 and metrics.closed_trades >= 30:
        # Low volatility flatters Sharpe, but the reason matters: sitting in
        # cash and holding small positions look identical in the ratio and are
        # completely different things to do with an account.
        if metrics.exposure_pct >= 70:
            source = (
                f"a position was open on {metrics.exposure_pct:.0f}% of sessions, "
                "so that comes from position sizes being small relative to the "
                "account rather than from sitting in cash"
            )
        else:
            source = (
                f"the book was empty on {100 - metrics.exposure_pct:.0f}% of "
                "sessions, so much of it comes from simply not being invested"
            )
        lines.append(
            f"Sharpe {metrics.sharpe:.2f} on {metrics.volatility_pct:.1f}% "
            f"volatility. Low volatility flatters the ratio, and {source}."
        )
    elif metrics.sharpe < 0.3 and metrics.closed_trades >= 30:
        lines.append(
            f"Sharpe {metrics.sharpe:.2f} - the returns are not compensating for "
            "the variance taken to get them."
        )

    # 4. Trade quality.
    if metrics.closed_trades >= 30:
        if metrics.profit_factor >= 1.5:
            lines.append(
                f"Profit factor {metrics.profit_factor:.2f} with a "
                f"{metrics.win_rate:.0f}% win rate and ${metrics.expectancy:,.2f} "
                "expected per trade."
            )
        elif metrics.profit_factor < 1.0:
            lines.append(
                f"Profit factor {metrics.profit_factor:.2f}: losses outweigh wins. "
                "The rules need changing before this is worth running at all."
            )

    if metrics.max_drawdown_pct < -25:
        lines.append(
            f"Worst drawdown {metrics.max_drawdown_pct:.1f}%. Ask honestly whether "
            "you would have kept following the rules through that, because the "
            "backtest assumes you would have."
        )

    lines.append(
        "Simulated results are not real results: no slippage on thin names, no "
        "borrow costs, no halts, no partial fills, no tax, and no you watching "
        "the account go down."
    )
    return lines
