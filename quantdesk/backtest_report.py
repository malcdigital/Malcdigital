"""Backtest reporting, as plain text and as a standalone HTML page."""

from __future__ import annotations

import html

from quantdesk.backtest import BacktestResult, verdict
from quantdesk.portfolio.report import DISCLAIMER
from quantdesk.web.charts import equity_comparison

E = html.escape


def _pf(value: float) -> str:
    return "inf" if value == float("inf") else f"{value:.2f}"


def to_text(result: BacktestResult, width: int = 78) -> str:
    metrics, benchmark = result.metrics, result.benchmark_metrics
    config = result.config
    rule, thin = "=" * width, "-" * width
    L: list[str] = [rule, "QUANTDESK BACKTEST".center(width), rule, ""]

    if result.equity_curve:
        L.append(f"  Period        {result.equity_curve[0][0]} to {result.equity_curve[-1][0]}")
    L.append(f"  Sessions      {result.sessions:,} ({result.scanned_sessions:,} scans)")
    L.append(f"  Universe      {len(config.symbols)} symbols")
    L.append(f"  Risk profile  {config.risk_profile}")
    L.append(f"  Starting cash ${config.starting_cash:,.0f}")
    L.append(f"  Ran in        {result.elapsed_seconds:.1f}s")

    if result.warnings:
        L.append("")
        for warning in result.warnings:
            L.append(f"  !! {warning}")

    if metrics is None:
        L.append("")
        L.append("  No result produced.")
        return "\n".join(L + ["", rule, DISCLAIMER, rule])

    L += ["", "PERFORMANCE", thin,
          f"  {'':<22}{'STRATEGY':>13}{'BUY & HOLD':>13}"]

    def row(label: str, a: float, b: float | None, suffix: str = "%") -> str:
        right = f"{b:>12,.2f}{suffix}" if b is not None else f"{'n/a':>13}"
        return f"  {label:<22}{a:>12,.2f}{suffix}{right}"

    L.append(row("Total return", metrics.total_return_pct,
                 benchmark.total_return_pct if benchmark else None))
    L.append(row("CAGR", metrics.cagr_pct, benchmark.cagr_pct if benchmark else None))
    L.append(row("Max drawdown", metrics.max_drawdown_pct,
                 benchmark.max_drawdown_pct if benchmark else None))
    L.append(row("Volatility", metrics.volatility_pct,
                 benchmark.volatility_pct if benchmark else None))
    L.append(row("Sharpe", metrics.sharpe, benchmark.sharpe if benchmark else None, ""))
    L.append(row("Sortino", metrics.sortino, benchmark.sortino if benchmark else None, ""))

    if benchmark:
        gap = metrics.total_return_pct - benchmark.total_return_pct
        L.append("")
        L.append(f"  {'Versus benchmark':<22}{gap:>+12,.2f}%")
        L.append(f"  {'':<22}{'^ the number that decides it':>13}")

    L += ["", "TRADES", thin,
          f"  Closed        {metrics.closed_trades:,}",
          f"  Win rate      {metrics.win_rate:.1f}%",
          f"  Profit factor {_pf(metrics.profit_factor)}",
          f"  Expectancy    ${metrics.expectancy:,.2f} per trade",
          f"  Avg win       ${metrics.avg_win:,.2f}    Avg loss ${metrics.avg_loss:,.2f}",
          f"  Best          ${metrics.best_trade:+,.2f}    Worst ${metrics.worst_trade:+,.2f}",
          f"  Exposure      {metrics.exposure_pct:.0f}% of sessions held a position"]

    L += ["", "VERDICT", thin]
    for line in verdict(result):
        L.append(f"  - {line}")

    L += ["", rule, DISCLAIMER, rule]
    return "\n".join(L)


def to_html(result: BacktestResult) -> str:
    metrics, benchmark = result.metrics, result.benchmark_metrics
    config = result.config

    if metrics is None:
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Backtest</title></head><body><p>No result produced.</p>"
            "</body></html>"
        )

    strategy_points = [(d.strftime("%b %y"), v) for d, v in result.equity_curve]
    benchmark_points = [(d.strftime("%b %y"), v) for d, v in result.benchmark_curve]
    chart = equity_comparison(strategy_points, benchmark_points)

    gap = (
        metrics.total_return_pct - benchmark.total_return_pct if benchmark else 0.0
    )
    gap_class = "up" if gap > 0 else "down"

    def compare_row(label: str, a: float, b: float | None, suffix: str = "%") -> str:
        better = b is None or a >= b
        right = f"{b:,.2f}{suffix}" if b is not None else "n/a"
        return (
            f"<tr><td>{E(label)}</td>"
            f'<td class="{"up" if better else "down"}">{a:,.2f}{suffix}</td>'
            f"<td class='muted'>{right}</td></tr>"
        )

    rows = "".join([
        compare_row("Total return", metrics.total_return_pct,
                    benchmark.total_return_pct if benchmark else None),
        compare_row("CAGR", metrics.cagr_pct, benchmark.cagr_pct if benchmark else None),
        compare_row("Max drawdown", metrics.max_drawdown_pct,
                    benchmark.max_drawdown_pct if benchmark else None),
        compare_row("Volatility", metrics.volatility_pct,
                    benchmark.volatility_pct if benchmark else None),
        compare_row("Sharpe", metrics.sharpe,
                    benchmark.sharpe if benchmark else None, ""),
        compare_row("Sortino", metrics.sortino,
                    benchmark.sortino if benchmark else None, ""),
    ])

    verdict_html = "".join(f"<li>{E(line)}</li>" for line in verdict(result))
    warnings_html = "".join(
        f"<div class='warn'>{E(w)}</div>" for w in result.warnings
    )
    period = (
        f"{result.equity_curve[0][0]} to {result.equity_curve[-1][0]}"
        if result.equity_curve else "n/a"
    )

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest - QuantDesk</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--up:#0f7b3f;--down:#b42318;--accent:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1116;--card:#171b21;--ink:#e6e8eb;
--muted:#9aa4b2;--line:#252b33;--up:#3ddc84;--down:#ff6b6b;--accent:#7aa2ff}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:24px;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:960px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
margin:26px 0 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px}}
.stat .l{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.stat .v{{font-size:19px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);font-size:14px}}
th:first-child,td:first-child{{text-align:left}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.up{{color:var(--up)}}.down{{color:var(--down)}}.muted{{color:var(--muted)}}
.chart{{width:100%;height:auto;display:block}}
.warn{{background:rgba(234,179,8,.15);border:1px solid rgba(234,179,8,.5);
border-radius:8px;padding:10px 12px;margin:12px 0;font-size:14px}}
.verdict li{{margin:8px 0}}
footer{{margin-top:26px;padding-top:12px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}}
.overflow{{overflow-x:auto}}
</style></head><body><div class="wrap">
<h1>Backtest</h1>
<p class="muted">{E(period)} &middot; {result.sessions:,} sessions &middot;
{len(config.symbols)} symbols &middot; {E(config.risk_profile)} risk</p>
{warnings_html}

<div class="grid">
<div class="stat"><div class="l">Strategy return</div>
  <div class="v {"up" if metrics.total_return_pct > 0 else "down"}">{metrics.total_return_pct:+.1f}%</div></div>
<div class="stat"><div class="l">Buy &amp; hold</div>
  <div class="v muted">{benchmark.total_return_pct:+.1f}%</div></div>
<div class="stat"><div class="l">Difference</div>
  <div class="v {gap_class}">{gap:+.1f}%</div></div>
<div class="stat"><div class="l">Max drawdown</div>
  <div class="v down">{metrics.max_drawdown_pct:.1f}%</div></div>
<div class="stat"><div class="l">Sharpe</div><div class="v">{metrics.sharpe:.2f}</div></div>
<div class="stat"><div class="l">Trades</div><div class="v">{metrics.closed_trades:,}</div></div>
<div class="stat"><div class="l">Win rate</div><div class="v">{metrics.win_rate:.0f}%</div></div>
<div class="stat"><div class="l">Exposure</div><div class="v">{metrics.exposure_pct:.0f}%</div></div>
</div>

<h2>Equity: strategy versus buy-and-hold</h2>
<div class="card">{chart}</div>

<h2>Side by side</h2>
<div class="card overflow"><table><thead><tr><th>Measure</th><th>Strategy</th>
<th>Buy &amp; hold</th></tr></thead><tbody>{rows}</tbody></table></div>

<h2>Verdict</h2>
<div class="card"><ul class="verdict">{verdict_html}</ul></div>

<footer>{E(DISCLAIMER)}</footer>
</div></body></html>"""
