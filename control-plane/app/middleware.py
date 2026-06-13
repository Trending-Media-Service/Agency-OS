from app.database import tenant_context
from app.observability import trace_context
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import uuid


class TraceMiddleware(BaseHTTPMiddleware):
  """Generates or propagates trace IDs to coordinate logs and telemetry across service hops."""

  async def dispatch(self, request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or request.headers.get("traceparent")
    if not trace_id:
      trace_id = f"tr-{uuid.uuid4().hex[:16]}"

    token = trace_context.set(trace_id)
    try:
      response = await call_next(request)
      response.headers["X-Trace-ID"] = trace_id
      return response
    finally:
      trace_context.reset(token)



class TenantIsolationMiddleware(BaseHTTPMiddleware):
  """Parses and asserts valid tenant headers across all endpoint executions,
  populating async-safe storage boundaries to prevent database leaks.
  """

  async def dispatch(self, request: Request, call_next):
    # Header format: X-Tenant-ID
    tenant_id = request.headers.get("X-Tenant-ID")

    # Bypass validation strictly on public API paths
    if request.url.path in ["/health", "/docs", "/openapi.json", "/tenants", "/audit/verify", "/tasks/drain-outbox", "/webhooks/whatsapp", "/tasks/trust-snapshots"]:
      return await call_next(request)

    if not tenant_id:
      return JSONResponse(
          status_code=status.HTTP_401_UNAUTHORIZED,
          content={"detail": "X-Tenant-ID header is missing."},
      )

    # Set tenant identification safely across the current thread-safe context
    token = tenant_context.set(tenant_id)
    try:
      response = await call_next(request)
      return response
    finally:
      # Safely clear the active context after processing ends
      tenant_context.reset(token)
