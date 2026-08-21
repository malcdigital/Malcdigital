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
BREAKEVEN = "stopped at breakeven"
STOP = "stop loss"
GAP_STOP = "gapped through stop"
GAP_TRAILED = "gapped through trailed stop"
TIME_STOP = "time stop"
OTHER = "other"

#: Ordered worst-to-best for reporting, so the eye lands on the losses first.
EXIT_ORDER = [TARGET, TRAILING, BREAKEVEN, TIME_STOP, GAP_TRAILED, STOP, GAP_STOP,
              OTHER]


def classify_exit(
    reason: str, r_multiple: float | None, stop_trailed: bool = False
) -> str:
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
        # Through the original stop is a loss beyond what was planned. Through a
        # stop already trailed into profit is giving some of that profit back.
        # Averaging them together produced a "gap" bucket reading better than a
        # planned stop, which is nonsense on its face.
        return GAP_TRAILED if stop_trailed else GAP_STOP
    if "target" in text and "reached" in text and "without" not in text:
        return TARGET
    if "stop" in text:
        if r_multiple is None:
            return STOP
        # A trail that reached breakeven and then stopped out is a scratch, not
        # a loss. Counting it as a loss overstates how often the strategy is
        # wrong, and understates what the trailing rule is doing.
        if abs(r_multiple) <= 0.05:
            return BREAKEVEN
        if r_multiple > 0:
            return TRAILING
        return STOP
    return OTHER


@dataclass
class RoundTrip:
    """One position from entry to close, however many exits that took.

    Reporting per exit *event* silently compares unlike things: taking half off
    at a target is one row and closing the remainder at a stop is another, so
    "average win" is measured on part-positions while "average loss" is measured
    on whole ones. That alone can make a working design look broken - and did.

    R is weighted by the share of the position each exit closed, so one number
    describes what the position actually returned.
    """

    key: str
    symbol: str = ""
    direction: str = "long"
    setup: str = ""
    pnl: float = 0.0
    r_multiple: float | None = None
    shares_exited: int = 0
    shares_entered: int = 0
    exits: int = 0
    final_exit: str = OTHER
    took_partial_profit: bool = False
    holding_days: int | None = None

    @property
    def fully_closed(self) -> bool:
        """False when part of the position was still open at the end of the run.

        An unfinished position is not a result yet; counting it as one would
        book its realised half and ignore the open remainder.
        """
        if self.shares_entered <= 0:
            return True  # no entry record to compare against; assume complete
        return self.shares_exited >= self.shares_entered

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


def build_round_trips(trades: list) -> list[RoundTrip]:
    """Collapse exit events into one record per position."""
    entries: dict = {}
    groups: dict = {}
    order: list = []
    anonymous = 0

    for trade in trades:
        pid = getattr(trade, "position_id", None)
        is_exit = getattr(trade, "is_exit", False)

        if not is_exit:
            if pid is not None:
                entries[pid] = entries.get(pid, 0) + int(trade.shares)
            continue

        if pid is None:
            # No position to group by - treat it as its own round trip rather
            # than lumping every such trade together under a shared null key.
            anonymous += 1
            key = f"anon-{anonymous}"
        else:
            key = f"pos-{pid}"

        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(trade)

    out: list[RoundTrip] = []
    for key in order:
        legs = sorted(groups[key], key=lambda t: (t.trade_date, t.id or 0))
        first = legs[0]
        pid = getattr(first, "position_id", None)

        trip = RoundTrip(
            key=key,
            symbol=first.symbol,
            direction=getattr(first, "direction", "long") or "long",
            setup=getattr(first, "setup", "") or "",
            shares_entered=entries.get(pid, 0),
            exits=len(legs),
        )

        weighted_r = 0.0
        weighted_shares = 0
        for leg in legs:
            trip.pnl += float(leg.realized_pnl or 0.0)
            trip.shares_exited += int(leg.shares)
            r = getattr(leg, "r_multiple", None)
            if r is not None:
                weighted_r += float(r) * int(leg.shares)
                weighted_shares += int(leg.shares)

        if weighted_shares:
            trip.r_multiple = round(weighted_r / weighted_shares, 4)

        last = legs[-1]
        trip.final_exit = classify_exit(
            last.reason, getattr(last, "r_multiple", None),
            bool(getattr(last, "stop_trailed", False)),
        )
        trip.holding_days = getattr(last, "holding_days", None)
        trip.took_partial_profit = len(legs) > 1 and any(
            classify_exit(leg.reason, getattr(leg, "r_multiple", None),
                          bool(getattr(leg, "stop_trailed", False))) == TARGET
            for leg in legs[:-1]
        )
        out.append(trip)
    return out


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
    multi_exit: int = 0
    partial_profit: int = 0
    open_at_end: int = 0
    avg_win_dollars: float = 0.0
    avg_loss_dollars: float = 0.0
    win_rate: float = 0.0
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

        if self.multi_exit:
            out.append(
                f"{self.multi_exit:,} of {self.closed:,} positions closed in "
                "stages. Each is counted once here, with R weighted by the share "
                "of the position each exit closed - reporting per exit event "
                "instead compares part-positions against whole ones and can make "
                "a working design look broken."
            )

        target_share = self.share(TARGET)
        time_share = self.share(TIME_STOP)
        trailing_share = self.share(TRAILING)
        stop_share = self.share(STOP) + self.share(GAP_STOP)

        # Counting only positions whose *final* exit was a target misses every
        # position that banked the first target and left on something else -
        # which is most of them, by design. Reporting 0.6% when 28% touched a
        # target is not a small error: it points at the entries when the real
        # story is what happens after the first target is hit.
        touched = self.buckets.get(TARGET, ExitBucket(TARGET)).count + \
            self.partial_profit
        touched_share = touched / self.closed * 100.0 if self.closed else 0.0

        if touched_share < 15:
            out.append(
                f"Only {touched_share:.0f}% of positions reached a profit target "
                "at all. The plans are built around 2R and 4R targets, so most "
                "are being closed by something else before the thesis plays out."
            )
        elif target_share < 5:
            out.append(
                f"{touched_share:.0f}% of positions banked the first target, but "
                f"only {target_share:.1f}% ran all the way to the second. The "
                "remainder is being closed by a stop or the clock, so the far "
                "target is doing almost no work - the trailing rule and the time "
                "stop are deciding what these trades earn."
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

        breakeven_share = self.share(BREAKEVEN)
        if breakeven_share > 10:
            out.append(
                f"{breakeven_share:.0f}% were scratched at breakeven by the trail. "
                "Those are neither wins nor losses; a high share means the trail "
                "is arming and then being clipped before the trade goes anywhere."
            )

        if stop_share > 55:
            out.append(
                f"{stop_share:.0f}% were stopped out at a loss. Either the stops sit "
                "inside normal noise for these instruments, or the entries are early."
            )

        gap_bucket = self.buckets.get(GAP_STOP)
        if gap_bucket and gap_bucket.count > self.closed * 0.03:
            out.append(
                f"{gap_bucket.count} positions ({self.share(GAP_STOP):.0f}%) gapped "
                f"through their original stop, averaging {gap_bucket.avg_r:+.2f}R "
                "against a planned -1R. This is the risk a stop cannot control: "
                "price is simply not available at your price when the market "
                "reopens."
            )

        trailed_gap = self.buckets.get(GAP_TRAILED)
        if trailed_gap and trailed_gap.count:
            out.append(
                f"{trailed_gap.count} positions gapped through a stop that had "
                f"already been trailed, averaging {trailed_gap.avg_r:+.2f}R. Those "
                "gave back profit rather than exceeding the planned loss - a "
                "different event from the line above, and not a failure."
            )
        return out


def _bucket_for(store: dict[str, ExitBucket], key: str) -> ExitBucket:
    if key not in store:
        store[key] = ExitBucket(reason=key)
    return store[key]


#: Histogram edges in R, placed around the design's own decision points: a stop
#: is meant to cost 1R and targets sit at 2R and 4R.
#:
#: The band around -1R is deliberately wide. Stops fill slightly past their
#: price because of slippage, so a perfectly ordinary stop lands at -1.02 or
#: -1.06R. A boundary drawn exactly at -1R therefore files almost every normal
#: stop under "worse than planned", which reads as alarming and buries the
#: genuinely bad fills - the gaps at -2R and beyond - in the same bucket.
_R_BINS = [
    ("< -2R (gapped badly)", -math.inf, -2.0),
    ("-2R to -1.25R (worse than planned)", -2.0, -1.25),
    ("-1.25R to -0.75R (stop, as planned)", -1.25, -0.75),
    ("-0.75R to -0.05R", -0.75, -0.05),
    ("breakeven (-0.05R to +0.05R)", -0.05, 0.05),
    ("+0.05R to +1R", 0.05, 1.0),
    ("+1R to +2R", 1.0, 2.0),
    ("+2R to +4R", 2.0, 4.0),
    ("> +4R", 4.0, math.inf),
]


def analyze_trades(trades: list) -> TradeAnalysis:
    """Summarise closed positions.

    Works on round trips, not exit events: a position that takes half off at a
    target and stops the remainder is one trade with one outcome, not a win and
    a loss that get averaged separately against each other.
    """
    analysis = TradeAnalysis()
    all_trips = build_round_trips(trades)
    trips = [t for t in all_trips if t.fully_closed]
    analysis.closed = len(trips)
    analysis.open_at_end = len(all_trips) - len(trips)
    if not trips:
        return analysis

    analysis.r_histogram = {label: 0 for label, _, _ in _R_BINS}
    win_r: list[float] = []
    loss_r: list[float] = []
    win_days: list[int] = []
    loss_days: list[int] = []

    for trip in trips:
        bucket = _bucket_for(analysis.buckets, trip.final_exit)
        bucket.count += 1
        bucket.total_pnl += trip.pnl
        if trip.r_multiple is not None:
            bucket.r_values.append(trip.r_multiple)
        if trip.holding_days is not None:
            bucket.holding_days.append(trip.holding_days)

        for group, key in (
            (analysis.by_setup, trip.setup or "unknown"),
            (analysis.by_direction, trip.direction or "long"),
        ):
            sub = _bucket_for(group, key)
            sub.count += 1
            sub.total_pnl += trip.pnl
            if trip.r_multiple is not None:
                sub.r_values.append(trip.r_multiple)

        if trip.exits > 1:
            analysis.multi_exit += 1
        if trip.took_partial_profit:
            analysis.partial_profit += 1

        if trip.r_multiple is None:
            analysis.missing_r += 1
        else:
            for label, low, high in _R_BINS:
                if low <= trip.r_multiple < high:
                    analysis.r_histogram[label] += 1
                    break

        if trip.final_exit == BREAKEVEN:
            pass  # a scratch belongs in neither the win nor the loss average
        elif trip.pnl > 0:
            if trip.r_multiple is not None:
                win_r.append(trip.r_multiple)
            if trip.holding_days is not None:
                win_days.append(trip.holding_days)
        else:
            if trip.r_multiple is not None:
                loss_r.append(trip.r_multiple)
            if trip.holding_days is not None:
                loss_days.append(trip.holding_days)

    analysis.avg_win_r = sum(win_r) / len(win_r) if win_r else 0.0
    analysis.avg_loss_r = sum(loss_r) / len(loss_r) if loss_r else 0.0
    analysis.winner_days = sum(win_days) / len(win_days) if win_days else 0.0
    analysis.loser_days = sum(loss_days) / len(loss_days) if loss_days else 0.0

    wins = [t.pnl for t in trips if t.pnl > 0]
    losses = [t.pnl for t in trips if t.pnl <= 0]
    analysis.avg_win_dollars = sum(wins) / len(wins) if wins else 0.0
    analysis.avg_loss_dollars = abs(sum(losses) / len(losses)) if losses else 0.0
    analysis.win_rate = len(wins) / len(trips) * 100.0 if trips else 0.0

    all_r = win_r + loss_r
    analysis.best_r = max(all_r) if all_r else 0.0
    analysis.worst_r = min(all_r) if all_r else 0.0
    return analysis


def _column_width(labels, *extra: str, minimum: int = 26) -> int:
    """Width of a label column, wide enough for its longest entry.

    Hard-coded widths quietly break alignment the moment a label is renamed or
    a bucket is added, and a misaligned table is easy to misread.
    """
    longest = max((len(str(x)) for x in (*labels, *extra)), default=0)
    return max(minimum, longest + 1)


def to_text(analysis: TradeAnalysis, width: int = 78) -> str:
    """Render the breakdown for a terminal."""
    thin = "-" * width
    if analysis.closed == 0:
        return "TRADE BREAKDOWN\n" + thin + "\n  No closed trades yet."

    exit_col = _column_width([b.reason for b in analysis.ordered_buckets],
                             "HOW IT ENDED")
    L = ["TRADE BREAKDOWN", thin,
         f"  {analysis.closed:,} closed positions"
         + (f" ({analysis.multi_exit:,} closed in stages, "
            f"{analysis.partial_profit:,} after banking a target)"
            if analysis.multi_exit else "")
         + (f"; {analysis.open_at_end:,} still open at the end and excluded"
            if analysis.open_at_end else ""),
         "",
         f"  {'HOW IT ENDED':<{exit_col}}{'COUNT':>7}{'SHARE':>8}{'AVG R':>8}"
         f"{'AVG DAYS':>10}{'TOTAL P&L':>14}"]

    for bucket in analysis.ordered_buckets:
        share = bucket.count / analysis.closed * 100.0
        L.append(
            f"  {bucket.reason:<{exit_col}}{bucket.count:>7,}{share:>7.1f}%"
            f"{bucket.avg_r:>+8.2f}{bucket.avg_days:>10.0f}"
            f"{bucket.total_pnl:>+14,.0f}"
        )

    L += ["", "  RESULT DISTRIBUTION (in R, the risk originally taken)"]
    peak = max(analysis.r_histogram.values()) if analysis.r_histogram else 0
    bin_col = _column_width(analysis.r_histogram, "(no R recorded)")
    for label, count in analysis.r_histogram.items():
        share = count / analysis.closed * 100.0
        bar = "#" * int(round(count / peak * 28)) if peak else ""
        L.append(f"  {label:<{bin_col}}{count:>6,}{share:>7.1f}%  {bar}")
    if analysis.missing_r:
        L.append(f"  {'(no R recorded)':<{bin_col}}{analysis.missing_r:>6,}")

    L += ["",
          f"  Win rate {analysis.win_rate:.1f}% of positions",
          f"  Average win {analysis.avg_win_r:+.2f}R "
          f"(${analysis.avg_win_dollars:,.0f}) held {analysis.winner_days:.0f} days",
          f"  Average loss {analysis.avg_loss_r:+.2f}R "
          f"(${analysis.avg_loss_dollars:,.0f}) held {analysis.loser_days:.0f} days",
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
