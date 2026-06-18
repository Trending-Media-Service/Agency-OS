import pytest
import logging
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.observability import trace_context

# Register a temporary test route that raises an unhandled exception
@app.get("/test-error-trigger")
async def trigger_error():
    raise RuntimeError("simulated boom error")

@pytest.mark.asyncio
async def test_global_exception_handler(caplog):
    # Set a mock trace ID in the trace context to verify the handler retrieves and returns it
    trace_context.set("mock-trace-12345")
    
    # We must pass the X-Tenant-Id header to pass the TenantIsolationMiddleware!
    headers = {"X-Tenant-Id": "t-test-tenant"}
    
    # We MUST set raise_app_exceptions=False so that the AsyncClient returns the 500 response
    # sent by the ServerErrorMiddleware instead of crashing the test with the re-raised RuntimeError!
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with caplog.at_level(logging.ERROR):
            res = await ac.get("/test-error-trigger", headers=headers)
            
    assert res.status_code == 500
    data = res.json()
    assert data["detail"] == "Internal server error"
    assert data["trace_id"] == "mock-trace-12345"
    
    # Verify that the unhandled exception was logged with traceback
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "ERROR"
    assert "Unhandled exception on GET /test-error-trigger" in record.message
    assert "simulated boom error" in record.message
    assert record.exc_info is not None  # Verifies that exception details/traceback are attached!
