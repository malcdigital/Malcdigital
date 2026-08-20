# Read this first

**This software is an educational simulation. It is not financial advice.**

- It trades **play money only**. The built-in broker is a simulator; no real
  orders are placed and no real account is touched. (The optional Alpaca
  adapter connects to a *paper* account, which is also play money.)
- Nothing it produces is a recommendation to buy or sell any security. The
  "recommendations" are the mechanical output of indicator rules, not advice
  from a licensed professional.
- **Simulated results are not real results.** A simulator cannot reproduce
  slippage on illiquid names, borrow costs, halted trading, partial fills,
  taxes, or your own behaviour under pressure. Real accounts underperform
  backtests, consistently and by a lot.
- The news sentiment engine is a keyword lexicon. It does not understand
  context, sarcasm, or whether a story is already priced in.
- If live market data is unavailable, the desk falls back to **generated price
  series** so it can still run. Those runs are labelled `SIMULATED PRICE DATA`
  in every report. Never read a synthetic run as market information.

Markets can and do go to zero. Most people who trade actively lose money.
Before risking real capital, talk to a licensed financial adviser who knows
your situation.

By using this software you accept that you are solely responsible for any
decisions you make with it.
