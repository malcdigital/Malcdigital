"""Trade construction: where to get in, where to get out, and how much to buy.

A signal without an exit plan is not a trade, it is a hope. Every plan built
here answers four questions before a share is bought:

* **Entry**  - the exact price and the condition that must occur first.
* **Stop**   - the price at which the idea is proven wrong, set from volatility
               (ATR) and structure (support), never from a round percentage.
* **Targets**- where profit is taken, expressed in R (multiples of the risk).
* **Exit**   - trailing rule, time stop, and what invalidates the thesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantdesk.config import RiskProfile


@dataclass
class Target:
    price: float
    r_multiple: float
    take_pct: float
    """Fraction of the position to sell here."""

    def describe(self, shares: int, direction: str = "long") -> str:
        qty = max(1, int(round(shares * self.take_pct)))
        verb = "Sell" if direction == "long" else "Buy to cover"
        return (
            f"{verb} {qty} share{'s' if qty != 1 else ''} "
            f"({self.take_pct:.0%}) at ${self.price:,.2f} (+{self.r_multiple:.1f}R)"
        )


@dataclass
class TradePlan:
    """A complete, executable instruction set for one idea."""

    symbol: str
    setup: str
    entry_style: str          # "buy_stop" | "sell_stop" | "limit" | "market"
    entry_price: float
    entry_condition: str
    stop_price: float
    stop_reason: str
    targets: list[Target]
    shares: int
    sizing_note: str
    risk_dollars: float
    position_value: float
    equity_pct: float
    trail_rule: str
    time_stop_days: int
    invalidation: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    direction: str = "long"
    proxy_for: str = ""
    """Set when a bearish view is expressed by buying an inverse ETF: names the
    symbol the view is actually about."""

    @property
    def is_short(self) -> bool:
        return self.direction == "short"

    @property
    def per_share_risk(self) -> float:
        """Distance from entry to stop, always positive."""
        if self.is_short:
            return self.stop_price - self.entry_price
        return self.entry_price - self.stop_price

    @property
    def stop_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.stop_price / self.entry_price - 1.0) * 100.0

    @property
    def reward_risk(self) -> float:
        """Blended reward:risk across all targets, weighted by size taken."""
        if not self.targets or self.per_share_risk <= 0:
            return 0.0
        return sum(t.r_multiple * t.take_pct for t in self.targets)

    @property
    def is_actionable(self) -> bool:
        return self.shares > 0 and self.per_share_risk > 0

    def instructions(self) -> list[str]:
        """Human-readable, step-by-step trade instructions."""
        verb = {
            "buy_stop": f"BUY STOP at ${self.entry_price:,.2f}",
            "sell_stop": f"SELL SHORT STOP at ${self.entry_price:,.2f}",
            "limit": (
                f"{'SELL SHORT LIMIT' if self.is_short else 'BUY LIMIT'} at "
                f"${self.entry_price:,.2f} or better"
            ),
            "market": (
                f"{'SELL SHORT' if self.is_short else 'BUY'} AT MARKET "
                f"(reference ${self.entry_price:,.2f})"
            ),
        }[self.entry_style]

        lines = []
        if self.proxy_for:
            lines.append(
                f"0. NOTE - this is a bearish view on {self.proxy_for}, expressed by "
                f"BUYING the inverse ETF {self.symbol}. You are buying, not shorting; "
                "loss is capped at the amount invested."
            )
        lines += [
            f"1. ENTRY - {verb} for {self.shares} shares "
            f"(${self.position_value:,.0f}, {self.equity_pct:.1f}% of equity).",
            f"   Condition: {self.entry_condition}",
            f"2. STOP LOSS - place immediately at ${self.stop_price:,.2f} "
            f"({self.stop_pct:+.1f}%). Risking ${self.risk_dollars:,.0f}.",
            f"   Why here: {self.stop_reason}",
        ]
        for i, target in enumerate(self.targets, start=3):
            lines.append(f"{i}. TARGET - {target.describe(self.shares, self.direction)}")
        n = len(self.targets) + 3
        lines.append(f"{n}. TRAIL - {self.trail_rule}")
        lines.append(
            f"{n + 1}. TIME STOP - if the trade has not reached the first target "
            f"within {self.time_stop_days} trading days, close it and free the capital."
        )
        if self.invalidation:
            lines.append(f"{n + 2}. EXIT EARLY IF - " + "; ".join(self.invalidation))
        return lines


def _round_price(price: float) -> float:
    """Round to a sensible tick so orders look like real orders."""
    if price >= 1.0:
        return round(price, 2)
    return round(price, 4)


def build_trade_plan(
    symbol: str,
    bars: pd.DataFrame,
    enriched: pd.DataFrame,
    trend_state,
    profile: RiskProfile,
    equity: float,
    setup: str,
    support_level: float | None = None,
    resistance_level: float | None = None,
    direction: str = "long",
    proxy_for: str = "",
) -> TradePlan:
    """Construct an executable plan from the current technical picture.

    The geometry mirrors for a short: entry breaks *down* through support rather
    than up through resistance, the stop sits *above* entry, and targets sit
    below it. Everything else - ATR-based distances, R multiples, the two sizing
    caps - is identical, so a short is sized and managed by the same discipline
    as a long rather than by a separate set of rules.
    """
    last = enriched.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    atr = float(last["atr14"]) if pd.notna(last.get("atr14")) else close * 0.02
    atr = max(atr, close * 0.002)  # guard against a degenerate ATR
    is_short = direction == "short"

    # --- entry --------------------------------------------------------------
    if setup in ("breakout", "breakdown"):
        if is_short:
            # Sell strength only once support actually breaks, never in anticipation.
            dc_lower = float(last.get("dc20_lower", low))
            trigger = min(dc_lower, low)
            entry_price = _round_price(trigger - 0.02 * atr)
            entry_style = "sell_stop"
            entry_condition = (
                f"Only if price trades below ${entry_price:,.2f} (the 20-day low). "
                "If it never triggers, there is no trade - do not force it."
            )
        else:
            dc_upper = float(last.get("dc20_upper", high))
            trigger = max(dc_upper, high)
            entry_price = _round_price(trigger + 0.02 * atr)
            entry_style = "buy_stop"
            entry_condition = (
                f"Only if price trades above ${entry_price:,.2f} (the 20-day high). "
                "If it never triggers, there is no trade - do not chase."
            )
    elif setup in ("pullback", "rally"):
        ema21 = float(last.get("ema21", close))
        if is_short:
            # Sell into a bounce toward the falling 21-day EMA.
            target_entry = max(close, min(ema21, close + 0.5 * atr))
            entry_price = _round_price(target_entry)
            entry_style = "limit"
            entry_condition = (
                f"Place a short limit order at ${entry_price:,.2f} (near the 21-day "
                "EMA). Fills on a bounce; if price keeps falling, skip it."
            )
        else:
            target_entry = min(close, max(ema21, close - 0.5 * atr))
            entry_price = _round_price(target_entry)
            entry_style = "limit"
            entry_condition = (
                f"Place a limit order at ${entry_price:,.2f} (near the 21-day EMA). "
                "Fills on a pullback; if price runs away, skip it."
            )
    else:  # reversal / momentum continuation
        entry_price = _round_price(close)
        entry_style = "market"
        entry_condition = (
            "Enter at the open of the next session. The reversal signal has "
            "already completed, so waiting risks giving up the move."
        )

    # --- stop ---------------------------------------------------------------
    if is_short:
        atr_stop = entry_price + profile.atr_stop_mult * atr
        stop_price = atr_stop
        stop_reason = (
            f"{profile.atr_stop_mult:.1f} x ATR (${atr:,.2f}) above entry - far "
            "enough that ordinary daily noise will not eject you."
        )
        # Prefer sitting just above real resistance when that is tighter: a break
        # back above it is genuine evidence the bearish idea is wrong.
        if resistance_level is not None and resistance_level > entry_price:
            structural = resistance_level + 0.25 * atr
            if structural < atr_stop:
                stop_price = structural
                stop_reason = (
                    f"Just above resistance at ${resistance_level:,.2f} - reclaiming "
                    "that level invalidates the setup, and it is tighter than the "
                    "ATR stop."
                )
        stop_price = _round_price(max(stop_price, entry_price + 0.05 * atr))
        per_share_risk = stop_price - entry_price
    else:
        atr_stop = entry_price - profile.atr_stop_mult * atr
        stop_price = atr_stop
        stop_reason = (
            f"{profile.atr_stop_mult:.1f} x ATR (${atr:,.2f}) below entry - far enough "
            "that ordinary daily noise will not eject you."
        )
        if support_level is not None and support_level < entry_price:
            structural = support_level - 0.25 * atr
            if structural > atr_stop:
                stop_price = structural
                stop_reason = (
                    f"Just below support at ${support_level:,.2f} - losing that level "
                    "invalidates the setup, and it is tighter than the ATR stop."
                )
        stop_price = _round_price(min(stop_price, entry_price - 0.05 * atr))
        per_share_risk = entry_price - stop_price

    # --- size ---------------------------------------------------------------
    shares, sizing_note = profile.size_position(equity, entry_price, stop_price, direction)
    position_value = shares * entry_price
    risk_dollars = shares * per_share_risk

    # --- targets ------------------------------------------------------------
    multiples = list(profile.target_r_multiples)
    if len(multiples) == 2:
        take = [0.5, 0.5]
    elif len(multiples) == 3:
        take = [0.4, 0.35, 0.25]
    else:
        take = [1.0 / len(multiples)] * len(multiples)

    sign = -1.0 if is_short else 1.0
    # A short's gain is capped at 100% - price cannot fall below zero - so a wide
    # stop can push a high-R target to an absurd level (5R on a 15%-wide stop is a
    # 77% decline). Floor the price so it stays a real number, and say so rather
    # than quietly printing a fantasy.
    price_floor = entry_price * 0.05
    targets = []
    unrealistic: list[float] = []
    for r, pct in zip(multiples, take):
        raw = entry_price + sign * r * per_share_risk
        price = max(raw, price_floor) if is_short else raw
        move_pct = abs(price / entry_price - 1.0)
        if is_short and move_pct > 0.40:
            unrealistic.append(r)
        targets.append(
            Target(price=_round_price(price), r_multiple=r, take_pct=pct)
        )

    notes: list[str] = []
    if unrealistic:
        listed = ", ".join(f"{r:g}R" for r in unrealistic)
        notes.append(
            f"The {listed} target implies a decline of more than 40%. That is a rare "
            "outcome for a swing trade - treat the trailing stop, not the far target, "
            "as the realistic exit."
        )
    if targets:
        first = targets[0]
        if is_short and support_level is not None and support_level > first.price:
            notes.append(
                f"Support at ${support_level:,.2f} sits above the first target "
                f"(${first.price:,.2f}); expect the decline to stall there and "
                "consider covering the first tranche early."
            )
        elif not is_short and resistance_level is not None and resistance_level < first.price:
            notes.append(
                f"Overhead resistance at ${resistance_level:,.2f} sits below the first "
                f"target (${first.price:,.2f}); expect the advance to stall there and "
                "consider taking the first tranche early."
            )
    if is_short and not proxy_for:
        notes.append(
            "Short position: losses are theoretically unlimited, borrow may be "
            "recalled, and a squeeze can gap price through your stop. The stop is "
            "not a guarantee."
        )

    # --- exits --------------------------------------------------------------
    trail_trigger = _round_price(
        entry_price + sign * profile.trail_after_r * per_share_risk
    )
    trail_rule = (
        f"Once the trade is up {profile.trail_after_r:.2f}R (${trail_trigger:,.2f}), "
        f"move the stop to breakeven, then trail it {profile.trail_atr_mult:.2f} x ATR "
        f"{'above the lowest close' if is_short else 'below the highest close'} "
        "reached. Never move a stop away from price."
    )

    if is_short:
        invalidation = [
            "a daily close back above the 50-day moving average",
            "a daily close above the stop level (cover on the close, do not wait)",
        ]
        if setup == "breakdown":
            invalidation.append(
                "price recovers back inside the breakdown range within two sessions "
                "(a failed breakdown)"
            )
    else:
        invalidation = [
            "a daily close back below the 50-day moving average",
            "a daily close below the stop level (exit on the close, do not wait)",
        ]
        if setup == "breakout":
            invalidation.append(
                "price falls back inside the breakout range within two sessions "
                "(a failed breakout)"
            )
    if trend_state is not None and getattr(trend_state, "is_choppy", False):
        invalidation.append("ADX stays below 20 - the move lacks conviction")

    return TradePlan(
        symbol=symbol.upper(),
        setup=setup,
        entry_style=entry_style,
        entry_price=entry_price,
        entry_condition=entry_condition,
        stop_price=stop_price,
        stop_reason=stop_reason,
        targets=targets,
        shares=shares,
        sizing_note=sizing_note,
        risk_dollars=round(risk_dollars, 2),
        position_value=round(position_value, 2),
        equity_pct=round(position_value / equity * 100.0, 2) if equity else 0.0,
        trail_rule=trail_rule,
        time_stop_days=profile.max_hold_days,
        invalidation=invalidation,
        notes=notes,
        direction=direction,
        proxy_for=proxy_for,
    )
