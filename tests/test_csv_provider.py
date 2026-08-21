"""Reading bars from local CSV files.

Matters for two reasons: a backtest against a live feed is not reproducible
(providers revise history and re-adjust for splits without telling you), and
the free endpoints break often enough that fetching once beats fetching on
every run.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quantdesk.data.base import DataUnavailable
from quantdesk.data.csv_files import CsvProvider, save_bars
from quantdesk.data.synthetic import SyntheticProvider


@pytest.fixture(scope="module")
def source():
    return SyntheticProvider()


@pytest.fixture
def data_dir(tmp_path, source):
    for symbol in ("SPY", "AAPL", "QQQ"):
        save_bars(source.history(symbol, 400), symbol, tmp_path)
    return tmp_path


def test_round_trip_preserves_the_bars(data_dir, source):
    """Values must survive the write/read exactly.

    The CSV provider honours ``lookback`` the way the live providers do, so the
    comparison is against the same tail rather than the whole file.
    """
    original = source.history("AAPL", 400)
    read_back = CsvProvider(data_dir).history("AAPL", 400)

    assert len(read_back) > 100
    overlap = original.tail(len(read_back))
    assert list(read_back.index) == list(overlap.index)
    for column in ("open", "high", "low", "close", "volume"):
        np.testing.assert_allclose(
            read_back[column].to_numpy(), overlap[column].to_numpy(), rtol=1e-9
        )


def test_the_whole_file_is_available_when_asked_for(data_dir, source):
    """A backtest asks for everything; nothing may be silently dropped."""
    original = source.history("AAPL", 400)
    read_back = CsvProvider(data_dir).history("AAPL", 20_000)
    assert len(read_back) == len(original)


def test_available_lists_symbols(data_dir):
    assert CsvProvider(data_dir).available() == ["AAPL", "QQQ", "SPY"]


def test_metadata_is_not_listed_as_a_symbol(data_dir):
    (data_dir / "metadata.csv").write_text("symbol,name\nAAPL,Apple\n")
    assert "METADATA" not in CsvProvider(data_dir).available()


# --- format tolerance ---------------------------------------------------------
def test_yahoo_style_export_is_read(tmp_path, source):
    """Title-case headers, a Date column, and an Adj Close."""
    bars = source.history("TSLA", 300)
    pd.DataFrame({
        "Date": bars.index.strftime("%Y-%m-%d"),
        "Open": bars["open"], "High": bars["high"], "Low": bars["low"],
        "Close": bars["close"], "Adj Close": bars["close"],
        "Volume": bars["volume"].astype(int),
    }).reset_index(drop=True).to_csv(tmp_path / "TSLA.csv", index=False)

    read_back = CsvProvider(tmp_path).history("TSLA", 20_000)
    assert len(read_back) == len(bars)


def test_adjusted_close_is_preferred(tmp_path, source):
    """Splits and dividends otherwise read as real price gaps."""
    bars = source.history("TSLA", 300)
    pd.DataFrame({
        "Date": bars.index,
        "Open": bars["open"], "High": bars["high"], "Low": bars["low"],
        "Close": bars["close"] * 2.0,        # unadjusted
        "Adj Close": bars["close"],          # adjusted
        "Volume": bars["volume"],
    }).to_csv(tmp_path / "TSLA.csv", index=False)

    read_back = CsvProvider(tmp_path).history("TSLA", 300)
    assert float(read_back["close"].iloc[-1]) == pytest.approx(
        float(bars["close"].iloc[-1]), rel=1e-6
    )


@pytest.mark.parametrize("date_column", ["date", "datetime", "timestamp", "time"])
def test_alternative_date_columns(tmp_path, source, date_column):
    bars = source.history("AAPL", 200)
    frame = pd.DataFrame({
        date_column: bars.index, "open": bars["open"], "high": bars["high"],
        "low": bars["low"], "close": bars["close"], "volume": bars["volume"],
    })
    frame.to_csv(tmp_path / "AAPL.csv", index=False)
    assert len(CsvProvider(tmp_path).history("AAPL", 20_000)) == len(bars)


def test_lowercase_filename_is_found(tmp_path, source):
    bars = source.history("JPM", 200)
    save_bars(bars, "JPM", tmp_path)
    (tmp_path / "JPM.csv").rename(tmp_path / "jpm.csv")
    assert len(CsvProvider(tmp_path).history("JPM", 20_000)) == len(bars)


# --- failure modes ------------------------------------------------------------
def test_missing_directory_explains_itself(tmp_path):
    with pytest.raises(DataUnavailable) as excinfo:
        CsvProvider(tmp_path / "nope")
    assert "quantdesk fetch" in str(excinfo.value)


def test_missing_symbol_names_the_expected_file(data_dir):
    with pytest.raises(DataUnavailable) as excinfo:
        CsvProvider(data_dir).history("NOSUCH")
    assert "NOSUCH.csv" in str(excinfo.value)


def test_file_without_a_date_column_is_rejected(tmp_path):
    (tmp_path / "BAD.csv").write_text("open,high,low,close,volume\n1,2,0,1,10\n")
    with pytest.raises(DataUnavailable) as excinfo:
        CsvProvider(tmp_path).history("BAD")
    assert "date column" in str(excinfo.value)


def test_file_missing_price_columns_is_rejected(tmp_path):
    (tmp_path / "BAD.csv").write_text("date,close\n2024-01-01,100\n")
    with pytest.raises(DataUnavailable):
        CsvProvider(tmp_path).history("BAD")


def test_empty_file_is_rejected(tmp_path):
    (tmp_path / "BAD.csv").write_text("date,open,high,low,close,volume\n")
    with pytest.raises(DataUnavailable):
        CsvProvider(tmp_path).history("BAD")


def test_one_bad_file_does_not_stop_the_others(tmp_path, source):
    save_bars(source.history("SPY", 300), "SPY", tmp_path)
    (tmp_path / "BAD.csv").write_text("nonsense\n1\n")
    provider = CsvProvider(tmp_path)
    fetched = provider.batch_history(["SPY", "BAD"], 300)
    assert "SPY" in fetched and "BAD" not in fetched


# --- metadata -----------------------------------------------------------------
def test_metadata_sidecar_is_applied(data_dir):
    (data_dir / "metadata.csv").write_text(
        "symbol,name,asset_type,sector\nAAPL,Apple Inc,stock,Technology\n"
    )
    instrument = CsvProvider(data_dir).instrument("AAPL")
    assert instrument.name == "Apple Inc"
    assert instrument.asset_type == "stock"
    assert instrument.sector == "Technology"


def test_etf_is_inferred_without_metadata(data_dir):
    provider = CsvProvider(data_dir)
    assert provider.instrument("QQQ").asset_type == "etf"
    assert provider.instrument("AAPL").asset_type == "stock"


# --- integration --------------------------------------------------------------
def test_backtest_runs_entirely_from_csv(tmp_path, source):
    from quantdesk.backtest import BacktestConfig, Backtester

    symbols = ["SPY", "AAPL", "MSFT", "QQQ"]
    for symbol in symbols:
        save_bars(source.history(symbol, 700), symbol, tmp_path)

    result = Backtester(
        CsvProvider(tmp_path),
        BacktestConfig(symbols=symbols, scan_every=15, max_new_ideas=2,
                       start=date.today() - timedelta(days=700)),
    ).run()

    assert result.sessions > 100
    assert result.metrics is not None
    assert result.benchmark_metrics is not None, "benchmark must come from CSV too"
    assert all(v > 0 for _, v in result.equity_curve)


def test_registry_builds_the_csv_provider(tmp_path, source):
    from quantdesk.data import get_provider

    save_bars(source.history("SPY", 300), "SPY", tmp_path)
    provider = get_provider("csv", csv_dir=tmp_path)
    assert len(provider.history("SPY", 300)) > 100


def test_registry_requires_a_directory():
    from quantdesk.data import get_provider

    with pytest.raises((ValueError, DataUnavailable)):
        get_provider("csv")
