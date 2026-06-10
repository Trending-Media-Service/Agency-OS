# Agency OS — DB Client with Buffer Ingestion Queue
import time
import typing
from google3.learning.gemini.agents.projects.agency_os import ingestion

class DatabaseConnectionError(Exception):
    """Raised when the database connection fails."""
    pass

class MockDatabaseClient:
    """Simulates a database client that can fail transiently."""

    def __init__(self):
        self.connected = True
        self.writes: typing.List[ingestion.NormalizedOrder] = []

    def write_order(self, order: ingestion.NormalizedOrder) -> None:
        if not self.connected:
            raise DatabaseConnectionError("Database connection is down.")
        self.writes.append(order)


class BufferedDatabaseClient:
    """Wraps DB client to queue writes in a buffer queue when DB is down."""

    def __init__(self, db_client: MockDatabaseClient):
        self.db_client = db_client
        self.buffer_queue: typing.List[ingestion.NormalizedOrder] = []

    def write_order(self, order: ingestion.NormalizedOrder) -> bool:
        """Writes order immediately or queues it in buffer if DB is down."""
        try:
            self.db_client.write_order(order)
            return True
        except DatabaseConnectionError:
            self.buffer_queue.append(order)
            return False

    def retry_flush(
        self,
        max_retries: int = 3,
        initial_backoff: float = 0.1,
        sleep_fn: typing.Callable[[float], None] = time.sleep
    ) -> bool:
        """Attempts to flush the queued orders with exponential backoff retry."""
        backoff = initial_backoff
        for _ in range(max_retries):
            if not self.buffer_queue:
                return True
            try:
                # Try to write all queued orders
                while self.buffer_queue:
                    order = self.buffer_queue[0]
                    self.db_client.write_order(order)
                    # Remove from queue only after successful write
                    self.buffer_queue.pop(0)
                return True
            except DatabaseConnectionError:
                # connection failed, sleep and increase backoff
                sleep_fn(backoff)
                backoff *= 2
        return len(self.buffer_queue) == 0
