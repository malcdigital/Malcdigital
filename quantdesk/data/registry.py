"""Provider selection, caching and fallback."""

from __future__ import annotations

from pathlib import Path

from quantdesk.data.base import Bars, DataProvider, DataUnavailable, Instrument
from quantdesk.data.cache import BarCache

# Order tried when the configured provider is "auto".
_FALLBACK_ORDER = ("yahoo", "stooq", "synthetic")


def _build(name: str) -> DataProvider:
    if name == "yahoo":
        from quantdesk.data.yahoo import YahooProvider

        return YahooProvider()
    if name == "stooq":
        from quantdesk.data.stooq import StooqProvider

        return StooqProvider()
    if name == "synthetic":
        from quantdesk.data.synthetic import SyntheticProvider

        return SyntheticProvider()
    raise ValueError(f"unknown data provider {name!r}")


class CachingProvider(DataProvider):
    """Wraps one or more providers with a disk cache and ordered fallback."""

    def __init__(
        self,
        providers: list[DataProvider],
        cache: BarCache | None = None,
        min_rows: int = 60,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = providers
        self.cache = cache
        self.min_rows = min_rows
        self.name = "+".join(p.name for p in providers)
        self._instrument_cache: dict[str, Instrument] = {}

    def history(self, symbol: str, lookback_days: int = 400) -> Bars:
        symbol = symbol.upper()
        errors: list[str] = []

        for provider in self.providers:
            if self.cache is not None:
                hit = self.cache.get(provider.name, symbol)
                if hit is not None and len(hit) >= self.min_rows:
                    return hit.tail(lookback_days + 5)
            try:
                bars = provider.history(symbol, lookback_days)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue

            if len(bars) < self.min_rows:
                errors.append(
                    f"{provider.name}: only {len(bars)} rows, need {self.min_rows}"
                )
                continue
            if self.cache is not None:
                self.cache.put(provider.name, symbol, bars)
            return bars

        raise DataUnavailable(f"no provider could serve {symbol} ({'; '.join(errors)})")

    def instrument(self, symbol: str) -> Instrument:
        symbol = symbol.upper()
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        for provider in self.providers:
            try:
                inst = provider.instrument(symbol)
            except Exception:
                continue
            self._instrument_cache[symbol] = inst
            return inst
        inst = Instrument(symbol=symbol)
        self._instrument_cache[symbol] = inst
        return inst


def get_provider(
    name: str = "auto", cache_dir: Path | None = None, cache_ttl: int = 6 * 3600
) -> CachingProvider:
    """Build the provider stack described by ``name``.

    ``auto`` tries live sources first and falls back to synthetic data so the
    desk still runs (clearly labelled) when the network is unavailable.
    """
    cache = BarCache(cache_dir, cache_ttl) if cache_dir is not None else None

    if name == "auto":
        built: list[DataProvider] = []
        for candidate in _FALLBACK_ORDER:
            try:
                built.append(_build(candidate))
            except Exception:
                continue
        if not built:
            built = [_build("synthetic")]
        return CachingProvider(built, cache)

    return CachingProvider([_build(name)], cache)
