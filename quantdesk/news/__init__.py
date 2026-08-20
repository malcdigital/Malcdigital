"""News retrieval and sentiment scoring."""

from quantdesk.news.sentiment import SentimentAnalyzer, SentimentResult
from quantdesk.news.fetch import NewsArticle, NewsFetcher

__all__ = ["SentimentAnalyzer", "SentimentResult", "NewsArticle", "NewsFetcher"]
