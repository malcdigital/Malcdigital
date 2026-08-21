"""Configuration and risk profiles.

The risk profile is the single most important knob in the system: it decides
which instruments are eligible, how much capital a single idea may consume, how
far a stop sits from entry, and how long a position is allowed to work.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path(os.environ.get("QUANTDESK_HOME", Path.home() / ".quantdesk"))


@dataclass(frozen=True)
class RiskProfile:
    """Parameters that define how aggressively the desk trades."""

    name: str
    label: str
    description: str

    # --- capital allocation -------------------------------------------------
    max_position_pct: float
    """Largest fraction of total equity a single position may occupy."""

    risk_per_trade_pct: float
    """Fraction of equity lost if the stop is hit. Drives position size."""

    max_positions: int
    """Concurrent open positions. Caps correlation and admin overhead."""

    cash_floor_pct: float
    """Fraction of equity never deployed, so there is always dry powder."""

    # --- trade management ---------------------------------------------------
    atr_stop_mult: float
    """Initial stop distance measured in ATRs below entry."""

    target_r_multiples: tuple[float, ...]
    """Profit targets expressed as multiples of the initial risk (R)."""

    trail_after_r: float
    """Once this much open profit (in R) is reached, trail the stop."""

    trail_atr_mult: float
    """Trailing stop distance in ATRs once trailing activates."""

    max_hold_days: int
    """Time stop. Capital tied up longer than this is capital wasted."""

    # --- idea selection -----------------------------------------------------
    min_score: float
    """Composite score (0-100) an idea must clear to be actionable."""

    allowed_asset_types: tuple[str, ...]
    max_annual_volatility: float
    """Reject instruments whose realised volatility exceeds this."""

    min_avg_dollar_volume: float
    """Liquidity floor, so simulated fills stay believable."""

    etf_target_pct: float
    """Share of the deployed book that should sit in ETFs rather than singles."""

    allow_short: bool = False
    """May the desk take short positions at all?"""

    short_size_pct: float = 0.6
    """Fraction of the usual risk budget used on shorts.

    Shorts carry unlimited theoretical loss and tend to move faster than longs,
    so the same signal quality warrants a smaller stake.
    """

    prefer_inverse_etf: bool = False
    """Express bearish views by buying an inverse ETF rather than selling short.

    A cash account cannot sell short at all, and an inverse ETF caps the loss at
    the amount invested. The cost is tracking error and decay over long holds.
    """

    max_short_positions: int = 3
    """Concurrent shorts. Kept well below the long cap - a short book that all
    moves together in a squeeze is how accounts blow up."""

    disabled_setups: tuple[str, ...] = ("rally",)
    """Setups the desk will not trade, whatever else the signal says.

    "rally" - selling a bounce into resistance inside a downtrend - is the only
    setup that lost money over the 2017-2023 fit window: -0.31R across 83
    positions, about -$4,300, while every other setup was positive. The other
    short setup, "breakdown", made money over the same window, so this is not a
    verdict on shorting in general.

    Two reasons to act on it rather than treat it as noise. It is roughly 2.2
    standard errors from zero, which is suggestive rather than conclusive. And
    it has a mechanism: shorting strength in a market that rose for most of the
    period is fighting the tide, and this setup is also the catch-all for any
    bearish-trend candidate that is not near a breakdown, so it collects the
    least specific short ideas the scanner produces.

    Named rather than deleted so the classifier still labels these candidates
    and the report still counts what was skipped - and so this can be reversed
    by editing one tuple when it turns out to be hindsight.
    """

    def size_position(
        self, equity: float, entry: float, stop: float, direction: str = "long"
    ) -> tuple[int, str]:
        """Return (shares, explanation) for a trade, honouring both risk caps.

        Two independent limits apply and the tighter one wins:
          * risk-based  - shares such that per-share risk * shares == risk budget
          * exposure    - shares such that entry * shares <= max position value

        Risk per share is measured in the direction the trade can go wrong: below
        entry for a long, above it for a short.
        """
        if entry <= 0:
            return 0, "invalid entry price"

        per_share_risk = (entry - stop) if direction == "long" else (stop - entry)
        if per_share_risk <= 0:
            side = "below" if direction == "long" else "above"
            return 0, f"stop must sit {side} entry for a {direction} position"

        risk_budget = equity * self.risk_per_trade_pct
        if direction == "short":
            risk_budget *= self.short_size_pct
        by_risk = int(risk_budget // per_share_risk)

        exposure_cap = equity * self.max_position_pct
        by_exposure = int(exposure_cap // entry)

        shares = max(0, min(by_risk, by_exposure))
        if shares == 0:
            return 0, "position rounds to zero shares under current caps"
        binding = "risk budget" if by_risk <= by_exposure else "position-size cap"
        return shares, (
            f"{shares} shares - {binding} is the binding constraint "
            f"(risk budget ${risk_budget:,.0f} at ${per_share_risk:,.2f}/share, "
            f"exposure cap ${exposure_cap:,.0f})"
        )


CONSERVATIVE = RiskProfile(
    name="conservative",
    label="Conservative",
    description=(
        "Capital preservation first. Broad ETFs and large, liquid, low-volatility "
        "names. Small positions, wide stops so ordinary noise does not eject you, "
        "and long holding periods."
    ),
    max_position_pct=0.08,
    risk_per_trade_pct=0.004,
    max_positions=8,
    cash_floor_pct=0.25,
    atr_stop_mult=3.0,
    target_r_multiples=(2.0, 3.5),
    trail_after_r=1.5,
    trail_atr_mult=3.5,
    max_hold_days=120,
    min_score=62.0,
    allowed_asset_types=("etf", "stock"),
    max_annual_volatility=0.35,
    min_avg_dollar_volume=25_000_000,
    etf_target_pct=0.70,
    allow_short=False,
    prefer_inverse_etf=True,
    max_short_positions=2,
)

MODERATE = RiskProfile(
    name="moderate",
    label="Moderate",
    description=(
        "Balanced growth. A core of index and sector ETFs with satellite positions "
        "in trending large- and mid-cap stocks. Medium stops and multi-week holds."
    ),
    max_position_pct=0.12,
    risk_per_trade_pct=0.0075,
    max_positions=10,
    cash_floor_pct=0.15,
    atr_stop_mult=2.5,
    target_r_multiples=(2.0, 4.0),
    trail_after_r=1.25,
    trail_atr_mult=3.0,
    max_hold_days=60,
    min_score=58.0,
    allowed_asset_types=("etf", "stock"),
    max_annual_volatility=0.55,
    min_avg_dollar_volume=10_000_000,
    etf_target_pct=0.45,
    allow_short=True,
    short_size_pct=0.55,
    prefer_inverse_etf=True,
    max_short_positions=3,
)

AGGRESSIVE = RiskProfile(
    name="aggressive",
    label="Aggressive",
    description=(
        "Momentum and growth hunting. Higher-beta single names and thematic ETFs, "
        "larger positions, tighter stops and shorter holds. Expect a lower win rate "
        "paid for by larger winners - and materially larger drawdowns."
    ),
    max_position_pct=0.18,
    risk_per_trade_pct=0.0125,
    max_positions=12,
    cash_floor_pct=0.05,
    atr_stop_mult=2.0,
    target_r_multiples=(1.5, 3.0, 5.0),
    trail_after_r=1.0,
    trail_atr_mult=2.25,
    max_hold_days=30,
    min_score=54.0,
    allowed_asset_types=("etf", "stock"),
    max_annual_volatility=0.95,
    min_avg_dollar_volume=5_000_000,
    etf_target_pct=0.25,
    allow_short=True,
    short_size_pct=0.75,
    prefer_inverse_etf=False,
    max_short_positions=5,
)

RISK_PROFILES: dict[str, RiskProfile] = {
    p.name: p for p in (CONSERVATIVE, MODERATE, AGGRESSIVE)
}


def get_profile(name: str) -> RiskProfile:
    key = (name or "").strip().lower()
    if key not in RISK_PROFILES:
        valid = ", ".join(RISK_PROFILES)
        raise KeyError(f"unknown risk profile {name!r}; choose one of: {valid}")
    return RISK_PROFILES[key]


@dataclass
class Settings:
    """Everything the desk needs to know to run, persisted as JSON."""

    home: Path = field(default_factory=lambda: DEFAULT_HOME)
    risk_profile: str = "moderate"
    starting_cash: float = 100_000.0
    data_provider: str = "auto"
    """auto | yahoo | stooq | csv | synthetic - 'auto' falls back down the list."""

    csv_dir: str = ""
    """Directory of <SYMBOL>.csv files, used when data_provider is 'csv'.
    Empty means the desk's own data/bars directory."""

    broker: str = "paper"
    """paper (built-in simulator) | alpaca (Alpaca paper account)."""

    execution_mode: str = "auto"
    """auto - ideas are placed as working orders immediately.
    manual - ideas are queued for approval and nothing reaches the broker
    until a human approves them."""

    proposal_lifetime_days: int = 3
    """How long a queued idea stays reviewable before the setup goes stale."""

    news_enabled: bool = True
    news_lookback_days: int = 7
    max_news_per_symbol: int = 25

    watchlist: list[str] = field(default_factory=list)
    """Extra symbols to consider on top of the risk-tier universe."""

    universe: str = "curated"
    """curated (the risk-tier list) | wide (screen the bundled symbol file)."""

    symbols_file: str = ""
    """Path to a newline-separated symbol list. Empty uses the bundled file."""

    multi_timeframe: bool = True
    """Require the weekly trend to agree before taking a daily entry."""

    use_regime_filter: bool = True
    """Scale exposure to the broad market regime."""

    commission_per_share: float = 0.0
    slippage_bps: float = 5.0
    """Simulated slippage in basis points applied against you on every fill."""

    @property
    def db_path(self) -> Path:
        return self.home / "portfolio.db"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def bars_dir(self) -> Path:
        """Where `quantdesk fetch` saves history for offline backtesting."""
        return Path(self.csv_dir).expanduser() if self.csv_dir else self.home / "bars"

    @property
    def reports_dir(self) -> Path:
        return self.home / "reports"

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def profile(self) -> RiskProfile:
        return get_profile(self.risk_profile)

    def ensure_dirs(self) -> None:
        for d in (self.home, self.cache_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- persistence --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["home"] = str(self.home)
        return d

    def save(self) -> None:
        self.ensure_dirs()
        self.config_path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, home: Path | str | None = None) -> "Settings":
        base = Path(home) if home else DEFAULT_HOME
        path = base / "config.json"
        if not path.exists():
            return cls(home=base)
        raw = json.loads(path.read_text())
        raw["home"] = Path(raw.get("home", base))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})
