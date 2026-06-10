from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import Brand, Tenant
from httpx import AsyncClient
import pytest
from sqlalchemy import text


@pytest.fixture(scope="session", autouse=True)
async def run_migrations():
  """Scaffolds baseline tables inside the local postgres testing database."""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)
    await conn.run_sync(Base.metadata.create_all)

    # Apply strict Row-Level Security policies to the test tables
    await conn.execute(text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;"))
    await conn.execute(text("ALTER TABLE brands ENABLE ROW LEVEL SECURITY;"))
    await conn.execute(text("""
            CREATE POLICY test_tenant_policy ON tenants
            FOR ALL USING (id = current_setting('app.current_tenant_id', true));
        """))
    await conn.execute(text("""
            CREATE POLICY test_tenant_policy ON brands
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true));
        """))
  yield
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_strict_multi_tenant_isolation():
  """Verifies that the control plane middleware and PostgreSQL Row-Level Security

  (RLS) prevent tenant boundary leaks during endpoint routing operations.
  """
  # 1. Direct high-privilege transactional setup
  async with AsyncSessionLocal() as session:
    async with session.begin():
      # Seed tenant 'A' details
      tenant_a = Tenant(id="tenant-a", name="Tanmatra")
      brand_a = Brand(id="brand-wok", tenant_id="tenant-a", name="Wok-Tok")
      session.add_all([tenant_a, brand_a])

      # Seed tenant 'B' details
      tenant_b = Tenant(id="tenant-b", name="Ableys")
      brand_b = Brand(
          id="brand-ableys", tenant_id="tenant-b", name="Ableys Main"
      )
      session.add_all([tenant_b, brand_b])

  # 2. Query execution as Tenant A
  async with AsyncClient(app=app, base_url="http://test") as ac:
    headers_a = {"X-Tenant-ID": "tenant-a"}
    response_a = await ac.get("/brands", headers=headers_a)
    assert response_a.status_code == 200
    data_a = response_a.json()
    # Assert Tenant A ONLY sees its own brands (Wok-Tok)
    assert len(data_a) == 1
    assert data_a[0]["id"] == "brand-wok"
    assert data_a[0]["name"] == "Wok-Tok"

  # 3. Query execution as Tenant B
  async with AsyncClient(app=app, base_url="http://test") as ac:
    headers_b = {"X-Tenant-ID": "tenant-b"}
    response_b = await ac.get("/brands", headers=headers_b)
    assert response_b.status_code == 200
    data_b = response_b.json()
    # Assert Tenant B ONLY sees its own brands (Ableys Main)
    assert len(data_b) == 1
    assert data_b[0]["id"] == "brand-ableys"
    assert data_b[0]["name"] == "Ableys Main"

  # 4. Request execution with missing Tenant Header boundary check
  async with AsyncClient(app=app, base_url="http://test") as ac:
    response_fail = await ac.get("/brands")
    assert response_fail.status_code == 400
    assert "X-Tenant-ID header is missing" in response_fail.json()["detail"]
