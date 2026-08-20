"""Financial sentiment scoring.

A general-purpose sentiment model is the wrong tool for market headlines. "Apple
shares plunge on soft guidance" is unambiguously negative to a trader while
looking mild to a generic classifier, and "beats estimates" is strongly positive
in finance and meaningless elsewhere. So this uses a domain lexicon (in the
spirit of Loughran-McDonald, which exists precisely because general lexicons
misread financial text) with three refinements that matter in practice:

* **Negation** - "not profitable" must not score as positive.
* **Intensifiers** - "sharply higher" outweighs "slightly higher".
* **Headline weighting** - headlines are written to carry the signal; body text
  dilutes it.

It is deliberately transparent and dependency-free: you can read exactly why a
story scored the way it did, which matters when it is moving your money.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Weights are hand-set on a -1..1 scale reflecting typical price impact.
POSITIVE_TERMS: dict[str, float] = {
    "beat": 0.7, "beats": 0.7, "outperform": 0.7, "outperformed": 0.7,
    "upgrade": 0.85, "upgraded": 0.85, "upgrades": 0.85,
    "surge": 0.8, "surged": 0.8, "surges": 0.8, "soar": 0.85, "soared": 0.85,
    "rally": 0.65, "rallied": 0.65, "jump": 0.6, "jumped": 0.6, "jumps": 0.6,
    "gain": 0.45, "gains": 0.45, "gained": 0.45, "rise": 0.4, "rises": 0.4,
    "rose": 0.4, "climb": 0.45, "climbed": 0.45, "advance": 0.4, "advanced": 0.4,
    "record": 0.6, "profit": 0.5, "profitable": 0.55, "profits": 0.5,
    "growth": 0.5, "grew": 0.45, "expansion": 0.45, "expanding": 0.4,
    "strong": 0.55, "stronger": 0.55, "strength": 0.5, "robust": 0.55,
    "raise": 0.5, "raised": 0.5, "raises": 0.5, "boost": 0.55, "boosted": 0.55,
    "buyback": 0.6, "dividend": 0.4, "approval": 0.6, "approved": 0.55,
    "breakthrough": 0.7, "milestone": 0.45, "partnership": 0.4, "contract": 0.4,
    "win": 0.5, "wins": 0.5, "won": 0.45, "expands": 0.4, "launch": 0.35,
    "bullish": 0.75, "optimistic": 0.5, "confidence": 0.4, "momentum": 0.45,
    "exceeded": 0.65, "exceeds": 0.65, "topped": 0.6, "accelerate": 0.5,
    "accelerating": 0.5, "recovery": 0.5, "rebound": 0.6, "rebounded": 0.6,
    "efficiency": 0.35, "innovative": 0.35, "demand": 0.35, "opportunity": 0.3,
    "positive": 0.45, "success": 0.45, "successful": 0.45, "outlook": 0.15,
}

NEGATIVE_TERMS: dict[str, float] = {
    "miss": -0.7, "missed": -0.7, "misses": -0.7, "downgrade": -0.85,
    "downgraded": -0.85, "downgrades": -0.85, "plunge": -0.9, "plunged": -0.9,
    "plunges": -0.9, "crash": -0.95, "crashed": -0.95, "tumble": -0.8,
    "tumbled": -0.8, "slump": -0.75, "slumped": -0.75, "sink": -0.7,
    "sank": -0.7, "fall": -0.45, "fell": -0.45, "falls": -0.45,
    "drop": -0.5, "dropped": -0.5, "drops": -0.5, "decline": -0.5,
    "declined": -0.5, "declines": -0.5, "loss": -0.6, "losses": -0.6,
    "lost": -0.5, "weak": -0.6, "weaker": -0.6, "weakness": -0.6,
    "warning": -0.7, "warns": -0.7, "warned": -0.7, "cut": -0.55, "cuts": -0.55,
    "slash": -0.75, "slashed": -0.75, "layoff": -0.6, "layoffs": -0.6,
    "bankruptcy": -0.95, "bankrupt": -0.95, "default": -0.85, "fraud": -0.9,
    "investigation": -0.65, "probe": -0.6, "lawsuit": -0.55, "sue": -0.5,
    "sued": -0.5, "litigation": -0.5, "recall": -0.65, "delay": -0.45,
    "delayed": -0.45, "halt": -0.6, "halted": -0.6, "suspend": -0.6,
    "suspended": -0.6, "resign": -0.5, "resigned": -0.5, "stepped": -0.25,
    "concern": -0.45, "concerns": -0.45, "risk": -0.35, "risks": -0.35,
    "bearish": -0.75, "pessimistic": -0.5, "recession": -0.7, "slowdown": -0.6,
    "slowing": -0.55, "headwind": -0.5, "headwinds": -0.5, "shortfall": -0.65,
    "underperform": -0.7, "underperformed": -0.7, "disappointing": -0.7,
    "disappointed": -0.65, "negative": -0.45, "failure": -0.7, "failed": -0.6,
    "struggle": -0.55, "struggling": -0.6, "pressure": -0.35, "deficit": -0.5,
    "overvalued": -0.55, "selloff": -0.7, "short": -0.3, "dilution": -0.55,
    "slowed": -0.55, "stalled": -0.6, "collapsed": -0.9, "shrank": -0.6,
    "slipped": -0.4, "deteriorated": -0.7, "weakened": -0.6,
}

NEGATORS = {
    "not", "no", "never", "without", "fails", "fail", "failed", "failing",
    "unable", "lacks", "lack", "lacking", "isn't", "wasn't", "aren't",
    "weren't", "doesn't", "didn't", "don't", "won't", "cannot", "can't",
    "nor", "neither", "hardly", "barely", "scarcely",
}

INTENSIFIERS = {
    "very": 1.4, "sharply": 1.5, "significantly": 1.4, "substantially": 1.4,
    "dramatically": 1.6, "massively": 1.7, "hugely": 1.6, "extremely": 1.6,
    "record": 1.4, "steeply": 1.5, "deeply": 1.4, "strongly": 1.4,
    "slightly": 0.5, "marginally": 0.45, "modestly": 0.6, "somewhat": 0.6,
    "mildly": 0.55, "slower": 0.8,
}

# Words that end a clause. Negation must not leak across one: in "not
# profitable and warns of weak demand", the "not" governs "profitable" only -
# without this barrier it flips "warns" positive and the sentence reads neutral.
CLAUSE_BARRIERS = {
    ".", ",", ";", ":", "!", "?", "-", "and", "but", "or", "while", "although",
    "however", "though", "yet", "despite", "whereas", "after", "before",
}

# Negative modifiers that invert a following positive noun. "weak demand",
# "slowing growth" and "declining profit" all read positive to a naive lexicon
# because the noun outweighs nothing; in finance they are plainly bearish.
NEGATIVE_MODIFIERS = {
    "weak", "weaker", "weakest", "soft", "softer", "falling", "declining",
    "slowing", "shrinking", "lower", "reduced", "poor", "disappointing",
    "sluggish", "tepid", "muted", "deteriorating", "waning", "sagging",
    "negative", "lackluster", "worsening",
}

# The mirror of NEGATIVE_MODIFIERS: a positive noun followed by a negative verb
# is a bearish sentence. "Profit fell", "revenue declined" and "margins shrank"
# otherwise net out to roughly neutral because the noun cancels the verb.
FALLING_VERBS = {
    "fell", "fall", "falls", "falling", "dropped", "drop", "drops", "declined",
    "decline", "declines", "plunged", "plunge", "plunges", "slumped", "slumps",
    "tumbled", "tumbles", "sank", "sink", "sinks", "missed", "misses",
    "slipped", "slips", "sagged", "shrank", "shrink", "shrinks", "weakened",
    "slowed", "stalled", "collapsed", "evaporated", "deteriorated",
}

_TOKEN_RE = re.compile(r"[a-z']+|[.,;:!?-]")


@dataclass
class SentimentResult:
    """Sentiment for a single piece of text."""

    score: float
    """-1 (very negative) .. +1 (very positive)."""

    magnitude: float
    """How much sentiment-bearing language was present at all."""

    label: str
    positive_hits: list[str] = field(default_factory=list)
    negative_hits: list[str] = field(default_factory=list)

    @property
    def is_meaningful(self) -> bool:
        return self.magnitude >= 0.5


def _label(score: float) -> str:
    if score >= 0.35:
        return "positive"
    if score >= 0.12:
        return "slightly positive"
    if score <= -0.35:
        return "negative"
    if score <= -0.12:
        return "slightly negative"
    return "neutral"


class SentimentAnalyzer:
    """Lexicon sentiment with negation and intensifier handling."""

    def __init__(self, negation_window: int = 3) -> None:
        self.negation_window = negation_window

    def score_text(self, text: str) -> SentimentResult:
        if not text:
            return SentimentResult(0.0, 0.0, "neutral")

        tokens = _TOKEN_RE.findall(text.lower())
        total = 0.0
        magnitude = 0.0
        pos_hits: list[str] = []
        neg_hits: list[str] = []

        for i, token in enumerate(tokens):
            weight = POSITIVE_TERMS.get(token, NEGATIVE_TERMS.get(token))
            if weight is None:
                continue

            # Look back a few tokens for negators and intensifiers, stopping at
            # a clause boundary so negation cannot leak into the next clause.
            multiplier = 1.0
            negated = False
            for j in range(i - 1, max(-1, i - 1 - self.negation_window), -1):
                prior = tokens[j]
                if prior in CLAUSE_BARRIERS:
                    break
                if prior in NEGATORS:
                    negated = True
                if prior in INTENSIFIERS:
                    multiplier *= INTENSIFIERS[prior]

            # English puts adverbs on either side of the verb: "sharply higher"
            # but also "rose sharply". Scan forward too, stopping at a clause
            # boundary or at the next sentiment word, which owns its own modifier.
            for j in range(i + 1, min(len(tokens), i + 3)):
                nxt = tokens[j]
                if nxt in CLAUSE_BARRIERS:
                    break
                if nxt in POSITIVE_TERMS or nxt in NEGATIVE_TERMS:
                    break
                if nxt in INTENSIFIERS:
                    multiplier *= INTENSIFIERS[nxt]

            # "weak demand": a negative modifier immediately before a positive
            # term inverts it rather than letting the noun score positive.
            if weight > 0 and i > 0 and tokens[i - 1] in NEGATIVE_MODIFIERS:
                weight = -weight * 0.8
            # "profit fell": a positive noun followed by a falling verb is bearish.
            elif weight > 0 and i + 1 < len(tokens) and tokens[i + 1] in FALLING_VERBS:
                weight = -weight * 0.8

            effective = weight * multiplier
            if negated:
                # Negation flips direction but dampens: "not strong" is weaker
                # evidence than "weak" stated outright.
                effective *= -0.75

            total += effective
            magnitude += abs(effective)
            (pos_hits if effective > 0 else neg_hits).append(token)

        if magnitude == 0.0:
            return SentimentResult(0.0, 0.0, "neutral")

        # Squash so a story stuffed with adjectives cannot dominate, while
        # preserving sign and relative strength.
        score = math.tanh(total / 2.5)
        return SentimentResult(
            score=round(score, 4),
            magnitude=round(magnitude, 4),
            label=_label(score),
            positive_hits=pos_hits,
            negative_hits=neg_hits,
        )

    def score_article(self, title: str, summary: str = "") -> SentimentResult:
        """Blend headline and body, weighting the headline more heavily."""
        head = self.score_text(title or "")
        body = self.score_text(summary or "")
        if head.magnitude == 0.0 and body.magnitude == 0.0:
            return SentimentResult(0.0, 0.0, "neutral")

        # 70/30 split: headlines are written to carry the signal.
        w_head, w_body = 0.70, 0.30
        if body.magnitude == 0.0:
            w_head, w_body = 1.0, 0.0
        elif head.magnitude == 0.0:
            w_head, w_body = 0.0, 1.0

        score = head.score * w_head + body.score * w_body
        return SentimentResult(
            score=round(score, 4),
            magnitude=round(head.magnitude * w_head + body.magnitude * w_body, 4),
            label=_label(score),
            positive_hits=head.positive_hits + body.positive_hits,
            negative_hits=head.negative_hits + body.negative_hits,
        )


@dataclass
class NewsSentiment:
    """Aggregate sentiment across all recent stories for one symbol."""

    symbol: str
    score: float
    """-1..1, recency-weighted."""

    label: str
    article_count: int
    coverage: float
    """0..1 - how much sentiment-bearing coverage exists. Low means 'no news'."""

    top_positive: list[tuple[str, float]] = field(default_factory=list)
    top_negative: list[tuple[str, float]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    is_synthetic: bool = False

    @property
    def summary_line(self) -> str:
        if self.article_count == 0:
            return "No recent coverage found."
        return (
            f"{self.article_count} stories, net sentiment {self.score:+.2f} "
            f"({self.label})"
        )


def aggregate_news_sentiment(
    symbol: str,
    articles: list,
    analyzer: "SentimentAnalyzer | None" = None,
    half_life_days: float = 2.5,
) -> NewsSentiment:
    """Combine article sentiments, weighting recent and opinionated stories more.

    Weighting by magnitude matters: ten filler headlines should not drown out one
    genuine earnings miss.
    """
    analyzer = analyzer or SentimentAnalyzer()
    if not articles:
        return NewsSentiment(symbol, 0.0, "neutral", 0, 0.0)

    weighted_sum = 0.0
    weight_total = 0.0
    magnitude_total = 0.0
    scored: list[tuple[str, float]] = []

    for art in articles:
        result = analyzer.score_article(art.title, art.summary)
        recency = 0.5 ** (art.age_days / half_life_days)
        # Opinionated stories carry more weight than filler.
        conviction = min(1.0, 0.35 + result.magnitude / 3.0)
        weight = recency * conviction

        weighted_sum += result.score * weight
        weight_total += weight
        magnitude_total += result.magnitude * recency
        scored.append((art.title, result.score))

    score = weighted_sum / weight_total if weight_total else 0.0
    coverage = min(1.0, magnitude_total / 4.0)

    positives = sorted([s for s in scored if s[1] > 0.05], key=lambda x: -x[1])[:3]
    negatives = sorted([s for s in scored if s[1] < -0.05], key=lambda x: x[1])[:3]
    sources = sorted({getattr(a, "source", "") for a in articles} - {""})

    return NewsSentiment(
        symbol=symbol.upper(),
        score=round(score, 4),
        label=_label(score),
        article_count=len(articles),
        coverage=round(coverage, 3),
        top_positive=positives,
        top_negative=negatives,
        sources=sources,
        is_synthetic=all("synthetic" in getattr(a, "source", "") for a in articles),
    )
