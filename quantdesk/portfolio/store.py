"""SQLite-backed portfolio state.

Everything the desk does is recorded: every fill, every stop move, every equity
snapshot. Without that history there is no way to tell whether the strategy is
actually working or you just remember the winners.

Money is stored as REAL for simplicity, but all comparisons that matter (fills,
stops) are done on rounded cents to avoid float drift creeping into balances.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    shares INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    entry_date TEXT NOT NULL,
    stop_price REAL NOT NULL,
    initial_stop REAL NOT NULL,
    targets TEXT NOT NULL,
    setup TEXT,
    risk_dollars REAL NOT NULL DEFAULT 0,
    highest_close REAL NOT NULL DEFAULT 0,
    time_stop_days INTEGER NOT NULL DEFAULT 60,
    status TEXT NOT NULL DEFAULT 'open',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    trade_date TEXT NOT NULL,
    commission REAL NOT NULL DEFAULT 0,
    reason TEXT,
    realized_pnl REAL,
    position_id INTEGER
);

CREATE TABLE IF NOT EXISTS equity_history (
    snapshot_date TEXT PRIMARY KEY,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    total_equity REAL NOT NULL,
    open_positions INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    shares INTEGER NOT NULL,
    trigger_price REAL,
    stop_loss REAL NOT NULL,
    targets TEXT NOT NULL,
    setup TEXT,
    risk_dollars REAL NOT NULL DEFAULT 0,
    time_stop_days INTEGER NOT NULL DEFAULT 60,
    created_date TEXT NOT NULL,
    expires_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date);
"""


@dataclass
class Position:
    symbol: str
    shares: int
    entry_price: float
    entry_date: date
    stop_price: float
    initial_stop: float
    targets: list[tuple[float, float]]  # (price, take_fraction)
    setup: str = ""
    risk_dollars: float = 0.0
    highest_close: float = 0.0
    time_stop_days: int = 60
    id: int | None = None
    status: str = "open"
    notes: str = ""

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    def market_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.shares

    def unrealized_pct(self, price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (price / self.entry_price - 1.0) * 100.0

    def r_multiple(self, price: float) -> float:
        """Open profit expressed in multiples of the original risk."""
        risk_per_share = self.entry_price - self.initial_stop
        if risk_per_share <= 0:
            return 0.0
        return (price - self.entry_price) / risk_per_share

    def days_held(self, as_of: date | None = None) -> int:
        return ((as_of or date.today()) - self.entry_date).days


@dataclass
class Order:
    """A working order awaiting its trigger.

    Recommendations are not filled the moment they are generated: a breakout
    idea is only a trade once price actually breaks out. Orders therefore sit
    pending and are matched against the following sessions' bars, which is how
    a real broker would treat them - and prevents the simulator from quietly
    granting fills that never would have happened.
    """

    symbol: str
    side: str          # "buy"
    order_type: str    # "market" | "stop" | "limit"
    shares: int
    trigger_price: float | None
    stop_loss: float
    targets: list[tuple[float, float]]
    setup: str = ""
    risk_dollars: float = 0.0
    time_stop_days: int = 60
    created_date: date = field(default_factory=date.today)
    expires_date: date = field(default_factory=date.today)
    status: str = "pending"
    note: str = ""
    id: int | None = None


@dataclass
class Trade:
    symbol: str
    action: str  # "buy" | "sell"
    shares: int
    price: float
    trade_date: date
    commission: float = 0.0
    reason: str = ""
    realized_pnl: float | None = None
    position_id: int | None = None
    id: int | None = None

    @property
    def value(self) -> float:
        return self.shares * self.price


@dataclass
class Portfolio:
    cash: float
    positions: list[Position] = field(default_factory=list)
    starting_cash: float = 0.0

    def positions_value(self, prices: dict[str, float]) -> float:
        return sum(p.market_value(prices.get(p.symbol, p.entry_price)) for p in self.positions)

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.positions_value(prices)

    def position_for(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol.upper():
                return p
        return None

    @property
    def symbols(self) -> set[str]:
        return {p.symbol for p in self.positions}


def _iso(value: date | datetime) -> str:
    return value.isoformat()


def _to_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _encode_targets(targets: list[tuple[float, float]]) -> str:
    return ";".join(f"{price:.6f}:{frac:.6f}" for price, frac in targets)


def _decode_targets(raw: str) -> list[tuple[float, float]]:
    if not raw:
        return []
    out: list[tuple[float, float]] = []
    for chunk in raw.split(";"):
        if not chunk:
            continue
        price, _, frac = chunk.partition(":")
        try:
            out.append((float(price), float(frac)))
        except ValueError:
            continue
    return out


class PortfolioStore:
    """All reads and writes of portfolio state."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- meta ---------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def is_initialised(self) -> bool:
        return self.get_meta("cash") is not None

    def initialise(self, starting_cash: float, force: bool = False) -> None:
        if self.is_initialised() and not force:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM positions")
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM equity_history")
        self.set_meta("cash", f"{starting_cash:.2f}")
        self.set_meta("starting_cash", f"{starting_cash:.2f}")
        self.set_meta("created", _iso(datetime.now()))

    # --- cash ---------------------------------------------------------------
    @property
    def cash(self) -> float:
        return float(self.get_meta("cash", "0") or 0.0)

    @cash.setter
    def cash(self, value: float) -> None:
        self.set_meta("cash", f"{round(value, 2):.2f}")

    @property
    def starting_cash(self) -> float:
        return float(self.get_meta("starting_cash", "0") or 0.0)

    # --- positions ----------------------------------------------------------
    def open_positions(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_date"
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            id=row["id"],
            symbol=row["symbol"],
            shares=row["shares"],
            entry_price=row["entry_price"],
            entry_date=_to_date(row["entry_date"]),
            stop_price=row["stop_price"],
            initial_stop=row["initial_stop"],
            targets=_decode_targets(row["targets"]),
            setup=row["setup"] or "",
            risk_dollars=row["risk_dollars"],
            highest_close=row["highest_close"],
            time_stop_days=row["time_stop_days"],
            status=row["status"],
            notes=row["notes"] or "",
        )

    def add_position(self, position: Position) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO positions(symbol, shares, entry_price, entry_date, "
                "stop_price, initial_stop, targets, setup, risk_dollars, "
                "highest_close, time_stop_days, status, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    position.symbol.upper(), position.shares, position.entry_price,
                    _iso(position.entry_date), position.stop_price, position.initial_stop,
                    _encode_targets(position.targets), position.setup,
                    position.risk_dollars, position.highest_close,
                    position.time_stop_days, position.status, position.notes,
                ),
            )
            return int(cur.lastrowid)

    def update_position(self, position: Position) -> None:
        if position.id is None:
            raise ValueError("cannot update a position without an id")
        with self._connect() as conn:
            conn.execute(
                "UPDATE positions SET shares=?, stop_price=?, targets=?, "
                "highest_close=?, status=?, notes=? WHERE id=?",
                (
                    position.shares, position.stop_price,
                    _encode_targets(position.targets), position.highest_close,
                    position.status, position.notes, position.id,
                ),
            )

    def close_position(self, position_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE positions SET status='closed', shares=0 WHERE id=?", (position_id,)
            )

    # --- trades -------------------------------------------------------------
    def record_trade(self, trade: Trade) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO trades(symbol, action, shares, price, trade_date, "
                "commission, reason, realized_pnl, position_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    trade.symbol.upper(), trade.action, trade.shares, trade.price,
                    _iso(trade.trade_date), trade.commission, trade.reason,
                    trade.realized_pnl, trade.position_id,
                ),
            )
            return int(cur.lastrowid)

    def trades(self, limit: int | None = None, since: date | None = None) -> list[Trade]:
        query = "SELECT * FROM trades"
        params: list = []
        if since is not None:
            query += " WHERE trade_date >= ?"
            params.append(_iso(since))
        query += " ORDER BY trade_date DESC, id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Trade(
                id=r["id"], symbol=r["symbol"], action=r["action"], shares=r["shares"],
                price=r["price"], trade_date=_to_date(r["trade_date"]),
                commission=r["commission"], reason=r["reason"] or "",
                realized_pnl=r["realized_pnl"], position_id=r["position_id"],
            )
            for r in rows
        ]

    # --- orders -------------------------------------------------------------
    def add_order(self, order: Order) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO orders(symbol, side, order_type, shares, trigger_price, "
                "stop_loss, targets, setup, risk_dollars, time_stop_days, "
                "created_date, expires_date, status, note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    order.symbol.upper(), order.side, order.order_type, order.shares,
                    order.trigger_price, order.stop_loss, _encode_targets(order.targets),
                    order.setup, order.risk_dollars, order.time_stop_days,
                    _iso(order.created_date), _iso(order.expires_date),
                    order.status, order.note,
                ),
            )
            return int(cur.lastrowid)

    def pending_orders(self) -> list[Order]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = 'pending' ORDER BY created_date"
            ).fetchall()
        return [
            Order(
                id=r["id"], symbol=r["symbol"], side=r["side"], order_type=r["order_type"],
                shares=r["shares"], trigger_price=r["trigger_price"],
                stop_loss=r["stop_loss"], targets=_decode_targets(r["targets"]),
                setup=r["setup"] or "", risk_dollars=r["risk_dollars"],
                time_stop_days=r["time_stop_days"],
                created_date=_to_date(r["created_date"]),
                expires_date=_to_date(r["expires_date"]),
                status=r["status"], note=r["note"] or "",
            )
            for r in rows
        ]

    def set_order_status(self, order_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

    def cancel_all_orders(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='cancelled' WHERE status='pending'"
            )
            return cur.rowcount

    # --- equity curve -------------------------------------------------------
    def snapshot_equity(
        self, snapshot_date: date, cash: float, positions_value: float, open_positions: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO equity_history(snapshot_date, cash, positions_value, "
                "total_equity, open_positions) VALUES(?,?,?,?,?) "
                "ON CONFLICT(snapshot_date) DO UPDATE SET cash=excluded.cash, "
                "positions_value=excluded.positions_value, "
                "total_equity=excluded.total_equity, "
                "open_positions=excluded.open_positions",
                (
                    _iso(snapshot_date), round(cash, 2), round(positions_value, 2),
                    round(cash + positions_value, 2), open_positions,
                ),
            )

    def equity_history(self, limit: int = 400) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_history ORDER BY snapshot_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def load_portfolio(self) -> Portfolio:
        return Portfolio(
            cash=self.cash,
            positions=self.open_positions(),
            starting_cash=self.starting_cash,
        )
