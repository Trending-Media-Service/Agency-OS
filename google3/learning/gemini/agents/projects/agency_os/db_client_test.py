# DB Client buffer tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import db_client
from google3.learning.gemini.agents.projects.agency_os import ingestion

class DbClientTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.mock_db = db_client.MockDatabaseClient()
        self.buffered_client = db_client.BufferedDatabaseClient(self.mock_db)
        # Create a mock order
        self.order = ingestion.NormalizedOrder(
            order_id="101",
            tenant_id="tenant-1",
            gross_revenue=100.0,
            discounts=0.0,
            shipping=0.0,
            tax=0.0,
            refunds=0.0,
            line_items=[],
            customer_email="hash1",
            customer_phone="hash2",
            created_at="now"
        )

    def test_direct_write_success(self):
        success = self.buffered_client.write_order(self.order)
        self.assertTrue(success)
        self.assertLen(self.mock_db.writes, 1)
        self.assertEmpty(self.buffered_client.buffer_queue)

    def test_write_buffers_when_down(self):
        self.mock_db.connected = False
        success = self.buffered_client.write_order(self.order)
        self.assertFalse(success)
        self.assertEmpty(self.mock_db.writes)
        self.assertLen(self.buffered_client.buffer_queue, 1)
        self.assertEqual(self.buffered_client.buffer_queue[0], self.order)

    def test_retry_flush_success_after_reconnect(self):
        # Disconnect and write to buffer
        self.mock_db.connected = False
        self.buffered_client.write_order(self.order)
        self.assertLen(self.buffered_client.buffer_queue, 1)

        # Reconnect and flush
        self.mock_db.connected = True
        sleep_durations = []
        def mock_sleep(seconds: float):
            sleep_durations.append(seconds)

        success = self.buffered_client.retry_flush(
            max_retries=3,
            initial_backoff=0.1,
            sleep_fn=mock_sleep
        )

        self.assertTrue(success)
        self.assertLen(self.mock_db.writes, 1)
        self.assertEmpty(self.buffered_client.buffer_queue)
        # No retries needed as it succeeded instantly on first loop
        self.assertEmpty(sleep_durations)

    def test_retry_flush_backoff_and_fail(self):
        self.mock_db.connected = False
        self.buffered_client.write_order(self.order)

        sleep_durations = []
        def mock_sleep(seconds: float):
            sleep_durations.append(seconds)

        # Keep connected = False, should retry and fail
        success = self.buffered_client.retry_flush(
            max_retries=3,
            initial_backoff=0.1,
            sleep_fn=mock_sleep
        )

        self.assertFalse(success)
        self.assertEmpty(self.mock_db.writes)
        self.assertLen(self.buffered_client.buffer_queue, 1)
        # Expecting 3 retries (attempts 1, 2, 3 fail, sleeps in between)
        # Attempt 1 fails -> sleeps 0.1
        # Attempt 2 fails -> sleeps 0.2
        # Attempt 3 fails -> sleeps 0.4
        self.assertEqual(sleep_durations, [0.1, 0.2, 0.4])

if __name__ == "__main__":
    absltest.main()
