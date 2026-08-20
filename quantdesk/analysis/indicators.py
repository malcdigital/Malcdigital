"""Technical indicators implemented directly on pandas.

Deliberately dependency-free (no TA-Lib): the formulas are short, and owning
them means no binary install step and no ambiguity about smoothing conventions.
Wilder's smoothing is used for RSI/ATR/ADX, matching the original definitions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def wilder(series: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing: an EMA with alpha = 1/window."""
    return series.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder). 0-100; >70 stretched, <30 washed out."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = wilder(gain, window)
    avg_loss = wilder(loss, window)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # All-gain stretches give infinite RS, which is RSI 100 by definition.
    return out.where(avg_loss != 0.0, 100.0).where(avg_gain != 0.0, out.fillna(0.0))


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range - the unit the desk measures stops and targets in."""
    return wilder(true_range(high, low, close), window)


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    upper, lower = mid + num_std * sd, mid - num_std * sd
    width = (upper - lower) / mid.replace(0.0, np.nan)
    pct_b = (close - lower) / (upper - lower).replace(0.0, np.nan)
    return pd.DataFrame(
        {"middle": mid, "upper": upper, "lower": lower, "width": width, "pct_b": pct_b}
    )


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> pd.DataFrame:
    """Average Directional Index - trend *strength* regardless of direction."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )

    atr_ = wilder(true_range(high, low, close), window).replace(0.0, np.nan)
    plus_di = 100.0 * wilder(plus_dm, window) / atr_
    minus_di = 100.0 * wilder(minus_dm, window) / atr_

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return pd.DataFrame({"adx": wilder(dx, window), "plus_di": plus_di, "minus_di": minus_di})


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3
) -> pd.DataFrame:
    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    percent_k = 100.0 * (close - lowest) / (highest - lowest).replace(0.0, np.nan)
    return pd.DataFrame(
        {"k": percent_k, "d": percent_k.rolling(d, min_periods=d).mean()}
    )


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume - does volume confirm the price path?"""
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).fillna(0.0).cumsum()


def realized_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualised standard deviation of daily log returns."""
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(TRADING_DAYS)


def donchian(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    upper = high.rolling(window, min_periods=window).max()
    lower = low.rolling(window, min_periods=window).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "middle": (upper + lower) / 2})


def slope_pct_per_day(series: pd.Series, window: int = 20) -> pd.Series:
    """Least-squares slope of the series, expressed as % of its own level per day.

    Normalising by level makes the number comparable across a $12 stock and a
    $600 one.

    Computed in closed form rather than by fitting a polynomial per window. For a
    fixed window the x values are constant, so the OLS slope collapses to a dot
    product with fixed weights:

        slope = sum((x_i - x_mean) * y_i) / sum((x_i - x_mean)^2)

    which is a convolution and runs ~50x faster than a rolling polyfit. This is
    the hot path of a universe scan, so it matters.
    """
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    if n < window or window < 2:
        return pd.Series(out, index=series.index, name=series.name)

    weights = np.arange(window, dtype=float)
    weights -= weights.mean()
    sxx = float((weights**2).sum())

    # mode="valid" keeps NaN contamination local to the windows that contain it,
    # matching the per-window fit it replaces.
    numerator = np.convolve(values, weights[::-1], mode="valid")
    means = np.convolve(values, np.full(window, 1.0 / window), mode="valid")

    with np.errstate(divide="ignore", invalid="ignore"):
        slope = numerator / sxx
        normalised = np.where(means != 0.0, slope / means * 100.0, np.nan)

    out[window - 1:] = normalised
    return pd.Series(out, index=series.index, name=series.name)


def max_drawdown(close: pd.Series) -> float:
    """Worst peak-to-trough decline over the whole series, as a negative fraction."""
    if close.empty:
        return 0.0
    running_max = close.cummax()
    return float((close / running_max - 1.0).min())


def compute_all(bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the desk's standard indicator set to a bar frame."""
    out = bars.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]

    for w in (10, 20, 50, 200):
        out[f"sma{w}"] = sma(close, w)
    for w in (9, 21, 50):
        out[f"ema{w}"] = ema(close, w)

    out["rsi14"] = rsi(close, 14)
    out = out.join(macd(close).add_prefix("macd_"))
    out["atr14"] = atr(high, low, close, 14)
    out["atr_pct"] = out["atr14"] / close * 100.0
    out = out.join(bollinger(close).add_prefix("bb_"))
    out = out.join(adx(high, low, close).add_prefix("adx_"))
    out = out.join(stochastic(high, low, close).add_prefix("stoch_"))
    out["obv"] = obv(close, volume)
    out["obv_slope"] = slope_pct_per_day(out["obv"].replace(0, np.nan).ffill(), 20)
    out["volatility20"] = realized_volatility(close, 20)
    out = out.join(donchian(high, low, 20).add_prefix("dc20_"))
    out = out.join(donchian(high, low, 55).add_prefix("dc55_"))
    out["slope20"] = slope_pct_per_day(close, 20)
    out["volume_sma20"] = sma(volume, 20)
    out["volume_ratio"] = volume / out["volume_sma20"].replace(0.0, np.nan)
    out["dollar_volume20"] = (close * volume).rolling(20, min_periods=5).mean()
    return out
