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
WORKER_SA = os.getenv("AOS_WORKER_SERVICE_ACCOUNT")

async def _drain_local_task(session_maker):
    """Local fallback: run drain_once directly with a privileged session."""
    print("\n[DEBUG] _drain_local_task STARTED")
    logger.info("Running local background outbox drain...")
    try:
        async with session_maker() as s:
            async with s.begin():
                processed = await loop.drain_once(s)
                print(f"[DEBUG] _drain_local_task processed {processed} items")
                logger.info(f"Local outbox drain processed {processed} items.")
    except Exception as e:
        print(f"[DEBUG] _drain_local_task FAILED: {e}")
        logger.error(f"Error in local background outbox drain: {e}", exc_info=True)

def enqueue_drain(background_tasks: BackgroundTasks, session_maker=None):
    """Enqueues a task to drain the outbox.

    Uses Cloud Tasks in GCP, falls back to FastAPI BackgroundTasks locally.
    """
    print(f"\n[DEBUG] enqueue_drain called, session_maker={session_maker}")
    if GCP_PROJECT and GCP_LOCATION and QUEUE_NAME and APP_URL:
        def _create_cloud_task(client, request_payload):
            try:
                response = client.create_task(request=request_payload)
                logger.info(f"Enqueued Cloud Task: {response.name}")
                print(f"[DEBUG] Enqueued Cloud Task: {response.name}")
            except Exception as e:
                logger.error(f"Failed to enqueue Cloud Task in background: {e}")

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
            if WORKER_SA:
                task["http_request"]["oidc_token"] = {
                    "service_account_email": WORKER_SA
                }
            
            # Offload the blocking synchronous GCP client call to the background tasks pool
            background_tasks.add_task(_create_cloud_task, client, {"parent": parent, "task": task})
            return
        except ImportError:
            logger.warning("google-cloud-tasks is not installed but GCP configs are set. Falling back to local.")
        except Exception as e:
            logger.error(f"Failed to setup Cloud Task request, falling back to local: {e}")

    # Local fallback
    if not session_maker:
        from app.database import WorkerAsyncSessionLocal
        session_maker = WorkerAsyncSessionLocal
    print("[DEBUG] Adding _drain_local_task to background_tasks")
    background_tasks.add_task(_drain_local_task, session_maker)
