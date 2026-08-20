"""Wide-market screening: the cheap pass that makes a big universe affordable."""

import numpy as np
import pandas as pd
import pytest

from quantdesk.data.base import DataProvider
from quantdesk.strategy.screener import (
    ScreenCriteria, Screener, load_symbols,
)


def bars(price=100.0, volume=5e7, n=300, seed=1, drift=1.0):
    rng = np.random.default_rng(seed)
    close = np.linspace(price, price * drift, n) + rng.normal(0, price * 0.01, n)
    close = np.maximum(close, 0.01)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.01,
         "low": np.minimum(open_, close) * 0.99, "close": close,
         "volume": np.full(n, volume)},
        index=pd.bdate_range(end="2026-01-01", periods=n),
    )


class FakeProvider(DataProvider):
    name = "fake"

    def __init__(self, table):
        self.table = table
        self.fetches = 0

    def history(self, symbol, lookback_days=400):
        self.fetches += 1
        frame = self.table.get(symbol.upper())
        if frame is None:
            raise RuntimeError("no data")
        return frame


@pytest.fixture
def provider():
    return FakeProvider({
        "GOOD": bars(),
        "CHEAP": bars(price=2.0),
        "THIN": bars(volume=1_000),
        "SHORTHIST": bars(n=80),
        "WILD": bars(price=100.0, seed=5, drift=1.0) .pipe(
            lambda df: df.assign(close=df["close"] * np.exp(
                np.cumsum(np.random.default_rng(7).normal(0, 0.15, len(df)))))
        ),
    })


def test_liquid_name_passes(provider):
    result = Screener(provider).screen(["GOOD"])
    assert result.passed == ["GOOD"]


@pytest.mark.parametrize("symbol,fragment", [
    ("CHEAP", "price below floor"),
    ("THIN", "illiquid"),
    ("SHORTHIST", "insufficient history"),
])
def test_rejections_explain_themselves(provider, symbol, fragment):
    result = Screener(provider).screen([symbol])
    assert result.passed == []
    assert fragment in result.rejected[symbol]


def test_missing_data_is_an_error_not_a_rejection(provider):
    result = Screener(provider).screen(["NOSUCH"])
    assert "NOSUCH" in result.errors
    assert "NOSUCH" not in result.rejected


def test_excluded_symbols_are_never_fetched(provider):
    criteria = ScreenCriteria(exclude_symbols={"GOOD"})
    result = Screener(provider, criteria).screen(["GOOD"])
    assert result.passed == []
    assert provider.fetches == 0, "an excluded symbol must not cost a request"


def test_limit_stops_early(provider):
    table = {f"S{i}": bars(seed=i) for i in range(30)}
    screener = Screener(FakeProvider(table), batch_size=5)
    result = screener.screen(list(table), limit=7)
    assert len(result.passed) == 7


def test_progress_is_reported(provider):
    table = {f"S{i}": bars(seed=i) for i in range(20)}
    seen = []
    Screener(FakeProvider(table), batch_size=5).screen(
        list(table), progress=lambda done, total, passed: seen.append((done, total))
    )
    assert seen and seen[-1][0] == seen[-1][1] == 20


def test_rejection_summary_groups_reasons(provider):
    result = Screener(provider).screen(["GOOD", "CHEAP", "THIN", "SHORTHIST"])
    summary = result.rejection_summary
    assert sum(summary.values()) == 3
    assert all(isinstance(count, int) for count in summary.values())


# --- symbol file --------------------------------------------------------------
def test_symbol_file_parsing(tmp_path):
    path = tmp_path / "syms.txt"
    path.write_text(
        "# a comment\n"
        "AAPL\n"
        "  msft  \n"
        "\n"
        "GOOGL # trailing comment\n"
        "AAPL\n"            # duplicate
        "TSLA,Tesla Inc,NASDAQ\n"   # CSV export
    )
    assert load_symbols(path) == ["AAPL", "MSFT", "GOOGL", "TSLA"]


def test_missing_symbol_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_symbols(tmp_path / "nope.txt")


def test_bundled_symbol_file_is_clean():
    from pathlib import Path

    import quantdesk

    path = Path(quantdesk.__file__).parent / "data" / "symbols.txt"
    symbols = load_symbols(path)
    assert len(symbols) > 300
    assert len(symbols) == len(set(symbols)), "bundled list must not repeat"
    assert all(s.isupper() for s in symbols)
    assert all(1 <= len(s) <= 6 for s in symbols)


def test_bundled_list_includes_the_inverse_etfs_for_substitution():
    """They must be present to be fetchable, and excluded from long screening."""
    from pathlib import Path

    import quantdesk
    from quantdesk.strategy.universe import INVERSE_SYMBOLS

    path = Path(quantdesk.__file__).parent / "data" / "symbols.txt"
    symbols = set(load_symbols(path))
    assert INVERSE_SYMBOLS <= symbols
