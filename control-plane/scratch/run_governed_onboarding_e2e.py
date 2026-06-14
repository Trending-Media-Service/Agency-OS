import asyncio
import os
import sys
import time
import sqlite3
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Setup environment
os.environ["AOS_ENV"] = "production"
os.environ["AOS_STATE_BUCKET"] = "aos-tfstate-tmg"

# Add custom terraform binary path to system PATH
bin_dir = "/google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS/control-plane/bin"
os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]

# Ensure control-plane is in python path
sys.path.insert(0, "/google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS/control-plane")

from app.database import Base
from app.models import Tenant, Brand, OpRow, OpTrace, OutboxItem, Approval, CostEntry, AuditEvent
from app.kernel import loop
from app.adapters.provision import ProvisionAdapter

# Register the provision adapter
loop.register(ProvisionAdapter())

DB_URL = "sqlite+aiosqlite:////google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS/control-plane/production_control_plane.db"
engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

def clean_database_records(brand_id: str):
    db_path = "/google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS/control-plane/production_control_plane.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"[CLEANUP] Cleaning up old database records for brand '{brand_id}'...")
    
    # Get all op IDs for this brand
    cursor.execute("SELECT id FROM ops WHERE brand_id=?", (brand_id,))
    op_ids = [row[0] for row in cursor.fetchall()]
    
    if op_ids:
        op_placeholder = ",".join("?" for _ in op_ids)
        cursor.execute(f"DELETE FROM approvals WHERE op_id IN ({op_placeholder})", op_ids)
        cursor.execute(f"DELETE FROM op_traces WHERE op_id IN ({op_placeholder})", op_ids)
        cursor.execute(f"DELETE FROM outbox WHERE op_id IN ({op_placeholder})", op_ids)
        cursor.execute(f"DELETE FROM cost_ledger WHERE op_id IN ({op_placeholder})", op_ids)
        cursor.execute(f"DELETE FROM audit_events WHERE op_id IN ({op_placeholder})", op_ids)
        cursor.execute(f"DELETE FROM ops WHERE id IN ({op_placeholder})", op_ids)
        
    conn.commit()
    conn.close()
    print("[CLEANUP] Done.")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def main():
    tenant_id = "t-trending-media"
    brand_id = "b-tanmatra-v5"  # Use a fresh brand ID to avoid conflicts
    
    clean_database_records(brand_id)
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # 1. Setup Tenant and Brand records if they don't exist
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            tenant = Tenant(id=tenant_id, name="Trending Media Group")
            session.add(tenant)
        
        brand = await session.get(Brand, brand_id)
        if not brand:
            brand = Brand(id=brand_id, tenant_id=tenant_id, name="Tanmatra")
            session.add(brand)
        
        await session.commit()
        print(f"[INFO] Initialized Tenant '{tenant_id}' and Brand '{brand_id}' in Database.")

        # 2. Plan the onboarding monorepo saga with custom project id passed in intent
        intent = "onboard brand tanmatra monorepo tanmatra.food dedicated brand-tanmatra-tmg"
        print(f"[INFO] Planning Onboarding Saga for intent: '{intent}'...")
        planned_ops = ProvisionAdapter().plan(intent, tenant_id, brand_id)
        
        # Propose and preview/gate each operation in sequence
        parent_row = None
        for op in planned_ops:
            row = await loop.propose(session, op, actor="system-onboard")
            await session.flush()
            gate, requirement = await loop.preview_and_gate(session, row, tier=1, actor="system-onboard")
            print(f"[PROPOSED] Op: {row.action} -> State: {row.state}, Req: {requirement}")
            if row.action == "provision.brand_bootstrap.create":
                parent_row = row
        
        await session.commit()
        
        if not parent_row:
            print("[ERROR] Parent bootstrap operation not found!")
            return

        # 3. Approve parent operation (triggers automatic approval of children and enqueues the first child)
        print(f"\n[INFO] Approving parent Op: {parent_row.id}...")
        await loop.decide(session, parent_row, decision="approve", actor="operator", role="AGENCY_OWNER", surface="script")
        await session.commit()
        print(f"[INFO] Parent and children approved. First child enqueued in outbox.")

        # 4. Drain the outbox loop until no pending items remain
        print("\n[INFO] Commencing governed execution drain loop...")
        while True:
            # Check if there are any PENDING items in outbox
            stmt_pending = select(OutboxItem).where(OutboxItem.status == "PENDING")
            res_pending = await session.execute(stmt_pending)
            pending_items = res_pending.scalars().all()
            if not pending_items:
                # Double check if any Op is still running or verifying
                stmt_running = select(OpRow).where(
                    OpRow.brand_id == brand_id,
                    OpRow.state.in_(["PENDING", "EXECUTING", "VERIFYING"])
                )
                res_running = await session.execute(stmt_running)
                running_ops = res_running.scalars().all()
                if not running_ops:
                    print("[INFO] No pending items in outbox and no running ops. Saga complete!")
                    break
                else:
                    print(f"[INFO] Waiting for running operations to complete: {[o.action for o in running_ops]}...")
                    await asyncio.sleep(2)
                    continue

            print(f"[DRAIN] Found {len(pending_items)} items in outbox. Draining...")
            processed = await loop.drain_once(session)
            await session.commit()
            print(f"[DRAIN] Processed {processed} items.")
            await asyncio.sleep(1)

        # Commit all remaining uncommitted transactions before printing/exiting
        await session.commit()

        # 5. Print final db records to verify success
        print("\n=== Artifact 1: GET /audit/verify ===")
        stmt_events = select(AuditEvent).order_by(AuditEvent.id)
        res_events = await session.execute(stmt_events)
        events = res_events.scalars().all()
        
        import hashlib
        prev = "0" * 64
        result_ok = True
        first_bad_id = None
        for ev in events:
            def _canonical(d):
                return json.dumps(d, sort_keys=True, separators=(',', ':'))
            p = ev.payload if ev.payload else {}
            preimage = prev + "|" + _canonical(
                {"ts": ev.ts, "tenant_id": ev.tenant_id, "actor": ev.actor,
                 "action": ev.action, "op_id": ev.op_id, "payload": p})
            calc_hash = hashlib.sha256(preimage.encode()).hexdigest()
            if ev.prev_hash != prev or calc_hash != ev.hash:
                result_ok = False
                first_bad_id = ev.id
                break
            prev = ev.hash
        print(json.dumps({"ok": result_ok, "first_bad_id": first_bad_id}))

        print("\n=== Artifact 2: Op Traces & Audit Events Sequence ===")
        stmt_final = select(OpRow).where(OpRow.brand_id == brand_id).order_by(OpRow.sequence_order)
        res_final = await session.execute(stmt_final)
        ops = res_final.scalars().all()
        print(f"Found {len(ops)} operations under brand '{brand_id}':")
        for op_row in ops:
            print(f"  - {op_row.action} (ID: {op_row.id}) -> State: {op_row.state}")

        print("\n--- Chronological Audit Events for these Ops ---")
        op_ids = [op_row.id for op_row in ops]
        if op_ids:
            stmt_audit = select(AuditEvent).where(AuditEvent.op_id.in_(op_ids)).order_by(AuditEvent.id)
            res_audit = await session.execute(stmt_audit)
            for audit in res_audit.scalars().all():
                print(f"[{audit.ts}] Op: {audit.op_id} -> Action: {audit.action} (Actor: {audit.actor}) {json.dumps(audit.payload)}")

        print("\n=== Artifact 3: Cost Ledger Rows ===")
        stmt_cost = select(CostEntry).where(CostEntry.tenant_id == tenant_id).order_by(CostEntry.id)
        res_cost = await session.execute(stmt_cost)
        for cost in res_cost.scalars().all():
            print(f"ID: {cost.id} | Op: {cost.op_id} | Kind: {cost.kind} | Amount: {cost.amount_minor/100:.2f} {cost.currency} | Meta: {json.dumps(cost.meta)}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
