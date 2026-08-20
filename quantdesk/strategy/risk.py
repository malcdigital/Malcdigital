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

    def describe(self, shares: int) -> str:
        qty = max(1, int(round(shares * self.take_pct)))
        return (
            f"Sell {qty} share{'s' if qty != 1 else ''} "
            f"({self.take_pct:.0%}) at ${self.price:,.2f} (+{self.r_multiple:.1f}R)"
        )


@dataclass
class TradePlan:
    """A complete, executable instruction set for one idea."""

    symbol: str
    setup: str
    entry_style: str          # "buy_stop" | "limit" | "market"
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

    @property
    def per_share_risk(self) -> float:
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
            "limit": f"BUY LIMIT at ${self.entry_price:,.2f} or better",
            "market": f"BUY AT MARKET (reference ${self.entry_price:,.2f})",
        }[self.entry_style]

        lines = [
            f"1. ENTRY - {verb} for {self.shares} shares "
            f"(${self.position_value:,.0f}, {self.equity_pct:.1f}% of equity).",
            f"   Condition: {self.entry_condition}",
            f"2. STOP LOSS - place immediately at ${self.stop_price:,.2f} "
            f"({self.stop_pct:+.1f}%). Risking ${self.risk_dollars:,.0f}.",
            f"   Why here: {self.stop_reason}",
        ]
        for i, target in enumerate(self.targets, start=3):
            lines.append(f"{i}. TARGET - {target.describe(self.shares)}")
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
) -> TradePlan:
    """Construct an executable long plan from the current technical picture."""
    last = enriched.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    atr = float(last["atr14"]) if pd.notna(last.get("atr14")) else close * 0.02
    atr = max(atr, close * 0.002)  # guard against a degenerate ATR

    # --- entry --------------------------------------------------------------
    if setup == "breakout":
        # Buy strength only once it actually breaks, never in anticipation.
        dc_upper = float(last.get("dc20_upper", high))
        trigger = max(dc_upper, high)
        entry_price = _round_price(trigger + 0.02 * atr)
        entry_style = "buy_stop"
        entry_condition = (
            f"Only if price trades above ${entry_price:,.2f} (the 20-day high). "
            "If it never triggers, there is no trade - do not chase."
        )
    elif setup == "pullback":
        # Buy weakness inside an established uptrend, near a moving average.
        ema21 = float(last.get("ema21", close))
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
    atr_stop = entry_price - profile.atr_stop_mult * atr
    stop_price = atr_stop
    stop_reason = (
        f"{profile.atr_stop_mult:.1f} x ATR (${atr:,.2f}) below entry - far enough "
        "that ordinary daily noise will not eject you."
    )

    # Prefer sitting just under real support when that is tighter than the ATR
    # stop, because a break of support is genuine evidence the idea is wrong.
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
    shares, sizing_note = profile.size_position(equity, entry_price, stop_price)
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

    targets = [
        Target(
            price=_round_price(entry_price + r * per_share_risk),
            r_multiple=r,
            take_pct=pct,
        )
        for r, pct in zip(multiples, take)
    ]

    notes: list[str] = []
    if resistance_level is not None and targets:
        first = targets[0]
        if resistance_level < first.price:
            notes.append(
                f"Overhead resistance at ${resistance_level:,.2f} sits below the first "
                f"target (${first.price:,.2f}); expect the advance to stall there and "
                "consider taking the first tranche early."
            )

    # --- exits --------------------------------------------------------------
    trail_rule = (
        f"Once the trade is up {profile.trail_after_r:.2f}R "
        f"(${_round_price(entry_price + profile.trail_after_r * per_share_risk):,.2f}), "
        f"move the stop to breakeven, then trail it {profile.trail_atr_mult:.2f} x ATR "
        "below the highest close reached. Never move a stop away from price."
    )

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
    )
