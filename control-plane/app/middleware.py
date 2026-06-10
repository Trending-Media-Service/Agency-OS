from app.database import tenant_context
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware


class TenantIsolationMiddleware(BaseHTTPMiddleware):
  """Parses and asserts valid tenant headers across all endpoint executions,

  populating async-safe storage boundaries to prevent database leaks.
  """

  async def dispatch(self, request: Request, call_next):
    # Header format: X-Tenant-ID
    tenant_id = request.headers.get("X-Tenant-ID")

    # Bypass validation strictly on public API paths
    if request.url.path in ["/health", "/docs", "/openapi.json"]:
      return await call_next(request)

    if not tenant_id:
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail="X-Tenant-ID header is missing.",
      )

    # Set tenant identification safely across the current thread-safe context
    token = tenant_context.set(tenant_id)
    try:
      response = await call_next(request)
      return response
    finally:
      # Safely clear the active context after processing ends
      tenant_context.reset(token)
