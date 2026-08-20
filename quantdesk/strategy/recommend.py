"""Turning analysis into a ranked, diversified list of actionable ideas."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from quantdesk.analysis import indicators as ind
from quantdesk.analysis.trend import find_levels, nearest_levels
from quantdesk.config import RiskProfile, Settings
from quantdesk.data.base import DataProvider, Instrument
from quantdesk.news.fetch import NewsFetcher
from quantdesk.news.sentiment import SentimentAnalyzer, aggregate_news_sentiment
from quantdesk.strategy.regime import (
    MarketRegime, SECTOR_ETFS, SectorRanking, assess_regime, rank_sectors,
)
from quantdesk.strategy.risk import TradePlan, build_trade_plan
from quantdesk.strategy.signals import SignalReport, score_symbol
from quantdesk.strategy.universe import (
    BENCHMARK, INVERSE_SYMBOLS, inverse_proxy, universe_for,
)


@dataclass
class Recommendation:
    signal: SignalReport
    plan: TradePlan
    instrument: Instrument

    @property
    def symbol(self) -> str:
        """The instrument actually traded.

        For an inverse-ETF proxy this is the ETF, not the index the view is
        about - orders, position lookups and de-duplication must all key off
        what is really bought or sold.
        """
        return self.plan.symbol

    @property
    def view_symbol(self) -> str:
        """The symbol the market view is about (the index, for a proxy trade)."""
        return self.signal.symbol

    @property
    def score(self) -> float:
        return self.signal.score

    @property
    def direction(self) -> str:
        """How the trade is actually placed - buying an inverse ETF is a long."""
        return self.plan.direction

    @property
    def view(self) -> str:
        """The market view being expressed, regardless of how it is placed."""
        return self.signal.direction

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
    regime: MarketRegime | None = None
    sectors: SectorRanking | None = None

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
        # Inverse ETFs are never scanned as ordinary longs: they decay structurally,
        # so their own charts rarely show a clean uptrend even when they are exactly
        # the right instrument. They are reached only by substitution below.
        candidates = [
            s.upper() for s in dict.fromkeys(candidates)
            if s.upper() not in exclude and s.upper() not in INVERSE_SYMBOLS
        ]

        result = ScanResult(scanned=len(candidates))

        try:
            benchmark_bars = self.provider.history(BENCHMARK, 400)
        except Exception:
            benchmark_bars = None

        # Portfolio-level context, computed once and applied to every candidate.
        regime: MarketRegime | None = None
        sectors: SectorRanking | None = None
        if benchmark_bars is not None:
            try:
                regime = assess_regime(benchmark_bars)
            except Exception:
                regime = None
            try:
                sector_bars = self.provider.batch_history(list(SECTOR_ETFS), 400)
                sectors = rank_sectors(sector_bars, benchmark_bars)
            except Exception:
                sectors = None
        result.regime = regime
        result.sectors = sectors

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
                sector_bias=(
                    sectors.bias_for(instrument.sector) if sectors else 0.0
                ),
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
        result.recommendations = self._diversify(
            passing, equity, limit, exclude, regime
        )
        return result

    def _diversify(self, passing, equity: float, limit: int,
                   already_held: set[str] | None = None,
                   regime: MarketRegime | None = None) -> list[Recommendation]:
        """Rank by score while enforcing sector caps and the ETF/stock mix.

        Ten uncorrelated ideas beat ten correlated ones with better scores: if the
        whole book is semiconductors, it is really one position wearing ten hats.
        """
        max_per_sector = max(2, limit // 3)
        target_etfs = round(limit * self.profile.etf_target_pct)

        already_held = already_held or set()
        chosen: list[Recommendation] = []
        sector_counts: dict[str, int] = {}
        etf_count = 0
        short_count = 0

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

            # Scale the capital a trade is sized against by the market regime.
            # Exposure is scaled rather than switched: a binary gate whipsaws
            # around the 200-day line, while scaling steps risk down as
            # conditions deteriorate without betting everything on one close.
            if regime is not None:
                exposure = (
                    regime.short_exposure if report.direction == "short"
                    else regime.long_exposure
                )
            else:
                exposure = 1.0
            if exposure <= 0.0:
                continue
            sizing_equity = equity * exposure

            if report.direction == "short":
                if short_count >= self.profile.max_short_positions:
                    continue
                built = self._build_bearish_plan(report, bars, instrument, sizing_equity)
                if built is None:
                    continue
                plan, instrument = built
            else:
                plan = build_trade_plan(
                    symbol=report.symbol,
                    bars=bars,
                    enriched=(
                        report.enriched if report.enriched is not None
                        else ind.compute_all(bars)
                    ),
                    trend_state=report.trend,
                    profile=self.profile,
                    equity=sizing_equity,
                    setup=report.setup,
                    support_level=report.support,
                    resistance_level=report.resistance,
                    direction="long",
                )

            if not plan.is_actionable:
                continue
            if plan.symbol in already_held or any(c.symbol == plan.symbol for c in chosen):
                continue  # the traded instrument may differ from the scanned one

            chosen.append(Recommendation(report, plan, instrument))
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            etf_count += int(instrument.is_etf)
            short_count += int(report.direction == "short")

        return chosen

    def _build_bearish_plan(self, report, bars, instrument, equity):
        """Express a bearish view, either by buying an inverse ETF or shorting.

        Buying an inverse ETF is preferred where one exists and the profile asks
        for it: a cash account cannot short at all, and the loss is capped at the
        amount invested rather than being theoretically unlimited. The plan is
        built on the *inverse ETF's* own chart, because that is the instrument
        whose price the entry and stop orders will actually reference.
        """
        proxy = inverse_proxy(report.symbol) if self.profile.prefer_inverse_etf else None

        if proxy:
            try:
                proxy_bars = self.provider.history(proxy, 400)
                proxy_instrument = self.provider.instrument(proxy)
            except Exception:
                proxy = None
            else:
                proxy_enriched = ind.compute_all(proxy_bars)
                levels = find_levels(proxy_bars)
                support, resistance = nearest_levels(
                    levels, float(proxy_bars["close"].iloc[-1])
                )
                plan = build_trade_plan(
                    symbol=proxy,
                    bars=proxy_bars,
                    enriched=proxy_enriched,
                    trend_state=report.trend,
                    profile=self.profile,
                    equity=equity,
                    setup="reversal",
                    support_level=support.price if support else None,
                    resistance_level=resistance.price if resistance else None,
                    direction="long",
                    proxy_for=report.symbol,
                )
                return plan, proxy_instrument

        if not self.profile.allow_short:
            return None

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
            direction="short",
        )
        return plan, instrument


def _safe(fn, arg):
    """Run ``fn(arg)`` returning (payload, error_message)."""
    try:
        return fn(arg), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
