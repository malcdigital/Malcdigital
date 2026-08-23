"""Out-of-sample testing: a window you are allowed to fit, and one you are not.

Every rule in this repository was written with the whole history available.
That makes every backtest number in it partly a memory of what happened rather
than a prediction of what will. The gap between those two things does not show
up as an error - it shows up as a strategy that worked in testing and does not
work with money in it.

A holdout is the only cheap defence. Split the history, develop against the
early part, and keep the late part sealed. The number that matters is then not
how the strategy did on either window but *how much worse* it did on the one it
could not have been fitted to.

The uncomfortable part is that a holdout is consumed by use. Look at it, change
something, look again, and it has quietly become training data - the same
overfitting as before, just slower and with more steps in between. Nothing in
software can prevent that. What this module does instead is refuse to show the
holdout unless asked, and count every time it is asked, so the erosion is at
least visible to the person doing it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

#: Fraction of the window given to fitting when no explicit split date is set.
#: Two-thirds is convention rather than theory: enough holdout to be more than
#: one market mood, enough fit window to have trades in it at all.
DEFAULT_FIT_FRACTION = 0.67

#: Reveals after which the holdout is worth little. Not a hard stop - there is
#: no honest way to enforce one - but the point where the report says so
#: plainly rather than presenting the number as if it were still clean.
SPENT_AFTER_REVEALS = 3


def split_window(start: date, end: date, at: date | None = None,
                 fit_fraction: float = DEFAULT_FIT_FRACTION) -> tuple[date, date]:
    """Return (fit_end, holdout_start) for a window.

    The holdout begins the day after the fit window ends, so no session belongs
    to both. A session in both windows would let the fit window's final open
    positions settle inside the holdout, which is exactly the leak the split
    exists to prevent.
    """
    if end <= start:
        raise ValueError("the window ends before it starts")

    if at is not None:
        if not (start < at <= end):
            raise ValueError(
                f"split date {at} is outside the window {start} to {end}"
            )
        fit_end = at
    else:
        if not 0.0 < fit_fraction < 1.0:
            raise ValueError("fit_fraction must be between 0 and 1")
        span = (end - start).days
        fit_end = start + timedelta(days=int(span * fit_fraction))

    holdout_start = fit_end + timedelta(days=1)
    if holdout_start > end:
        raise ValueError("the split leaves no holdout period")
    return fit_end, holdout_start


@dataclass
class Degradation:
    """How much worse the holdout was than the window it was fitted against.

    Stored as (fit, holdout, change) per measure rather than just the change,
    because "Sharpe fell 0.4" reads very differently starting from 1.6 than
    from 0.5.
    """

    measure: str
    fit: float
    holdout: float
    higher_is_better: bool = True
    suffix: str = "%"
    is_gap: bool = False
    """Whether the two values are already differences against the benchmark.

    A gap can sit either side of zero, so the share of it that survived is not
    a meaningful quantity: an edge of +0.04 followed by -0.43 would report as
    "kept -1075%", which reads as arithmetic rather than as the sign change it
    actually is.
    """

    @property
    def change(self) -> float:
        return self.holdout - self.fit

    @property
    def worse(self) -> bool:
        return self.change < 0 if self.higher_is_better else self.change > 0

    @property
    def retained(self) -> float | None:
        """Holdout as a fraction of fit, where that means anything.

        Undefined when the fit value is at or below zero: "kept 40% of a
        negative return" is not a sentence worth printing.
        """
        if self.is_gap or not self.higher_is_better or self.fit <= 0:
            return None
        return self.holdout / self.fit


@dataclass
class SplitResult:
    fit_start: date
    fit_end: date
    holdout_start: date
    holdout_end: date
    fit: object = None
    holdout: object = None
    reveals: int = 0
    revealed: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def holdout_days(self) -> int:
        return (self.holdout_end - self.holdout_start).days

    @property
    def holdout_years(self) -> float:
        return self.holdout_days / 365.25

    def degradations(self) -> list[Degradation]:
        """The comparison this whole module exists to produce."""
        if not (self.fit and self.holdout):
            return []
        a, b = self.fit.metrics, self.holdout.metrics
        if not (a and b):
            return []
        return [
            Degradation("CAGR", a.cagr_pct, b.cagr_pct),
            Degradation("Sharpe", a.sharpe, b.sharpe, suffix=""),
            Degradation("Sortino", a.sortino, b.sortino, suffix=""),
            # Drawdown is stored as a negative percentage, so -0.9% is a
            # better outcome than -2.3% and "higher is better" is correct as
            # written. Reading it as a cost to be minimised marks every
            # shallower drawdown as a regression.
            Degradation("Max drawdown", a.max_drawdown_pct, b.max_drawdown_pct),
            Degradation("Profit factor", a.profit_factor, b.profit_factor,
                        suffix=""),
            Degradation("Expectancy", a.expectancy, b.expectancy, suffix=""),
            Degradation("Win rate", a.win_rate, b.win_rate),
        ]

    def benchmark_gaps(self) -> list[Degradation]:
        """The same comparison, measured against buy-and-hold in each window.

        Comparing a strategy to itself across two windows answers "was this
        fitted to its development data" and nothing else. It cannot tell you
        that both windows got easier, which is what a table of across-the-board
        improvement usually means. Holding each window against its own
        benchmark removes the regime from both sides: a strategy that beat the
        index in-sample and lost to it out-of-sample has lost the only thing it
        had, however healthy its own numbers look.

        Restricted to measures buy-and-hold can meaningfully post. Profit
        factor, expectancy and win rate over a single held position are not
        comparable quantities.
        """
        if not (self.fit and self.holdout):
            return []
        a, b = self.fit.metrics, self.holdout.metrics
        fb = getattr(self.fit, "benchmark_metrics", None)
        hb = getattr(self.holdout, "benchmark_metrics", None)
        if not (a and b and fb and hb):
            return []
        pairs = [
            ("CAGR", "cagr_pct", "%"),
            ("Sharpe", "sharpe", ""),
            ("Sortino", "sortino", ""),
            ("Max drawdown", "max_drawdown_pct", "%"),
        ]
        return [
            Degradation(measure,
                        getattr(a, attr) - getattr(fb, attr),
                        getattr(b, attr) - getattr(hb, attr),
                        suffix=suffix, is_gap=True)
            for measure, attr, suffix in pairs
        ]

    def verdict(self) -> list[str]:
        """Read the split, phrased to disappoint where warranted."""
        out: list[str] = []

        if not self.revealed:
            out.append(
                f"The holdout ({self.holdout_start} to {self.holdout_end}, "
                f"{self.holdout_years:.1f} years) was not run. Develop against "
                "the fit window, then reveal it once with --reveal-holdout when "
                "you are done changing things."
            )
            return out

        if self.reveals > 1:
            out.append(
                f"This holdout has now been revealed {self.reveals} times. Each "
                "look after the first is a little less out-of-sample than the "
                "last, because what you saw informed what you changed."
            )
        if self.reveals >= SPENT_AFTER_REVEALS:
            out.append(
                f"After {self.reveals} reveals this is not really a holdout any "
                "more - it is a slower way of fitting to the same data. Treat "
                "the number below as optimistic, and get fresh data before "
                "believing it."
            )

        degradations = self.degradations()
        cagr = next((d for d in degradations if d.measure == "CAGR"), None)
        if cagr:
            retained = cagr.retained
            if cagr.fit <= 0:
                out.append(
                    f"The fit window itself lost money ({cagr.fit:+.2f}% CAGR). "
                    "The holdout is not the problem - there is nothing here that "
                    "worked even on the data it was written against."
                )
            elif retained is None or retained < 0:
                out.append(
                    f"CAGR went from {cagr.fit:+.2f}% in the fit window to "
                    f"{cagr.holdout:+.2f}% out of sample - it did not merely "
                    "weaken, it changed sign. That is the signature of a rule "
                    "fitted to noise."
                )
            elif retained < 0.5:
                out.append(
                    f"Out of sample it kept {retained * 100:.0f}% of its fitted "
                    f"CAGR ({cagr.fit:+.2f}% to {cagr.holdout:+.2f}%). Losing "
                    "more than half is the usual sign that the rules were shaped "
                    "by this particular history."
                )
            else:
                out.append(
                    f"Out of sample it kept {retained * 100:.0f}% of its fitted "
                    f"CAGR ({cagr.fit:+.2f}% to {cagr.holdout:+.2f}%). Some decay "
                    "is normal and expected; this is within the range where the "
                    "edge might be real."
                )

        # Across-the-board improvement is not the good news it reads as.
        if degradations and all(not d.worse for d in degradations):
            out.append(
                "Every measure improved out of sample. A set of rules does not "
                "get better on data it has never seen, so the likelier reading "
                "is that the holdout was an easier stretch of market than the "
                "fit window - check what the two periods contained before "
                "taking this as a pass."
            )

        # And the check that survives a change of regime: how each window did
        # against its own benchmark, rather than how the strategy did against
        # itself.
        gap = next((d for d in self.benchmark_gaps() if d.measure == "Sharpe"),
                   None)
        if gap and gap.fit > 0 and gap.holdout < 0:
            out.append(
                f"Against buy-and-hold, Sharpe went from {gap.fit:+.2f} in the "
                f"fit window to {gap.holdout:+.2f} out of sample. Beating the "
                "index on risk-adjusted terms is the case for running something "
                "that underperforms it outright, and that case did not survive "
                "the split."
            )
        elif gap and gap.fit <= 0 and gap.holdout <= 0:
            out.append(
                f"It trailed buy-and-hold on Sharpe in both windows "
                f"({gap.fit:+.2f} then {gap.holdout:+.2f}). Overfitting is not "
                "the problem here - it has not beaten the index on "
                "risk-adjusted terms in either period."
            )
        elif gap and gap.worse:
            out.append(
                f"Its Sharpe advantage over buy-and-hold narrowed from "
                f"{gap.fit:+.2f} to {gap.holdout:+.2f}. Still ahead of the "
                "index on risk-adjusted terms, by less."
            )
        elif gap:
            out.append(
                f"It held its Sharpe advantage over buy-and-hold "
                f"({gap.fit:+.2f} to {gap.holdout:+.2f}). That is the "
                "comparison that survives a change of regime, and it is the "
                "one worth weighting."
            )

        # A holdout that matches the fit window too closely is more often a leak
        # than a triumph, and it is worth saying so before anyone celebrates.
        if cagr and cagr.fit > 0 and cagr.retained and 0.95 <= cagr.retained <= 1.05:
            out.append(
                "The two windows agree almost exactly, which is rarer than it "
                "looks. Check the split is real - overlapping sessions, a cache "
                "spanning both windows, or symbols chosen for the whole period "
                "will all produce this."
            )

        if self.holdout_years < 2:
            out.append(
                f"The holdout is only {self.holdout_years:.1f} years. That is "
                "likely one market mood, so passing it means less than it feels "
                "like."
            )

        if self.holdout and self.holdout.metrics:
            closed = self.holdout.metrics.closed_trades
            if closed < 30:
                out.append(
                    f"Only {closed} closed positions out of sample. That is too "
                    "few to separate an edge from luck in either direction."
                )

        bench = self.holdout.benchmark_metrics if self.holdout else None
        if bench and self.holdout.metrics:
            gap = self.holdout.metrics.total_return_pct - bench.total_return_pct
            if gap < 0:
                out.append(
                    f"On the holdout it still lost to buy-and-hold by "
                    f"{abs(gap):.1f} percentage points. Whatever the split says "
                    "about overfitting, this is the comparison that decides "
                    "whether to run it."
                )
        return out


class RevealLog:
    """Counts how many times each holdout has been looked at.

    Kept on disk rather than in memory because the erosion being tracked
    happens across sessions, over weeks - which is exactly when a person stops
    remembering how many times they have already peeked.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt or missing log must not stop a backtest. Undercounting
            # reveals is a smaller harm than refusing to run.
            return {}

    @staticmethod
    def key(holdout_start: date, holdout_end: date, symbols: list[str]) -> str:
        """Identifies one holdout.

        Includes the universe: the same dates over a different symbol set is a
        different test, and charging it against the same count would overstate
        how used up that particular holdout is.
        """
        # hashlib, not hash(): Python salts str hashing per process, so the
        # built-in would give the same holdout a different key on every run and
        # the count would never rise above one.
        digest = hashlib.sha256(
            ",".join(sorted(s.upper() for s in symbols)).encode("utf-8")
        ).hexdigest()[:8]
        return f"{holdout_start}:{holdout_end}:{len(symbols)}:{digest}"

    def count(self, key: str) -> int:
        entry = self._load().get(key)
        return int(entry.get("reveals", 0)) if isinstance(entry, dict) else 0

    def record(self, key: str, when: date) -> int:
        """Register a reveal and return the new count."""
        data = self._load()
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {"reveals": 0, "first": when.isoformat()}
        entry["reveals"] = int(entry.get("reveals", 0)) + 1
        entry["last"] = when.isoformat()
        data[key] = entry
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True),
                                 encoding="utf-8")
        except OSError:
            pass  # see _load: never fail a backtest over bookkeeping
        return entry["reveals"]


def run_split(provider, config, at: date | None = None,
              fit_fraction: float = DEFAULT_FIT_FRACTION,
              reveal: bool = False, log: RevealLog | None = None,
              today: date | None = None, progress=None) -> SplitResult:
    """Run the fit window, and the holdout only if explicitly asked for.

    The two windows are run as independent backtests, each starting from the
    same cash and each with its own benchmark. Continuing one portfolio across
    the boundary would carry the fit window's open positions - and its ending
    equity - into the holdout, so the holdout would be measuring the fit window
    as much as itself.
    """
    from dataclasses import replace

    from quantdesk.backtest import Backtester

    start, end = config.start, config.end
    if start is None or end is None:
        raise ValueError(
            "an out-of-sample split needs an explicit start and end; without "
            "them the window depends on whatever history the provider returns"
        )

    fit_end, holdout_start = split_window(start, end, at=at,
                                          fit_fraction=fit_fraction)
    split = SplitResult(fit_start=start, fit_end=fit_end,
                        holdout_start=holdout_start, holdout_end=end)

    split.fit = Backtester(
        provider, replace(config, start=start, end=fit_end)
    ).run(progress=progress)

    if not reveal:
        return split

    split.revealed = True
    if log is not None:
        key = log.key(holdout_start, end, config.symbols)
        # Counted before the run, not after: a reveal that is started and then
        # abandoned has still been seen if it printed anything, and the failure
        # mode to avoid is undercounting.
        split.reveals = log.record(key, today or date.today())
    else:
        split.reveals = 1

    split.holdout = Backtester(
        provider, replace(config, start=holdout_start, end=end)
    ).run(progress=progress)
    return split


def to_text(split: SplitResult, width: int = 78) -> str:
    """Render the split comparison for a terminal."""
    thin = "-" * width
    L = ["OUT-OF-SAMPLE SPLIT", thin,
         f"  Fit window    {split.fit_start} to {split.fit_end}",
         f"  Holdout       {split.holdout_start} to {split.holdout_end} "
         f"({split.holdout_years:.1f} years)"]

    if split.revealed:
        L.append(f"  Reveals       {split.reveals}"
                 + ("  <- each one costs some of what a holdout is for"
                    if split.reveals > 1 else ""))

    if not split.revealed or not split.holdout:
        L += ["", "  The holdout has not been run."]
        L += [""] + [f"  - {line}" for line in split.verdict()]
        return "\n".join(L)

    L += ["",
          f"  {'MEASURE':<18}{'FIT':>12}{'HOLDOUT':>12}{'CHANGE':>12}"]
    for d in split.degradations():
        mark = "  worse" if d.worse else ""
        L.append(
            f"  {d.measure:<18}{d.fit:>11,.2f}{d.suffix:<1}"
            f"{d.holdout:>11,.2f}{d.suffix:<1}"
            f"{d.change:>+11,.2f}{d.suffix:<1}{mark}"
        )

    gaps = split.benchmark_gaps()
    if gaps:
        L += ["",
              "  VERSUS BUY-AND-HOLD (strategy minus its own benchmark, "
              "per window)",
              f"  {'MEASURE':<18}{'FIT':>12}{'HOLDOUT':>12}{'CHANGE':>12}"]
        for d in gaps:
            mark = "  worse" if d.worse else ""
            L.append(
                f"  {d.measure:<18}{d.fit:>+11,.2f}{d.suffix:<1}"
                f"{d.holdout:>+11,.2f}{d.suffix:<1}"
                f"{d.change:>+11,.2f}{d.suffix:<1}{mark}"
            )
        L.append("  A positive number beat the index in that window. This is "
                 "the table")
        L.append("  to read when both windows improved: it takes the regime "
                 "out of both sides.")

    bench = split.holdout.benchmark_metrics
    if bench:
        L += ["",
              f"  Holdout buy-and-hold {bench.total_return_pct:+.2f}% "
              f"versus strategy {split.holdout.metrics.total_return_pct:+.2f}%"]

    L += ["", "  WHAT THE SPLIT SAYS", thin]
    L += [f"  - {line}" for line in split.verdict()]
    return "\n".join(L)
