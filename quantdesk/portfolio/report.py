"""Daily portfolio reporting, as plain text and as a standalone HTML page."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime

from quantdesk.portfolio.metrics import Performance
from quantdesk.portfolio.store import Portfolio, Position, Trade

DISCLAIMER = (
    "Educational simulation only. Not financial advice. Play money - no real "
    "orders are placed. Past or simulated performance does not predict future "
    "results."
)


def _r_cell(value: float | None) -> str:
    """R for a fixed-width column, blank when the position has no usable risk."""
    return "  -" if value is None else f"{value:+.2f}"


def _r_text(value: float | None) -> str:
    """R for an HTML cell. A dash, not 0.00R, which would read as break-even."""
    return "-" if value is None else f"{value:+.2f}R"


@dataclass
class DailyReport:
    as_of: date
    portfolio: Portfolio
    prices: dict[str, float]
    performance: Performance
    events: list
    recommendations: list
    equity: float
    positions_value: float
    risk_profile: str
    data_warning: str = ""

    # --- helpers ------------------------------------------------------------
    def _position_rows(self) -> list[dict]:
        rows = []
        for p in sorted(
            self.portfolio.positions,
            key=lambda x: -x.unrealized_pnl(self.prices.get(x.symbol, x.entry_price)),
        ):
            price = self.prices.get(p.symbol, p.entry_price)
            rows.append({
                "symbol": p.symbol,
                "shares": p.shares,
                "entry": p.entry_price,
                "price": price,
                "value": p.market_value(price),
                "pnl": p.unrealized_pnl(price),
                "pnl_pct": p.unrealized_pct(price),
                "r": p.r_multiple(price),
                "stop": p.stop_price,
                "risk_now": (price - p.stop_price) * p.shares,
                "days": p.days_held(self.as_of),
                "setup": p.setup,
            })
        return rows

    # --- text ---------------------------------------------------------------
    def to_text(self, width: int = 78) -> str:
        L: list[str] = []
        rule = "=" * width
        thin = "-" * width

        L.append(rule)
        L.append(f"QUANTDESK DAILY REPORT - {self.as_of.isoformat()}".center(width))
        L.append(f"risk profile: {self.risk_profile}".center(width))
        L.append(rule)

        if self.data_warning:
            L.append("")
            L.append(f"!! {self.data_warning}")

        perf = self.performance
        start = self.portfolio.starting_cash
        L.append("")
        L.append("PORTFOLIO")
        L.append(thin)
        L.append(f"  Total equity      ${self.equity:>14,.2f}")
        L.append(f"  Cash              ${self.portfolio.cash:>14,.2f}")
        L.append(f"  Positions         ${self.positions_value:>14,.2f}  "
                 f"({len(self.portfolio.positions)} open)")
        L.append(f"  Starting capital  ${start:>14,.2f}")
        L.append(f"  Total P&L         ${perf.total_pnl:>+14,.2f}  "
                 f"({perf.total_return_pct:+.2f}%)")

        L.append("")
        L.append("PERFORMANCE")
        L.append(thin)
        L.append(f"  Closed trades {perf.closed_trades:<5} "
                 f"Win rate {perf.win_rate:>5.1f}%  "
                 f"({perf.wins}W / {perf.losses}L)")
        L.append(f"  Avg win  ${perf.avg_win:>10,.2f}   Avg loss ${perf.avg_loss:>10,.2f}")
        pf = "inf" if perf.profit_factor == float("inf") else f"{perf.profit_factor:.2f}"
        L.append(f"  Profit factor {pf:<8} Expectancy ${perf.expectancy:,.2f}/trade")
        L.append(f"  Max drawdown {perf.max_drawdown_pct:>6.2f}%   Sharpe {perf.sharpe:.2f}")
        L.append(f"  Best ${perf.best_trade:+,.2f}   Worst ${perf.worst_trade:+,.2f}")
        L.append(f"  > {perf.verdict()}")

        rows = self._position_rows()
        L.append("")
        L.append(f"OPEN POSITIONS ({len(rows)})")
        L.append(thin)
        if not rows:
            L.append("  none - the desk is fully in cash")
        else:
            L.append(f"  {'SYM':<7}{'QTY':>5}{'ENTRY':>10}{'LAST':>10}"
                     f"{'P&L':>12}{'%':>8}{'R':>7}{'STOP':>10}{'DAYS':>6}")
            for r in rows:
                L.append(
                    f"  {r['symbol']:<7}{r['shares']:>5}{r['entry']:>10,.2f}"
                    f"{r['price']:>10,.2f}{r['pnl']:>+12,.2f}{r['pnl_pct']:>+8.1f}"
                    f"{_r_cell(r['r']):>7}{r['stop']:>10,.2f}{r['days']:>6}"
                )
            open_risk = sum((r['price'] - r['stop']) * r['shares'] for r in rows)
            L.append("")
            L.append(f"  Capital at risk if every stop triggers: ${open_risk:,.2f} "
                     f"({open_risk / self.equity * 100:.2f}% of equity)")

        L.append("")
        L.append("TODAY'S ACTIVITY")
        L.append(thin)
        if not self.events:
            L.append("  no fills, exits or stop changes")
        else:
            for e in self.events:
                L.append(f"  - {e.symbol}: {e.detail}")

        L.append("")
        L.append(f"NEW IDEAS ({len(self.recommendations)})")
        L.append(thin)
        if not self.recommendations:
            L.append("  nothing met the criteria today - staying in cash is a position")
        for rec in self.recommendations:
            plan, sig = rec.plan, rec.signal
            L.append("")
            L.append(f"  {rec.symbol} - {rec.instrument.name[:44]}")
            L.append(f"  score {sig.score:.0f}/100 ({rec.confidence_label()} confidence)"
                     f" | {plan.setup} | {sig.trend.label}")
            L.append(f"  Why:")
            for reason in sig.reasons[:4]:
                L.append(f"    - {reason}")
            L.append(f"  Plan (reward:risk {plan.reward_risk:.1f}:1):")
            for line in plan.instructions():
                L.append(f"    {line}")
            for note in plan.notes:
                L.append(f"    ! {note}")

        L.append("")
        L.append(rule)
        L.append(DISCLAIMER)
        L.append(rule)
        return "\n".join(L)

    # --- html ---------------------------------------------------------------
    def to_html(self) -> str:
        e = html.escape
        perf = self.performance
        rows = self._position_rows()

        def money(v: float) -> str:
            return f"${v:,.2f}"

        def cls(v: float) -> str:
            return "up" if v > 0 else ("down" if v < 0 else "flat")

        pos_html = "".join(
            f"<tr><td class='sym'>{e(r['symbol'])}</td><td>{r['shares']}</td>"
            f"<td>{money(r['entry'])}</td><td>{money(r['price'])}</td>"
            f"<td class='{cls(r['pnl'])}'>{r['pnl']:+,.2f}</td>"
            f"<td class='{cls(r['pnl'])}'>{r['pnl_pct']:+.1f}%</td>"
            f"<td class='{cls(r['r'] or 0.0)}'>{_r_text(r['r'])}</td>"
            f"<td>{money(r['stop'])}</td><td>{r['days']}</td></tr>"
            for r in rows
        ) or "<tr><td colspan='9' class='muted'>No open positions.</td></tr>"

        events_html = "".join(
            f"<li><strong>{e(ev.symbol)}</strong> - {e(ev.detail)}</li>"
            for ev in self.events
        ) or "<li class='muted'>No fills, exits or stop changes today.</li>"

        recs_html = ""
        for rec in self.recommendations:
            plan, sig = rec.plan, rec.signal
            steps = "".join(f"<li>{e(line)}</li>" for line in plan.instructions())
            reasons = "".join(f"<li>{e(r)}</li>" for r in sig.reasons[:4])
            notes = "".join(f"<p class='note'>{e(n)}</p>" for n in plan.notes)
            recs_html += f"""
            <article class="idea">
              <header>
                <h3>{e(rec.symbol)} <span class="muted">{e(rec.instrument.name[:44])}</span></h3>
                <span class="badge">{sig.score:.0f}/100 - {e(rec.confidence_label())}</span>
              </header>
              <p class="meta">{e(plan.setup)} setup &middot; {e(sig.trend.label)}
                 &middot; reward:risk {plan.reward_risk:.1f}:1</p>
              <h4>Why</h4><ul class="why">{reasons}</ul>
              <h4>Instructions</h4><ol class="steps">{steps}</ol>{notes}
            </article>"""
        if not self.recommendations:
            recs_html = ("<p class='muted'>Nothing met the criteria today. "
                         "Staying in cash is a position.</p>")

        warning = (
            f"<div class='warn'>{e(self.data_warning)}</div>" if self.data_warning else ""
        )
        pf = "&infin;" if perf.profit_factor == float("inf") else f"{perf.profit_factor:.2f}"

        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QuantDesk - {self.as_of.isoformat()}</title>
<style>
  :root {{
    --bg:#f6f7f9; --card:#fff; --ink:#1a1d21; --muted:#6b7280; --line:#e5e7eb;
    --up:#0f7b3f; --down:#b42318; --accent:#1d4ed8;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0e1116; --card:#171b21; --ink:#e6e8eb; --muted:#9aa4b2;
             --line:#252b33; --up:#3ddc84; --down:#ff6b6b; --accent:#7aa2ff; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:24px; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--muted); margin:28px 0 10px; }}
  h3 {{ margin:0; font-size:17px; }}
  h4 {{ margin:14px 0 6px; font-size:13px; text-transform:uppercase;
       letter-spacing:.05em; color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--line);
    border-radius:12px; padding:18px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
  .stat {{ background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:12px 14px; }}
  .stat .label {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); }}
  .stat .value {{ font-size:20px; font-weight:650; margin-top:2px;
    font-variant-numeric:tabular-nums; }}
  table {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
  th,td {{ text-align:right; padding:8px 10px; border-bottom:1px solid var(--line);
    font-size:14px; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); }}
  .sym {{ font-weight:650; }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }}
  .muted {{ color:var(--muted); }}
  .idea {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:16px 18px; margin-bottom:14px; }}
  .idea header {{ display:flex; justify-content:space-between; align-items:center;
    gap:12px; flex-wrap:wrap; }}
  .badge {{ background:var(--accent); color:#fff; border-radius:999px;
    padding:3px 10px; font-size:12px; font-weight:600; white-space:nowrap; }}
  .meta {{ color:var(--muted); font-size:13px; margin:6px 0 0; }}
  .steps li {{ margin:5px 0; }}
  .why li {{ margin:3px 0; color:var(--muted); }}
  .note {{ background:rgba(180,35,24,.08); border-left:3px solid var(--down);
    padding:8px 10px; border-radius:0 6px 6px 0; font-size:13px; }}
  .warn {{ background:rgba(234,179,8,.15); border:1px solid rgba(234,179,8,.5);
    border-radius:8px; padding:10px 12px; margin:14px 0; font-size:14px; }}
  footer {{ margin-top:28px; padding-top:14px; border-top:1px solid var(--line);
    color:var(--muted); font-size:12px; }}
  ul,ol {{ margin:6px 0; padding-left:20px; }}
  .overflow {{ overflow-x:auto; }}
</style></head><body><div class="wrap">
  <h1>QuantDesk daily report</h1>
  <p class="muted">{self.as_of.isoformat()} &middot; {e(self.risk_profile)} risk profile</p>
  {warning}

  <h2>Portfolio</h2>
  <div class="grid">
    <div class="stat"><div class="label">Total equity</div>
      <div class="value">{money(self.equity)}</div></div>
    <div class="stat"><div class="label">Total P&amp;L</div>
      <div class="value {cls(perf.total_pnl)}">{perf.total_pnl:+,.2f}</div></div>
    <div class="stat"><div class="label">Return</div>
      <div class="value {cls(perf.total_return_pct)}">{perf.total_return_pct:+.2f}%</div></div>
    <div class="stat"><div class="label">Cash</div>
      <div class="value">{money(self.portfolio.cash)}</div></div>
    <div class="stat"><div class="label">Win rate</div>
      <div class="value">{perf.win_rate:.0f}%</div></div>
    <div class="stat"><div class="label">Profit factor</div>
      <div class="value">{pf}</div></div>
    <div class="stat"><div class="label">Max drawdown</div>
      <div class="value down">{perf.max_drawdown_pct:.2f}%</div></div>
    <div class="stat"><div class="label">Sharpe</div>
      <div class="value">{perf.sharpe:.2f}</div></div>
  </div>
  <p class="muted" style="margin-top:10px">{e(perf.verdict())}</p>

  <h2>Open positions</h2>
  <div class="card overflow"><table>
    <thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Last</th><th>P&amp;L</th>
    <th>%</th><th>R</th><th>Stop</th><th>Days</th></tr></thead>
    <tbody>{pos_html}</tbody></table></div>

  <h2>Today's activity</h2>
  <div class="card"><ul>{events_html}</ul></div>

  <h2>New ideas</h2>
  {recs_html}

  <footer>{e(DISCLAIMER)}</footer>
</div></body></html>"""
