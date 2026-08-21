"""Post-trade analysis: where the money actually went.

Headline statistics say whether a strategy made money. They do not say *why*,
and the difference matters when deciding what to change. A 58% win rate with an
average win smaller than the average loss is not a mildly disappointing result -
it is a specific, diagnosable failure, because a design targeting 2R and 4R
against a 1R stop should produce wins that are multiples of losses.

This module classifies how each trade ended and what it returned in R, so the
question "are the signals bad, or are the exits throwing away good signals?" has
an answer from the data rather than an opinion.

Nothing here searches for better parameters. It reads what happened. Tuning a
strategy until its backtest improves, on the same data that produced the
diagnosis, is how backtests become fiction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TARGET = "target reached"
TRAILING = "trailing stop (in profit)"
STOP = "stop loss"
GAP_STOP = "gapped through stop"
TIME_STOP = "time stop"
OTHER = "other"

#: Ordered worst-to-best for reporting, so the eye lands on the losses first.
EXIT_ORDER = [TARGET, TRAILING, TIME_STOP, STOP, GAP_STOP, OTHER]


def classify_exit(reason: str, r_multiple: float | None) -> str:
    """Bucket an exit by how it ended.

    A trailing stop and an original stop both record "stop loss hit", because
    trailing works by moving the stop rather than by placing a different order.
    The R multiple separates them: leaving at a profit means the stop had been
    ratcheted up above entry, which is a materially different outcome from being
    stopped out at a loss and should not be counted alongside it.
    """
    text = (reason or "").lower()
    # Order matters. The time-stop message reads "time stop - held N days
    # without reaching target", so a naive check for "target" classifies it as a
    # target hit - which would hide cut-short winners inside the very bucket
    # meant to show the strategy working. Most specific match first.
    if "time stop" in text:
        return TIME_STOP
    if "gapped through" in text:
        return GAP_STOP
    if "target" in text and "reached" in text and "without" not in text:
        return TARGET
    if "stop" in text:
        if r_multiple is not None and r_multiple > 0:
            return TRAILING
        return STOP
    return OTHER


@dataclass
class ExitBucket:
    reason: str
    count: int = 0
    total_pnl: float = 0.0
    r_values: list[float] = field(default_factory=list)
    holding_days: list[int] = field(default_factory=list)

    @property
    def avg_r(self) -> float:
        return sum(self.r_values) / len(self.r_values) if self.r_values else 0.0

    @property
    def avg_days(self) -> float:
        return sum(self.holding_days) / len(self.holding_days) if self.holding_days else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.count if self.count else 0.0


@dataclass
class TradeAnalysis:
    closed: int = 0
    buckets: dict[str, ExitBucket] = field(default_factory=dict)
    r_histogram: dict[str, int] = field(default_factory=dict)
    winner_days: float = 0.0
    loser_days: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    best_r: float = 0.0
    worst_r: float = 0.0
    missing_r: int = 0
    by_setup: dict[str, ExitBucket] = field(default_factory=dict)
    by_direction: dict[str, ExitBucket] = field(default_factory=dict)

    @property
    def ordered_buckets(self) -> list[ExitBucket]:
        return [self.buckets[k] for k in EXIT_ORDER if k in self.buckets]

    def share(self, reason: str) -> float:
        bucket = self.buckets.get(reason)
        return (bucket.count / self.closed * 100.0) if bucket and self.closed else 0.0

    def findings(self) -> list[str]:
        """What the distribution says, in plain English.

        Deliberately phrased as diagnosis rather than prescription: each line
        names what the data shows and what it would imply, not what to change.
        """
        out: list[str] = []
        if self.closed < 30:
            return [
                f"Only {self.closed} closed trades - too few to read anything into "
                "the distribution."
            ]

        target_share = self.share(TARGET)
        time_share = self.share(TIME_STOP)
        trailing_share = self.share(TRAILING)
        stop_share = self.share(STOP) + self.share(GAP_STOP)

        if target_share < 15:
            out.append(
                f"Only {target_share:.0f}% of trades reached a profit target. The "
                "plans are built around 2R and 4R targets, so most positions are "
                "being closed by something else before the thesis plays out."
            )

        if time_share > 20:
            bucket = self.buckets.get(TIME_STOP)
            out.append(
                f"{time_share:.0f}% ended on the time stop at an average of "
                f"{bucket.avg_r:+.2f}R. Capital is being recycled before trades "
                "resolve either way - the holding period is short relative to how "
                "long these setups take to work."
            )

        if trailing_share > 30:
            bucket = self.buckets.get(TRAILING)
            out.append(
                f"{trailing_share:.0f}% were trailing-stopped in profit, averaging "
                f"{bucket.avg_r:+.2f}R. The trail is protecting gains, but if that "
                "average sits well below the first target it is also ending trades "
                "during ordinary pullbacks."
            )

        if self.avg_win_r and self.avg_loss_r:
            ratio = self.avg_win_r / abs(self.avg_loss_r)
            if ratio < 1.5:
                out.append(
                    f"Average win {self.avg_win_r:+.2f}R against average loss "
                    f"{self.avg_loss_r:+.2f}R - a ratio of {ratio:.2f}. Losses run "
                    "the full distance to the stop while wins are cut early, which "
                    "is the arithmetic that turns a good win rate into a thin edge."
                )
            else:
                out.append(
                    f"Average win {self.avg_win_r:+.2f}R against average loss "
                    f"{self.avg_loss_r:+.2f}R - wins are {ratio:.1f}x losses, which "
                    "is the shape the design intends."
                )

        if self.winner_days and self.loser_days and self.winner_days < self.loser_days:
            out.append(
                f"Winners are held {self.winner_days:.0f} days on average and losers "
                f"{self.loser_days:.0f}. Holding losers longer than winners is the "
                "opposite of the intended discipline."
            )

        if stop_share > 55:
            out.append(
                f"{stop_share:.0f}% were stopped out at a loss. Either the stops sit "
                "inside normal noise for these instruments, or the entries are early."
            )

        gap_bucket = self.buckets.get(GAP_STOP)
        if gap_bucket and gap_bucket.count > self.closed * 0.05:
            out.append(
                f"{gap_bucket.count} trades ({self.share(GAP_STOP):.0f}%) gapped "
                f"through their stop, averaging {gap_bucket.avg_r:+.2f}R against a "
                "planned -1R. This is the risk a stop cannot control, and it is "
                "why realised losses exceed planned ones."
            )
        return out


def _bucket_for(store: dict[str, ExitBucket], key: str) -> ExitBucket:
    if key not in store:
        store[key] = ExitBucket(reason=key)
    return store[key]


#: Histogram edges in R. Chosen around the design's own decision points: -1R is
#: a stop working as planned, 2R and 4R are where targets sit.
_R_BINS = [
    ("< -1R (worse than planned)", -math.inf, -1.0),
    ("-1R to -0.5R", -1.0, -0.5),
    ("-0.5R to 0", -0.5, 0.0),
    ("0 to +1R", 0.0, 1.0),
    ("+1R to +2R", 1.0, 2.0),
    ("+2R to +4R", 2.0, 4.0),
    ("> +4R", 4.0, math.inf),
]


def analyze_trades(trades: list) -> TradeAnalysis:
    """Summarise how closed trades ended."""
    analysis = TradeAnalysis()
    closed = [t for t in trades if getattr(t, "is_exit", False)
              and t.realized_pnl is not None]
    analysis.closed = len(closed)
    if not closed:
        return analysis

    analysis.r_histogram = {label: 0 for label, _, _ in _R_BINS}
    win_r: list[float] = []
    loss_r: list[float] = []
    win_days: list[int] = []
    loss_days: list[int] = []

    for trade in closed:
        r = trade.r_multiple
        reason = classify_exit(trade.reason, r)

        bucket = _bucket_for(analysis.buckets, reason)
        bucket.count += 1
        bucket.total_pnl += float(trade.realized_pnl)
        if r is not None:
            bucket.r_values.append(float(r))
        if trade.holding_days is not None:
            bucket.holding_days.append(int(trade.holding_days))

        for group, key in (
            (analysis.by_setup, trade.setup or "unknown"),
            (analysis.by_direction, trade.direction or "long"),
        ):
            sub = _bucket_for(group, key)
            sub.count += 1
            sub.total_pnl += float(trade.realized_pnl)
            if r is not None:
                sub.r_values.append(float(r))

        if r is None:
            analysis.missing_r += 1
        else:
            for label, low, high in _R_BINS:
                if low <= r < high:
                    analysis.r_histogram[label] += 1
                    break

        if float(trade.realized_pnl) > 0:
            if r is not None:
                win_r.append(float(r))
            if trade.holding_days is not None:
                win_days.append(int(trade.holding_days))
        else:
            if r is not None:
                loss_r.append(float(r))
            if trade.holding_days is not None:
                loss_days.append(int(trade.holding_days))

    analysis.avg_win_r = sum(win_r) / len(win_r) if win_r else 0.0
    analysis.avg_loss_r = sum(loss_r) / len(loss_r) if loss_r else 0.0
    analysis.winner_days = sum(win_days) / len(win_days) if win_days else 0.0
    analysis.loser_days = sum(loss_days) / len(loss_days) if loss_days else 0.0

    all_r = win_r + loss_r
    analysis.best_r = max(all_r) if all_r else 0.0
    analysis.worst_r = min(all_r) if all_r else 0.0
    return analysis


def to_text(analysis: TradeAnalysis, width: int = 78) -> str:
    """Render the breakdown for a terminal."""
    thin = "-" * width
    if analysis.closed == 0:
        return "TRADE BREAKDOWN\n" + thin + "\n  No closed trades yet."

    L = ["TRADE BREAKDOWN", thin,
         f"  {'HOW IT ENDED':<26}{'COUNT':>7}{'SHARE':>8}{'AVG R':>8}"
         f"{'AVG DAYS':>10}{'TOTAL P&L':>14}"]

    for bucket in analysis.ordered_buckets:
        share = bucket.count / analysis.closed * 100.0
        L.append(
            f"  {bucket.reason:<26}{bucket.count:>7,}{share:>7.1f}%"
            f"{bucket.avg_r:>+8.2f}{bucket.avg_days:>10.0f}"
            f"{bucket.total_pnl:>+14,.0f}"
        )

    L += ["", "  RESULT DISTRIBUTION (in R, the risk originally taken)"]
    peak = max(analysis.r_histogram.values()) if analysis.r_histogram else 0
    for label, count in analysis.r_histogram.items():
        share = count / analysis.closed * 100.0
        bar = "#" * int(round(count / peak * 28)) if peak else ""
        L.append(f"  {label:<28}{count:>6,}{share:>7.1f}%  {bar}")
    if analysis.missing_r:
        L.append(f"  {'(no R recorded)':<28}{analysis.missing_r:>6,}")

    L += ["", f"  Average win {analysis.avg_win_r:+.2f}R held "
              f"{analysis.winner_days:.0f} days | "
              f"average loss {analysis.avg_loss_r:+.2f}R held "
              f"{analysis.loser_days:.0f} days",
          f"  Best {analysis.best_r:+.2f}R | worst {analysis.worst_r:+.2f}R"]

    if len(analysis.by_direction) > 1:
        L += ["", "  BY DIRECTION"]
        for key, bucket in sorted(analysis.by_direction.items()):
            L.append(f"    {key:<10}{bucket.count:>6,} trades  "
                     f"avg {bucket.avg_r:+.2f}R  P&L {bucket.total_pnl:>+12,.0f}")

    if len(analysis.by_setup) > 1:
        L += ["", "  BY SETUP"]
        for key, bucket in sorted(analysis.by_setup.items(),
                                  key=lambda kv: -kv[1].total_pnl):
            L.append(f"    {key:<12}{bucket.count:>6,} trades  "
                     f"avg {bucket.avg_r:+.2f}R  P&L {bucket.total_pnl:>+12,.0f}")

    findings = analysis.findings()
    if findings:
        L += ["", "  WHAT THIS SAYS", thin]
        for finding in findings:
            L.append(f"  - {finding}")
    return "\n".join(L)
