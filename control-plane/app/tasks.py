import os
import logging
from fastapi import BackgroundTasks
from app.kernel import loop

logger = logging.getLogger(__name__)

# Configs for GCP Cloud Tasks
GCP_PROJECT = os.getenv("GCP_PROJECT")
GCP_LOCATION = os.getenv("GCP_LOCATION")
QUEUE_NAME = os.getenv("OUTBOX_QUEUE_NAME")
APP_URL = os.getenv("APP_URL")

async def _drain_local_task(session_maker):
    """Local fallback: run drain_once directly with a privileged session."""
    logger.info("Running local background outbox drain...")
    try:
        async with session_maker() as s:
            async with s.begin():
                processed = await loop.drain_once(s)
                logger.info(f"Local outbox drain processed {processed} items.")
    except Exception as e:
        logger.error(f"Error in local background outbox drain: {e}", exc_info=True)

def enqueue_drain(background_tasks: BackgroundTasks, session_maker=None):
    """Enqueues a task to drain the outbox.

    Uses Cloud Tasks in GCP, falls back to FastAPI BackgroundTasks locally.
    """
    if GCP_PROJECT and GCP_LOCATION and QUEUE_NAME and APP_URL:
        try:
            from google.cloud import tasks_v2
            client = tasks_v2.CloudTasksClient()
            parent = client.queue_path(GCP_PROJECT, GCP_LOCATION, QUEUE_NAME)

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{APP_URL}/tasks/drain-outbox",
                }
            }
            # We don't block the request waiting for Cloud Tasks API
            # but since create_task is sync, it might block slightly.
            # In a highly optimized setup, we could run this in a thread pool.
            response = client.create_task(request={"parent": parent, "task": task})
            logger.info(f"Enqueued Cloud Task: {response.name}")
            return
        except ImportError:
            logger.warning("google-cloud-tasks is not installed but GCP configs are set. Falling back to local.")
        except Exception as e:
            logger.error(f"Failed to enqueue Cloud Task, falling back to local: {e}")

    # Local fallback
    if not session_maker:
        from app.database import WorkerAsyncSessionLocal
        session_maker = WorkerAsyncSessionLocal
    background_tasks.add_task(_drain_local_task, session_maker)
