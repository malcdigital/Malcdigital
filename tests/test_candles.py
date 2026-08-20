"""Every detector is exercised against a hand-built example of its pattern.

Also checks the property that makes the module worth having: identical geometry
must read differently depending on the trend it appears in.
"""

import pytest

from quantdesk.analysis.candles import BEARISH, BULLISH, CandlestickScanner


def detected(frame, lookback=3):
    return {p.name for p in CandlestickScanner().scan(frame, lookback=lookback)}


def test_hammer_after_decline(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.2, last - 4.0, last + 0.1, 2_000_000))
    assert "Hammer" in detected(bar_frame(rows))


def test_same_shape_after_a_rally_is_a_hanging_man_not_a_hammer(bar_frame, trending_prefix):
    """Context, not geometry, decides what a candle means."""
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 0.2, last - 4.0, last - 0.1, 2_000_000))
    names = detected(bar_frame(rows))
    assert "Hanging Man" in names
    assert "Hammer" not in names


def test_shooting_star_after_rally(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 4.0, last - 0.2, last - 0.1, 2_000_000))
    assert "Shooting Star" in detected(bar_frame(rows))


def test_inverted_hammer_after_decline(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 4.0, last - 0.2, last + 0.1, 2_000_000))
    assert "Inverted Hammer" in detected(bar_frame(rows))


def test_bullish_engulfing(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 2.1, last - 2.0, 1_000_000))
    rows.append((last - 2.3, last + 0.6, last - 2.4, last + 0.4, 3_000_000))
    assert "Bullish Engulfing" in detected(bar_frame(rows))


def test_bearish_engulfing(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 2.1, last - 0.1, last + 2.0, 1_000_000))
    rows.append((last + 2.3, last + 2.4, last - 0.6, last - 0.4, 3_000_000))
    assert "Bearish Engulfing" in detected(bar_frame(rows))


def test_piercing_line(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 4.1, last - 4.0, 1_000_000))
    rows.append((last - 5.0, last - 1.5, last - 5.2, last - 1.6, 3_000_000))
    assert "Piercing Line" in detected(bar_frame(rows))


def test_dark_cloud_cover(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 4.1, last - 0.1, last + 4.0, 1_000_000))
    rows.append((last + 5.0, last + 5.2, last + 1.4, last + 1.6, 3_000_000))
    assert "Dark Cloud Cover" in detected(bar_frame(rows))


def test_morning_star(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 4.1, last - 4.0, 1_500_000))
    rows.append((last - 4.6, last - 4.4, last - 5.2, last - 4.7, 800_000))
    rows.append((last - 4.5, last - 1.3, last - 4.6, last - 1.4, 3_000_000))
    assert "Morning Star" in detected(bar_frame(rows))


def test_evening_star(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 4.1, last - 0.1, last + 4.0, 1_500_000))
    rows.append((last + 4.6, last + 5.2, last + 4.4, last + 4.7, 800_000))
    rows.append((last + 4.5, last + 4.6, last + 1.3, last + 1.4, 3_000_000))
    assert "Evening Star" in detected(bar_frame(rows))


def test_three_white_soldiers(bar_frame, trending_prefix):
    rows = trending_prefix("down", step=0.05)
    price = rows[-1][3]
    for _ in range(3):
        open_ = price - 0.5           # opens inside the prior body, no gap
        close = open_ + 2.2
        rows.append((open_, close + 0.1, open_ - 0.15, close, 2_000_000))
        price = close
    assert "Three White Soldiers" in detected(bar_frame(rows))


def test_three_black_crows(bar_frame, trending_prefix):
    rows = trending_prefix("up", step=0.05)
    price = rows[-1][3]
    for _ in range(3):
        open_ = price + 0.5
        close = open_ - 2.2
        rows.append((open_, open_ + 0.15, close - 0.1, close, 2_000_000))
        price = close
    assert "Three Black Crows" in detected(bar_frame(rows))


def test_soldiers_require_opening_inside_the_prior_body(bar_frame, trending_prefix):
    """Three gapping bars are not the pattern - each open must sit in the last body."""
    rows = trending_prefix("down", step=0.05)
    price = rows[-1][3]
    for _ in range(3):
        open_ = price + 0.3           # gaps above the prior close
        close = open_ + 2.2
        rows.append((open_, close + 0.1, open_ - 0.15, close, 2_000_000))
        price = close
    assert "Three White Soldiers" not in detected(bar_frame(rows))


def test_bullish_harami(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 4.1, last - 4.0, 1_500_000))
    rows.append((last - 3.4, last - 3.0, last - 3.6, last - 3.2, 700_000))
    assert "Bullish Harami" in detected(bar_frame(rows))


def test_bearish_harami(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 4.1, last - 0.1, last + 4.0, 1_500_000))
    rows.append((last + 3.2, last + 3.6, last + 3.0, last + 3.4, 700_000))
    assert "Bearish Harami" in detected(bar_frame(rows))


def test_doji_and_marubozu(bar_frame, trending_prefix):
    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 1.6, last - 1.6, last + 0.01, 1_500_000))
    assert "Doji" in detected(bar_frame(rows))

    rows = trending_prefix("down", step=0.05)
    last = rows[-1][3]
    rows.append((last, last + 3.0, last - 0.02, last + 2.98, 2_500_000))
    assert "Marubozu" in detected(bar_frame(rows))


def test_tweezers(bar_frame, trending_prefix):
    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 3.0, last - 2.5, 1_500_000))
    rows.append((last - 2.5, last - 1.0, last - 3.0, last - 1.2, 2_000_000))
    assert "Tweezer Bottom" in detected(bar_frame(rows))

    rows = trending_prefix("up")
    last = rows[-1][3]
    rows.append((last, last + 3.0, last - 0.1, last + 2.5, 1_500_000))
    rows.append((last + 2.5, last + 3.0, last + 1.0, last + 1.2, 2_000_000))
    assert "Tweezer Top" in detected(bar_frame(rows))


def test_quiet_market_produces_no_patterns(bar_frame):
    rows = [(100.0, 100.4, 99.6, 100.0, 1_000_000) for _ in range(60)]
    assert detected(bar_frame(rows)) == set()


def test_summary_direction_matches_pattern_bias(bar_frame, trending_prefix):
    from quantdesk.analysis.candles import summarise_patterns

    rows = trending_prefix("down")
    last = rows[-1][3]
    rows.append((last, last + 0.1, last - 2.1, last - 2.0, 1_000_000))
    rows.append((last - 2.3, last + 0.6, last - 2.4, last + 0.4, 3_000_000))
    frame = bar_frame(rows)
    patterns = CandlestickScanner().scan(frame, lookback=3)
    summary = summarise_patterns(patterns, latest_index=len(frame) - 1)
    assert summary["bias"] == BULLISH
    assert summary["score"] > 0
