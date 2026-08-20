"""Performance measurement.

Total return alone tells you almost nothing: it hides how much risk was taken to
get there and how many times the account nearly blew up on the way. These are
the numbers that actually say whether an approach is working.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quantdesk.portfolio.store import Trade

TRADING_DAYS = 252


@dataclass
class Performance:
    total_return_pct: float
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    wins: int
    losses: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown_pct: float
    sharpe: float
    best_trade: float
    worst_trade: float
    closed_trades: int

    def verdict(self) -> str:
        """A plain-English read on the numbers so far."""
        if self.closed_trades < 10:
            return (
                f"Only {self.closed_trades} closed trades - far too few to judge. "
                "Treat any result here as noise until there are 30+."
            )
        if self.profit_factor >= 1.5 and self.max_drawdown_pct > -20:
            return "Working: profits outweigh losses with a tolerable drawdown."
        if self.profit_factor >= 1.0:
            return "Marginally profitable - edge is thin relative to the risk taken."
        return "Losing money. The rules need review before committing anything real."


def _drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst * 100.0


def _sharpe(equity: list[float]) -> float:
    """Annualised Sharpe of the daily equity curve, risk-free assumed zero."""
    if len(equity) < 3:
        return 0.0
    returns = [
        equity[i] / equity[i - 1] - 1.0
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    sd = math.sqrt(variance)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(TRADING_DAYS)


def compute_performance(
    trades: list[Trade],
    equity_curve: list[float],
    starting_cash: float,
    current_equity: float,
    unrealized_pnl: float = 0.0,
) -> Performance:
    """Summarise results from the trade log and equity history."""
    closed = [t for t in trades if t.action == "sell" and t.realized_pnl is not None]
    pnls = [float(t.realized_pnl) for t in closed]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    win_rate = (len(wins) / len(pnls) * 100.0) if pnls else 0.0
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_win > 0 else 0.0
    )
    expectancy = (sum(pnls) / len(pnls)) if pnls else 0.0

    total_return = (
        (current_equity / starting_cash - 1.0) * 100.0 if starting_cash > 0 else 0.0
    )

    return Performance(
        total_return_pct=round(total_return, 2),
        total_pnl=round(current_equity - starting_cash, 2),
        realized_pnl=round(sum(pnls), 2),
        unrealized_pnl=round(unrealized_pnl, 2),
        win_rate=round(win_rate, 1),
        wins=len(wins),
        losses=len(losses),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2) if math.isfinite(profit_factor) else float("inf"),
        expectancy=round(expectancy, 2),
        max_drawdown_pct=round(_drawdown(equity_curve), 2),
        sharpe=round(_sharpe(equity_curve), 2),
        best_trade=round(max(pnls), 2) if pnls else 0.0,
        worst_trade=round(min(pnls), 2) if pnls else 0.0,
        closed_trades=len(pnls),
    )
