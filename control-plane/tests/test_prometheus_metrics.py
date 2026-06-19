# Feature 4 Prometheus Telemetry and Observability tests
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(client):
    """Test 46: Verify that the Prometheus scrape endpoint exists and returns standard text/plain formatting."""
    # Trigger a request to populate middleware metrics
    await client.get("/healthz")
    
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    
    metrics_text = resp.text
    assert "# HELP" in metrics_text
    assert "# TYPE" in metrics_text

@pytest.mark.asyncio
async def test_http_request_duration_histogram(client):
    """Verify that HTTP latency and request count histograms are recorded with path and method labels."""
    await client.get("/healthz")
    
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    metrics_text = resp.text
    
    # Assert standard middleware metrics are present
    assert "http_requests_total" in metrics_text
    assert "http_request_duration_seconds" in metrics_text
    assert 'path="/healthz"' in metrics_text
    assert 'method="GET"' in metrics_text

@pytest.mark.asyncio
async def test_active_connections_gauge(client, session):
    """Verify connection status changes trigger increment/decrement of connection status gauge metrics."""
    # Trigger a scraping of metrics
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    metrics_text = resp.text
    
    # The production code doesn't implement this gauge yet.
    # We assert that the metric is registered, which will fail (expected Red state).
    assert "aos_connections_active" in metrics_text or "connection_status" in metrics_text

@pytest.mark.asyncio
async def test_outbox_lag_gauge(client):
    """Verify outbox lag (pending items) and retry metrics are registered in Prometheus."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    metrics_text = resp.text
    
    # The production code doesn't implement this gauge yet.
    # We assert that the metric is registered, which will fail (expected Red state).
    assert "aos_outbox_lag" in metrics_text or "outbox_pending" in metrics_text
