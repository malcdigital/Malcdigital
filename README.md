# QuantDesk

A paper-trading research desk. It reads candlesticks and trends, weighs the news
around a stock, ranks ideas against your chosen risk level, tells you exactly
when to get in and out, and then trades them with play money and reports back
every day.

> **Play money only.** No real orders, no real account. Read
> [DISCLAIMER.md](DISCLAIMER.md) before you do anything else.

---

## Quick start

```bash
git clone <this repo> && cd Malcdigital
pip install -r requirements.txt

python -m quantdesk.cli init --cash 100000 --risk moderate
python -m quantdesk.cli run
```

That's it. `run` executes one trading day and prints a full report. To have it
run itself every weekday:

```bash
python -m quantdesk.cli schedule --install     # weekdays at 16:30 local
```

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

"Risk per trade" is the fraction of equity you lose if the stop is hit — the
number that actually determines position size.

---

## Commands

```bash
quantdesk init --cash 100000 --risk moderate --watchlist NVDA,AMD
quantdesk run                      # one trading day + report
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
`--offline`, `--home`.

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
and on the CLI. Bars are cached to `~/.quantdesk/cache/` for six hours.

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

84 tests. Indicators are checked against hand-derived values; every candlestick
detector against a constructed example of its pattern; the trend classifier for
directional bias on random data; execution semantics for gaps, ties, slippage
and cash reconciliation; and a walk-forward run that verifies the accounting
invariants hold over many sessions without look-ahead.

---

## Layout

```
quantdesk/
  config.py            risk profiles and settings
  engine.py            the daily cycle
  cli.py               command line interface
  notify.py            email / webhook delivery
  data/                providers (Yahoo, Stooq, synthetic), cache, fallback
  analysis/            indicators, candlestick patterns, trend and levels
  news/                RSS retrieval, financial sentiment
  strategy/            universes, scoring, risk sizing, trade plans
  broker/              paper simulator, optional Alpaca adapter
  portfolio/           SQLite store, performance metrics, reports
```

---

## Honest limits

- **Long only.** No shorting, options or futures.
- **Daily bars.** Nothing intraday, so same-bar sequencing is assumed, not known.
- **Sentiment is a lexicon,** not a language model. It cannot tell whether news
  is already priced in.
- **The universe is a curated list**, not the whole market.
- **A profitable simulation is not an edge.** With a handful of closed trades you
  are looking at noise; the report says so until there are 30+.
