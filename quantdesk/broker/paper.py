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

* **Shorts hold margin.** Selling short does not credit the proceeds to cash -
  the notional is held aside as margin and released on cover, along with the
  profit or loss. Real brokers require roughly 150% under Reg T; holding 100%
  is a simplification, but it is the conservative direction and it stops the
  simulator handing out unlimited leverage, which crediting the proceeds would.
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


def _fmt_r(value: float | None) -> str:
    """Render an R multiple for humans, saying so when there isn't one."""
    return "R n/a" if value is None else f"{value:+.2f}R"


def _round_or_none(value: float | None) -> float | None:
    """Round an R multiple, preserving "no usable risk figure" as None.

    round(None) raises, and substituting 0.0 would file a position with an
    unknown denominator alongside genuine break-even scratches.
    """
    return None if value is None else round(value, 4)


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

        order_type = {
            "buy_stop": "stop", "sell_stop": "stop",
            "limit": "limit", "market": "market",
        }[plan.entry_style]
        order = Order(
            symbol=plan.symbol,
            side="sell" if plan.direction == "short" else "buy",
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
            direction=plan.direction,
            proxy_for=plan.proxy_for,
        )
        self.store.add_order(order)
        side = "sell-short" if plan.direction == "short" else "buy"
        label = {
            "stop": f"{side}-stop @ ${plan.entry_price:,.2f}",
            "limit": f"{side}-limit @ ${plan.entry_price:,.2f}",
            "market": f"{side} market-on-open",
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
            #    A short is stopped out when price rises through the stop.
            stopped = (h >= position.stop_price) if position.is_short else (l <= position.stop_price)
            if stopped:
                gapped = (
                    o >= position.stop_price if position.is_short
                    else o <= position.stop_price
                )
                # A gap through the stop fills at the open, not the stop price.
                exit_price = o if gapped else position.stop_price
                reason = (
                    "gapped through the stop - filled at the open"
                    if gapped else "stop loss hit"
                )
                self._close(position, position.shares, exit_price, as_of, reason, summary)
                continue

            # 2. Targets. For a short these sit below entry and are hit on the low.
            remaining_targets = list(position.targets)
            hit_any = False
            for target_price, take_frac in list(remaining_targets):
                reached = (
                    l <= target_price if position.is_short else h >= target_price
                )
                if reached and position.shares > 0:
                    qty = max(1, int(round(position.shares * take_frac)))
                    qty = min(qty, position.shares)
                    # A gap beyond the target fills better, in either direction.
                    fill = min(target_price, o) if position.is_short else max(target_price, o)
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
        if position.is_short:
            if position.lowest_close <= 0 or close < position.lowest_close:
                position.lowest_close = close
        elif close > position.highest_close:
            position.highest_close = close

        r_now = position.r_multiple(close)
        # No usable risk figure means the trail's arming condition cannot be
        # evaluated. Leave the stop where it is rather than guessing: not
        # trailing costs some open profit, trailing on a fabricated R could
        # eject a working position.
        if r_now is None or r_now < profile.trail_after_r:
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

        if position.is_short:
            trailed = position.lowest_close + profile.trail_atr_mult * atr_val
            # Never above breakeven once trailing has activated, and never backwards.
            new_stop = round(min(trailed, position.entry_price, position.stop_price), 2)
            improved = new_stop < position.stop_price - 1e-9
            verb = "lowered"
        else:
            trailed = position.highest_close - profile.trail_atr_mult * atr_val
            new_stop = round(max(trailed, position.entry_price, position.stop_price), 2)
            improved = new_stop > position.stop_price + 1e-9
            verb = "raised"

        if improved:
            old = position.stop_price
            position.stop_price = new_stop
            self.store.update_position(position)
            summary.add(ExecutionEvent(
                "stop_moved", position.symbol,
                f"trailing stop {verb} ${old:,.2f} -> ${new_stop:,.2f} "
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

        commission = self._commission(shares)
        if position.is_short:
            # Covering is a purchase, so slippage pushes the price up against you.
            fill = self._buy_fill_price(price)
            pnl = (position.entry_price - fill) * shares - commission
            # Release the margin held at entry, then apply the result.
            self.store.cash = self.store.cash + shares * position.entry_price + pnl
            action = "cover"
        else:
            fill = self._sell_fill_price(price)
            pnl = (fill - position.entry_price) * shares - commission
            self.store.cash = self.store.cash + shares * fill - commission
            action = "sell"

        self.store.record_trade(Trade(
            symbol=position.symbol, action=action, shares=shares, price=fill,
            trade_date=as_of, commission=commission, reason=reason,
            realized_pnl=round(pnl, 2), position_id=position.id,
            r_multiple=_round_or_none(position.r_multiple(fill)),
            holding_days=position.days_held(as_of),
            stop_trailed=abs(position.stop_price - position.initial_stop) > 1e-9,
            direction=position.direction, setup=position.setup,
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
            f"{'covered' if position.is_short else 'sold'} {shares} @ ${fill:,.2f} - {reason} "
            f"(P&L ${pnl:+,.2f}, {_fmt_r(position.r_multiple(fill))})",
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

            if order.direction == "short":
                if not profile.allow_short:
                    self.store.set_order_status(order.id, "cancelled")
                    summary.add(ExecutionEvent(
                        "rejected", order.symbol,
                        f"the {profile.name} profile does not permit short selling",
                    ))
                    continue
                open_shorts = sum(1 for p in positions if p.is_short)
                if open_shorts >= profile.max_short_positions:
                    self.store.set_order_status(order.id, "cancelled")
                    summary.add(ExecutionEvent(
                        "rejected", order.symbol,
                        f"at the {profile.max_short_positions}-short limit - a short "
                        "book that all squeezes together is how accounts blow up",
                    ))
                    continue

            if order.direction == "short":
                # Selling short: slippage pushes the fill down against you.
                fill = self._sell_fill_price(fill_price)
            else:
                fill = self._buy_fill_price(fill_price)
            commission = self._commission(order.shares)
            # Cost is the same either way: cash paid for a long, margin held for
            # a short. Both reduce buying power by the notional.
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
                direction=order.direction, lowest_close=fill,
                proxy_for=order.proxy_for, entry_shares=order.shares,
            )
            pid = self.store.add_position(position)
            self.store.record_trade(Trade(
                symbol=order.symbol,
                action="short" if order.direction == "short" else "buy",
                shares=order.shares, price=fill,
                trade_date=as_of, commission=commission,
                reason=f"{order.setup} {order.direction} entry ({order.order_type})",
                position_id=pid, direction=order.direction, setup=order.setup,
            ))
            self.store.set_order_status(order.id, "filled")
            open_symbols.add(order.symbol)

            summary.add(ExecutionEvent(
                "fill", order.symbol,
                f"{'sold short' if order.direction == 'short' else 'bought'} "
                f"{order.shares} @ ${fill:,.2f} "
                f"({order.order_type} order, {order.setup} setup), "
                f"stop ${order.stop_loss:,.2f}",
                shares=order.shares, price=fill,
            ))

    @staticmethod
    def _match(order: Order, open_: float, high: float, low: float) -> float | None:
        """Return the fill price if this bar triggers the order, else None.

        The comparisons mirror for a short: a sell-stop triggers on the way
        *down*, and a short limit fills on a rally *up* to the price. In both
        directions a gap through the trigger fills at the open, which is worse
        for stops and better for limits - the same asymmetry a real book has.
        """
        if order.order_type == "market":
            return open_
        trigger = order.trigger_price
        if trigger is None:
            return None
        is_short = order.direction == "short"

        if order.order_type == "stop":
            if is_short:
                # Sell-stop: triggers breaking down; a gap below fills at the open.
                if low <= trigger:
                    return min(open_, trigger)
                return None
            if high >= trigger:
                return max(open_, trigger)
            return None

        if order.order_type == "limit":
            if is_short:
                # Short limit: fills only at or above the limit.
                if high >= trigger:
                    return max(open_, trigger)
                return None
            if low <= trigger:
                return min(open_, trigger)
            return None
        return None
