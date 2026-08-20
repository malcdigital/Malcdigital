"""Preflight checks.

The desk is designed to keep working when the network does not, by falling back
to generated prices. That is the right behaviour for a demo and the wrong thing
to discover halfway through a month of "real" paper trading. These checks answer
one question plainly: **is this machine actually getting live market data?**
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    fatal: bool = False
    """A failure here means live data is not available at all."""


@dataclass
class Diagnosis:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def live_data_available(self) -> bool:
        return any(c.ok for c in self.checks if c.fatal)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def _check_python(diagnosis: Diagnosis) -> None:
    version = sys.version_info
    ok = version >= (3, 10)
    diagnosis.add(Check(
        "Python version",
        ok,
        f"{platform.python_version()} on {platform.system()}",
        fix="QuantDesk needs Python 3.10 or newer." if not ok else "",
    ))


def _check_packages(diagnosis: Diagnosis) -> None:
    for package, required in (("pandas", True), ("numpy", True),
                              ("requests", True), ("yfinance", False)):
        try:
            module = __import__(package)
            version = getattr(module, "__version__", "unknown")
            diagnosis.add(Check(f"package: {package}", True, f"v{version}"))
        except ImportError:
            diagnosis.add(Check(
                f"package: {package}", False, "not installed",
                fix=f"pip install {package}",
            ))


def _check_yahoo(diagnosis: Diagnosis) -> None:
    try:
        from quantdesk.data.yahoo import YahooProvider

        bars = YahooProvider().history("SPY", 30)
        last = bars.index[-1].date()
        close = float(bars["close"].iloc[-1])
        staleness = (date.today() - last).days
        fresh = staleness <= 5  # allow a long weekend plus a holiday
        diagnosis.add(Check(
            "Yahoo Finance (live prices)",
            fresh,
            f"SPY closed ${close:,.2f} on {last} ({len(bars)} bars, "
            f"{staleness}d old)",
            fix=("Data is stale - the market may be closed, or the feed is "
                 "lagging. Re-run during a trading day." if not fresh else ""),
            fatal=True,
        ))
    except Exception as exc:
        diagnosis.add(Check(
            "Yahoo Finance (live prices)", False, f"{type(exc).__name__}: {exc}",
            fix="pip install --upgrade yfinance, and check your network/firewall.",
            fatal=True,
        ))


def _check_stooq(diagnosis: Diagnosis) -> None:
    try:
        from quantdesk.data.stooq import StooqProvider

        bars = StooqProvider().history("SPY", 30)
        diagnosis.add(Check(
            "Stooq (fallback prices)", True,
            f"SPY closed ${float(bars['close'].iloc[-1]):,.2f} "
            f"on {bars.index[-1].date()}",
            fatal=True,
        ))
    except Exception as exc:
        diagnosis.add(Check(
            "Stooq (fallback prices)", False, f"{type(exc).__name__}: {exc}",
            fix="Optional - only used if Yahoo is unavailable.",
            fatal=True,
        ))


def _check_news(diagnosis: Diagnosis) -> None:
    try:
        from quantdesk.news.fetch import NewsFetcher

        articles = NewsFetcher(timeout=15).fetch("AAPL", 7, 10)
        synthetic = all("synthetic" in a.source for a in articles)
        if not articles:
            diagnosis.add(Check("News feed", False, "no articles returned",
                                fix="Sentiment will score neutral for every symbol."))
        elif synthetic:
            diagnosis.add(Check(
                "News feed", False, "fell back to placeholder headlines",
                fix="Live news is unreachable; sentiment will not reflect reality.",
            ))
        else:
            newest = min(a.age_days for a in articles)
            diagnosis.add(Check(
                "News feed", True,
                f"{len(articles)} live articles from "
                f"{', '.join(sorted({a.source for a in articles}))} "
                f"(newest {newest * 24:.0f}h old)",
            ))
    except Exception as exc:
        diagnosis.add(Check("News feed", False, f"{type(exc).__name__}: {exc}",
                            fix="Sentiment will score neutral for every symbol."))


def _check_resolved_provider(diagnosis: Diagnosis) -> None:
    """Report which source `--provider auto` would actually use."""
    try:
        from quantdesk.data import get_provider

        provider = get_provider("auto")
        bars = provider.history("SPY", 60)
        used = "unknown"
        for candidate in provider.providers:
            try:
                candidate.history("SPY", 30)
                used = candidate.name
                break
            except Exception:
                continue
        real = used not in ("synthetic", "unknown")
        diagnosis.add(Check(
            "Resolved data source", real,
            f"'auto' resolves to: {used}",
            fix=("Reports would be based on GENERATED prices, not the market. "
                 "Fix the feed above, or run with --strict to refuse to start."
                 if not real else ""),
        ))
    except Exception as exc:
        diagnosis.add(Check("Resolved data source", False,
                            f"{type(exc).__name__}: {exc}"))


def run_diagnostics(include_news: bool = True) -> Diagnosis:
    diagnosis = Diagnosis()
    _check_python(diagnosis)
    _check_packages(diagnosis)
    _check_yahoo(diagnosis)
    _check_stooq(diagnosis)
    if include_news:
        _check_news(diagnosis)
    _check_resolved_provider(diagnosis)
    return diagnosis
