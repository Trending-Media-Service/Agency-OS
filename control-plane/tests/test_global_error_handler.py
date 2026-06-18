import pytest
import logging

class ListHandler(logging.Handler):
    """Custom logging handler to capture log records in-memory, isolated from global test pollution."""
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

@pytest.mark.asyncio
async def test_global_exception_handler():
    # Dynamically import to ensure synchronization with the latest sys.modules state
    from app.main import app
    from app.observability import trace_context
    from httpx import AsyncClient, ASGITransport

    # Register the temporary test route dynamically on the active app instance
    route_paths = [r.path for r in app.routes]
    if "/test-error-trigger" not in route_paths:
        @app.get("/test-error-trigger")
        async def trigger_error():
            raise RuntimeError("simulated boom error")

    # Set a mock trace ID in the trace context to verify the handler retrieves and returns it
    trace_context.set("mock-trace-12345")
    
    # We must pass the X-Tenant-Id header to pass the TenantIsolationMiddleware!
    headers = {"X-Tenant-Id": "t-test-tenant"}
    
    # Get the app.main logger and explicitly force its level to DEBUG and enable it to prevent other tests from silencing or disabling it
    test_logger = logging.getLogger("app.main")
    original_level = test_logger.level
    original_disabled = test_logger.disabled
    test_logger.setLevel(logging.DEBUG)
    test_logger.disabled = False
    
    # Add our custom isolated log handler configured to capture all records
    handler = ListHandler()
    handler.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    
    try:
        # We MUST set raise_app_exceptions=False so that the AsyncClient returns the 500 response
        # sent by the ServerErrorMiddleware instead of crashing the test with the re-raised RuntimeError!
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/test-error-trigger", headers=headers)
                
        assert res.status_code == 500
        data = res.json()
        assert data["detail"] == "Internal server error"
        assert data["trace_id"] == "mock-trace-12345"
        
        # Verify that the unhandled exception was logged with traceback in our isolated handler
        assert len(handler.records) == 1
        record = handler.records[0]
        assert record.levelname == "ERROR"
        assert "Unhandled exception on GET /test-error-trigger" in record.getMessage()
        assert "simulated boom error" in record.getMessage()
        assert record.exc_info is not None  # Verifies that exception details/traceback are attached!
        
    finally:
        # Restore the logger's original level, disabled state, and remove the handler to prevent pollution
        test_logger.removeHandler(handler)
        test_logger.setLevel(original_level)
        test_logger.disabled = original_disabled
