"""Wide-market screening.

The curated universe is fast and safe but structurally blind: it can only ever
surface names someone thought to list. Screening thousands of symbols finds what
the list misses, at a cost that has to be managed rather than wished away.

Two costs dominate, and both are handled here rather than left to bite at
runtime:

* **Time.** Full analysis of one symbol is tens of milliseconds, so thousands of
  them is minutes, most of it spent on names that fail on liquidity alone. The
  screen is therefore staged: a cheap pass on recent bars rejects the bulk, and
  only survivors get the expensive full scoring.

* **Rate limits.** Free data endpoints throttle aggressively. Fetches are
  chunked with a pause between batches, and a symbol that fails is skipped
  rather than retried into a ban.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from quantdesk.data.base import DataProvider

#: Bundled fallback list. Deliberately not "every listed ticker": thousands of
#: them are sub-$1, barely traded, or delisted shells that no strategy here
#: would touch, and fetching them all just burns the rate limit. A user-supplied
#: file replaces this entirely.
DEFAULT_SYMBOL_FILE = "symbols.txt"


@dataclass
class ScreenCriteria:
    """Cheap, objective filters applied before any expensive analysis."""

    min_price: float = 5.0
    """Sub-$5 names have wide spreads and erratic fills."""

    max_price: float = 10_000.0
    min_dollar_volume: float = 10_000_000.0
    min_history_days: int = 250
    """Enough history for a 200-day average to exist at all."""

    max_annual_volatility: float = 1.5
    exclude_symbols: set[str] = field(default_factory=set)

    def describe(self) -> str:
        return (
            f"price ${self.min_price:,.0f}-${self.max_price:,.0f}, "
            f"dollar volume > ${self.min_dollar_volume / 1e6:.0f}M, "
            f"{self.min_history_days}+ days of history"
        )


@dataclass
class ScreenResult:
    passed: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    considered: int = 0
    elapsed_seconds: float = 0.0

    @property
    def rejection_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reason in self.rejected.values():
            key = reason.split("(")[0].strip()
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def load_symbols(path: Path | str | None = None) -> list[str]:
    """Read a newline-separated symbol list, ignoring blanks and # comments."""
    if path is None:
        return []
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"symbol list not found: {file}")

    symbols: list[str] = []
    seen: set[str] = set()
    for line in file.read_text().splitlines():
        token = line.split("#", 1)[0].strip().upper()
        # Tolerate CSV exports by taking the first field.
        if "," in token:
            token = token.split(",", 1)[0].strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        symbols.append(token)
    return symbols


class Screener:
    """Stages a wide symbol list down to a tractable candidate set."""

    def __init__(
        self,
        provider: DataProvider,
        criteria: ScreenCriteria | None = None,
        batch_size: int = 40,
        pause_seconds: float = 0.0,
        lookback_days: int = 300,
    ) -> None:
        self.provider = provider
        self.criteria = criteria or ScreenCriteria()
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds
        self.lookback_days = lookback_days

    def screen(
        self, symbols: list[str], limit: int | None = None, progress=None
    ) -> ScreenResult:
        """Return the symbols worth analysing properly.

        ``progress`` is called as ``progress(done, total, passed)`` so a long
        screen can report rather than appearing to hang.
        """
        started = time.monotonic()
        result = ScreenResult(considered=len(symbols))
        criteria = self.criteria

        candidates = [
            s.upper() for s in symbols if s.upper() not in criteria.exclude_symbols
        ]

        for start in range(0, len(candidates), self.batch_size):
            batch = candidates[start : start + self.batch_size]
            fetched = self.provider.batch_history(batch, self.lookback_days)

            for symbol in batch:
                bars = fetched.get(symbol)
                if bars is None:
                    result.errors[symbol] = "no data"
                    continue
                verdict = self._assess(bars)
                if verdict is None:
                    result.passed.append(symbol)
                else:
                    result.rejected[symbol] = verdict

            if progress is not None:
                progress(
                    min(start + self.batch_size, len(candidates)),
                    len(candidates),
                    len(result.passed),
                )

            if limit is not None and len(result.passed) >= limit:
                break
            if self.pause_seconds and start + self.batch_size < len(candidates):
                time.sleep(self.pause_seconds)

        if limit is not None:
            result.passed = result.passed[:limit]
        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    def _assess(self, bars: pd.DataFrame) -> str | None:
        """Return a rejection reason, or None if the symbol passes.

        Uses only cheap column arithmetic - no indicator suite, no pattern scan.
        The whole point is to reject most candidates before that cost is paid.
        """
        criteria = self.criteria

        if len(bars) < criteria.min_history_days:
            return f"insufficient history ({len(bars)} days)"

        close = bars["close"]
        price = float(close.iloc[-1])
        if price < criteria.min_price:
            return f"price below floor (${price:,.2f})"
        if price > criteria.max_price:
            return f"price above ceiling (${price:,.2f})"

        recent = bars.tail(20)
        dollar_volume = float((recent["close"] * recent["volume"]).mean())
        if dollar_volume < criteria.min_dollar_volume:
            return f"illiquid (${dollar_volume / 1e6:.1f}M/day)"

        log_returns = np.log(close / close.shift(1)).tail(60).dropna()
        if len(log_returns) > 5:
            volatility = float(log_returns.std(ddof=0) * np.sqrt(252))
            if volatility > criteria.max_annual_volatility:
                return f"too volatile ({volatility:.0%} annualised)"

        return None
