"""HTML pages for the dashboard."""

from __future__ import annotations

import html
import traceback
from datetime import date

import pandas as pd

from quantdesk.analysis.candles import CandlestickScanner
from quantdesk.analysis.indicators import compute_all
from quantdesk.analysis.trend import classify, find_levels
from quantdesk.portfolio.metrics import compute_performance
from quantdesk.portfolio.report import DISCLAIMER
from quantdesk.web.charts import candlestick, equity_curve

STYLE = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--up:#0f7b3f;--down:#b42318;--accent:#1d4ed8;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#171b21;--ink:#e6e8eb;
--muted:#9aa4b2;--line:#252b33;--up:#3ddc84;--down:#ff6b6b;--accent:#7aa2ff;--warn:#f0b429}}
*{box-sizing:border-box}
body{margin:0;padding:0 0 40px;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:10;background:var(--card);
border-bottom:1px solid var(--line);padding:10px 16px}
.wrap{max-width:1000px;margin:0 auto;padding:0 16px}
nav{display:flex;gap:4px;flex-wrap:wrap;align-items:center}
nav a{padding:7px 12px;border-radius:8px;text-decoration:none;color:var(--muted);
font-size:14px;font-weight:550}
nav a:hover{background:var(--bg)}
nav a.on{background:var(--accent);color:#fff}
nav .sp{flex:1}
h1{font-size:20px;margin:20px 0 4px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
margin:26px 0 10px}
h3{margin:0;font-size:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.stat .v{font-size:19px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:8px 9px;border-bottom:1px solid var(--line);font-size:14px}
th:first-child,td:first-child{text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
td a{color:var(--accent);text-decoration:none;font-weight:600}
.up{color:var(--up)}.down{color:var(--down)}.muted{color:var(--muted)}
.chart{width:100%;height:auto;display:block}
.badge{border-radius:999px;padding:2px 9px;font-size:12px;font-weight:600;
white-space:nowrap;background:var(--accent);color:#fff}
.badge.short{background:var(--down)}
.badge.long{background:var(--up)}
.idea header{position:static;background:none;border:0;padding:0;display:flex;
justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.steps{margin:8px 0 0;padding-left:20px}.steps li{margin:4px 0;font-size:14px}
.why{margin:6px 0;padding-left:20px;color:var(--muted);font-size:13px}
.actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
button{font:inherit;font-weight:600;border:0;border-radius:9px;padding:10px 18px;
cursor:pointer;min-height:42px}
.approve{background:var(--up);color:#fff}
.reject{background:var(--card);color:var(--muted);border:1px solid var(--line)}
.run{background:var(--accent);color:#fff}
.warn{background:rgba(234,179,8,.14);border:1px solid rgba(234,179,8,.45);
border-radius:9px;padding:9px 12px;margin:12px 0;font-size:14px}
.note{background:rgba(180,35,24,.08);border-left:3px solid var(--down);
padding:7px 10px;border-radius:0 6px 6px 0;font-size:13px;margin:8px 0 0}
footer{color:var(--muted);font-size:12px;margin-top:26px;padding-top:12px;
border-top:1px solid var(--line)}
.overflow{overflow-x:auto}
.row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
@media(max-width:600px){th,td{padding:7px 5px;font-size:13px}
.stat .v{font-size:17px}button{flex:1}}
"""

E = html.escape


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _cls(v: float) -> str:
    return "up" if v > 0 else ("down" if v < 0 else "")


def page(title: str, active: str, body: str, warning: str = "") -> str:
    tabs = [("/", "Overview"), ("/ideas", "Ideas"),
            ("/positions", "Positions"), ("/history", "History")]
    nav = "".join(
        f'<a href="{href}" class="{"on" if href == active else ""}">{label}</a>'
        for href, label in tabs
    )
    warn = f'<div class="warn">{E(warning)}</div>' if warning else ""
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} - QuantDesk</title><style>{STYLE}</style></head><body>
<header><div class="wrap"><nav>{nav}<span class="sp"></span>
<form method="post" action="/run" style="margin:0">
<button class="run" type="submit">Run scan</button></form></nav></div></header>
<div class="wrap">{warn}{body}
<footer>{E(DISCLAIMER)}</footer></div></body></html>"""


def _prices_for(engine, portfolio) -> dict[str, float]:
    bars = engine._bars_for(portfolio.symbols)
    return engine._latest_prices(bars)


# --- pages --------------------------------------------------------------------
def dashboard(engine) -> str:
    portfolio = engine.store.load_portfolio()
    prices = _prices_for(engine, portfolio)
    positions_value = portfolio.positions_value(prices)
    equity = portfolio.cash + positions_value

    history = engine.store.equity_history()
    curve = [(row["snapshot_date"][5:], row["total_equity"]) for row in history]
    perf = compute_performance(
        engine.store.trades(), [r["total_equity"] for r in history],
        engine.store.starting_cash, equity,
        sum(p.unrealized_pnl(prices.get(p.symbol, p.entry_price))
            for p in portfolio.positions),
    )

    pending = engine.store.proposals("pending")
    mode = engine.settings.execution_mode
    pf = "&infin;" if perf.profit_factor == float("inf") else f"{perf.profit_factor:.2f}"

    stats = f"""<div class="grid">
<div class="stat"><div class="l">Equity</div><div class="v">{_money(equity)}</div></div>
<div class="stat"><div class="l">Total P&amp;L</div>
  <div class="v {_cls(perf.total_pnl)}">{perf.total_pnl:+,.2f}</div></div>
<div class="stat"><div class="l">Return</div>
  <div class="v {_cls(perf.total_return_pct)}">{perf.total_return_pct:+.2f}%</div></div>
<div class="stat"><div class="l">Cash</div><div class="v">{_money(portfolio.cash)}</div></div>
<div class="stat"><div class="l">Open</div><div class="v">{len(portfolio.positions)}</div></div>
<div class="stat"><div class="l">Win rate</div><div class="v">{perf.win_rate:.0f}%</div></div>
<div class="stat"><div class="l">Profit factor</div><div class="v">{pf}</div></div>
<div class="stat"><div class="l">Max drawdown</div>
  <div class="v down">{perf.max_drawdown_pct:.2f}%</div></div>
</div>"""

    queue = ""
    if pending:
        queue = (
            f'<div class="card"><div class="row"><h3>{len(pending)} idea'
            f'{"s" if len(pending) != 1 else ""} awaiting your decision</h3>'
            f'<a href="/ideas" style="color:var(--accent);font-weight:600;'
            f'text-decoration:none">Review &rarr;</a></div></div>'
        )

    body = f"""<h1>Overview</h1>
<p class="muted">{E(engine.settings.profile.label)} risk &middot; {E(mode)} mode
&middot; {date.today().isoformat()}</p>
{queue}{stats}
<h2>Equity curve</h2><div class="card">{equity_curve(curve)}</div>
<h2>Where the money is</h2><div class="card overflow">{_positions_table(portfolio, prices)}</div>
<p class="muted" style="font-size:13px">{E(perf.verdict())}</p>"""
    return page("Overview", "/", body, _data_warning(engine))


def _positions_table(portfolio, prices) -> str:
    if not portfolio.positions:
        return '<p class="muted">No open positions - the desk is fully in cash.</p>'
    rows = ""
    for p in sorted(portfolio.positions,
                    key=lambda x: -x.unrealized_pnl(prices.get(x.symbol, x.entry_price))):
        price = prices.get(p.symbol, p.entry_price)
        pnl = p.unrealized_pnl(price)
        badge = f'<span class="badge {"short" if p.is_short else "long"}">{"SHORT" if p.is_short else "LONG"}</span>'
        rows += (
            f'<tr><td><a href="/symbol?s={E(p.symbol)}">{E(p.symbol)}</a> {badge}</td>'
            f'<td>{p.shares}</td><td>{_money(p.entry_price)}</td><td>{_money(price)}</td>'
            f'<td class="{_cls(pnl)}">{pnl:+,.2f}</td>'
            f'<td class="{_cls(pnl)}">{p.unrealized_pct(price):+.1f}%</td>'
            f'<td class="{_cls(p.r_multiple(price))}">{p.r_multiple(price):+.2f}R</td>'
            f'<td>{_money(p.stop_price)}</td><td>{p.days_held()}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Last</th>"
        "<th>P&amp;L</th><th>%</th><th>R</th><th>Stop</th><th>Days</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def ideas(engine) -> str:
    pending = engine.store.proposals("pending")
    mode = engine.settings.execution_mode

    if mode != "manual":
        note = (
            '<div class="warn">Running in <strong>auto</strong> mode: ideas are '
            "placed as working orders without asking. Set execution_mode to "
            "&quot;manual&quot; in config.json to review them here first.</div>"
        )
    else:
        note = ""

    if not pending:
        working = engine.store.pending_orders()
        extra = ""
        if working:
            rows = "".join(
                f"<tr><td>{E(o.symbol)}</td><td>{E(o.direction)}</td>"
                f"<td>{o.shares}</td>"
                f"<td>{_money(o.trigger_price) if o.trigger_price else 'market'}</td>"
                f"<td>{o.expires_date}</td></tr>"
                for o in working
            )
            extra = (
                f"<h2>Working orders ({len(working)})</h2><div class='card overflow'>"
                "<table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th>"
                "<th>Trigger</th><th>Expires</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )
        body = (
            f"<h1>Ideas</h1>{note}"
            '<div class="card"><p class="muted">Nothing waiting. Press '
            "<strong>Run scan</strong> to look for new setups - and remember that "
            "finding nothing is a valid result, not a failure.</p></div>" + extra
        )
        return page("Ideas", "/ideas", body, _data_warning(engine))

    cards = "".join(_idea_card(p) for p in pending)
    body = f"<h1>Ideas</h1>{note}<p class='muted'>{len(pending)} awaiting a decision.</p>{cards}"
    return page("Ideas", "/ideas", body, _data_warning(engine))


def _idea_card(p) -> str:
    steps = "".join(f"<li>{E(line)}</li>" for line in p.instruction_lines)
    reasons = "".join(f"<li>{E(r)}</li>" for r in p.rationale.split(" | ") if r)
    proxy = (
        f'<p class="note">Bearish view on {E(p.proxy_for)}, expressed by buying '
        f"the inverse ETF {E(p.symbol)}. You are buying, not shorting.</p>"
        if p.proxy_for else ""
    )
    side = "SHORT" if p.is_short else "LONG"
    return f"""<div class="card idea"><header>
<h3><a href="/symbol?s={E(p.symbol)}" style="color:inherit;text-decoration:none">{E(p.symbol)}</a>
<span class="badge {"short" if p.is_short else "long"}">{side}</span></h3>
<span class="badge">{p.score:.0f}/100</span></header>
<p class="muted" style="font-size:13px;margin:6px 0 0">{E(p.setup)} &middot;
{p.shares} shares &middot; risk {_money(p.risk_dollars)} &middot;
reward:risk {p.reward_risk:.1f}:1 &middot; expires {p.expires_date}</p>
<ul class="why">{reasons}</ul>{proxy}
<ol class="steps">{steps}</ol>
<div class="actions">
<form method="post" action="/approve" style="margin:0;flex:1">
<input type="hidden" name="id" value="{p.id}">
<button class="approve" type="submit" style="width:100%">Approve</button></form>
<form method="post" action="/reject" style="margin:0;flex:1">
<input type="hidden" name="id" value="{p.id}">
<button class="reject" type="submit" style="width:100%">Skip</button></form>
</div></div>"""


def positions(engine) -> str:
    portfolio = engine.store.load_portfolio()
    prices = _prices_for(engine, portfolio)
    open_risk = sum(
        abs(prices.get(p.symbol, p.entry_price) - p.stop_price) * p.shares
        for p in portfolio.positions
    )
    equity = portfolio.cash + portfolio.positions_value(prices)
    risk_line = (
        f'<p class="muted">If every stop triggered at once: {_money(open_risk)} '
        f"({open_risk / equity * 100:.2f}% of equity).</p>"
        if portfolio.positions and equity else ""
    )
    body = (
        f"<h1>Positions</h1><div class='card overflow'>"
        f"{_positions_table(portfolio, prices)}</div>{risk_line}"
    )
    return page("Positions", "/positions", body, _data_warning(engine))


def history(engine) -> str:
    trades = engine.store.trades(limit=120)
    if not trades:
        body = "<h1>History</h1><div class='card'><p class='muted'>No trades yet.</p></div>"
        return page("History", "/history", body, _data_warning(engine))

    rows = ""
    for t in trades:
        pnl = f"{t.realized_pnl:+,.2f}" if t.realized_pnl is not None else ""
        cls = _cls(t.realized_pnl) if t.realized_pnl is not None else ""
        rows += (
            f"<tr><td>{t.trade_date.isoformat()}</td>"
            f'<td><a href="/symbol?s={E(t.symbol)}">{E(t.symbol)}</a></td>'
            f"<td>{E(t.action)}</td><td>{t.shares}</td><td>{_money(t.price)}</td>"
            f'<td class="{cls}">{pnl}</td>'
            f'<td class="muted" style="text-align:left">{E(t.reason[:44])}</td></tr>'
        )
    body = f"""<h1>History</h1><div class="card overflow"><table><thead><tr>
<th>Date</th><th>Symbol</th><th>Action</th><th>Qty</th><th>Price</th>
<th>P&amp;L</th><th style="text-align:left">Reason</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""
    return page("History", "/history", body, _data_warning(engine))


def symbol_detail(engine, symbol: str) -> str:
    try:
        bars = engine.provider.history(symbol, 400)
    except Exception as exc:
        body = (
            f"<h1>{E(symbol)}</h1><div class='card'><p class='muted'>"
            f"Could not load data: {E(str(exc))}</p></div>"
        )
        return page(symbol, "", body, _data_warning(engine))

    enriched = compute_all(bars)
    trend = classify(bars, enriched)
    patterns = CandlestickScanner().scan(bars, lookback=60)
    markers = [
        {"date": p.date, "label": f"{p.name} - {p.explanation}",
         "direction": p.direction}
        for p in patterns
    ]
    levels = [
        {"price": lv.price, "label": f"{lv.kind} {lv.touches}x", "kind": lv.kind}
        for lv in find_levels(bars)[:4]
    ]

    position = engine.store.load_portfolio().position_for(symbol)
    if position:
        levels.append({"price": position.entry_price, "label": "entry", "kind": "entry"})
        levels.append({"price": position.stop_price, "label": "stop", "kind": "stop"})
        for price, _ in position.targets:
            levels.append({"price": price, "label": "target", "kind": "target"})

    chart = candlestick(
        bars, overlays={"SMA20": enriched["sma20"], "SMA50": enriched["sma50"]},
        markers=markers, levels=levels, sessions=110,
    )

    recent = sorted(patterns, key=lambda p: -p.index)[:6]
    pattern_rows = "".join(
        f'<tr><td>{p.date.date()}</td><td class="{"up" if p.direction == "bullish" else "down"}">'
        f"{E(p.name)}</td><td>{p.strength:.2f}</td>"
        f'<td class="muted" style="text-align:left">{E(p.explanation)}</td></tr>'
        for p in recent
    ) or '<tr><td colspan="4" class="muted">No patterns in the recent window.</td></tr>'

    reasons = "".join(f"<li>{E(r)}</li>" for r in trend.reasons)
    last = enriched.iloc[-1]
    body = f"""<h1>{E(symbol)}</h1>
<p class="muted">{E(trend.label)} &middot; ADX {trend.adx:.0f} &middot;
ATR {_money(float(last['atr14']))} ({float(last['atr_pct']):.1f}%) &middot;
{trend.pct_from_52w_high:+.1f}% from the 52-week high</p>
<div class="card">{chart}</div>
<h2>Why the desk reads it this way</h2>
<div class="card"><ul class="why">{reasons}</ul></div>
<h2>Recent candlestick patterns</h2>
<div class="card overflow"><table><thead><tr><th>Date</th><th>Pattern</th>
<th>Strength</th><th style="text-align:left">Meaning</th></tr></thead>
<tbody>{pattern_rows}</tbody></table></div>"""
    return page(symbol, "", body, _data_warning(engine))


# --- helpers ------------------------------------------------------------------
def _data_warning(engine) -> str:
    name = getattr(engine.provider, "name", "")
    if "synthetic" in name:
        return (
            "SIMULATED PRICE DATA - live market data is unavailable, so these "
            "charts and figures are generated, not the real market."
        )
    return ""


def state_json(engine) -> dict:
    portfolio = engine.store.load_portfolio()
    prices = _prices_for(engine, portfolio)
    equity = portfolio.cash + portfolio.positions_value(prices)
    return {
        "as_of": date.today().isoformat(),
        "mode": engine.settings.execution_mode,
        "risk_profile": engine.settings.profile.name,
        "equity": round(equity, 2),
        "cash": round(portfolio.cash, 2),
        "positions": [
            {
                "symbol": p.symbol, "direction": p.direction, "shares": p.shares,
                "entry": p.entry_price,
                "price": prices.get(p.symbol, p.entry_price),
                "unrealized": round(
                    p.unrealized_pnl(prices.get(p.symbol, p.entry_price)), 2
                ),
                "r": round(p.r_multiple(prices.get(p.symbol, p.entry_price)), 2),
                "stop": p.stop_price,
            }
            for p in portfolio.positions
        ],
        "pending_proposals": [
            {"id": p.id, "symbol": p.symbol, "direction": p.direction,
             "score": p.score, "shares": p.shares, "entry": p.entry_price,
             "stop": p.stop_price}
            for p in engine.store.proposals("pending")
        ],
        "simulated_data": bool(_data_warning(engine)),
    }


def not_found(route: str) -> str:
    body = (
        f"<h1>Not found</h1><div class='card'><p class='muted'>No page at "
        f"<code>{E(route)}</code>.</p></div>"
    )
    return page("Not found", "", body)


def error_page(exc: Exception) -> str:
    detail = E("".join(traceback.format_exception_only(type(exc), exc)).strip())
    body = (
        f"<h1>Something broke</h1><div class='card'><p>{detail}</p>"
        "<p class='muted'>The server is still running - go back and try again.</p>"
        "</div>"
    )
    return page("Error", "", body)
