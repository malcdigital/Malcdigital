"""On-disk bar cache.

Market history for a closed day never changes, so re-downloading it on every run
is wasted time and a good way to get rate-limited. Cached as CSV to avoid
dragging in a parquet engine.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from quantdesk.data.base import Bars, OHLCV_COLUMNS


class BarCache:
    def __init__(self, directory: Path, ttl_seconds: int = 6 * 3600) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("\\", "_")
        return self.directory / f"{provider}_{safe}.csv"

    def get(self, provider: str, symbol: str) -> Bars | None:
        path = self._path(provider, symbol)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        except Exception:
            return None
        if df.empty or any(c not in df.columns for c in OHLCV_COLUMNS):
            return None
        df.index.name = "date"
        return df

    def put(self, provider: str, symbol: str, bars: Bars) -> None:
        try:
            bars.to_csv(self._path(provider, symbol))
        except Exception:
            pass  # a cache failure must never break a run

    def clear(self) -> int:
        removed = 0
        for f in self.directory.glob("*.csv"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        return removed
