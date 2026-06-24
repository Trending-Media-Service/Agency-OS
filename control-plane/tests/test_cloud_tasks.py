import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi import BackgroundTasks
from app.tasks import enqueue_drain
import asyncio


@pytest.fixture
def mock_tasks_client():
    """Mock the Google Cloud Tasks client and its module."""
    # Create mock classes
    mock_client_inst = MagicMock()
    mock_client_class = MagicMock(return_value=mock_client_inst)
    
    # Setup mock queue path helper
    mock_client_inst.queue_path.return_value = "projects/mock-proj/locations/mock-loc/queues/mock-queue"
    mock_client_inst.create_task.return_value = MagicMock(name="mock-task-name")

    # Mock the tasks_v2 module and inject it into sys.modules to handle lazy import
    mock_tasks_v2 = MagicMock()
    mock_tasks_v2.CloudTasksClient = mock_client_class
    mock_tasks_v2.HttpMethod.POST = "POST"

    with patch.dict(sys.modules, {"google.cloud.tasks_v2": mock_tasks_v2}):
        yield mock_client_inst


def test_enqueue_drain_cloud_tasks_with_oidc(mock_tasks_client, monkeypatch):
    """Verify that enqueue_drain enqueues a Cloud Task with OIDC token when GCP configs and WORKER_SA are set."""
    # 1. Setup environment
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.setenv("GCP_LOCATION", "asia-south1")
    monkeypatch.setenv("OUTBOX_QUEUE_NAME", "test-queue")
    monkeypatch.setenv("APP_URL", "https://test-app.run.app")
    monkeypatch.setenv("AOS_WORKER_SERVICE_ACCOUNT", "worker@test-project.iam.gserviceaccount.com")

    # Reload variables in tasks module since they are evaluated at import time!
    import app.tasks as tasks
    monkeypatch.setattr(tasks, "GCP_PROJECT", "test-project")
    monkeypatch.setattr(tasks, "GCP_LOCATION", "asia-south1")
    monkeypatch.setattr(tasks, "QUEUE_NAME", "test-queue")
    monkeypatch.setattr(tasks, "APP_URL", "https://test-app.run.app")
    monkeypatch.setattr(tasks, "WORKER_SA", "worker@test-project.iam.gserviceaccount.com")

    bg_tasks = BackgroundTasks()

    # 2. Call enqueue_drain
    enqueue_drain(bg_tasks)

    # 3. Execute the deferred background task
    assert len(bg_tasks.tasks) == 1
    # Run the background task synchronously to trigger the mock
    asyncio.run(bg_tasks.tasks[0]())

    # 4. Assertions
    mock_tasks_client.queue_path.assert_called_once_with("test-project", "asia-south1", "test-queue")
    
    expected_task = {
        "http_request": {
            "http_method": "POST",
            "url": "https://test-app.run.app/tasks/drain-outbox",
            "oidc_token": {
                "service_account_email": "worker@test-project.iam.gserviceaccount.com"
            }
        }
    }
    
    mock_tasks_client.create_task.assert_called_once_with(
        request={
            "parent": "projects/mock-proj/locations/mock-loc/queues/mock-queue",
            "task": expected_task
        }
    )


def test_enqueue_drain_cloud_tasks_no_oidc_when_sa_missing(mock_tasks_client, monkeypatch):
    """Verify that the OIDC token block is omitted from the Cloud Task if WORKER_SA is not configured."""
    # 1. Setup environment (no WORKER_SA)
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.setenv("GCP_LOCATION", "asia-south1")
    monkeypatch.setenv("OUTBOX_QUEUE_NAME", "test-queue")
    monkeypatch.setenv("APP_URL", "https://test-app.run.app")
    monkeypatch.delenv("AOS_WORKER_SERVICE_ACCOUNT", raising=False)

    # Reload variables
    import app.tasks as tasks
    monkeypatch.setattr(tasks, "GCP_PROJECT", "test-project")
    monkeypatch.setattr(tasks, "GCP_LOCATION", "asia-south1")
    monkeypatch.setattr(tasks, "QUEUE_NAME", "test-queue")
    monkeypatch.setattr(tasks, "APP_URL", "https://test-app.run.app")
    monkeypatch.setattr(tasks, "WORKER_SA", None)

    bg_tasks = BackgroundTasks()

    # 2. Call enqueue_drain
    enqueue_drain(bg_tasks)

    # 3. Execute the deferred background task
    assert len(bg_tasks.tasks) == 1
    asyncio.run(bg_tasks.tasks[0]())

    # 4. Assertions
    expected_task = {
        "http_request": {
            "http_method": "POST",
            "url": "https://test-app.run.app/tasks/drain-outbox"
            # oidc_token must be absent!
        }
    }
    
    mock_tasks_client.create_task.assert_called_once_with(
        request={
            "parent": "projects/mock-proj/locations/mock-loc/queues/mock-queue",
            "task": expected_task
        }
    )


def test_enqueue_drain_local_fallback(monkeypatch):
    """Verify that enqueue_drain gracefully falls back to FastAPI BackgroundTasks if GCP configs are missing."""
    # 1. Clear environment GCP configs
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GCP_LOCATION", raising=False)
    monkeypatch.delenv("OUTBOX_QUEUE_NAME", raising=False)
    monkeypatch.delenv("APP_URL", raising=False)

    # Reload variables in tasks module
    import app.tasks as tasks
    monkeypatch.setattr(tasks, "GCP_PROJECT", None)
    monkeypatch.setattr(tasks, "GCP_LOCATION", None)
    monkeypatch.setattr(tasks, "QUEUE_NAME", None)
    monkeypatch.setattr(tasks, "APP_URL", None)

    # Mock the BackgroundTasks.add_task method
    bg_tasks = BackgroundTasks()
    mock_add_task = MagicMock()
    monkeypatch.setattr(bg_tasks, "add_task", mock_add_task)

    # 2. Call enqueue_drain
    enqueue_drain(bg_tasks)

    # 3. Assertions: it must add the local drain task to background tasks!
    mock_add_task.assert_called_once()
    args, kwargs = mock_add_task.call_args
    assert args[0] == tasks._drain_local_task
