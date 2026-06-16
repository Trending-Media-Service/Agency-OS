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

    # Create restricted role and grant permissions
    async with admin_engine.begin() as conn:
        await conn.execute(text(
            f"DO $$ BEGIN CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PW}'; "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        await conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"))
        await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"))

    yield admin_engine

    # Cleanup RLS role and tables. Drop alembic_version too so this test leaves a clean
    # slate — otherwise the next Postgres test's run_migrate no-ops and its tables are
    # missing (this is what was erroring test_rls.py with 'relation "tenants" does not exist').
    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await conn.execute(text(f"DROP OWNED BY {APP_ROLE}"))
        await conn.execute(text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
    await admin_engine.dispose()


@pytest.fixture()
async def rls_api_client(setup_postgres_schema):
    """Overrides app database dependencies to use the restricted RLS role for normal queries

    and the privileged admin role for worker/bootstrap queries.
    """
    # 1. Privileged engine (admin/worker bypasses RLS)
    admin_engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    admin_session_maker = async_sessionmaker(admin_engine, expire_on_commit=False)

    # 2. Restricted engine (runs as APP_ROLE, RLS is active)
    p = urlparse(DATABASE_URL)
    app_url = f"postgresql+asyncpg://{APP_ROLE}:{APP_PW}@{p.hostname}:{p.port or 5432}{p.path}"
    app_engine = create_async_engine(app_url, poolclass=NullPool)
    app_session_maker = async_sessionmaker(app_engine, expire_on_commit=False)

    # Override get_db (restricted RLS role)
    async def override_get_db():
        async with app_session_maker() as session:
            await session.begin()
            # Injects the active tenant ID context at the DB connection level
            from app.database import tenant_context
            tenant_id = tenant_context.get()
            if tenant_id:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_id},
                )
            try:
                yield session
                if session.in_transaction():
                    await session.commit()
            except Exception:
                if session.in_transaction():
                    await session.rollback()
                raise

    # Override get_worker_db (privileged worker/bootstrap role)
    async def override_get_worker_db():
        async with admin_session_maker() as session:
            await session.begin()
            try:
                yield session
                if session.in_transaction():
                    await session.commit()
            except Exception:
                if session.in_transaction():
                    await session.rollback()
                raise

    # Override session maker for background task workers
    async def override_get_worker_session_maker():
        return admin_session_maker

    # Apply overrides
    mainmod.app.dependency_overrides[get_db] = override_get_db
    mainmod.app.dependency_overrides[get_worker_db] = override_get_worker_db
    mainmod.app.dependency_overrides[get_worker_session_maker] = override_get_worker_session_maker

    async with AsyncClient(transport=ASGITransport(app=mainmod.app), base_url="http://test") as ac:
        yield ac

    # Clear overrides and dispose engines
    mainmod.app.dependency_overrides.clear()
    await app_engine.dispose()
    await admin_engine.dispose()


async def test_postgres_api_onboarding_and_rls_isolation(rls_api_client):
    """End-to-end API test verifying tenant onboarding and RLS isolation on real Postgres.

    1. POST /tenants -> Bootstraps tenant & brand using get_worker_db (RLS bypassed).
    2. GET /ops -> Fetches operations as newly created tenant (RLS active, set_config executed).
    3. GET /connections -> Fetches connections as newly created tenant.
    """
    # Step 1: Onboard a brand-new tenant and brand
    onboard_res = await rls_api_client.post(
        "/tenants",
        json={"name": "Ableys Corp", "brand_name": "Ableys Retail"}
    )
    assert onboard_res.status_code == 200
    data = onboard_res.json()
    tenant_id = data["tenant_id"]
    brand_id = data["brand_id"]
    assert tenant_id is not None
    assert brand_id is not None

    # Step 2: Query tenant-scoped operations using the new X-Tenant-ID header
    # This exercises get_db's RLS set_config call.
    ops_res = await rls_api_client.get(
        "/ops",
        headers={"X-Tenant-ID": tenant_id}
    )
    assert ops_res.status_code == 200
    assert ops_res.json() == []  # Successfully RLS-isolated and returns empty list!

    # Step 3: Query tenant-scoped connections using the new X-Tenant-ID header
    conns_res = await rls_api_client.get(
        "/connections",
        headers={"X-Tenant-ID": tenant_id}
    )
    assert conns_res.status_code == 200
    assert conns_res.json() == []  # Successfully RLS-isolated and returns empty list!
