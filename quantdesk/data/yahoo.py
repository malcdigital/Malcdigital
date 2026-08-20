"""Yahoo Finance provider backed by yfinance.

Free and needs no API key, which makes it the sensible default, but it is an
undocumented endpoint that rate-limits and occasionally changes shape - hence
the cache and the fallback chain in the registry.
"""

from __future__ import annotations

import logging

import pandas as pd

from quantdesk.data.base import Bars, DataProvider, DataUnavailable, Instrument, normalise


class YahooProvider(DataProvider):
    name = "yahoo"

    def __init__(self) -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise DataUnavailable(
                "yfinance is not installed; run: pip install yfinance"
            ) from exc

        # yfinance logs its own multi-line traceback for every failed symbol.
        # A universe scan skips dead symbols by design, so that output is noise
        # that buries the desk's own reporting. Failures still surface as
        # DataUnavailable exceptions, which the callers handle.
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        import yfinance as yf

        period = self._period_for(lookback_days)
        try:
            raw = yf.download(
                symbol,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        except Exception as exc:
            raise DataUnavailable(f"yahoo download failed for {symbol}: {exc}") from exc

        bars = normalise(raw, symbol)
        return bars.tail(lookback_days + 5)

    @staticmethod
    def _period_for(lookback_days: int) -> str:
        # Ask for calendar span, not trading days, plus headroom for indicators.
        if lookback_days <= 100:
            return "6mo"
        if lookback_days <= 260:
            return "1y"
        if lookback_days <= 520:
            return "2y"
        if lookback_days <= 1300:
            return "5y"
        return "10y"

    def instrument(self, symbol: str) -> Instrument:
        import yfinance as yf

        try:
            info = yf.Ticker(symbol).get_info()
        except Exception:
            info = {}
        quote_type = str(info.get("quoteType", "")).lower()
        return Instrument(
            symbol=symbol.upper(),
            name=info.get("shortName") or info.get("longName") or symbol.upper(),
            asset_type="etf" if quote_type == "etf" else "stock",
            sector=info.get("sector") or ("ETF" if quote_type == "etf" else "Unknown"),
        )
