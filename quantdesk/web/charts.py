"""Server-rendered SVG charts.

Charts are drawn as inline SVG on the server rather than handed to a JavaScript
charting library. Three reasons, in order of how much they matter here:

1. **No CDN.** A local dashboard should work with the laptop offline; pulling a
   charting bundle from the network at page load would break exactly when the
   rest of the desk still works fine.
2. **No build step.** Nothing to install, bundle or keep up to date.
3. **It is the right size of problem.** Candles, a line and some markers are a
   few hundred lines of geometry. A general charting library is megabytes of
   capability for a page that needs none of it.

Everything is drawn in a viewBox with a fixed coordinate space and scaled by CSS,
so the charts stay sharp at any width and readable on a phone.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import pandas as pd


@dataclass
class ChartTheme:
    up: str = "var(--up)"
    down: str = "var(--down)"
    grid: str = "var(--line)"
    text: str = "var(--muted)"
    accent: str = "var(--accent)"
    stop: str = "var(--down)"
    target: str = "var(--up)"


def _fmt(value: float) -> str:
    """Compact axis labels: 1.2K, 3.4M, or plain money."""
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 10_000:
        return f"{value / 1_000:.0f}K"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def candlestick(
    bars: pd.DataFrame,
    width: int = 900,
    height: int = 360,
    sessions: int = 90,
    overlays: dict[str, pd.Series] | None = None,
    markers: list[dict] | None = None,
    levels: list[dict] | None = None,
    theme: ChartTheme | None = None,
) -> str:
    """Render an OHLC candlestick chart as standalone SVG.

    ``markers`` are pattern annotations: {"date", "label", "direction"}.
    ``levels`` are horizontal lines: {"price", "label", "kind"}.
    """
    theme = theme or ChartTheme()
    if bars is None or bars.empty:
        return '<svg viewBox="0 0 900 360" role="img"><title>No data</title></svg>'

    view = bars.tail(sessions)
    if view.empty:
        return '<svg viewBox="0 0 900 360" role="img"><title>No data</title></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 8, 62, 12, 26
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    lows = [float(v) for v in view["low"]]
    highs = [float(v) for v in view["high"]]
    low = min(lows)
    high = max(highs)

    # Include overlays and levels in the range, or a moving average can run off
    # the top of the plot and simply not be drawn.
    extra: list[float] = []
    for series in (overlays or {}).values():
        tail = series.reindex(view.index).dropna()
        extra.extend(float(v) for v in tail)
    for level in levels or []:
        extra.append(float(level["price"]))
    if extra:
        low = min(low, min(extra))
        high = max(high, max(extra))

    span = max(high - low, 1e-9)
    low -= span * 0.06
    high += span * 0.06
    span = high - low

    n = len(view)
    step = plot_w / max(n, 1)
    body_w = max(1.4, min(step * 0.62, 14.0))

    def x_of(i: int) -> float:
        return pad_left + step * (i + 0.5)

    def y_of(price: float) -> float:
        return pad_top + (high - price) / span * plot_h

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'class="chart" role="img">'
    ]

    # --- horizontal grid and price axis ---
    for k in range(5):
        price = high - span * k / 4
        y = y_of(price)
        parts.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" '
            f'y2="{y:.1f}" stroke="{theme.grid}" stroke-width="1" '
            f'stroke-dasharray="2 4"/>'
        )
        parts.append(
            f'<text x="{pad_left + plot_w + 6}" y="{y + 4:.1f}" '
            f'font-size="11" fill="{theme.text}">{_fmt(price)}</text>'
        )

    # --- named levels (support / resistance / stop / target) ---
    for level in levels or []:
        y = y_of(float(level["price"]))
        colour = {
            "stop": theme.stop, "target": theme.target,
            "entry": theme.accent,
        }.get(level.get("kind", ""), theme.grid)
        dash = "6 3" if level.get("kind") in ("stop", "target", "entry") else "1 5"
        parts.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" '
            f'y2="{y:.1f}" stroke="{colour}" stroke-width="1.5" '
            f'stroke-dasharray="{dash}" opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{pad_left + 4}" y="{y - 4:.1f}" font-size="10" '
            f'fill="{colour}">{html.escape(str(level.get("label", "")))}</text>'
        )

    # --- candles ---
    for i in range(n):
        row = view.iloc[i]
        o, h, l, c = (float(row["open"]), float(row["high"]),
                      float(row["low"]), float(row["close"]))
        colour = theme.up if c >= o else theme.down
        cx = x_of(i)
        parts.append(
            f'<line x1="{cx:.1f}" y1="{y_of(h):.1f}" x2="{cx:.1f}" '
            f'y2="{y_of(l):.1f}" stroke="{colour}" stroke-width="1"/>'
        )
        top = y_of(max(o, c))
        body_h = max(1.0, abs(y_of(o) - y_of(c)))
        parts.append(
            f'<rect x="{cx - body_w / 2:.1f}" y="{top:.1f}" '
            f'width="{body_w:.1f}" height="{body_h:.1f}" fill="{colour}"/>'
        )

    # --- overlays (moving averages) ---
    palette = [theme.accent, "#f59e0b", "#a855f7"]
    for index, (label, series) in enumerate((overlays or {}).items()):
        aligned = series.reindex(view.index)
        points: list[str] = []
        for i, value in enumerate(aligned):
            if pd.isna(value):
                continue
            points.append(f"{x_of(i):.1f},{y_of(float(value)):.1f}")
        if len(points) > 1:
            colour = palette[index % len(palette)]
            parts.append(
                f'<polyline points="{" ".join(points)}" fill="none" '
                f'stroke="{colour}" stroke-width="1.6" opacity="0.85"/>'
            )
            parts.append(
                f'<text x="{pad_left + 6 + index * 62}" y="{pad_top + 12}" '
                f'font-size="11" fill="{colour}">{html.escape(label)}</text>'
            )

    # --- pattern markers ---
    positions = {d: i for i, d in enumerate(view.index)}
    for marker in markers or []:
        i = positions.get(pd.Timestamp(marker["date"]))
        if i is None:
            continue
        row = view.iloc[i]
        bullish = marker.get("direction") == "bullish"
        colour = theme.up if bullish else theme.down
        cx = x_of(i)
        cy = y_of(float(row["low"])) + 12 if bullish else y_of(float(row["high"])) - 12
        arrow = (
            f"{cx:.1f},{cy - 7:.1f} {cx - 5:.1f},{cy + 2:.1f} {cx + 5:.1f},{cy + 2:.1f}"
            if bullish else
            f"{cx:.1f},{cy + 7:.1f} {cx - 5:.1f},{cy - 2:.1f} {cx + 5:.1f},{cy - 2:.1f}"
        )
        parts.append(f'<polygon points="{arrow}" fill="{colour}" opacity="0.95">')
        parts.append(f'<title>{html.escape(str(marker.get("label", "")))}</title>')
        parts.append("</polygon>")

    # --- date axis ---
    for i in (0, n // 2, n - 1):
        if 0 <= i < n:
            label = view.index[i].strftime("%d %b")
            anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
            parts.append(
                f'<text x="{x_of(i):.1f}" y="{height - 8}" font-size="11" '
                f'text-anchor="{anchor}" fill="{theme.text}">{label}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


def equity_curve(
    points: list[tuple[str, float]], width: int = 900, height: int = 220,
    theme: ChartTheme | None = None,
) -> str:
    """Render the equity history as a filled line chart."""
    theme = theme or ChartTheme()
    if len(points) < 2:
        return (
            '<svg viewBox="0 0 900 220" role="img"><text x="450" y="110" '
            'text-anchor="middle" font-size="13" fill="var(--muted)">'
            'Not enough history yet - run the desk for a few days.</text></svg>'
        )

    values = [v for _, v in points]
    low, high = min(values), max(values)
    span = max(high - low, 1e-9)
    low -= span * 0.08
    high += span * 0.08
    span = high - low

    pad_left, pad_right, pad_top, pad_bottom = 8, 62, 12, 24
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    step = plot_w / max(len(points) - 1, 1)

    def x_of(i: int) -> float:
        return pad_left + step * i

    def y_of(v: float) -> float:
        return pad_top + (high - v) / span * plot_h

    coords = [f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values)]
    gained = values[-1] >= values[0]
    colour = theme.up if gained else theme.down

    area = (
        f"{pad_left},{pad_top + plot_h} " + " ".join(coords)
        + f" {x_of(len(values) - 1):.1f},{pad_top + plot_h}"
    )

    parts = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'class="chart" role="img">'
    ]
    for k in range(4):
        value = high - span * k / 3
        y = y_of(value)
        parts.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" '
            f'y2="{y:.1f}" stroke="{theme.grid}" stroke-width="1" '
            f'stroke-dasharray="2 4"/>'
        )
        parts.append(
            f'<text x="{pad_left + plot_w + 6}" y="{y + 4:.1f}" font-size="11" '
            f'fill="{theme.text}">{_fmt(value)}</text>'
        )

    parts.append(f'<polygon points="{area}" fill="{colour}" opacity="0.10"/>')
    parts.append(
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="{colour}" '
        f'stroke-width="2"/>'
    )
    for i in (0, len(points) - 1):
        parts.append(
            f'<text x="{x_of(i):.1f}" y="{height - 6}" font-size="11" '
            f'text-anchor="{"start" if i == 0 else "end"}" fill="{theme.text}">'
            f'{html.escape(points[i][0])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
