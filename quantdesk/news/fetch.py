"""Headline retrieval.

Uses plain RSS over stdlib XML parsing rather than a feed library, keeping the
dependency footprint small. Two keyless sources are tried in order, and a
deterministic offline source keeps the desk demonstrable without a network.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class NewsArticle:
    title: str
    summary: str
    url: str
    source: str
    published: datetime

    @property
    def age_days(self) -> float:
        now = datetime.now(timezone.utc)
        published = self.published
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return max(0.0, (now - published).total_seconds() / 86400.0)


def _strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


def _parse_rss(xml_text: str, source: str) -> list[NewsArticle]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    articles: list[NewsArticle] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        raw_date = item.findtext("pubDate") or ""
        try:
            published = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            published = datetime.now(timezone.utc)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        articles.append(
            NewsArticle(
                title=_strip_html(title),
                summary=_strip_html(item.findtext("description") or "")[:600],
                url=(item.findtext("link") or "").strip(),
                source=source,
                published=published,
            )
        )
    return articles


class NewsFetcher:
    """Fetches recent headlines for a symbol, with graceful degradation."""

    YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
    GOOGLE_RSS = "https://news.google.com/rss/search"

    def __init__(self, timeout: int = 12, offline: bool = False) -> None:
        self.timeout = timeout
        self.offline = offline
        self._offline_notice_shown = False

    def fetch(
        self, symbol: str, lookback_days: int = 7, limit: int = 25
    ) -> list[NewsArticle]:
        symbol = symbol.upper()
        articles: list[NewsArticle] = []

        if not self.offline:
            for getter in (self._from_yahoo, self._from_google):
                try:
                    articles = getter(symbol)
                except Exception:
                    articles = []
                if articles:
                    break

        if not articles:
            articles = synthetic_news(symbol, lookback_days)

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        fresh = [a for a in articles if a.published >= cutoff]
        fresh.sort(key=lambda a: a.published, reverse=True)

        # De-duplicate near-identical headlines syndicated across outlets.
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for art in fresh:
            key = re.sub(r"[^a-z0-9]+", "", art.title.lower())[:70]
            if key in seen:
                continue
            seen.add(key)
            unique.append(art)
        return unique[:limit]

    def _from_yahoo(self, symbol: str) -> list[NewsArticle]:
        import requests

        resp = requests.get(
            self.YAHOO_RSS,
            params={"s": symbol, "region": "US", "lang": "en-US"},
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; quantdesk/0.1)"},
        )
        resp.raise_for_status()
        return _parse_rss(resp.text, "Yahoo Finance")

    def _from_google(self, symbol: str) -> list[NewsArticle]:
        import requests

        resp = requests.get(
            self.GOOGLE_RSS,
            params={
                "q": f"{symbol} stock",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; quantdesk/0.1)"},
        )
        resp.raise_for_status()
        return _parse_rss(resp.text, "Google News")


# --- offline fallback -------------------------------------------------------
_TEMPLATES = [
    ("{sym} beats quarterly estimates and raises full-year guidance",
     "Management pointed to strong demand and improving margins."),
    ("{sym} misses revenue expectations as growth slows",
     "Executives warned of headwinds and a weaker near-term outlook."),
    ("Analysts upgrade {sym} on accelerating momentum",
     "The note cites a robust product cycle and expanding market share."),
    ("{sym} downgraded amid valuation concerns",
     "The analyst flagged risks to margins and a crowded positioning."),
    ("{sym} announces expanded buyback and dividend increase",
     "The board approved additional capital returns to shareholders."),
    ("{sym} shares slump following disappointing guidance",
     "Investors reacted negatively to a cautious commentary on demand."),
    ("{sym} secures major partnership contract",
     "The multi-year agreement is expected to contribute to growth."),
    ("Regulatory probe weighs on {sym}",
     "The investigation introduces uncertainty for the coming quarters."),
    ("{sym} trades quietly ahead of the earnings report",
     "Volume was light with no company-specific developments."),
    ("{sym} rebounds sharply on record profit",
     "The recovery was driven by strong cost efficiency and rising demand."),
]


def synthetic_news(symbol: str, lookback_days: int = 7, count: int = 6) -> list[NewsArticle]:
    """Deterministic offline headlines so the pipeline is always exercisable.

    Clearly labelled as synthetic - these must never be mistaken for real news.
    """
    import numpy as np

    digest = hashlib.sha256(f"news:{symbol.upper()}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    now = datetime.now(timezone.utc)

    picks = rng.choice(len(_TEMPLATES), size=min(count, len(_TEMPLATES)), replace=False)
    out: list[NewsArticle] = []
    for k, idx in enumerate(picks):
        title, summary = _TEMPLATES[int(idx)]
        hours_ago = float(rng.uniform(1, max(2, lookback_days * 24)))
        out.append(
            NewsArticle(
                title=title.format(sym=symbol.upper()),
                summary=summary,
                url="",
                source="synthetic (offline)",
                published=now - timedelta(hours=hours_ago),
            )
        )
    return out
