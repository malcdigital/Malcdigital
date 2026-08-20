"""Candidate universes by risk tier.

Screening the whole market on every run is slow and mostly wasted, so each risk
profile starts from a curated list appropriate to its mandate. Conservative
tiers lean on broad, liquid funds; aggressive tiers include higher-beta single
names. The user's own watchlist is always merged in on top.
"""

from __future__ import annotations

# Broad, liquid core exposures.
CORE_ETFS = [
    "SPY", "VOO", "VTI", "QQQ", "IWM", "DIA", "SCHD", "VYM", "VIG",
]

# Defensive / low-volatility tilts and bonds.
DEFENSIVE_ETFS = [
    "USMV", "SPLV", "XLP", "XLU", "XLV", "AGG", "BND", "TLT", "IEF", "GLD",
]

# Sector and style exposures for the balanced tier.
SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLI", "XLY", "XLB", "XLC", "XLRE",
    "VUG", "VTV", "MTUM", "QUAL", "EFA", "EEM",
]

# Thematic / higher-beta funds.
THEMATIC_ETFS = [
    "SMH", "SOXX", "ARKK", "XBI", "IBB", "TAN", "ICLN", "KWEB", "JETS",
]

MEGA_CAP_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B", "JPM", "V",
    "JNJ", "WMT", "PG", "XOM", "UNH", "MA", "HD", "COST", "KO", "PEP", "MRK",
]

LARGE_CAP_STOCKS = [
    "AMD", "CRM", "ADBE", "NFLX", "TSLA", "ORCL", "CSCO", "INTC", "QCOM",
    "TXN", "AMAT", "MU", "BA", "CAT", "GE", "DE", "LMT", "NKE", "SBUX",
    "MCD", "DIS", "T", "VZ", "PFE", "ABBV", "LLY", "TMO", "ABT", "GS", "MS",
    "BAC", "WFC", "AXP", "SPGI", "NOW", "INTU", "ISRG", "REGN", "VRTX",
]

HIGH_BETA_STOCKS = [
    "PLTR", "COIN", "SQ", "SHOP", "SNAP", "UBER", "LYFT", "RIVN", "LCID",
    "MRNA", "ROKU", "DKNG", "AFRM", "SOFI", "CRWD", "ZS", "NET", "DDOG",
    "SNOW", "MDB", "PANW", "ANET", "SMCI", "MARA", "RIOT",
]


def universe_for(risk_profile: str) -> list[str]:
    """Return the candidate symbols appropriate to a risk tier."""
    tier = (risk_profile or "moderate").lower()
    if tier == "conservative":
        symbols = CORE_ETFS + DEFENSIVE_ETFS + MEGA_CAP_STOCKS
    elif tier == "aggressive":
        symbols = (
            CORE_ETFS + SECTOR_ETFS + THEMATIC_ETFS
            + MEGA_CAP_STOCKS + LARGE_CAP_STOCKS + HIGH_BETA_STOCKS
        )
    else:  # moderate
        symbols = (
            CORE_ETFS + SECTOR_ETFS + DEFENSIVE_ETFS[:5]
            + MEGA_CAP_STOCKS + LARGE_CAP_STOCKS
        )

    seen: set[str] = set()
    ordered: list[str] = []
    for sym in symbols:
        if sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    return ordered


BENCHMARK = "SPY"
"""Used for relative-strength comparison and market-regime gating."""
