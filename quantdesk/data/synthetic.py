"""Deterministic synthetic market data.

Purpose is twofold: it lets the whole desk be demoed and unit-tested without a
network connection, and it gives tests a price series with *known* properties.

Prices are built from regime-switching geometric Brownian motion, so a symbol
spends stretches trending and stretches chopping - which is what the trend and
pattern code is meant to tell apart. The seed derives from the symbol name, so
"AAPL" is always the same series on every machine and every run.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from quantdesk.data.base import Bars, DataProvider, Instrument, normalise

# Symbols the synthetic universe treats as funds rather than single names.
_ETF_HINTS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO", "AGG", "BND",
    "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "SLV", "XLK", "XLF", "XLV",
    "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SCHD", "VYM",
    "DVY", "USMV", "SPLV", "QUAL", "MTUM", "VUG", "VTV", "ARKK", "SOXX",
    "SMH", "IBB", "XBI", "TAN", "ICLN", "JETS", "KWEB", "EEM", "EFA",
}


class SyntheticProvider(DataProvider):
    """Offline provider generating plausible OHLCV series."""

    name = "synthetic"

    def __init__(self, seed_salt: str = "quantdesk") -> None:
        self.seed_salt = seed_salt

    def _rng(self, symbol: str) -> np.random.Generator:
        digest = hashlib.sha256(f"{self.seed_salt}:{symbol.upper()}".encode()).digest()
        return np.random.default_rng(int.from_bytes(digest[:8], "big"))

    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        symbol = symbol.upper()
        rng = self._rng(symbol)
        n = max(int(lookback_days) + 60, 260)

        is_etf = symbol in _ETF_HINTS
        # Funds are diversified, so they carry less idiosyncratic volatility.
        base_vol = rng.uniform(0.10, 0.22) if is_etf else rng.uniform(0.22, 0.70)
        start_price = float(rng.uniform(28, 240) if is_etf else rng.uniform(9, 480))

        log_returns = self._regime_returns(rng, n, base_vol)
        close = start_price * np.exp(np.cumsum(log_returns))

        daily_vol = base_vol / np.sqrt(252)

        # Open gaps from the prior close; the gap is a fraction of daily vol.
        gaps = rng.normal(0.0, daily_vol * 0.35, size=n)
        prev_close = np.concatenate([[start_price], close[:-1]])
        open_ = prev_close * np.exp(gaps)

        # Intrabar extension beyond the open/close body, always non-negative.
        body_hi = np.maximum(open_, close)
        body_lo = np.minimum(open_, close)
        up_wick = np.abs(rng.normal(0.0, daily_vol * 0.6, size=n))
        dn_wick = np.abs(rng.normal(0.0, daily_vol * 0.6, size=n))
        high = body_hi * (1.0 + up_wick)
        low = body_lo * (1.0 - dn_wick)

        # Volume rises with the size of the move, as it does in real tape.
        move = np.abs(log_returns) / max(daily_vol, 1e-9)
        base_volume = rng.uniform(1.2e6, 4.5e7)
        volume = base_volume * np.exp(rng.normal(0.0, 0.28, size=n)) * (0.7 + 0.5 * move)

        index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        frame = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.round(volume),
            },
            index=index,
        )
        return normalise(frame, symbol)

    @staticmethod
    def _regime_returns(
        rng: np.random.Generator, n: int, annual_vol: float
    ) -> np.ndarray:
        """Log returns that switch between bull, bear and sideways regimes."""
        daily_vol = annual_vol / np.sqrt(252)
        # (annual drift, volatility multiplier) per regime.
        regimes = [(0.28, 0.85), (-0.24, 1.35), (0.02, 0.70), (0.55, 1.10)]
        weights = np.array([0.38, 0.20, 0.27, 0.15])

        out = np.empty(n)
        filled = 0
        while filled < n:
            drift, vol_mult = regimes[rng.choice(len(regimes), p=weights)]
            length = min(int(rng.integers(25, 95)), n - filled)
            mu = drift / 252
            sigma = daily_vol * vol_mult
            out[filled : filled + length] = rng.normal(
                mu - 0.5 * sigma**2, sigma, size=length
            )
            filled += length
        return out

    def instrument(self, symbol: str) -> Instrument:
        symbol = symbol.upper()
        is_etf = symbol in _ETF_HINTS
        rng = self._rng(symbol + ":meta")
        sectors = [
            "Technology", "Healthcare", "Financials", "Consumer Discretionary",
            "Industrials", "Energy", "Consumer Staples", "Utilities",
            "Communication Services", "Materials", "Real Estate",
        ]
        return Instrument(
            symbol=symbol,
            name=f"{symbol} {'Fund' if is_etf else 'Inc.'} (synthetic)",
            asset_type="etf" if is_etf else "stock",
            sector="ETF" if is_etf else sectors[int(rng.integers(len(sectors)))],
        )
