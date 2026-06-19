import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_metrics_endpoint_and_middleware(client):
    # 1. Trigger the metrics middleware by making a request to healthz
    resp_health = client.get("/healthz")
    assert resp_health.status_code == 200
    
    # 2. Scraping the metrics endpoint (should work without X-Tenant-ID due to bypass)
    resp_metrics = client.get("/metrics")
    assert resp_metrics.status_code == 200
    assert resp_metrics.headers.get("content-type").startswith("text/plain")
    
    metrics_text = resp_metrics.text
    assert "http_requests_total" in metrics_text
    assert "http_request_duration_seconds" in metrics_text
    
    # Check that our request to /healthz was recorded with status 200
    expected_label = 'path="/healthz"'
    assert expected_label in metrics_text
    assert 'status="200"' in metrics_text
