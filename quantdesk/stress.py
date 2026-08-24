"""How the strategy behaved while the index was falling.

A backtest that spans one bull market cannot tell you whether a defensive
design is defensive or merely small. The headline drawdown comparison is worse
than uninformative: any strategy holding less equity loses less in a decline by
construction, and the number flatters it without saying whether it gave the
difference back on the way up.

So this module cuts the period into the index's own drawdown episodes and
scores both legs. The measure that decides it is the round trip - the
strategy's return from the index's peak to the day the index got back to that
peak. The index earns exactly 0% over that span by definition, so the
strategy's figure is what it added or cost you for the whole episode, entry
and exit included. Losing less on the way down and more on the way up nets out
here, where a max-drawdown column would show only the flattering half.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date

DEFAULT_MIN_DEPTH_PCT = 10.0
"""Below this the episode is noise, not a regime worth reporting separately."""


@dataclass(frozen=True)
class Episode:
    """One peak-to-trough-to-recovery cycle in the benchmark."""

    peak: date
    trough: date
    recovered: date | None
    benchmark_fall_pct: float
    strategy_fall_pct: float
    benchmark_rebound_pct: float | None
    strategy_rebound_pct: float | None
    strategy_round_trip_pct: float | None

    @property
    def spared_pct(self) -> float:
        """Percentage points of the fall the strategy avoided.

        Positive means it fell less than the index. On its own this proves
        nothing - see the module docstring - but it is the number people
        expect to see, and omitting it invites the reader to assume it was
        hidden because it was bad.
        """
        return self.strategy_fall_pct - self.benchmark_fall_pct

    @property
    def fall_days(self) -> int:
        return (self.trough - self.peak).days

    @property
    def episode_days(self) -> int | None:
        return (self.recovered - self.peak).days if self.recovered else None

    @property
    def helped(self) -> bool | None:
        """Whether the strategy came out of the whole episode ahead.

        Undefined while the index has not recovered: the episode is still
        running, and judging it now scores the half that has happened.
        """
        if self.strategy_round_trip_pct is None:
            return None
        return self.strategy_round_trip_pct > 0


class _Curve:
    """Date-indexed equity, tolerant of the two curves not lining up exactly."""

    def __init__(self, points: list[tuple[date, float]]):
        ordered = sorted(points)
        self.dates = [d for d, _ in ordered]
        self.values = [v for _, v in ordered]

    def __bool__(self) -> bool:
        return bool(self.dates)

    def at(self, when: date) -> float | None:
        """The last value on or before `when`.

        Carrying the previous session forward is right for a missing day and
        wrong for a date before the curve starts, which returns None rather
        than inventing a starting value.
        """
        i = bisect.bisect_right(self.dates, when) - 1
        return self.values[i] if i >= 0 else None


def _pct(curve: _Curve, start: date, end: date) -> float | None:
    a, b = curve.at(start), curve.at(end)
    if a is None or b is None or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def drawdown_episodes(
    benchmark: list[tuple[date, float]],
    strategy: list[tuple[date, float]],
    min_depth_pct: float = DEFAULT_MIN_DEPTH_PCT,
) -> list[Episode]:
    """Cut the period into the benchmark's drawdowns, deeper than the floor.

    Episodes are peak-to-peak and so cannot overlap. The last one may still be
    open at the end of the data, which is reported rather than dropped: an
    unrecovered decline is a real thing that happened.
    """
    bench, strat = _Curve(benchmark), _Curve(strategy)
    if not bench or not strat:
        return []

    episodes: list[Episode] = []
    peak_date, peak_value = bench.dates[0], bench.values[0]
    trough_date, trough_value = peak_date, peak_value

    def close(recovered: date | None) -> None:
        depth = (trough_value / peak_value - 1.0) * 100.0
        if depth > -min_depth_pct:
            return
        fall = _pct(strat, peak_date, trough_date)
        if fall is None:
            return
        rebound = bench_rebound = round_trip = None
        if recovered is not None:
            bench_rebound = _pct(bench, trough_date, recovered)
            rebound = _pct(strat, trough_date, recovered)
            round_trip = _pct(strat, peak_date, recovered)
        episodes.append(Episode(
            peak=peak_date, trough=trough_date, recovered=recovered,
            benchmark_fall_pct=depth, strategy_fall_pct=fall,
            benchmark_rebound_pct=bench_rebound, strategy_rebound_pct=rebound,
            strategy_round_trip_pct=round_trip,
        ))

    for when, value in zip(bench.dates[1:], bench.values[1:]):
        if value >= peak_value:
            close(when)
            peak_date, peak_value = when, value
            trough_date, trough_value = when, value
        elif value < trough_value:
            trough_date, trough_value = when, value

    close(None)  # whatever was still open when the data ran out
    return episodes


def verdict(episodes: list[Episode], min_depth_pct: float = DEFAULT_MIN_DEPTH_PCT
            ) -> list[str]:
    """Say what the episodes amount to, including when they amount to nothing."""
    if not episodes:
        return [
            f"The index never fell more than {min_depth_pct:.0f}% in this "
            "period, so there is nothing here to test a defensive design "
            "against. A drawdown figure from a window with no drawdowns in it "
            "is not evidence."
        ]

    out: list[str] = []
    judged = [e for e in episodes if e.helped is not None]
    unrecovered = [e for e in episodes if e.recovered is None]

    if not judged:
        out.append(
            "The index has not recovered its peak, so no episode here can be "
            "scored end to end yet. What the strategy avoided on the way down "
            "is only half the question."
        )
    else:
        helped = [e for e in judged if e.helped]
        out.append(
            f"{len(judged)} completed drawdown "
            f"{'episode' if len(judged) == 1 else 'episodes'} deeper than "
            f"{min_depth_pct:.0f}%. The index returns 0% peak to recovery by "
            f"definition; the strategy came out ahead in {len(helped)} of them."
        )
        worst = min(judged, key=lambda e: e.strategy_round_trip_pct)
        best = max(judged, key=lambda e: e.strategy_round_trip_pct)
        if len(helped) == len(judged):
            out.append(
                f"It was positive through every one, worst case "
                f"{worst.strategy_round_trip_pct:+.1f}%. That is the shape a "
                "genuinely defensive design has - and the reading to trust "
                "over any single-window drawdown comparison."
            )
        elif not helped:
            out.append(
                f"It lost money through all of them, best case "
                f"{best.strategy_round_trip_pct:+.1f}%. Falling less than the "
                "index and then failing to come back with it is not defence; "
                "it is a smaller position in the same trade."
            )
        else:
            out.append(
                f"Mixed: {best.strategy_round_trip_pct:+.1f}% at best, "
                f"{worst.strategy_round_trip_pct:+.1f}% at worst. Two or three "
                "episodes cannot separate a defensive design from a lucky one, "
                "so treat this as a direction rather than a finding."
            )

        gave_back = [
            e for e in judged
            if e.spared_pct > 0 and e.strategy_round_trip_pct is not None
            and e.strategy_round_trip_pct < 0
        ]
        if gave_back:
            out.append(
                f"{len(gave_back)} of them fell less than the index and still "
                "finished the episode down. That combination is what a max "
                "drawdown column cannot show you: the protection was real on "
                "the way down and was handed back on the way up."
            )

    if unrecovered:
        e = unrecovered[0]
        out.append(
            f"One episode is still open: the index peaked {e.peak} and was "
            f"{e.benchmark_fall_pct:.1f}% below it at the end of the data, "
            f"against the strategy's {e.strategy_fall_pct:+.1f}%. It cannot be "
            "scored until the index recovers."
        )
    return out


def to_text(episodes: list[Episode], width: int = 78,
            min_depth_pct: float = DEFAULT_MIN_DEPTH_PCT) -> str:
    """Render the stress table for a terminal."""
    thin = "-" * width
    L = ["WHEN THE INDEX FELL", thin]

    if episodes:
        L += [
            "  Each row is one index peak-to-recovery cycle. ROUND TRIP is the",
            "  strategy's return across the whole cycle, over which the index",
            "  earns 0% by definition - it is the number that decides this.",
            "",
            f"  {'INDEX PEAK':<12}{'FALL':>9}{'STRATEGY':>10}{'SPARED':>9}"
            f"{'ROUND TRIP':>12}{'DAYS':>7}",
        ]
        for e in episodes:
            trip = (f"{e.strategy_round_trip_pct:+.1f}%"
                    if e.strategy_round_trip_pct is not None else "open")
            days = str(e.episode_days) if e.episode_days is not None else "-"
            L.append(
                f"  {e.peak.isoformat():<12}{e.benchmark_fall_pct:>8.1f}%"
                f"{e.strategy_fall_pct:>+9.1f}%{e.spared_pct:>+8.1f}%"
                f"{trip:>12}{days:>7}"
            )
        L.append("")

    L += [f"  - {line}" for line in verdict(episodes, min_depth_pct)]
    return "\n".join(L)
