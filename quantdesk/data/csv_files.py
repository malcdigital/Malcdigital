"""Bars read from local CSV files.

Two problems this solves, both of which bite exactly when you care most:

**Reproducibility.** A backtest run against a live feed is not repeatable - the
provider revises history, adjusts for splits and dividends, and quietly changes
what "2019-03-04" means. Re-running a month later gives different numbers with
no record of why. Reading from files you keep pins the input.

**Availability.** The free endpoints are undocumented, rate-limited and prone to
breaking. Fetching once and testing many times against the saved copy means a
provider outage stops you fetching, not working.

The reader is deliberately forgiving about layout, because the CSV you already
have is whatever your broker or data source chose to emit: it accepts Yahoo's
export headers, lowercase variants, several date column names, and both
adjusted and unadjusted close columns.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quantdesk.data.base import (
    Bars, DataProvider, DataUnavailable, Instrument, normalise,
)

#: Column names seen in the wild that mean "the date of this bar".
_DATE_COLUMNS = ("date", "datetime", "timestamp", "time", "day", "period")

#: Symbols treated as funds when no metadata file says otherwise.
_ETF_HINTS = {
    "SPY", "VOO", "IVV", "VTI", "QQQ", "IWM", "DIA", "RSP", "VUG", "VTV",
    "VYM", "VIG", "SCHD", "DVY", "MTUM", "QUAL", "USMV", "SPLV", "IJH", "IJR",
    "MDY", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB",
    "XLRE", "XLC", "SMH", "SOXX", "IBB", "XBI", "ARKK", "IGV", "EFA", "EEM",
    "AGG", "BND", "LQD", "HYG", "TLT", "IEF", "SHY", "GLD", "IAU", "SLV",
    "GDX", "USO", "SH", "PSQ", "RWM", "DOG", "EFZ", "EUM",
}


class CsvProvider(DataProvider):
    """Serves bars from ``<directory>/<SYMBOL>.csv``."""

    name = "csv"

    def __init__(self, directory: Path | str, metadata: Path | str | None = None) -> None:
        self.directory = Path(directory).expanduser()
        if not self.directory.is_dir():
            raise DataUnavailable(
                f"CSV data directory not found: {self.directory}. "
                "Create it and add <SYMBOL>.csv files, or run: quantdesk fetch"
            )
        self._metadata = self._load_metadata(metadata)
        self._cache: dict[str, Bars] = {}

    # --- discovery ----------------------------------------------------------
    def available(self) -> list[str]:
        """Symbols with a file present, regardless of whether they parse."""
        return sorted(
            p.stem.upper() for p in self.directory.glob("*.csv")
            if p.stem.lower() != "metadata"
        )

    def _path_for(self, symbol: str) -> Path | None:
        # Match case-insensitively: exports vary, filesystems differ.
        for candidate in (symbol.upper(), symbol.lower(), symbol):
            path = self.directory / f"{candidate}.csv"
            if path.exists():
                return path
        return None

    def _load_metadata(self, metadata: Path | str | None) -> dict[str, dict]:
        path = Path(metadata) if metadata else self.directory / "metadata.csv"
        if not path.exists():
            return {}
        try:
            frame = pd.read_csv(path)
        except Exception:
            return {}
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        if "symbol" not in frame.columns:
            return {}
        out: dict[str, dict] = {}
        for _, row in frame.iterrows():
            out[str(row["symbol"]).strip().upper()] = {
                "name": str(row.get("name", "") or ""),
                "asset_type": str(row.get("asset_type", "") or "").lower(),
                "sector": str(row.get("sector", "") or ""),
            }
        return out

    # --- reading ------------------------------------------------------------
    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        key = symbol.upper()
        if key not in self._cache:
            self._cache[key] = self._read(key)
        return self._cache[key].tail(lookback_days + 5)

    def _read(self, symbol: str) -> Bars:
        path = self._path_for(symbol)
        if path is None:
            raise DataUnavailable(
                f"no CSV for {symbol} in {self.directory} "
                f"(expected {symbol.upper()}.csv)"
            )
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            raise DataUnavailable(f"could not read {path}: {exc}") from exc

        if raw.empty:
            raise DataUnavailable(f"{path} is empty")

        raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]

        date_column = next((c for c in _DATE_COLUMNS if c in raw.columns), None)
        if date_column is None:
            # Some exports put the date in an unnamed index column.
            if raw.columns[0].startswith("unnamed"):
                date_column = raw.columns[0]
            else:
                raise DataUnavailable(
                    f"{path} has no recognisable date column "
                    f"(looked for {', '.join(_DATE_COLUMNS)})"
                )
        raw = raw.set_index(date_column)

        # Prefer an adjusted close when one is present: splits and dividends
        # otherwise show up as price gaps the strategy would read as real moves.
        if "adj_close" in raw.columns and "close" in raw.columns:
            raw["close"] = raw["adj_close"]

        try:
            return normalise(raw, symbol)
        except DataUnavailable as exc:
            raise DataUnavailable(f"{path}: {exc}") from exc

    # --- metadata -----------------------------------------------------------
    def instrument(self, symbol: str) -> Instrument:
        key = symbol.upper()
        meta = self._metadata.get(key, {})
        asset_type = meta.get("asset_type") or (
            "etf" if key in _ETF_HINTS else "stock"
        )
        return Instrument(
            symbol=key,
            name=meta.get("name") or key,
            asset_type=asset_type,
            sector=meta.get("sector") or ("ETF" if asset_type == "etf" else "Unknown"),
        )


def save_bars(bars: Bars, symbol: str, directory: Path | str) -> Path:
    """Write bars in the layout :class:`CsvProvider` reads back."""
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{symbol.upper()}.csv"
    frame = bars.copy()
    frame.index.name = "date"
    frame.to_csv(path)
    return path
