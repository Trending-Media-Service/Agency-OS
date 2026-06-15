import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.models import Base
from app.database import DATABASE_URL

async def migrate(engine=None):
    if engine is None:
        print(f"Connecting to {DATABASE_URL}...")
        engine = create_async_engine(DATABASE_URL, echo=True)
        should_dispose = True
    else:
        should_dispose = False

    print("Creating tables...")
    async with engine.begin() as conn:
        # Create all tables defined in models.py
        await conn.run_sync(Base.metadata.create_all)

        tables_with_tenant = [
            "brands", "ops", "audit_events", "trust_events",
            "trust_snapshots", "cost_ledger", "connections",
            "brand_properties", "cadences", "op_traces", "approvals",
            "orders", "order_lines", "refunds", "fulfillment_costs",
            "campaigns", "spend_facts", "touchpoints", "circuit_breakers",
            "op_dependencies", "policy_versions"
        ]

        print("Enabling Row-Level Security (RLS)...")
        # Enable RLS on tenants (isolated by id)
        await conn.execute(text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;"))
        await conn.execute(text("ALTER TABLE tenants FORCE ROW LEVEL SECURITY;"))
        await conn.execute(text("""
            DROP POLICY IF EXISTS tenant_isolation ON tenants;
            CREATE POLICY tenant_isolation ON tenants
              USING (id = current_setting('app.current_tenant_id', true));
        """))

        # Enable RLS on other tables (isolated by tenant_id)
        for table in tables_with_tenant:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"))
            await conn.execute(text(f"""
                DROP POLICY IF EXISTS tenant_isolation ON {table};
                CREATE POLICY tenant_isolation ON {table}
                  USING (tenant_id = current_setting('app.current_tenant_id', true));
            """))

    print("Migration complete.")
    if should_dispose:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
