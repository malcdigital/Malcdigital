"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from quantdesk import __version__
from quantdesk.config import RISK_PROFILES, Settings, get_profile


def _c(text: str, code: str, enabled: bool = True) -> str:
    if not enabled or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return _c(t, "1")


def green(t: str) -> str:
    return _c(t, "32")


def red(t: str) -> str:
    return _c(t, "31")


def dim(t: str) -> str:
    return _c(t, "2")


def money(v: float) -> str:
    coloured = green if v > 0 else (red if v < 0 else str)
    return coloured(f"${v:+,.2f}") if v else f"${v:,.2f}"


def load_settings(args) -> Settings:
    settings = Settings.load(getattr(args, "home", None))
    if getattr(args, "risk", None):
        settings.risk_profile = args.risk
    if getattr(args, "provider", None):
        settings.data_provider = args.provider
    if getattr(args, "csv_dir", None):
        settings.csv_dir = str(args.csv_dir)
        settings.data_provider = "csv"
    if getattr(args, "offline", False):
        settings.data_provider = "synthetic"
        settings.news_enabled = True
    return settings


def _engine(settings: Settings, offline: bool = False, strict: bool = False):
    from quantdesk.data import get_provider
    from quantdesk.engine import TradingEngine
    from quantdesk.news.fetch import NewsFetcher

    provider = None
    if settings.data_provider == "csv":
        from quantdesk.data import get_provider

        provider = get_provider("csv", csv_dir=settings.bars_dir)
    elif strict:
        # Building the provider is not enough: yfinance imports cleanly and only
        # fails when it tries to fetch. Without an actual probe, a dead feed
        # yields an empty report at exit 0 - the silent failure --strict exists
        # to prevent. So fetch the benchmark and refuse to start if it is absent.
        from quantdesk.data.base import DataUnavailable
        from quantdesk.strategy.universe import BENCHMARK

        provider = get_provider(
            settings.data_provider, settings.cache_dir, allow_synthetic=False
        )
        try:
            probe = provider.history(BENCHMARK, 60)
        except Exception as exc:
            raise DataUnavailable(
                f"--strict: no live market data ({BENCHMARK} could not be "
                f"fetched: {exc}). Run 'quantdesk doctor' to diagnose."
            ) from exc
        if probe.empty:
            raise DataUnavailable(
                f"--strict: {BENCHMARK} returned no rows. "
                "Run 'quantdesk doctor' to diagnose."
            )
    return TradingEngine(
        settings, provider=provider, news_fetcher=NewsFetcher(offline=offline)
    )


# --- commands ---------------------------------------------------------------
def cmd_init(args) -> int:
    settings = load_settings(args)
    settings.starting_cash = args.cash
    settings.risk_profile = args.risk or settings.risk_profile
    if args.watchlist:
        settings.watchlist = [s.strip().upper() for s in args.watchlist.split(",") if s.strip()]
    settings.save()

    from quantdesk.portfolio.store import PortfolioStore

    store = PortfolioStore(settings.db_path)
    already = store.is_initialised()
    if already and not args.force:
        print(f"Account already exists at {settings.db_path}")
        print("Re-run with --force to wipe it and start over.")
        return 1
    store.initialise(settings.starting_cash, force=True)

    profile = settings.profile
    print(bold(f"\nQuantDesk initialised at {settings.home}"))
    print(f"  Starting play money : ${settings.starting_cash:,.2f}")
    print(f"  Risk profile        : {profile.label}")
    print(f"  {profile.description}\n")
    print(f"  Max position        : {profile.max_position_pct:.0%} of equity")
    print(f"  Risk per trade      : {profile.risk_per_trade_pct:.2%} of equity")
    print(f"  Max open positions  : {profile.max_positions}")
    print(f"  Stop distance       : {profile.atr_stop_mult:.1f} x ATR")
    print(f"  Profit targets      : {', '.join(f'{r:g}R' for r in profile.target_r_multiples)}")
    if settings.watchlist:
        print(f"  Watchlist           : {', '.join(settings.watchlist)}")
    print(dim("\nNext: quantdesk run    (executes a day and writes a report)"))
    return 0


def cmd_profiles(args) -> int:
    print()
    for profile in RISK_PROFILES.values():
        print(bold(f"{profile.label} ({profile.name})"))
        print(f"  {profile.description}")
        print(f"  position {profile.max_position_pct:.0%} max | "
              f"risk {profile.risk_per_trade_pct:.2%}/trade | "
              f"{profile.max_positions} slots | "
              f"stop {profile.atr_stop_mult:g}xATR | "
              f"targets {', '.join(f'{r:g}R' for r in profile.target_r_multiples)}")
        print(f"  hold up to {profile.max_hold_days}d | "
              f"vol ceiling {profile.max_annual_volatility:.0%} | "
              f"ETF target {profile.etf_target_pct:.0%}\n")
    return 0


def cmd_scan(args) -> int:
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))
    equity = engine.current_equity()

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print(dim(f"Scanning with the {settings.profile.label.lower()} profile "
              f"against ${equity:,.0f} equity..."))
    result = engine.recommender.scan(equity=equity, symbols=symbols, limit=args.limit)

    if result.used_synthetic_data:
        print(red("\n!! SIMULATED DATA - live prices unavailable; "
                  "these are generated series, not the real market."))

    print(bold(f"\n{len(result.recommendations)} idea(s) from {result.scanned} candidates\n"))
    for rec in result.recommendations:
        plan, sig = rec.plan, rec.signal
        print(bold(f"{rec.symbol}  {sig.score:.0f}/100  ({rec.confidence_label()})")
              + f"  {plan.setup} | {sig.trend.label}")
        print(f"  {rec.instrument.name[:60]}")
        for reason in sig.reasons[: (4 if not args.verbose else 8)]:
            print(dim(f"    - {reason}"))
        print(f"  {bold('Trade plan')} (reward:risk {plan.reward_risk:.1f}:1)")
        for line in plan.instructions():
            print(f"    {line}")
        for note in plan.notes:
            print(red(f"    ! {note}"))
        print()

    if args.verbose and result.rejected:
        print(dim("Why others were rejected:"))
        for reason, count in list(result.top_rejection_reasons.items())[:8]:
            print(dim(f"  {count:>3}x {reason}"))
    if result.errors and args.verbose:
        print(dim(f"\n{len(result.errors)} symbol(s) failed to load"))
    return 0


def cmd_analyze(args) -> int:
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))
    symbol = args.symbol.upper()

    from quantdesk.analysis import indicators as ind
    from quantdesk.analysis.candles import CandlestickScanner
    from quantdesk.analysis.trend import classify, find_levels
    from quantdesk.news.sentiment import aggregate_news_sentiment

    try:
        bars = engine.provider.history(symbol, 400)
    except Exception as exc:
        print(red(f"Could not load {symbol}: {exc}"))
        return 1

    enriched = ind.compute_all(bars)
    trend = classify(bars, enriched)
    last = enriched.iloc[-1]
    instrument = engine.provider.instrument(symbol)

    print(bold(f"\n{symbol} - {instrument.name}"))
    print(f"{instrument.asset_type.upper()} | {instrument.sector}")
    print(f"Last ${float(last['close']):,.2f}   "
          f"ATR ${float(last['atr14']):,.2f} ({float(last['atr_pct']):.1f}%)   "
          f"20d vol {float(last['volatility20']):.0%}")

    print(bold("\nTREND"))
    print(f"  {trend.label}  (score {trend.score:+.0f}, ADX {trend.adx:.0f})")
    for reason in trend.reasons:
        print(dim(f"    - {reason}"))
    print(f"  {trend.pct_from_52w_high:+.1f}% from the 52-week high, "
          f"{trend.pct_from_52w_low:+.1f}% from the low")
    if trend.is_choppy:
        print(red("    ! ADX below 20 - directionless. Breakouts fail here."))

    print(bold("\nCANDLESTICKS (last 10 sessions)"))
    patterns = CandlestickScanner().scan(bars, lookback=10)
    if not patterns:
        print(dim("  no significant patterns"))
    for p in sorted(patterns, key=lambda x: -x.index):
        colour = green if p.direction == "bullish" else (red if p.direction == "bearish" else dim)
        print(f"  {p.date.date()}  {colour(p.name):<28} strength {p.strength:.2f}")
        print(dim(f"      {p.explanation}"))

    print(bold("\nKEY LEVELS"))
    price = float(last["close"])
    for level in find_levels(bars):
        arrow = "above" if level.price > price else "below"
        print(f"  ${level.price:>10,.2f}  {level.kind:<11} "
              f"{level.touches} touches, {abs(level.distance_pct(price)):.1f}% {arrow}")

    if settings.news_enabled:
        print(bold("\nNEWS"))
        articles = engine.news.fetch(symbol, settings.news_lookback_days, 15)
        sentiment = aggregate_news_sentiment(symbol, articles)
        print(f"  {sentiment.summary_line}")
        if sentiment.is_synthetic:
            print(red("  ! placeholder headlines - live news was unavailable"))
        for title, score in sentiment.top_positive:
            print(green(f"    +{score:.2f} ") + title[:70])
        for title, score in sentiment.top_negative:
            print(red(f"    {score:.2f} ") + title[:70])

    print(bold("\nVERDICT"))
    from quantdesk.strategy.signals import score_symbol
    from quantdesk.strategy.universe import BENCHMARK

    try:
        bench = engine.provider.history(BENCHMARK, 400)
    except Exception:
        bench = None
    report = score_symbol(symbol, bars, settings.profile, bench,
                          asset_type=instrument.asset_type)
    print(f"  Composite score {report.score:.0f}/100 for a "
          f"{settings.profile.label.lower()} profile")
    if report.vetoes:
        print(red("  NOT actionable:"))
        for veto in report.vetoes:
            print(red(f"    - {veto}"))
    else:
        print(green("  Actionable. Run 'quantdesk scan' to get a sized trade plan."))
    print()
    return 0


def cmd_run(args) -> int:
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))
    outcome = engine.run_daily(
        max_new_ideas=args.ideas,
        execute=not args.dry_run,
        write_files=not args.no_files,
    )
    report = outcome.report
    print(report.to_text())
    if outcome.html_path:
        print(dim(f"\nHTML report: {outcome.html_path}"))

    if args.email or args.webhook:
        from quantdesk import notify

        if args.email:
            try:
                print(dim(notify.send_email(
                    f"QuantDesk {report.as_of.isoformat()} - "
                    f"${report.equity:,.0f} ({report.performance.total_return_pct:+.2f}%)",
                    report.to_text(), report.to_html(),
                )))
            except Exception as exc:
                print(red(f"email failed: {exc}"))
        if args.webhook:
            try:
                print(dim(notify.send_webhook({
                    "date": report.as_of.isoformat(),
                    "equity": round(report.equity, 2),
                    "return_pct": report.performance.total_return_pct,
                    "open_positions": len(report.portfolio.positions),
                    "new_ideas": [r.symbol for r in report.recommendations],
                    "activity": [str(e) for e in report.events],
                })))
            except Exception as exc:
                print(red(f"webhook failed: {exc}"))
    return 0


def cmd_fetch(args) -> int:
    """Download history to CSV so backtests run offline and reproducibly."""
    settings = load_settings(args)
    from quantdesk.data import get_provider
    from quantdesk.data.csv_files import save_bars
    from quantdesk.strategy.screener import load_symbols
    from quantdesk.strategy.universe import BENCHMARK, universe_for

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.symbols_file:
        symbols = load_symbols(args.symbols_file)
    else:
        symbols = universe_for(settings.profile.name)
    # The benchmark is always needed: without it there is nothing to compare a
    # backtest against, which is the one number that decides the result.
    if BENCHMARK not in symbols:
        symbols.append(BENCHMARK)

    out = Path(args.out).expanduser() if args.out else settings.bars_dir
    out.mkdir(parents=True, exist_ok=True)

    # Never write generated data into a directory meant to hold real history:
    # a backtest reading it would look real and mean nothing.
    provider = get_provider(
        args.source, settings.cache_dir, allow_synthetic=False
    )

    print(bold(f"\nFetching {len(symbols)} symbols into {out}"))
    print(dim(f"  source: {provider.name} | {args.years} years of daily bars\n"))

    saved = failed = 0
    lookback = int(args.years * 252)
    for index, symbol in enumerate(symbols, start=1):
        try:
            bars = provider.history(symbol, lookback)
        except Exception as exc:
            failed += 1
            print(red(f"  [{index}/{len(symbols)}] {symbol:<8} failed: "
                      f"{str(exc)[:60]}"))
            continue
        path = save_bars(bars, symbol, out)
        saved += 1
        print(dim(f"  [{index}/{len(symbols)}] {symbol:<8} {len(bars):>5} bars "
                  f"{bars.index[0].date()} to {bars.index[-1].date()}"))

    print()
    print(green(f"  saved {saved} symbol(s) to {out}"))
    if failed:
        print(red(f"  {failed} failed - they will simply be skipped by a backtest"))
    if saved:
        print(dim("\nBacktest against them with:"))
        print(dim(f"  quantdesk backtest --provider csv --csv-dir {out}"))
    return 0 if saved else 1


def cmd_backtest(args) -> int:
    """Replay the strategy over history and compare it to buy-and-hold."""
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))

    from quantdesk.backtest import Backtester, BacktestConfig
    from quantdesk.backtest_report import to_html, to_text
    from quantdesk.strategy.screener import load_symbols
    from quantdesk.strategy.universe import universe_for

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.symbols_file:
        symbols = load_symbols(args.symbols_file)
    else:
        symbols = universe_for(settings.profile.name)
    if args.max_symbols:
        symbols = symbols[: args.max_symbols]

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    config = BacktestConfig(
        symbols=symbols,
        start=start,
        end=end,
        starting_cash=args.cash,
        risk_profile=settings.profile.name,
        max_new_ideas=args.ideas,
        scan_every=args.scan_every,
    )

    print(dim(f"Backtesting {len(symbols)} symbols on the "
              f"{settings.profile.label.lower()} profile..."))
    print(dim("Loading history and precomputing indicators - this takes a moment.\n"))

    started = time.time()

    def progress(done: int, total: int, equity: float) -> None:
        elapsed = time.time() - started
        remaining = (elapsed / max(done, 1)) * (total - done)
        print(dim(f"  {done}/{total} sessions  equity ${equity:,.0f}  "
                  f"~{remaining:.0f}s left"), flush=True)

    result = Backtester(engine.provider, config).run(progress=progress)
    print()
    print(to_text(result))

    if not args.no_files:
        settings.ensure_dirs()
        reports = settings.reports_dir

        html_path = reports / "backtest.html"
        html_path.write_text(to_html(result), encoding="utf-8")

        # The terminal output scrolls away; without a text copy the only record
        # is HTML, which is awkward to read back or paste anywhere.
        text_path = reports / "backtest.txt"
        text_path.write_text(to_text(result), encoding="utf-8")

        # The backtest's own database is temporary, so without this the trade
        # log dies with the run and re-examining it means replaying everything.
        trades_path = reports / "backtest-trades.csv"
        _write_trade_log(result.trades, trades_path)

        print(dim(f"\nHTML report:  {html_path}"))
        print(dim(f"Text report:  {text_path}"))
        print(dim(f"Trade log:    {trades_path}"))
    return 0


def _write_trade_log(trades, path) -> None:
    import csv

    fields = ["trade_date", "symbol", "action", "direction", "setup", "shares",
              "price", "commission", "realized_pnl", "r_multiple",
              "holding_days", "stop_trailed", "position_id", "reason"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for trade in sorted(trades, key=lambda t: (t.trade_date, t.id or 0)):
            writer.writerow([
                trade.trade_date.isoformat(), trade.symbol, trade.action,
                trade.direction, trade.setup, trade.shares,
                f"{trade.price:.4f}", f"{trade.commission:.2f}",
                "" if trade.realized_pnl is None else f"{trade.realized_pnl:.2f}",
                "" if trade.r_multiple is None else f"{trade.r_multiple:.4f}",
                "" if trade.holding_days is None else trade.holding_days,
                int(bool(trade.stop_trailed)), trade.position_id or "",
                trade.reason,
            ])


def cmd_serve(args) -> int:
    """Run the local dashboard."""
    settings = load_settings(args)
    if getattr(args, "manual", False):
        settings.execution_mode = "manual"
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))

    from quantdesk.web import serve

    serve(engine, host=args.host, port=args.port, open_browser=args.open)
    return 0


def cmd_approve(args) -> int:
    """Approve or reject queued ideas from the terminal."""
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))

    pending = engine.store.proposals("pending")
    if not pending:
        print(dim("Nothing queued for approval."))
        return 0

    if args.list or not (args.approve or args.reject):
        print(bold(f"\n{len(pending)} idea(s) awaiting a decision\n"))
        for p in pending:
            side = "SHORT" if p.is_short else "LONG"
            print(bold(f"  #{p.id}  {p.symbol}  {side}  {p.score:.0f}/100")
                  + f"  {p.setup}  expires {p.expires_date}")
            if p.proxy_for:
                print(dim(f"      bearish view on {p.proxy_for} via inverse ETF"))
            for line in p.instruction_lines[:3]:
                print(f"      {line}")
            print()
        print(dim("Approve with:  quantdesk approve --approve <id>"))
        print(dim("Reject with:   quantdesk approve --reject <id>"))
        return 0

    for pid in args.approve or []:
        proposal, event = engine.approve_proposal(pid)
        if proposal is None:
            print(red(f"  #{pid} is not pending"))
        else:
            print(green(f"  approved #{pid} {proposal.symbol}") + f" - {event.detail}")
    for pid in args.reject or []:
        proposal = engine.reject_proposal(pid)
        print(red(f"  #{pid} is not pending") if proposal is None
              else dim(f"  skipped #{pid} {proposal.symbol}"))
    return 0


def cmd_doctor(args) -> int:
    """Verify this machine can actually reach live market data."""
    from quantdesk.diagnostics import run_diagnostics

    print(bold("\nQuantDesk preflight"))
    print(dim("Checking whether this machine gets real market data...\n"))

    diagnosis = run_diagnostics(include_news=not args.skip_news)

    for check in diagnosis.checks:
        mark = green("  ok  ") if check.ok else red(" FAIL ")
        print(f"{mark} {check.name:<30} {check.detail}")
        if check.fix:
            print(dim(f"         -> {check.fix}"))

    print()
    if diagnosis.live_data_available:
        print(green(bold("Live market data is available on this machine.")))
        print(dim("Run with --strict to guarantee reports never use generated data:"))
        print(dim("  quantdesk run --strict"))
        return 0

    print(red(bold("NO LIVE MARKET DATA.")))
    print("Every price source failed, so runs would use GENERATED data")
    print("(labelled SIMULATED PRICE DATA in reports). Fix the failures above,")
    print("or use --strict to make the desk refuse to start instead.")
    return 1


def cmd_schedule(args) -> int:
    """Print (or install) a cron entry so the desk runs itself each weekday."""
    import shutil
    import subprocess

    settings = load_settings(args)
    python = sys.executable
    home_flag = f" --home {settings.home}" if str(settings.home) else ""
    command = (
        f"{python} -m quantdesk.cli{home_flag} run --ideas {args.ideas}"
        f" >> {settings.home / 'daily.log'} 2>&1"
    )
    # Weekdays only, after the US close (default 16:30 local time).
    hour, _, minute = args.at.partition(":")
    entry = f"{int(minute or 0)} {int(hour)} * * 1-5 {command}"

    print(bold("\nDaily automation"))
    print(f"  Runs weekdays at {args.at} local time.")
    print(f"  Report lands in {settings.reports_dir / 'latest.html'}")
    print(f"  Log: {settings.home / 'daily.log'}\n")
    print(dim("cron entry:"))
    print(f"  {entry}\n")

    if not args.install:
        print(dim("Add it with:  quantdesk schedule --install"))
        print(dim("Or paste it yourself:  crontab -e"))
        return 0

    if not shutil.which("crontab"):
        print(red("crontab is not available on this system."))
        print("On macOS you may prefer launchd; on Windows, Task Scheduler.")
        return 1

    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = [
        line for line in existing.stdout.splitlines()
        if "quantdesk.cli" not in line  # replace any previous entry
    ]
    lines.append(entry)
    result = subprocess.run(
        ["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True
    )
    if result.returncode != 0:
        print(red(f"could not install: {result.stderr.strip()}"))
        return 1
    print(green("Installed. Remove it later with: crontab -e"))
    return 0


def cmd_status(args) -> int:
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))
    portfolio = engine.store.load_portfolio()

    bars = engine._bars_for(portfolio.symbols)
    prices = engine._latest_prices(bars)
    equity = portfolio.total_equity(prices)
    pnl = equity - portfolio.starting_cash

    header = bold(f"\nEquity ${equity:,.2f}   ") + money(pnl)
    if portfolio.starting_cash:
        header += f"  ({pnl / portfolio.starting_cash * 100:+.2f}%)"
    print(header)
    print(f"Cash ${portfolio.cash:,.2f} | "
          f"{len(portfolio.positions)} position(s) | "
          f"{settings.profile.label} risk\n")

    if not portfolio.positions:
        print(dim("No open positions."))
    else:
        print(f"  {'SYM':<7}{'QTY':>5}{'ENTRY':>10}{'LAST':>10}{'P&L':>12}"
              f"{'%':>8}{'R':>7}{'STOP':>10}{'DAYS':>6}")
        for p in portfolio.positions:
            price = prices.get(p.symbol, p.entry_price)
            print(f"  {p.symbol:<7}{p.shares:>5}{p.entry_price:>10,.2f}{price:>10,.2f}"
                  f"{p.unrealized_pnl(price):>+12,.2f}{p.unrealized_pct(price):>+8.1f}"
                  f"{p.r_multiple(price):>+7.2f}{p.stop_price:>10,.2f}"
                  f"{p.days_held():>6}")

    pending = engine.store.pending_orders()
    if pending:
        print(bold(f"\nWorking orders ({len(pending)})"))
        for o in pending:
            trigger = f"@ ${o.trigger_price:,.2f}" if o.trigger_price else "market-on-open"
            print(f"  {o.symbol:<7} {o.order_type:<7} x{o.shares:<5} {trigger}"
                  f"   expires {o.expires_date}")
    print()
    return 0


def cmd_trades(args) -> int:
    """Break down how closed trades ended."""
    settings = load_settings(args)
    from quantdesk.analysis.trades import analyze_trades, to_text
    from quantdesk.portfolio.store import PortfolioStore

    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            # A mistyped path is the likeliest way to get here; a traceback
            # says the same thing at ten times the length.
            print(f"No trade log at {path}. `backtest` writes one to "
                  f"{settings.reports_dir / 'backtest-trades.csv'}.")
            return 2
        trades = _read_trade_log(path)
        print(dim(f"Reading {len(trades)} trades from {path}"))
    else:
        store = PortfolioStore(settings.db_path)
        trades = store.trades(limit=100_000)
    analysis = analyze_trades(trades)
    if not analysis.closed:
        print(dim("No closed trades yet - nothing to break down."))
        return 0
    print()
    print(to_text(analysis))
    print()
    return 0


def _read_trade_log(path):
    """Read back a trade log written by `backtest`."""
    import csv
    from datetime import date as _date

    from quantdesk.portfolio.store import Trade

    def maybe_float(value):
        return float(value) if value not in ("", None) else None

    def maybe_int(value):
        return int(value) if value not in ("", None) else None

    out = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out.append(Trade(
                symbol=row["symbol"], action=row["action"],
                shares=int(row["shares"]), price=float(row["price"]),
                trade_date=_date.fromisoformat(row["trade_date"]),
                commission=float(row["commission"] or 0.0),
                reason=row["reason"], realized_pnl=maybe_float(row["realized_pnl"]),
                position_id=maybe_int(row["position_id"]),
                r_multiple=maybe_float(row["r_multiple"]),
                holding_days=maybe_int(row["holding_days"]),
                stop_trailed=bool(int(row["stop_trailed"] or 0)),
                direction=row["direction"] or "long", setup=row["setup"] or "",
            ))
    return out


def cmd_history(args) -> int:
    settings = load_settings(args)
    from quantdesk.portfolio.store import PortfolioStore

    store = PortfolioStore(settings.db_path)
    trades = store.trades(limit=args.limit)
    if not trades:
        print(dim("No trades recorded yet."))
        return 0
    print(bold(f"\n{'DATE':<12}{'SYM':<7}{'ACTION':<7}{'QTY':>5}{'PRICE':>10}{'P&L':>12}  REASON"))
    for t in trades:
        pnl = f"{t.realized_pnl:+,.2f}" if t.realized_pnl is not None else ""
        print(f"{t.trade_date.isoformat():<12}{t.symbol:<7}{t.action:<7}{t.shares:>5}"
              f"{t.price:>10,.2f}{pnl:>12}  {dim(t.reason[:44])}")
    print()
    return 0


def cmd_backfill(args) -> int:
    """Replay the strategy day by day to build up history quickly."""
    settings = load_settings(args)
    engine = _engine(settings, getattr(args, "offline", False),
                     getattr(args, "strict", False))
    start = date.today() - timedelta(days=args.days)
    print(dim(f"Replaying {args.days} sessions from {start}...\n"))

    sessions = []
    current = start
    while current <= date.today():
        if current.weekday() < 5:  # weekdays only
            sessions.append(current)
        current += timedelta(days=1)

    # A full-universe scan per session takes seconds, so a silent multi-minute
    # wait looks like a hang. Report progress and a running estimate instead.
    import time

    started = time.time()
    for index, session in enumerate(sessions, start=1):
        engine.run_daily(as_of=session, max_new_ideas=args.ideas, write_files=False)
        elapsed = time.time() - started
        remaining = elapsed / index * (len(sessions) - index)
        print(dim(f"  [{index}/{len(sessions)}] {session}  "
                  f"~{remaining:.0f}s remaining"), flush=True)
    runs = len(sessions)

    outcome = engine.run_daily(max_new_ideas=args.ideas)
    print(outcome.report.to_text())
    print(dim(f"\nReplayed {runs} sessions."))
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    """Accept the global flags after the subcommand too.

    ``quantdesk init --risk aggressive`` is what anyone would naturally type, but
    argparse only accepts parent options before the subcommand. SUPPRESS defaults
    mean an omitted flag here leaves whatever the parent parsed intact, instead of
    silently overwriting it with None.
    """
    p.add_argument("--home", default=argparse.SUPPRESS,
                   help="data directory (default ~/.quantdesk)")
    p.add_argument("--risk", choices=sorted(RISK_PROFILES), default=argparse.SUPPRESS,
                   help="risk profile")
    p.add_argument("--provider",
                   choices=["auto", "yahoo", "stooq", "csv", "synthetic"],
                   default=argparse.SUPPRESS, help="market data source")
    p.add_argument("--offline", action="store_true", default=argparse.SUPPRESS,
                   help="use generated data and headlines - no network calls")
    p.add_argument("--strict", action="store_true", default=argparse.SUPPRESS,
                   help="refuse to run on generated data - real market data only")
    p.add_argument("--csv-dir", default=argparse.SUPPRESS,
                   help="directory of <SYMBOL>.csv files (with --provider csv)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantdesk",
        description="Paper-trading research desk: candlestick, trend and news "
                    "analysis with risk-tiered trade plans.",
    )
    parser.add_argument("--version", action="version", version=f"quantdesk {__version__}")
    parser.add_argument("--home", help="data directory (default ~/.quantdesk)")
    parser.add_argument("--risk", choices=sorted(RISK_PROFILES),
                        help="override the risk profile for this command")
    parser.add_argument("--provider",
                        choices=["auto", "yahoo", "stooq", "csv", "synthetic"],
                        help="market data source")
    parser.add_argument("--offline", action="store_true",
                        help="use generated data and headlines - no network calls")
    parser.add_argument("--strict", action="store_true",
                        help="refuse to run on generated data - real market data only")
    parser.add_argument("--csv-dir",
                        help="directory of <SYMBOL>.csv files (with --provider csv)")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the play-money account")
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--watchlist", help="comma-separated extra symbols")
    p.add_argument("--force", action="store_true", help="wipe an existing account")
    _add_common(p)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("profiles", help="explain the risk levels")
    _add_common(p)
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("scan", help="find trade ideas with full instructions")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--symbols", help="only scan these comma-separated symbols")
    p.add_argument("-v", "--verbose", action="store_true")
    _add_common(p)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("analyze", help="deep dive on one symbol")
    p.add_argument("symbol")
    _add_common(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("run", help="run one trading day and print the report")
    p.add_argument("--ideas", type=int, default=5)
    p.add_argument("--dry-run", action="store_true", help="analyse without trading")
    p.add_argument("--no-files", action="store_true")
    p.add_argument("--email", action="store_true",
                   help="email the report (needs QUANTDESK_SMTP_* env vars)")
    p.add_argument("--webhook", action="store_true",
                   help="POST a summary to QUANTDESK_WEBHOOK_URL")
    _add_common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("fetch",
                       help="download history to CSV for offline backtesting")
    p.add_argument("--symbols", help="comma-separated symbols")
    p.add_argument("--symbols-file", help="newline-separated symbol list")
    p.add_argument("--out", help="output directory (default ~/.quantdesk/bars)")
    p.add_argument("--years", type=float, default=6.0,
                   help="years of history to request (default 6)")
    p.add_argument("--source", default="auto",
                   choices=["auto", "yahoo", "stooq"],
                   help="where to fetch from; generated data is never written")
    _add_common(p)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("backtest",
                       help="replay the strategy over history vs buy-and-hold")
    p.add_argument("--symbols", help="comma-separated symbols to test")
    p.add_argument("--symbols-file", help="newline-separated symbol list")
    p.add_argument("--max-symbols", type=int,
                   help="cap the universe (runtime scales with it)")
    p.add_argument("--start", help="YYYY-MM-DD")
    p.add_argument("--end", help="YYYY-MM-DD")
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--ideas", type=int, default=4)
    p.add_argument("--scan-every", type=int, default=1,
                   help="sessions between idea scans; positions are still "
                        "managed daily. Raise it to trade fidelity for speed.")
    p.add_argument("--no-files", action="store_true")
    _add_common(p)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("serve", help="run the local dashboard with charts")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 to reach it from your phone on the same Wi-Fi. "
                        "There is no authentication: anyone who can reach the "
                        "port can approve trades. Trusted networks only.")
    p.add_argument("--manual", action="store_true",
                   help="queue ideas for approval instead of placing them")
    p.add_argument("--open", action="store_true", help="open a browser")
    _add_common(p)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("approve", help="review queued ideas from the terminal")
    p.add_argument("--approve", type=int, nargs="*", metavar="ID")
    p.add_argument("--reject", type=int, nargs="*", metavar="ID")
    p.add_argument("--list", action="store_true")
    _add_common(p)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("doctor", help="check this machine can reach live market data")
    p.add_argument("--skip-news", action="store_true", help="only test price feeds")
    _add_common(p)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("schedule", help="run the desk automatically every weekday")
    p.add_argument("--at", default="16:30", help="local time, HH:MM (default 16:30)")
    p.add_argument("--ideas", type=int, default=5)
    p.add_argument("--install", action="store_true", help="write the cron entry")
    _add_common(p)
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("status", help="show the portfolio right now")
    _add_common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("trades",
                       help="break down how closed trades ended, and why")
    p.add_argument("--file",
                   help="read a trade log written by `backtest` instead of the "
                        "live portfolio")
    _add_common(p)
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("history", help="list recorded trades")
    p.add_argument("--limit", type=int, default=40)
    _add_common(p)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("backfill", help="replay past sessions to build history")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--ideas", type=int, default=5)
    _add_common(p)
    p.set_defaults(func=cmd_backfill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from quantdesk.data.base import DataUnavailable

    try:
        return args.func(args)
    except DataUnavailable as exc:
        print(red(f"\nMarket data unavailable: {exc}"))
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
