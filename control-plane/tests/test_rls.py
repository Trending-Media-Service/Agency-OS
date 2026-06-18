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
from migrate import migrate as run_migrate

ADMIN_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os",
)


def _pg_reachable(url: str) -> bool:
    import asyncio
    async def check():
        # Short timeout for connection attempt
        engine = create_async_engine(url, connect_args={"timeout": 1.0}, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()
    try:
        return asyncio.run(check())
    except Exception:
        return False

if not _pg_reachable(ADMIN_URL):
    pytest.skip("postgres not reachable or not responding — RLS test skipped", allow_module_level=True)

APP_ROLE, APP_PW = "aos_app_rls", "aos_app_rls_pw"


@pytest.fixture(scope="module")
async def rls_db():
    admin = create_async_engine(ADMIN_URL, poolclass=NullPool)
    async with admin.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # drop_all leaves Alembic's version table; without dropping it, run_migrate
        # below would no-op and leave no tables (order-independent robustness).
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Run migration to create tables and enable RLS
    await run_migrate(admin)

    async with admin.begin() as conn:
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
        await conn.execute(text(
            "INSERT INTO ops (id, tenant_id, brand_id, domain, action, state, impact, reversibility, params, "
            "statutory, sequence_order, created_at, updated_at, idem_key) VALUES "
            "('op-a', 'tenant-a', 'brand-wok', 'web', 'deploy', 'DONE', 1, 'reversible', '{}', false, 0, now(), now(), 'idem-a'), "
            "('op-b', 'tenant-b', 'brand-abl', 'web', 'deploy', 'DONE', 1, 'reversible', '{}', false, 0, now(), now(), 'idem-b')"))
        await conn.execute(text(
            "INSERT INTO op_traces (tenant_id, op_id, kind, detail, ts) VALUES "
            "('tenant-a', 'op-a', 'note', '{}', now()), "
            "('tenant-b', 'op-b', 'note', '{}', now())"))
        await conn.execute(text(
            "INSERT INTO approvals (id, tenant_id, op_id, actor, role, surface, decision, ts) VALUES "
            "('app-a', 'tenant-a', 'op-a', 'user-a', 'owner', 'web', 'approve', now()), "
            "('app-b', 'tenant-b', 'op-b', 'user-b', 'owner', 'web', 'approve', now())"))
        await conn.execute(text(
            "INSERT INTO orders (id, tenant_id, brand_id, amount_minor, currency, placed_at, created_at) VALUES "
            "('order-a', 'tenant-a', 'brand-wok', 100, 'INR', now(), now()), "
            "('order-b', 'tenant-b', 'brand-abl', 100, 'INR', now(), now())"))
        await conn.execute(text(
            "INSERT INTO outbox (op_id, tenant_id, status, attempts, next_attempt_at, created_at) VALUES "
            "('op-a', 'tenant-a', 'PENDING', 0, now(), now()), "
            "('op-b', 'tenant-b', 'PENDING', 0, now(), now())"))

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


async def _get_ids(sessions, table_name, tenant_id):
    async with sessions() as s:
        async with s.begin():
            if tenant_id is not None:
                await s.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            rows = await s.execute(text(f"SELECT id FROM {table_name} ORDER BY id"))
            return [r[0] for r in rows]


async def _get_op_traces_op_ids(sessions, tenant_id):
    async with sessions() as s:
        async with s.begin():
            if tenant_id is not None:
                await s.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            rows = await s.execute(text("SELECT op_id FROM op_traces ORDER BY op_id"))
            return [r[0] for r in rows]


async def test_rls_isolates_op_traces(rls_db):
    assert await _get_op_traces_op_ids(rls_db, "tenant-a") == ["op-a"]
    assert await _get_op_traces_op_ids(rls_db, "tenant-b") == ["op-b"]


async def test_rls_isolates_approvals(rls_db):
    assert await _get_ids(rls_db, "approvals", "tenant-a") == ["app-a"]
    assert await _get_ids(rls_db, "approvals", "tenant-b") == ["app-b"]


async def test_rls_isolates_orders(rls_db):
    assert await _get_ids(rls_db, "orders", "tenant-a") == ["order-a"]
    assert await _get_ids(rls_db, "orders", "tenant-b") == ["order-b"]


async def test_rls_blocks_cross_tenant_read(rls_db):
    async with rls_db() as s:
        async with s.begin():
            # Assert that under tenant-a context, tenant-b's data is invisible even with direct ID lookup
            await s.execute(text("SELECT set_config('app.current_tenant_id', 'tenant-a', true)"))
            
            res_brand = await s.execute(text("SELECT id FROM brands WHERE id = 'brand-abl'"))
            assert res_brand.scalar_one_or_none() is None

            res_app = await s.execute(text("SELECT id FROM approvals WHERE id = 'app-b'"))
            assert res_app.scalar_one_or_none() is None

            res_order = await s.execute(text("SELECT id FROM orders WHERE id = 'order-b'"))
            assert res_order.scalar_one_or_none() is None

            res_msg = await s.execute(text("SELECT op_id FROM outbox WHERE op_id = 'op-b'"))
            assert res_msg.scalar_one_or_none() is None


async def _get_outbox_op_ids(sessions, tenant_id):
    async with sessions() as s:
        async with s.begin():
            if tenant_id is not None:
                await s.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            rows = await s.execute(text("SELECT op_id FROM outbox ORDER BY op_id"))
            return [r[0] for r in rows]


async def test_rls_isolates_outbox(rls_db):
    assert await _get_outbox_op_ids(rls_db, "tenant-a") == ["op-a"]
    assert await _get_outbox_op_ids(rls_db, "tenant-b") == ["op-b"]
