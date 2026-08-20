"""Execution venues: a built-in simulator and an optional Alpaca paper adapter."""

from quantdesk.broker.paper import PaperBroker, ExecutionEvent

__all__ = ["PaperBroker", "ExecutionEvent"]
