# Sentiment Scraper unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import sentiment_scraper

class SentimentScraperTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.tenant_id = "tenant-1"
        self.threat_keywords = ["scam", "fraud", "fake", "stole"]
        self.scraper = sentiment_scraper.SentimentScraper(
            tenant_id=self.tenant_id,
            threat_keywords=self.threat_keywords
        )

    def test_sentiment_classification(self):
        pos = sentiment_scraper.Review(
            "r1", "GBP", "User", "Loved it!", 5, "now"
        )
        neu = sentiment_scraper.Review(
            "r2", "GBP", "User", "Okay.", 3, "now"
        )
        neg = sentiment_scraper.Review(
            "r3", "GBP", "User", "Bad.", 1, "now"
        )

        self.assertEqual(self.scraper.analyze_sentiment(pos), "POSITIVE")
        self.assertEqual(self.scraper.analyze_sentiment(neu), "NEUTRAL")
        self.assertEqual(self.scraper.analyze_sentiment(neg), "NEGATIVE")

    def test_process_reviews_no_alert(self):
        reviews = [
            sentiment_scraper.Review(
                "r1", "GBP", "User", "This is NOT a scam!", 5, "now"
            ),
            sentiment_scraper.Review(
                "r2", "Trustpilot", "User", "Shipping was too slow.", 2, "now"
            )
        ]

        alerts = self.scraper.process_reviews(reviews)
        self.assertEmpty(alerts)

    def test_process_reviews_triggers_alert(self):
        reviews = [
            sentiment_scraper.Review(
                "r1", "GBP", "AngryUser", "They stole my money! absolute fraud",
                1, "now"
            )
        ]

        alerts = self.scraper.process_reviews(reviews)
        self.assertLen(alerts, 1)
        alert = alerts[0]
        self.assertEqual(alert.tenant_id, self.tenant_id)
        self.assertEqual(alert.alert_type, "BRAND_REPUTATION_CRITICAL")
        self.assertEqual(alert.source_review_id, "r1")

    def test_process_media_mentions_triggers_alert(self):
        mentions = [
            sentiment_scraper.MediaMention(
                mention_id="m1",
                title="Abley brand is a fake fraud",
                source="Google News",
                url="http://news.com/abley",
                sentiment_score=-0.7,
                backlink_present=False,
                published_date="now"
            )
        ]

        alerts = self.scraper.process_media_mentions(mentions)
        self.assertLen(alerts, 1)
        self.assertEqual(alerts[0].source_review_id, "m1")
        self.assertIn("fake", alerts[0].message)

    def test_process_media_mentions_no_alert(self):
        mentions = [
            sentiment_scraper.MediaMention(
                mention_id="m2",
                title="Abley brand is awesome",
                source="TechCrunch",
                url="http://tc.com/abley",
                sentiment_score=0.9,
                backlink_present=True,
                published_date="now"
            )
        ]

        alerts = self.scraper.process_media_mentions(mentions)
        self.assertEmpty(alerts)

if __name__ == "__main__":
    absltest.main()
