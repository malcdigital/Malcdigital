"""Financial sentiment, including the constructions generic lexicons get wrong."""

import pytest

from quantdesk.news.fetch import synthetic_news
from quantdesk.news.sentiment import SentimentAnalyzer, aggregate_news_sentiment


@pytest.fixture
def analyzer():
    return SentimentAnalyzer()


@pytest.mark.parametrize("headline", [
    "Apple beats earnings estimates, raises guidance",
    "Stock surges sharply on record profit and upgrade",
    "Analysts upgrade the shares on accelerating momentum",
])
def test_clearly_positive_headlines(analyzer, headline):
    assert analyzer.score_text(headline).score > 0.2


@pytest.mark.parametrize("headline", [
    "Tesla shares plunge after disappointing delivery numbers",
    "Analyst downgrades stock, cites significant headwinds",
    "Regulatory probe and lawsuit weigh on the shares",
])
def test_clearly_negative_headlines(analyzer, headline):
    assert analyzer.score_text(headline).score < -0.2


def test_neutral_text_scores_zero(analyzer):
    assert analyzer.score_text("The company announced a board meeting on Tuesday").score == 0.0


def test_negation_flips_sentiment(analyzer):
    assert analyzer.score_text("The company is not profitable").score < 0


def test_negation_does_not_leak_across_a_clause_boundary(analyzer):
    """'not' governs 'profitable' only - it must not flip 'warns' to positive."""
    assert analyzer.score_text(
        "Company is not profitable and warns of weak demand"
    ).score < -0.2


def test_negative_modifier_inverts_a_following_positive_noun(analyzer):
    """'weak demand' and 'slowing growth' are bearish, not bullish."""
    assert analyzer.score_text("Soft demand and weak margins force a guidance cut").score < -0.2
    assert analyzer.score_text("Slowing growth and falling profit pressure the shares").score < -0.2


def test_intensifiers_scale_magnitude(analyzer):
    strong = analyzer.score_text("Shares rose sharply")
    mild = analyzer.score_text("Shares rose slightly")
    assert strong.score > mild.score > 0


def test_headline_outweighs_body(analyzer):
    result = analyzer.score_article(
        "Stock plunges on fraud investigation",
        "Some analysts noted modest growth in one small segment.",
    )
    assert result.score < 0


def test_aggregate_weights_and_labels_correctly():
    sentiment = aggregate_news_sentiment("AAPL", synthetic_news("AAPL", 7))
    assert sentiment.article_count > 0
    assert -1.0 <= sentiment.score <= 1.0
    assert sentiment.is_synthetic is True
    assert "sentiment" in sentiment.summary_line


def test_aggregate_handles_no_articles():
    sentiment = aggregate_news_sentiment("AAPL", [])
    assert sentiment.score == 0.0
    assert sentiment.article_count == 0


def test_positive_noun_with_a_falling_verb_reads_bearish(analyzer):
    """'Profit fell' must not net out to neutral because 'profit' is positive."""
    for headline in ("Profit fell sharply", "Revenue declined this quarter",
                     "Margins shrank on higher costs", "Growth slowed materially"):
        assert analyzer.score_text(headline).score < -0.1, headline


def test_the_same_noun_with_a_rising_verb_stays_bullish(analyzer):
    assert analyzer.score_text("Profit rose sharply").score > 0.2
