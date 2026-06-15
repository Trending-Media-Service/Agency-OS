"""CORS regression tests.

The operator/brand console is served from a separate Cloud Run origin, so every
browser call to this API is cross-origin. These tests prove:
  1. A preflight OPTIONS to a tenant-scoped route is answered by CORSMiddleware
     (200 + access-control-allow-origin) and is NOT rejected by
     TenantIsolationMiddleware (which would 400 a preflight carrying no
     X-Tenant-ID header). This is the bug that left the console stuck on
     "Loading…" with a CORRUPT audit badge.
  2. Actual responses to an allowed origin carry the ACAO header.
  3. A disallowed origin gets no ACAO header.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

ALLOWED = "http://localhost:3000"
DISALLOWED = "https://evil.example.com"


@pytest.mark.asyncio
async def test_preflight_on_tenant_scoped_route_not_blocked_by_tenant_mw():
    # OPTIONS preflight carries no X-Tenant-ID — must still succeed because
    # CORSMiddleware is outermost and short-circuits before the tenant gate.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.options(
            "/ops",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-tenant-id, content-type",
            },
        )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ALLOWED


@pytest.mark.asyncio
async def test_actual_response_has_acao_for_allowed_origin():
    # /healthz is exempt from the tenant gate and needs no DB.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/healthz", headers={"Origin": ALLOWED})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ALLOWED


@pytest.mark.asyncio
async def test_disallowed_origin_gets_no_acao():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/healthz", headers={"Origin": DISALLOWED})
    assert "access-control-allow-origin" not in res.headers
