"""Stooq CSV provider - a keyless fallback when Yahoo is unavailable."""

from __future__ import annotations

import io

import pandas as pd

from quantdesk.data.base import Bars, DataProvider, DataUnavailable, normalise

_BASE = "https://stooq.com/q/d/l/"


class StooqProvider(DataProvider):
    name = "stooq"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        import requests

        params = {"s": self._stooq_symbol(symbol), "i": "d"}
        try:
            resp = requests.get(_BASE, params=params, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as exc:
            raise DataUnavailable(f"stooq request failed for {symbol}: {exc}") from exc

        text = resp.text.strip()
        if not text or text.lower().startswith("no data"):
            raise DataUnavailable(f"stooq has no data for {symbol}")

        raw = pd.read_csv(io.StringIO(text))
        if "Date" not in raw.columns:
            raise DataUnavailable(f"unexpected stooq payload for {symbol}")
        raw = raw.set_index("Date")
        bars = normalise(raw, symbol)
        return bars.tail(lookback_days + 5)

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        s = symbol.lower().replace("-", ".")
        # Stooq namespaces US listings with a .us suffix.
        return s if "." in s else f"{s}.us"
