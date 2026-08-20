"""Optional adapter for an Alpaca paper-trading account.

The built-in simulator is the default and needs no account, no keys and no
network. This adapter exists for when you want play money that behaves like a
real brokerage: genuine market hours, genuine order rejections, genuine partial
fills against the real book.

Requires ``pip install alpaca-py`` and a free paper-trading account. Set:

    export ALPACA_API_KEY=...
    export ALPACA_SECRET_KEY=...

then run with ``--broker alpaca``.

Note: this talks to a live external API and therefore cannot be exercised by the
offline test suite. Treat it as the less-tested path, and check the Alpaca
dashboard after the first run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from quantdesk.strategy.risk import TradePlan

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"


class AlpacaNotConfigured(RuntimeError):
    pass


@dataclass
class AlpacaCredentials:
    api_key: str
    secret_key: str
    paper: bool = True

    @classmethod
    def from_env(cls) -> "AlpacaCredentials":
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key or not secret:
            raise AlpacaNotConfigured(
                "set ALPACA_API_KEY and ALPACA_SECRET_KEY to use the Alpaca broker"
            )
        return cls(key, secret, paper=True)


class AlpacaBroker:
    """Places bracket orders on an Alpaca paper account.

    A bracket order submits the entry together with its stop loss and take
    profit as one unit, so the protective orders exist from the moment the
    position does - there is no window where a fill sits unprotected.
    """

    def __init__(self, credentials: AlpacaCredentials | None = None) -> None:
        self.credentials = credentials or AlpacaCredentials.from_env()
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise AlpacaNotConfigured(
                "the Alpaca broker needs alpaca-py: pip install alpaca-py"
            ) from exc

        self._client = TradingClient(
            self.credentials.api_key,
            self.credentials.secret_key,
            paper=self.credentials.paper,
        )

    # --- account ------------------------------------------------------------
    def account_equity(self) -> float:
        return float(self._client.get_account().equity)

    def cash(self) -> float:
        return float(self._client.get_account().cash)

    def positions(self) -> list[dict]:
        return [
            {
                "symbol": p.symbol,
                "shares": int(float(p.qty)),
                "entry_price": float(p.avg_entry_price),
                "price": float(p.current_price or 0.0),
                "unrealized_pnl": float(p.unrealized_pl or 0.0),
            }
            for p in self._client.get_all_positions()
        ]

    # --- orders -------------------------------------------------------------
    def submit_plan(self, plan: TradePlan) -> str:
        """Submit a plan as a bracket order. Returns the broker order id."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest, MarketOrderRequest, StopLossRequest,
            StopOrderRequest, TakeProfitRequest,
        )

        if plan.shares <= 0:
            raise ValueError("cannot submit a plan with no shares")

        # The first target is the bracket's take-profit; later tranches are
        # managed manually, since a bracket carries only one profit leg.
        take_profit = TakeProfitRequest(limit_price=round(plan.targets[0].price, 2))
        stop_loss = StopLossRequest(stop_price=round(plan.stop_price, 2))

        common = {
            "symbol": plan.symbol,
            "qty": plan.shares,
            "side": OrderSide.BUY,
            "time_in_force": TimeInForce.DAY,
            "order_class": OrderClass.BRACKET,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }

        if plan.entry_style == "buy_stop":
            request = StopOrderRequest(stop_price=round(plan.entry_price, 2), **common)
        elif plan.entry_style == "limit":
            request = LimitOrderRequest(limit_price=round(plan.entry_price, 2), **common)
        else:
            request = MarketOrderRequest(**common)

        return str(self._client.submit_order(request).id)

    def cancel_all(self) -> int:
        responses = self._client.cancel_orders()
        return len(responses or [])

    def close_position(self, symbol: str) -> None:
        self._client.close_position(symbol)
