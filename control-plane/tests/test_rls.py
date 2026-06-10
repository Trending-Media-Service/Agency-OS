# Real Postgres RLS verification (issue #2). Skips when no Postgres is reachable
# (local dev); runs for real in CI against the postgres service container.
#
# Two fixes over the first draft of this test:
#   1. Tables must be FORCE ROW LEVEL SECURITY and queried by a NON-superuser
#      role — the postgres superuser bypasses RLS unconditionally, so the
#      original test could never prove isolation.
#   2. Uses the kernel's actual Base/models (app.models), not a parallel one —
#      one metadata, one system of record (ARCHITECTURE.md §2.7).
import os
import socket
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base

ADMIN_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os",
)


def _pg_reachable(url: str) -> bool:
    p = urlparse(url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((p.hostname or "localhost", p.port or 5432), timeout=1):
            return True
    except OSError:
        return False


if not _pg_reachable(ADMIN_URL):
    pytest.skip("postgres not reachable — RLS test runs in CI", allow_module_level=True)

APP_ROLE, APP_PW = "aos_app_rls", "aos_app_rls_pw"


@pytest.fixture(scope="module")
async def rls_db():
    admin = create_async_engine(ADMIN_URL, poolclass=NullPool)
    async with admin.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        for tbl, col in (("tenants", "id"), ("brands", "tenant_id")):
            await conn.execute(text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(
                f"CREATE POLICY tenant_isolation_{tbl} ON {tbl} FOR ALL "
                f"USING ({col} = current_setting('app.current_tenant_id', true))"))
        await conn.execute(text(
            f"DO $$ BEGIN CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PW}'; "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        await conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"))
        # Seed two tenants as admin (admin bypasses RLS — that is expected)
        await conn.execute(text(
            "INSERT INTO tenants (id, name, hosting_tier, created_at) VALUES "
            "('tenant-a','Tanmatra','shared',now()), ('tenant-b','Ableys','shared',now())"))
        await conn.execute(text(
            "INSERT INTO brands (id, tenant_id, name, created_at) VALUES "
            "('brand-wok','tenant-a','Wok-Tok',now()), ('brand-abl','tenant-b','Ableys',now())"))

    p = urlparse(ADMIN_URL)
    app_url = f"postgresql+asyncpg://{APP_ROLE}:{APP_PW}@{p.hostname}:{p.port or 5432}{p.path}"
    app_engine = create_async_engine(app_url, poolclass=NullPool)
    yield async_sessionmaker(app_engine, expire_on_commit=False)

    await app_engine.dispose()
    async with admin.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text(f"DROP OWNED BY {APP_ROLE}"))
        await conn.execute(text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
    await admin.dispose()


async def _visible_brands(sessions, tenant_id):
    async with sessions() as s:
        async with s.begin():
            if tenant_id is not None:
                await s.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            rows = await s.execute(text("SELECT id FROM brands ORDER BY id"))
            return [r[0] for r in rows]


async def test_rls_isolates_tenants(rls_db):
    assert await _visible_brands(rls_db, "tenant-a") == ["brand-wok"]
    assert await _visible_brands(rls_db, "tenant-b") == ["brand-abl"]


async def test_rls_no_context_means_no_rows(rls_db):
    # Fail-closed: a session that never asserted a tenant sees NOTHING.
    assert await _visible_brands(rls_db, None) == []


async def test_rls_blocks_cross_tenant_write(rls_db):
    with pytest.raises(Exception) as exc:
        async with rls_db() as s:
            async with s.begin():
                await s.execute(text("SELECT set_config('app.current_tenant_id', 'tenant-a', true)"))
                await s.execute(text(
                    "INSERT INTO brands (id, tenant_id, name, created_at) "
                    "VALUES ('evil','tenant-b','X',now())"))
    assert "row-level security" in str(exc.value).lower()
