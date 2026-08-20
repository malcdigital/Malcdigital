# QuantDesk

A paper-trading research desk. It reads candlesticks and trends, weighs the news
around a stock, ranks ideas against your chosen risk level, tells you exactly
when to get in and out, and then trades them with play money and reports back
every day.

It trades both directions, scales exposure to the market regime, and comes with
a local dashboard where you can see the charts and approve each trade yourself.

> **Play money only.** No real orders, no real account. Read
> [DISCLAIMER.md](DISCLAIMER.md) before you do anything else.

---

## Quick start

```bash
git clone <this repo> && cd Malcdigital
pip install -r requirements.txt

python -m quantdesk.cli doctor                                  # confirm live data works
python -m quantdesk.cli init --cash 100000 --risk moderate
python -m quantdesk.cli run --strict                            # real market data only
python -m quantdesk.cli serve                                   # dashboard at localhost:8000
```

**Always run `doctor` first.** The desk is built to keep working when the
network does not, by falling back to generated prices — right for a demo, wrong
to discover a month into "real" paper trading. `doctor` answers one question
plainly: is this machine actually getting live market data?

```
  ok   Python version                 3.12.4 on Darwin
  ok   package: yfinance              v0.2.51
  ok   Yahoo Finance (live prices)    SPY closed $571.34 on 2026-08-19 (30 bars, 1d old)
  ok   Stooq (fallback prices)        SPY closed $571.34 on 2026-08-19
  ok   News feed                      18 live articles from Yahoo Finance (newest 3h old)
  ok   Resolved data source           'auto' resolves to: yahoo

Live market data is available on this machine.
```

Then `--strict` guarantees it: it fetches the benchmark before starting and
**refuses to run** (exit code 2) rather than produce a report about a market
that does not exist. Without it, a dead feed silently yields generated prices —
labelled in the report, but easy to miss.

`run` executes one trading day and prints a full report. To have it run itself
every weekday:

```bash
python -m quantdesk.cli schedule --install     # weekdays at 16:30 local
```

The scheduled job inherits whatever flags you pass, so add `--strict` there too
if you never want a cron run quietly falling back to generated data.

Try it without touching the network at all (uses clearly-labelled generated
data, good for kicking the tyres):

```bash
python -m quantdesk.cli run --offline
```

---

## What it actually does

### 1. Reads the chart

**18 candlestick patterns**, detected geometrically rather than by eye — body
size, shadow length and overlap, each normalised against the bar's range and
recent ATR, so the same rules work on a \$9 stock and a \$600 one.

Hammer · Hanging Man · Inverted Hammer · Shooting Star · Doji · Marubozu ·
Bullish/Bearish Engulfing · Piercing Line · Dark Cloud Cover · Bullish/Bearish
Harami · Tweezer Top/Bottom · Morning Star · Evening Star · Three White
Soldiers · Three Black Crows

Crucially, **context decides meaning**. The identical shape is a bullish hammer
after a decline and a bearish hanging man after a rally, and the scanner refuses
to fire in the wrong context. Each detection carries a strength score, so a
textbook engulfing outranks a marginal one.

**Trend** is judged from four independent angles, because any one alone is easy
to fool:

| Angle | Question it answers |
|---|---|
| Moving-average stack | Are price, 20, 50 and 200 lined up in order? |
| ADX | Is there directional strength, or is it drifting? |
| Regression slope | Which way is the 20-day best-fit line pointing? |
| Swing structure | Higher highs and higher lows, or lower ones? |

Agreement across all four is a real trend. Disagreement is chop — and when ADX
is below 20 the desk **refuses breakout entries entirely**, because breakouts
fail in directionless markets.

It also finds support and resistance by clustering swing pivots, keeping the
touch count (a level tested three times means far more than one tested once).

### 2. Reads the news

Headlines are scored with a **financial** lexicon, not a general-purpose one —
"plunge" and "beats estimates" carry weight in markets that a generic model
misses. Three refinements that matter in practice:

- **Negation is clause-scoped.** In *"not profitable and warns of weak demand"*,
  the "not" governs "profitable" only. Let it leak across the conjunction and it
  flips "warns" positive and the sentence reads neutral — which is exactly
  backwards.
- **Modifiers invert nouns.** *"weak demand"* and *"slowing growth"* are bearish,
  even though "demand" and "growth" are positive words on their own. So is
  *"profit fell"* — a positive noun with a falling verb.
- **Intensifiers scale, on both sides.** *"rose sharply"* and *"sharply higher"*
  both register; *"rose slightly"* is damped.

Stories are then combined with recency weighting, so last night's earnings miss
outweighs a puff piece from a week ago.

### 3. Ranks ideas against your risk level

Six weighted components produce a 0–100 score: trend (30%), candlesticks (15%),
momentum (15%), news (15%), relative strength vs SPY (15%) and volume
confirmation (10%).

Then **hard vetoes** apply. These are not penalties — a candidate failing any of
them is not traded, however good the rest looks:

- the trend is down (the desk does not buy falling markets)
- volatility exceeds your tier's ceiling
- dollar volume is below the liquidity floor
- ADX < 20 on a breakout setup
- the composite score is under your tier's threshold

Survivors are diversified before selection: sector caps and an ETF/stock mix,
because ten correlated ideas are really one position wearing ten hats.

### 4. Tells you exactly when to get in and out

Every idea comes with a complete, executable plan — this is the part most
screeners leave out:

```
1. ENTRY - BUY STOP at $61.74 for 153 shares ($9,446, 9.4% of equity).
   Condition: Only if price trades above $61.74 (the 20-day high). If it
   never triggers, there is no trade - do not chase.
2. STOP LOSS - place immediately at $56.84 (-7.9%). Risking $750.
   Why here: 2.5 x ATR ($1.96) below entry - far enough that ordinary daily
   noise will not eject you.
3. TARGET - Sell 76 shares (50%) at $71.54 (+2.0R)
4. TARGET - Sell 76 shares (50%) at $81.34 (+4.0R)
5. TRAIL - Once the trade is up 1.25R ($67.86), move the stop to breakeven,
   then trail it 3.00 x ATR below the highest close reached. Never move a
   stop away from price.
6. TIME STOP - if the trade has not reached the first target within 60
   trading days, close it and free the capital.
7. EXIT EARLY IF - a daily close back below the 50-day moving average; a
   daily close below the stop (exit on the close, do not wait); price falls
   back inside the breakout range within two sessions.
```

Stops are set from **volatility and structure**, never a round percentage.
Position size is whichever is smaller: the share count that risks exactly your
per-trade budget if the stop hits, or your maximum position cap. The plan tells
you which constraint bound.

### 5. Trades it and reports daily

Each `run` advances the account one session: manage open positions (stops,
targets, trailing, time stops), fill or expire working orders, scan for new
ideas, place tomorrow's orders, snapshot equity, write the report.

Reports land in `~/.quantdesk/reports/` as text and as a self-contained HTML
page (`latest.html`) that works in light and dark mode.

---

## Backtesting

The only way to find out whether any of this works — and the easiest thing in
quantitative finance to get flatteringly wrong.

```bash
quantdesk backtest --symbols SPY,QQQ,AAPL,MSFT,NVDA --scan-every 2
quantdesk backtest --max-symbols 40 --start 2019-01-01
```

```
                             STRATEGY   BUY & HOLD
  Total return                 28.07%      229.88%
  CAGR                          6.67%       36.56%
  Max drawdown                 -6.32%      -20.26%
  Sharpe                        1.47         1.63

  Versus benchmark           -201.81%
                             ^ the number that decides it
```

Three commitments keep it honest:

**No look-ahead.** Each session sees only bars dated on or before that day. The
test for this is direct: run the same window twice with different end dates, and
the overlapping equity must be identical to the cent. If a signal could see the
future, extending the end would change the past.

**The same code as live.** Scoring, sizing, plan construction and execution all
run through the production path. A backtest with its own simplified fill logic
measures the simplified logic, not the strategy you would actually run.

**A benchmark, always.** Absolute return means nothing alone — beating cash
while losing to buy-and-hold is a losing strategy that looks like a winning one.
The verdict says so in those words when it happens.

The verdict is written to disappoint where warranted: it leads with sample size,
flags a window too short to span more than one regime, and pairs every
favourable reading with the reason it might be wrong. A good backtest number
believed is more dangerous than a bad one.

**News is off during backtests.** Historical headlines are not available from
the free feeds, and scoring today's news against a 2019 bar would be look-ahead
of the worst kind. Sentiment scores neutral throughout, so a backtest measures
the technical rules only.

Runtime scales with universe × sessions. Roughly 12 symbols over 1,000 sessions
takes about a minute; `--scan-every 5` scans weekly while still managing
positions daily, cutting it by most of that.

## The dashboard

```bash
quantdesk serve                 # http://localhost:8000
quantdesk serve --manual        # queue ideas for your approval
quantdesk serve --host 0.0.0.0  # reach it from your phone (read the warning)
```

Four pages: an overview with the equity curve and open risk, an ideas queue, your
positions, and the trade history. Each symbol has its own page with a candlestick
chart, moving averages, support and resistance, and every detected pattern marked
on the bar it occurred on.

Charts are server-rendered SVG. There is no CDN and no JavaScript, so the
dashboard works with your machine offline — which matters, because that is
exactly when the desk still runs but a charting bundle would not load.

**It has no authentication.** Bound to localhost that is fine. `--host 0.0.0.0`
makes it reachable from your phone on the same Wi-Fi, and from everyone else on
that network too — anyone who can reach the port can approve trades. Trusted
networks only.

## Deciding trades yourself

Set `execution_mode` to `manual` (or pass `--manual`) and nothing reaches the
broker until you approve it. Each idea shows the chart, the reasoning and the
full plan, then waits:

```
NVDA   LONG                                    78/100
breakout · 153 shares · risk $750 · reward:risk 3.0:1

1. ENTRY - BUY STOP at $61.74 for 153 shares...
2. STOP LOSS - place immediately at $56.84...

        [ Approve ]        [ Skip ]
```

A proposal freezes the whole plan rather than pointing at one, so approving
tomorrow acts on exactly what you reviewed today. Approving twice places one
order, not two. Ideas expire after three days, because a stale setup is not the
setup any more.

From the terminal instead:

```bash
quantdesk approve --list
quantdesk approve --approve 3 --reject 5
```

## Trading both directions

The desk was long-only at first, which meant sitting in cash through every
downtrend — roughly half of market conditions. It now takes the short side too.

Scoring picks a direction from the trend, then reads the same evidence from that
side: a short's score is the bullish reading inverted, not a second rulebook that
could drift out of step. Entry, stop, targets and the trailing stop all mirror.

Shorts are treated as more dangerous, because they are:

| | Long | Short |
|---|---|---|
| Risk budget | full | 55–75% of it |
| Concurrent positions | up to 12 | 2–5 |
| Loss if it goes wrong | capped at the position | theoretically unlimited |

Conservative never shorts at all. Where a profile prefers it, a bearish view on
an index is expressed by **buying a liquid inverse ETF** (SPY → SH, QQQ → PSQ)
— something a cash account can actually hold, with the loss capped at what you
put in.

## Market regime and sector rotation

Grading signals in isolation is how a book ends up fully invested at a top: every
name still looks fine on its own chart while the market underneath them rolls
over.

The benchmark's own regime — 200- and 50-day averages, trend slope, drawdown from
the high, realised volatility — scales position sizing:

| Regime | Long exposure | Short exposure |
|---|---|---|
| Bull | 100% | 25% |
| Correction | 55% | 75% |
| Bear | 20% | 100% |

Scaled, not switched. A binary gate whipsaws around the 200-day line; scaling
steps risk down as conditions deteriorate without betting everything on one
close.

Sectors are ranked by relative strength and fed in as a scoring component, so a
decent name in the weakest sector is penalised rather than treated as equal to
one in the strongest.

## Multi-timeframe confirmation

A daily chart prints a clean breakout about as often in a market grinding lower
on the weekly as in one genuinely advancing. A conflicting weekly trend now
**vetoes** the trade rather than merely docking its score.

The cost is real: fewer trades, and slightly later entries, because a weekly bar
confirms after the daily one. Turn it off with `multi_timeframe: false`.

Thin history is neutral, never a rejection — otherwise absence of evidence reads
as evidence against and every recently listed name is permanently untradeable.

## Screening the wider market

The curated list is fast but structurally blind: it can only surface names
someone thought to list.

```json
{"universe": "wide", "symbols_file": "/path/to/my-symbols.txt"}
```

Screening is staged. A cheap pass on price, dollar volume, history depth and
volatility rejects most candidates using column arithmetic alone, before any
indicator or pattern work is paid for — on the bundled list, 396 symbols screened
in about 3 seconds, of which ~319 survive to full analysis.

A hand-checked list of ~396 liquid US listings ships as a starting point, not a
claim to be the whole market. Point `--symbols-file` at your own list to replace
it; a CSV export works, since the first field is used.

## Risk levels

```bash
python -m quantdesk.cli profiles
```

| | Conservative | Moderate | Aggressive |
|---|---|---|---|
| Max position | 8% | 12% | 18% |
| Risk per trade | 0.40% | 0.75% | 1.25% |
| Open positions | 8 | 10 | 12 |
| Cash floor | 25% | 15% | 5% |
| Stop distance | 3.0 × ATR | 2.5 × ATR | 2.0 × ATR |
| Targets | 2R, 3.5R | 2R, 4R | 1.5R, 3R, 5R |
| Max hold | 120 days | 60 days | 30 days |
| Volatility ceiling | 35% | 55% | 95% |
| ETF share of book | 70% | 45% | 25% |
| Shorting | never | yes | yes |
| Max shorts | – | 3 | 5 |
| Short risk budget | – | 55% | 75% |
| Bearish view via | inverse ETF | inverse ETF | direct short |

"Risk per trade" is the fraction of equity you lose if the stop is hit — the
number that actually determines position size.

---

## Commands

```bash
quantdesk doctor                   # can this machine reach live market data?
quantdesk init --cash 100000 --risk moderate --watchlist NVDA,AMD
quantdesk run --strict             # one trading day + report, real data only
quantdesk backtest --max-symbols 20   # test the rules against history
quantdesk serve                    # dashboard with charts at localhost:8000
quantdesk approve --list           # review queued ideas in the terminal
quantdesk run --email --webhook    # and deliver it
quantdesk scan --limit 5 -v        # ideas only, no trading
quantdesk analyze NVDA             # deep dive on one symbol
quantdesk status                   # positions and working orders
quantdesk history                  # the trade log
quantdesk backfill --days 60       # replay past sessions to build history
quantdesk schedule --install       # run automatically each weekday
quantdesk profiles                 # explain the risk tiers
```

Global flags work before or after the subcommand: `--risk`, `--provider`,
`--offline`, `--strict`, `--home`.

| Flag | Effect |
|---|---|
| `--strict` | Real market data only. Probes the feed and exits 2 if it is dead. |
| `--offline` | Generated data and placeholder headlines. No network calls. |
| `--provider yahoo` | Pin one source; no fallback chain. |
| `--manual` | Queue ideas for approval instead of placing them (`serve`). |

---

## How the simulator stays honest

A simulator that flatters you is worse than none, because it gives you
confidence you have not earned. Four decisions keep this one straight, each
covered by tests:

- **Orders wait for their trigger.** A breakout idea is filled only if a later
  session actually trades through the price. In a recent 120-session run, 48
  orders produced 34 fills — 14 setups simply never triggered, exactly as they
  would not have in a real account.
- **Gaps hurt.** If a stock gaps below your stop overnight you are filled at the
  open, not at the stop. That is where real accounts take their worst losses.
- **Stops beat targets on ties.** When one daily bar spans both the stop and a
  target, there is no way to know which came first, so the engine assumes the
  stop. This biases results pessimistic — the only safe direction to be wrong.
- **Slippage and commission are charged** on every fill, always against you.

---

## Data sources

Tried in order, falling back automatically:

1. **Yahoo Finance** via `yfinance` — free, no key
2. **Stooq** CSV — free, no key
3. **Generated data** — so the desk still runs offline

Runs using generated data are labelled `SIMULATED PRICE DATA` in every report
and on the CLI, and `--strict` removes step 3 entirely. Bars are cached to
`~/.quantdesk/cache/` for six hours; `doctor` reports which source `auto`
actually resolved to.

If `doctor` shows Yahoo failing, in order: `pip install --upgrade yfinance`
(the endpoint is undocumented and changes), then check whether a corporate VPN
or firewall is blocking `finance.yahoo.com`, then try `--provider stooq`.

News comes from Yahoo Finance and Google News RSS.

---

## Optional extras

**Real paper brokerage.** For play money that behaves like a real account —
genuine market hours, real rejections, partial fills:

```bash
pip install alpaca-py
export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...
```

Plans are submitted as bracket orders, so the stop exists the moment the
position does. This path talks to a live API and so is not covered by the
offline test suite — check the Alpaca dashboard after your first run.

**Delivery.** `--email` needs `QUANTDESK_SMTP_HOST`, `QUANTDESK_SMTP_USER`,
`QUANTDESK_SMTP_PASSWORD`, `QUANTDESK_EMAIL_TO`. `--webhook` needs
`QUANTDESK_WEBHOOK_URL` (Slack, Discord, anything that takes JSON).

---

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

182 tests, green on Python 3.10–3.13 and on the oldest supported dependencies.

Indicators are checked against hand-derived values; every candlestick detector
against a constructed example of its pattern; the trend classifier for
directional bias across random-walk seeds; execution semantics for gaps,
stop-vs-target ties, slippage direction and exact cash reconciliation in both
directions; charts against an all-NaN overlay, since a NaN in an SVG attribute
silently drops the shape rather than erroring; the approval path driven over
real HTTP; and a walk-forward run verifying the accounting invariants hold over
many sessions without look-ahead.

The backtest's look-ahead guarantee is tested directly rather than asserted:
the same window run to two different end dates must produce identical
overlapping equity, and the precomputed indicator frames that make it fast are
checked against freshly computed ones column by column.

---

## Layout

```
quantdesk/
  config.py            risk profiles and settings
  engine.py            the daily cycle
  cli.py               command line interface
  backtest.py          walk-forward backtesting
  backtest_report.py   backtest report (text + HTML)
  diagnostics.py       preflight checks
  notify.py            email / webhook delivery
  data/                providers (Yahoo, Stooq, synthetic), cache, symbol list
  analysis/            indicators, candlestick patterns, trend, weekly timeframe
  news/                RSS retrieval, financial sentiment
  strategy/            universes, screener, regime, scoring, risk, trade plans
  broker/              paper simulator, optional Alpaca adapter
  portfolio/           SQLite store, performance metrics, reports
  web/                 dashboard server, pages, SVG charts
```

---

## Honest limits

- **No options or futures.** Equities and ETFs only.
- **Daily bars.** Nothing intraday, so same-bar sequencing is assumed, not known.
- **Sentiment is a lexicon,** not a language model. It cannot tell whether news
  is already priced in.
- **The universe is a curated list**, not the whole market.
- **A profitable simulation is not an edge.** With a handful of closed trades you
  are looking at noise; the report says so until there are 30+.
- **These rules were written with this data available.** Some of any backtested
  edge is hindsight, and no amount of testing removes that. Out-of-sample
  results on data you have never looked at are the only real check.
