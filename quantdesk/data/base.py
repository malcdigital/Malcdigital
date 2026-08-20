"""Provider-agnostic market data contracts.

Every provider returns the same thing: a DataFrame indexed by timezone-naive
date with lowercase ``open/high/low/close/volume`` columns, oldest row first.
Normalising here means the analysis layer never learns where data came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

Bars = pd.DataFrame


class DataUnavailable(RuntimeError):
    """Raised when a provider cannot serve a symbol."""


@dataclass(frozen=True)
class Instrument:
    """Minimal metadata the desk needs about a tradable symbol."""

    symbol: str
    name: str = ""
    asset_type: str = "stock"  # "stock" | "etf"
    sector: str = "Unknown"

    @property
    def is_etf(self) -> bool:
        return self.asset_type == "etf"


def normalise(df: pd.DataFrame, symbol: str = "") -> Bars:
    """Coerce a provider's raw frame into the canonical OHLCV shape."""
    if df is None or len(df) == 0:
        raise DataUnavailable(f"no rows returned for {symbol or 'symbol'}")

    out = df.copy()

    # yfinance hands back a MultiIndex when asked for several tickers.
    if isinstance(out.columns, pd.MultiIndex):
        level0 = out.columns.get_level_values(0)
        if symbol and symbol in out.columns.get_level_values(-1):
            out = out.xs(symbol, axis=1, level=-1)
        else:
            out.columns = level0

    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    if "adj_close" in out.columns and "close" not in out.columns:
        out["close"] = out["adj_close"]

    missing = [c for c in OHLCV_COLUMNS if c not in out.columns]
    if missing:
        raise DataUnavailable(
            f"{symbol or 'data'} missing required columns: {', '.join(missing)}"
        )

    out = out[OHLCV_COLUMNS].copy()
    for col in OHLCV_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    idx = pd.to_datetime(out.index, errors="coerce", utc=True)
    out.index = idx.tz_localize(None)
    out.index.name = "date"

    out = out[~out.index.isna()]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0)
    out = out[~out.index.duplicated(keep="last")].sort_index()

    # A bar whose high is below its low (or below open/close) is corrupt data.
    sane = (
        (out["high"] >= out["low"])
        & (out["high"] >= out[["open", "close"]].max(axis=1) - 1e-6)
        & (out["low"] <= out[["open", "close"]].min(axis=1) + 1e-6)
        & (out["close"] > 0)
    )
    out = out[sane]

    if out.empty:
        raise DataUnavailable(f"no usable rows for {symbol or 'symbol'} after cleaning")
    return out


class DataProvider(ABC):
    """Source of historical bars and light instrument metadata."""

    name: str = "base"

    @abstractmethod
    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        """Return daily bars for ``symbol`` covering roughly ``lookback_days``."""

    def instrument(self, symbol: str) -> Instrument:
        """Best-effort metadata. Providers may override with something richer."""
        return Instrument(symbol=symbol.upper())

    def batch_history(
        self, symbols: list[str], lookback_days: int = 400
    ) -> dict[str, Bars]:
        """Fetch many symbols, skipping the ones that fail."""
        out: dict[str, Bars] = {}
        for sym in symbols:
            try:
                out[sym] = self.history(sym, lookback_days)
            except Exception:  # a dead symbol must not sink the whole scan
                continue
        return out
