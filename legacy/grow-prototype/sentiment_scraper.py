"""Agency OS — Sentiment Scraper & Reputation Alert Engine.

Monitors brand sentiment by scraping and parsing reviews, raising critical
reputation alert cards if negative reviews contain high-risk threat keywords.
"""

import dataclasses
import typing


@dataclasses.dataclass
class Review:
    review_id: str
    platform: str  # e.g., 'GBP', 'Trustpilot'
    author: str
    content: str
    rating: int  # 1 to 5 stars
    date: str


@dataclasses.dataclass
class AlertCard:
    tenant_id: str
    alert_type: str  # e.g., 'BRAND_REPUTATION_CRITICAL'
    message: str
    source_review_id: str
    status: str = "OPEN"


@dataclasses.dataclass
class MediaMention:
    mention_id: str
    title: str
    source: str
    url: str
    sentiment_score: float  # -1.0 to 1.0
    backlink_present: bool
    published_date: str


class SentimentScraper:
    """Classifies sentiment and fires automated action alerts."""

    def __init__(self, tenant_id: str, threat_keywords: typing.List[str]):
        """Initializes scraper.

        Args:
            tenant_id: Active tenant context ID.
            threat_keywords: Keywords indicating high-severity complaints
              (e.g., 'scam', 'fraud', 'stole').
        """
        self.tenant_id = tenant_id
        self.threat_keywords = [kw.lower() for kw in threat_keywords]

    def analyze_sentiment(self, review: Review) -> str:
        """Categorizes review sentiment based on star rating."""
        if review.rating >= 4:
            return "POSITIVE"
        elif review.rating == 3:
            return "NEUTRAL"
        else:
            return "NEGATIVE"

    def process_reviews(
        self,
        reviews: typing.List[Review]
    ) -> typing.List[AlertCard]:
        """Audits reviews and generates reputation alert cards.

        Fires an alert if a review has NEGATIVE sentiment and contains one or
        more threat keywords in its content.

        Args:
            reviews: List of newly fetched reviews.

        Returns:
            List of generated AlertCards.
        """
        alerts = []
        for rev in reviews:
            sentiment = self.analyze_sentiment(rev)
            if sentiment == "NEGATIVE":
                content_lower = rev.content.lower()
                matched_keywords = [
                    kw for kw in self.threat_keywords if kw in content_lower
                ]
                if matched_keywords:
                    msg = (
                        f"Critical alert: {rev.platform} review from "
                        f"{rev.author} contains high-risk terms "
                        f"{matched_keywords}."
                    )
                    alerts.append(AlertCard(
                        tenant_id=self.tenant_id,
                        alert_type="BRAND_REPUTATION_CRITICAL",
                        message=msg,
                        source_review_id=rev.review_id
                    ))
        return alerts

    def process_media_mentions(
        self,
        mentions: typing.List[MediaMention]
    ) -> typing.List[AlertCard]:
        """Crawls RSS news mentions and raises alerts on brand reputation threat.

        Args:
            mentions: List of Google News or PR RSS feed mentions.

        Returns:
            List of AlertCards.
        """
        alerts = []
        for item in mentions:
            # Check negative sentiment score and threat keywords in title
            if item.sentiment_score < -0.3:
                title_lower = item.title.lower()
                matched_keywords = [
                    kw for kw in self.threat_keywords if kw in title_lower
                ]
                if matched_keywords:
                    msg = (
                        f"PR Alert: Negative news at {item.source} - "
                        f'"{item.title}" contains terms {matched_keywords}.'
                    )
                    alerts.append(AlertCard(
                        tenant_id=self.tenant_id,
                        alert_type="BRAND_REPUTATION_CRITICAL",
                        message=msg,
                        source_review_id=item.mention_id
                    ))
        return alerts
