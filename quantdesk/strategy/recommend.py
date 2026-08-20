"""Turning analysis into a ranked, diversified list of actionable ideas."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from quantdesk.analysis import indicators as ind
from quantdesk.config import RiskProfile, Settings
from quantdesk.data.base import DataProvider, Instrument
from quantdesk.news.fetch import NewsFetcher
from quantdesk.news.sentiment import SentimentAnalyzer, aggregate_news_sentiment
from quantdesk.strategy.risk import TradePlan, build_trade_plan
from quantdesk.strategy.signals import SignalReport, score_symbol
from quantdesk.strategy.universe import BENCHMARK, universe_for


@dataclass
class Recommendation:
    signal: SignalReport
    plan: TradePlan
    instrument: Instrument

    @property
    def symbol(self) -> str:
        return self.signal.symbol

    @property
    def score(self) -> float:
        return self.signal.score

    def confidence_label(self) -> str:
        s = self.signal.score
        if s >= 75:
            return "high"
        if s >= 65:
            return "moderate"
        return "speculative"


@dataclass
class ScanResult:
    recommendations: list[Recommendation] = field(default_factory=list)
    rejected: list[SignalReport] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    used_synthetic_data: bool = False
    used_synthetic_news: bool = False
    scanned: int = 0

    @property
    def top_rejection_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for report in self.rejected:
            for veto in report.vetoes:
                key = veto.split(" - ")[0].split(":")[0][:60]
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


class Recommender:
    """Scans a universe and produces ranked, diversified trade ideas."""

    def __init__(
        self,
        provider: DataProvider,
        settings: Settings,
        news_fetcher: NewsFetcher | None = None,
        max_workers: int = 8,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.profile: RiskProfile = settings.profile
        self.news_fetcher = news_fetcher or NewsFetcher()
        self.analyzer = SentimentAnalyzer()
        self.max_workers = max_workers

    def scan(
        self,
        equity: float,
        symbols: list[str] | None = None,
        limit: int = 10,
        exclude: set[str] | None = None,
    ) -> ScanResult:
        exclude = {s.upper() for s in (exclude or set())}
        candidates = symbols or (
            universe_for(self.profile.name) + list(self.settings.watchlist)
        )
        candidates = [s.upper() for s in dict.fromkeys(candidates) if s.upper() not in exclude]

        result = ScanResult(scanned=len(candidates))

        try:
            benchmark_bars = self.provider.history(BENCHMARK, 400)
        except Exception:
            benchmark_bars = None

        def analyse(symbol: str):
            bars = self.provider.history(symbol, 400)
            instrument = self.provider.instrument(symbol)

            news_score = news_cov = 0.0
            news_summary = ""
            synthetic_news = False
            if self.settings.news_enabled:
                try:
                    articles = self.news_fetcher.fetch(
                        symbol,
                        self.settings.news_lookback_days,
                        self.settings.max_news_per_symbol,
                    )
                    sentiment = aggregate_news_sentiment(symbol, articles, self.analyzer)
                    news_score = sentiment.score
                    news_cov = sentiment.coverage
                    news_summary = sentiment.summary_line
                    synthetic_news = sentiment.is_synthetic
                except Exception:
                    news_summary = "news unavailable"

            report = score_symbol(
                symbol=symbol,
                bars=bars,
                profile=self.profile,
                benchmark_bars=benchmark_bars,
                news_score=news_score,
                news_coverage=news_cov,
                news_summary=news_summary,
                asset_type=instrument.asset_type,
            )
            return report, instrument, bars, synthetic_news

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            outcomes = list(pool.map(lambda s: (s, _safe(analyse, s)), candidates))

        passing: list[tuple[SignalReport, Instrument, object]] = []
        for symbol, (payload, error) in outcomes:
            if error is not None:
                result.errors[symbol] = error
                continue
            report, instrument, bars, synthetic_news = payload
            result.used_synthetic_news |= synthetic_news
            if report.is_actionable:
                passing.append((report, instrument, bars))
            else:
                result.rejected.append(report)

        result.used_synthetic_data = "synthetic" in getattr(self.provider, "name", "")

        passing.sort(key=lambda t: -t[0].score)
        result.recommendations = self._diversify(passing, equity, limit)
        return result

    def _diversify(self, passing, equity: float, limit: int) -> list[Recommendation]:
        """Rank by score while enforcing sector caps and the ETF/stock mix.

        Ten uncorrelated ideas beat ten correlated ones with better scores: if the
        whole book is semiconductors, it is really one position wearing ten hats.
        """
        max_per_sector = max(2, limit // 3)
        target_etfs = round(limit * self.profile.etf_target_pct)

        chosen: list[Recommendation] = []
        sector_counts: dict[str, int] = {}
        etf_count = 0

        for report, instrument, bars in passing:
            if len(chosen) >= limit:
                break

            sector = instrument.sector or "Unknown"
            if sector != "ETF" and sector_counts.get(sector, 0) >= max_per_sector:
                continue

            remaining = limit - len(chosen)
            etfs_still_needed = max(0, target_etfs - etf_count)
            if not instrument.is_etf and remaining <= etfs_still_needed:
                continue  # reserve the last slots for fund exposure

            plan = build_trade_plan(
                symbol=report.symbol,
                bars=bars,
                enriched=(
                    report.enriched if report.enriched is not None
                    else ind.compute_all(bars)
                ),
                trend_state=report.trend,
                profile=self.profile,
                equity=equity,
                setup=report.setup,
                support_level=report.support,
                resistance_level=report.resistance,
            )
            if not plan.is_actionable:
                continue

            chosen.append(Recommendation(report, plan, instrument))
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            etf_count += int(instrument.is_etf)

        return chosen


def _safe(fn, arg):
    """Run ``fn(arg)`` returning (payload, error_message)."""
    try:
        return fn(arg), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
