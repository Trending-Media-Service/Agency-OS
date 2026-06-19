# Real Postgres API RLS verification
# Exercises RLS context setting (SELECT set_config) and RLS bypass during bootstrapping
# against a real PostgreSQL database (e.g. in CI or local postgres).
# Skips if no Postgres is reachable.

import os
from urllib.parse import urlparse
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import Base
from migrate import migrate as run_migrate
import app.main as mainmod
from app.database import get_db, get_worker_db, get_worker_session_maker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os",
)


def _pg_reachable(url: str) -> bool:
    import asyncio
    async def check():
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


# Skip module-level if postgres is not reachable
if not _pg_reachable(DATABASE_URL):
    pytest.skip("postgres not reachable or not responding — Postgres API RLS test skipped", allow_module_level=True)

APP_ROLE, APP_PW = "aos_api_rls_role", "aos_api_rls_password"
# The worker is a NON-superuser role configured exactly like prod (Cloud SQL):
# DML grants + a permissive worker_bypass policy emulating BYPASSRLS. Using the
# superuser for the worker (as before) hid the prod create_tenant 500 — a real
# superuser bypasses RLS/grants for free, unlike the Cloud SQL worker role.
WORKER_ROLE, WORKER_PW = "aos_api_rls_worker", "aos_api_rls_worker_password"


@pytest.fixture(scope="module")
async def setup_postgres_schema():
    """Initializes the postgres database schema, creates the RLS role, and grants permissions."""
    admin_engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    
    # Reset database schema. NOTE: Base.metadata.drop_all does NOT drop Alembic's
    # alembic_version table — if left behind, run_migrate (alembic upgrade head) becomes
    # a no-op and the tables are never recreated, which breaks any later Postgres test
    # that shares this database. Drop it explicitly so migrations always rebuild.
    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Run migrations to create tables & enable RLS
    await run_migrate(admin_engine)

    # Create restricted RLS app role (tenant-isolated, like aos_app in prod).
    async with admin_engine.begin() as conn:
        await conn.execute(text(
            f"DO $$ BEGIN CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PW}'; "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        await conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"))
        await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"))

    # Create the NON-superuser worker role and configure it exactly like prod:
    # grants + a permissive worker_bypass policy on every RLS table (emulated
    # BYPASSRLS). This mirrors control-plane/scripts/setup_worker_role.sql so the
    # test exercises the real Cloud SQL worker configuration, not a superuser.
    async with admin_engine.begin() as conn:
        await conn.execute(text(
            f"DO $$ BEGIN CREATE ROLE {WORKER_ROLE} LOGIN PASSWORD '{WORKER_PW}'; "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {WORKER_ROLE}"))
        await conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {WORKER_ROLE}"))
        await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {WORKER_ROLE}"))
        await conn.execute(text(
            "DO $$ DECLARE r record; BEGIN "
            "FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity LOOP "
            "EXECUTE format('DROP POLICY IF EXISTS worker_bypass ON public.%I', r.relname); "
            "EXECUTE format('CREATE POLICY worker_bypass ON public.%I AS PERMISSIVE FOR ALL TO "
            f"{WORKER_ROLE} USING (true) WITH CHECK (true)', r.relname); "
            "END LOOP; END $$"))

    yield admin_engine

    # Cleanup RLS role and tables. Drop alembic_version too so this test leaves a clean
    # slate — otherwise the next Postgres test's run_migrate no-ops and its tables are
    # missing (this is what was erroring test_rls.py with 'relation "tenants" does not exist').
    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # drops tables AND their RLS policies
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        for role in (APP_ROLE, WORKER_ROLE):
            await conn.execute(text(f"DROP OWNED BY {role}"))
            await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
    await admin_engine.dispose()


@pytest.fixture()
async def rls_api_client(setup_postgres_schema, monkeypatch):
    """Overrides app database session makers to use the restricted RLS role for normal queries

    and the privileged admin role for worker/bootstrap queries.
    Exercises the ACTUAL get_db and get_worker_db implementations.
    """
    p = urlparse(DATABASE_URL)

    # 1. Worker engine — runs as the NON-superuser WORKER_ROLE (grants + worker_bypass
    #    policy), mirroring the Cloud SQL worker. NOT the superuser: that is the whole
    #    point of this test, so create_tenant's permission path is actually exercised.
    worker_url = f"postgresql+asyncpg://{WORKER_ROLE}:{WORKER_PW}@{p.hostname}:{p.port or 5432}{p.path}"
    worker_engine = create_async_engine(worker_url, poolclass=NullPool)
    worker_session_maker = async_sessionmaker(worker_engine, expire_on_commit=False)

    # 2. App engine — runs as APP_ROLE (RLS active, tenant-isolated).
    app_url = f"postgresql+asyncpg://{APP_ROLE}:{APP_PW}@{p.hostname}:{p.port or 5432}{p.path}"
    app_engine = create_async_engine(app_url, poolclass=NullPool)
    app_session_maker = async_sessionmaker(app_engine, expire_on_commit=False)

    # Monkeypatch the session makers in app.database to use our test engines
    import app.database as dbmod
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", app_session_maker)
    monkeypatch.setattr(dbmod, "WorkerAsyncSessionLocal", worker_session_maker)
    monkeypatch.setattr(dbmod, "engine", app_engine)
    monkeypatch.setattr(dbmod, "worker_engine", worker_engine)

    # SQL Spying on the RLS engine
    from sqlalchemy import event
    sql_statements = []

    @event.listens_for(app_engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql_statements.append(statement)

    async with AsyncClient(transport=ASGITransport(app=mainmod.app), base_url="http://test") as ac:
        ac.sql_statements = sql_statements  # Attach spy log to client
        yield ac

    await app_engine.dispose()
    await worker_engine.dispose()


async def test_postgres_api_onboarding_and_rls_isolation(rls_api_client):
    """End-to-end API test verifying tenant onboarding and RLS isolation on real Postgres.

    1. POST /tenants -> Bootstraps tenant & brand using get_worker_db (RLS bypassed).
    2. GET /ops -> Fetches operations as newly created tenant (RLS active, set_config executed).
    3. GET /connections -> Fetches connections as newly created tenant.
    """
    # Step 1: Onboard a brand-new tenant and brand
    onboard_res = await rls_api_client.post(
        "/tenants",
        json={"name": "Ableys Corp", "brand_name": "Ableys Retail"},
        headers={"Authorization": f"Bearer {os.getenv('OPERATOR_TOKEN', 'default-dev-token')}"},
    )
    assert onboard_res.status_code == 200
    data = onboard_res.json()
    tenant_id = data["tenant_id"]
    brand_id = data["brand_id"]
    assert tenant_id is not None
    assert brand_id is not None

    # Clear recorded SQL statements before RLS call so we only check the GET /ops call
    rls_api_client.sql_statements.clear()

    # Step 2: Query tenant-scoped operations using the new X-Tenant-ID header
    # This exercises the actual get_db's RLS set_config call.
    ops_res = await rls_api_client.get(
        "/ops",
        headers={"X-Tenant-ID": tenant_id}
    )
    assert ops_res.status_code == 200
    assert ops_res.json() == []  # Successfully RLS-isolated and returns empty list!

    # Assertions on executed SQL for Step 2
    sql_logs = rls_api_client.sql_statements
    
    # We expect SELECT set_config to have been executed
    set_config_calls = [s for s in sql_logs if "set_config" in s]
    assert len(set_config_calls) > 0, "Expected set_config to be called for RLS context"
    assert any("app.current_tenant_id" in s for s in set_config_calls), "Expected app.current_tenant_id to be set in set_config"

    # We expect SET LOCAL to NEVER be used (as it was the source of the prod 500)
    set_local_calls = [s for s in sql_logs if "SET LOCAL" in s.upper()]
    assert len(set_local_calls) == 0, f"Detected forbidden 'SET LOCAL' call: {set_local_calls}"

    # Step 3: Query tenant-scoped connections using the new X-Tenant-ID header
    conns_res = await rls_api_client.get(
        "/connections",
        headers={"X-Tenant-ID": tenant_id}
    )
    assert conns_res.status_code == 200
    assert conns_res.json() == []  # Successfully RLS-isolated and returns empty list!

    # Step 4: list_tenants (GET /tenants) reads ACROSS tenants via the worker role.
    # No X-Tenant-ID / no RLS context is set, so this only returns the tenant if the
    # worker role actually bypasses RLS (the worker_bypass policy). With a plain
    # RLS-enforced role this would be [] — and create_tenant in Step 1 would have
    # 500'd with "permission denied for table tenants" (the prod bug this guards).
    list_res = await rls_api_client.get(
        "/tenants",
        headers={"Authorization": f"Bearer {os.getenv('OPERATOR_TOKEN', 'default-dev-token')}"},
    )
    assert list_res.status_code == 200
    listed = list_res.json()
    assert any(t["tenant_id"] == tenant_id for t in listed), (
        "Worker role must read across tenants (emulated BYPASSRLS); "
        f"created tenant {tenant_id} not in {listed}"
    )
