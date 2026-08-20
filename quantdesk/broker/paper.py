"""Play-money execution engine.

Design decisions that keep the simulation honest rather than flattering:

* **Orders wait for their trigger.** A breakout idea generated today is filled
  only if a later session actually trades through the trigger price. Ideas that
  never trigger expire unfilled, exactly as they would in a real account.

* **Gaps are respected.** If a stock gaps below your stop overnight you are
  filled at the open, not at the stop price. This is where real accounts take
  their worst losses and a simulator that ignores it is lying to you.

* **Stops are assumed to fill before targets.** When a single daily bar spans
  both the stop and a target, there is no way to know which came first. The
  engine assumes the stop. Over many trades this biases results slightly
  pessimistic, which is the only safe direction to be wrong in.

* **Slippage and commission are charged** on every fill, always against you.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from quantdesk.config import Settings
from quantdesk.portfolio.store import Order, PortfolioStore, Position, Trade
from quantdesk.strategy.risk import TradePlan

ORDER_LIFETIME_DAYS = 5
"""How long a working order stays live before the setup is considered stale."""


@dataclass
class ExecutionEvent:
    """Something the broker did, for the daily report."""

    kind: str  # "fill" | "exit" | "partial" | "stop_moved" | "expired" | "rejected"
    symbol: str
    detail: str
    shares: int = 0
    price: float = 0.0
    pnl: float | None = None

    def __str__(self) -> str:
        return f"[{self.kind}] {self.symbol}: {self.detail}"


@dataclass
class DailyRunSummary:
    events: list[ExecutionEvent] = field(default_factory=list)
    orders_placed: int = 0
    fills: int = 0
    exits: int = 0
    realized_pnl: float = 0.0

    def add(self, event: ExecutionEvent) -> None:
        self.events.append(event)
        if event.kind == "fill":
            self.fills += 1
        elif event.kind in ("exit", "partial"):
            self.exits += 1
            if event.pnl:
                self.realized_pnl += event.pnl


class PaperBroker:
    """Simulated broker operating on daily bars."""

    def __init__(self, store: PortfolioStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    # --- costs --------------------------------------------------------------
    def _slippage(self, price: float) -> float:
        return price * self.settings.slippage_bps / 10_000.0

    def _buy_fill_price(self, price: float) -> float:
        return round(price + self._slippage(price), 4)

    def _sell_fill_price(self, price: float) -> float:
        return round(max(0.01, price - self._slippage(price)), 4)

    def _commission(self, shares: int) -> float:
        return round(shares * self.settings.commission_per_share, 2)

    # --- order placement ----------------------------------------------------
    def place_from_plan(self, plan: TradePlan, as_of: date | None = None) -> ExecutionEvent:
        """Turn a trade plan into a working order."""
        as_of = as_of or date.today()
        if plan.shares <= 0:
            return ExecutionEvent("rejected", plan.symbol, "plan sizes to zero shares")

        order_type = {"buy_stop": "stop", "limit": "limit", "market": "market"}[
            plan.entry_style
        ]
        order = Order(
            symbol=plan.symbol,
            side="buy",
            order_type=order_type,
            shares=plan.shares,
            trigger_price=plan.entry_price if order_type != "market" else None,
            stop_loss=plan.stop_price,
            targets=[(t.price, t.take_pct) for t in plan.targets],
            setup=plan.setup,
            risk_dollars=plan.risk_dollars,
            time_stop_days=plan.time_stop_days,
            created_date=as_of,
            expires_date=as_of + timedelta(days=ORDER_LIFETIME_DAYS),
            note=plan.entry_condition,
        )
        self.store.add_order(order)
        label = {
            "stop": f"buy-stop @ ${plan.entry_price:,.2f}",
            "limit": f"buy-limit @ ${plan.entry_price:,.2f}",
            "market": "market-on-open",
        }[order_type]
        return ExecutionEvent(
            "order", plan.symbol,
            f"working order placed: {label} x{plan.shares}, "
            f"stop ${plan.stop_price:,.2f}",
            shares=plan.shares, price=plan.entry_price,
        )

    # --- daily processing ---------------------------------------------------
    def process_day(
        self, bars_by_symbol: dict[str, pd.DataFrame], as_of: date | None = None
    ) -> DailyRunSummary:
        """Advance the account by one session.

        Exits are processed before entries so capital freed by a stop-out is
        available to the same day's new orders.
        """
        as_of = as_of or date.today()
        summary = DailyRunSummary()

        self._manage_positions(bars_by_symbol, as_of, summary)
        self._process_orders(bars_by_symbol, as_of, summary)
        return summary

    # --- exits --------------------------------------------------------------
    def _manage_positions(self, bars_by_symbol, as_of: date, summary: DailyRunSummary) -> None:
        for position in self.store.open_positions():
            bars = bars_by_symbol.get(position.symbol)
            if bars is None or bars.empty:
                continue
            bar = bars.iloc[-1]
            o, h, l, c = (float(bar["open"]), float(bar["high"]),
                          float(bar["low"]), float(bar["close"]))

            # 1. Stop first - the pessimistic assumption (see module docstring).
            if l <= position.stop_price:
                # A gap through the stop fills at the open, not the stop price.
                exit_price = o if o <= position.stop_price else position.stop_price
                reason = (
                    "gapped through the stop - filled at the open"
                    if o <= position.stop_price
                    else "stop loss hit"
                )
                self._close(position, position.shares, exit_price, as_of, reason, summary)
                continue

            # 2. Targets, in ascending order.
            remaining_targets = list(position.targets)
            hit_any = False
            for target_price, take_frac in list(remaining_targets):
                if h >= target_price and position.shares > 0:
                    qty = max(1, int(round(position.shares * take_frac)))
                    qty = min(qty, position.shares)
                    fill = max(target_price, o)  # a gap above the target fills better
                    self._close(
                        position, qty, fill, as_of,
                        f"target ${target_price:,.2f} reached", summary,
                        partial=qty < position.shares,
                    )
                    remaining_targets.remove((target_price, take_frac))
                    hit_any = True
                    if position.shares <= 0:
                        break
            if hit_any and position.shares > 0:
                position.targets = remaining_targets
                self.store.update_position(position)
            if position.shares <= 0:
                continue

            # 3. Trailing stop, driven by the highest close achieved.
            self._update_trailing_stop(position, c, bars, as_of, summary)

            # 4. Time stop.
            if position.days_held(as_of) > position.time_stop_days:
                self._close(
                    position, position.shares, c, as_of,
                    f"time stop - held {position.days_held(as_of)} days without "
                    "reaching target", summary,
                )

    def _update_trailing_stop(
        self, position: Position, close: float, bars, as_of: date, summary
    ) -> None:
        profile = self.settings.profile
        if close > position.highest_close:
            position.highest_close = close

        r_now = position.r_multiple(close)
        if r_now < profile.trail_after_r:
            return

        atr_val = None
        if "atr14" in bars.columns:
            raw = bars["atr14"].iloc[-1]
            atr_val = float(raw) if pd.notna(raw) else None
        if atr_val is None:
            from quantdesk.analysis.indicators import atr as _atr

            series = _atr(bars["high"], bars["low"], bars["close"], 14)
            raw = series.iloc[-1]
            atr_val = float(raw) if pd.notna(raw) else close * 0.02

        trailed = position.highest_close - profile.trail_atr_mult * atr_val
        # Never below breakeven once trailing has activated, and never backwards.
        new_stop = round(max(trailed, position.entry_price, position.stop_price), 2)

        if new_stop > position.stop_price + 1e-9:
            old = position.stop_price
            position.stop_price = new_stop
            self.store.update_position(position)
            summary.add(ExecutionEvent(
                "stop_moved", position.symbol,
                f"trailing stop raised ${old:,.2f} -> ${new_stop:,.2f} "
                f"(open profit {r_now:.2f}R)",
                price=new_stop,
            ))

    def _close(
        self, position: Position, shares: int, price: float, as_of: date,
        reason: str, summary: DailyRunSummary, partial: bool = False,
    ) -> None:
        shares = min(shares, position.shares)
        if shares <= 0:
            return

        fill = self._sell_fill_price(price)
        commission = self._commission(shares)
        proceeds = shares * fill - commission
        pnl = (fill - position.entry_price) * shares - commission

        self.store.cash = self.store.cash + proceeds
        self.store.record_trade(Trade(
            symbol=position.symbol, action="sell", shares=shares, price=fill,
            trade_date=as_of, commission=commission, reason=reason,
            realized_pnl=round(pnl, 2), position_id=position.id,
        ))

        position.shares -= shares
        if position.shares <= 0:
            position.status = "closed"
            self.store.close_position(position.id)
        else:
            self.store.update_position(position)

        summary.add(ExecutionEvent(
            "partial" if partial and position.shares > 0 else "exit",
            position.symbol,
            f"sold {shares} @ ${fill:,.2f} - {reason} "
            f"(P&L ${pnl:+,.2f}, {position.r_multiple(fill):+.2f}R)",
            shares=shares, price=fill, pnl=round(pnl, 2),
        ))

    # --- entries ------------------------------------------------------------
    def _process_orders(self, bars_by_symbol, as_of: date, summary: DailyRunSummary) -> None:
        profile = self.settings.profile
        open_symbols = {p.symbol for p in self.store.open_positions()}

        for order in self.store.pending_orders():
            if as_of > order.expires_date:
                self.store.set_order_status(order.id, "expired")
                summary.add(ExecutionEvent(
                    "expired", order.symbol,
                    "working order expired without triggering - the setup went stale",
                ))
                continue

            bars = bars_by_symbol.get(order.symbol)
            if bars is None or bars.empty:
                continue
            bar = bars.iloc[-1]
            o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])

            fill_price = self._match(order, o, h, l)
            if fill_price is None:
                continue

            if order.symbol in open_symbols:
                self.store.set_order_status(order.id, "cancelled")
                summary.add(ExecutionEvent(
                    "rejected", order.symbol, "already holding this symbol",
                ))
                continue

            positions = self.store.open_positions()
            if len(positions) >= profile.max_positions:
                self.store.set_order_status(order.id, "cancelled")
                summary.add(ExecutionEvent(
                    "rejected", order.symbol,
                    f"at the {profile.max_positions}-position limit for "
                    f"{profile.name} risk",
                ))
                continue

            fill = self._buy_fill_price(fill_price)
            commission = self._commission(order.shares)
            cost = order.shares * fill + commission

            # Respect the cash floor: never deploy the whole account.
            equity = self.store.cash + sum(
                p.market_value(p.entry_price) for p in positions
            )
            min_cash = equity * profile.cash_floor_pct
            if self.store.cash - cost < min_cash:
                affordable = int(max(0, (self.store.cash - min_cash - commission)) // fill)
                if affordable <= 0:
                    self.store.set_order_status(order.id, "cancelled")
                    summary.add(ExecutionEvent(
                        "rejected", order.symbol,
                        f"insufficient cash above the {profile.cash_floor_pct:.0%} "
                        "reserve floor",
                    ))
                    continue
                order.shares = affordable
                commission = self._commission(order.shares)
                cost = order.shares * fill + commission
                summary.add(ExecutionEvent(
                    "resized", order.symbol,
                    f"order trimmed to {affordable} shares to respect the cash reserve",
                ))

            self.store.cash = self.store.cash - cost
            position = Position(
                symbol=order.symbol, shares=order.shares, entry_price=fill,
                entry_date=as_of, stop_price=order.stop_loss,
                initial_stop=order.stop_loss, targets=order.targets,
                setup=order.setup, risk_dollars=order.risk_dollars,
                highest_close=fill, time_stop_days=order.time_stop_days,
            )
            pid = self.store.add_position(position)
            self.store.record_trade(Trade(
                symbol=order.symbol, action="buy", shares=order.shares, price=fill,
                trade_date=as_of, commission=commission,
                reason=f"{order.setup} entry ({order.order_type})", position_id=pid,
            ))
            self.store.set_order_status(order.id, "filled")
            open_symbols.add(order.symbol)

            summary.add(ExecutionEvent(
                "fill", order.symbol,
                f"bought {order.shares} @ ${fill:,.2f} "
                f"({order.order_type} order, {order.setup} setup), "
                f"stop ${order.stop_loss:,.2f}",
                shares=order.shares, price=fill,
            ))

    @staticmethod
    def _match(order: Order, open_: float, high: float, low: float) -> float | None:
        """Return the fill price if this bar triggers the order, else None."""
        if order.order_type == "market":
            return open_
        trigger = order.trigger_price
        if trigger is None:
            return None
        if order.order_type == "stop":
            # Buy-stop triggers on the way up; a gap above fills at the open.
            if high >= trigger:
                return max(open_, trigger)
            return None
        if order.order_type == "limit":
            # Buy-limit fills only at or below the limit; a gap below fills better.
            if low <= trigger:
                return min(open_, trigger)
            return None
        return None
