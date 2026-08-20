import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest


@pytest.fixture
def bar_frame():
    """Build an OHLCV frame from a list of (o, h, l, c[, v]) tuples."""

    def _build(rows):
        normalised = [r if len(r) == 5 else (*r, 1_000_000) for r in rows]
        return pd.DataFrame(
            normalised,
            columns=["open", "high", "low", "close", "volume"],
            index=pd.bdate_range(end="2026-01-01", periods=len(normalised)),
        )

    return _build


@pytest.fixture
def trending_prefix():
    """A clean run of bars so candlestick trend context is unambiguous."""

    def _build(direction, n=40, start=100.0, step=1.0, wick=0.3):
        rows, price = [], start
        for _ in range(n):
            open_ = price
            close = price + step if direction == "up" else price - step
            rows.append((open_, max(open_, close) + wick, min(open_, close) - wick,
                         close, 1_000_000))
            price = close
        return rows

    return _build
