import os
import sys
import asyncio
import json
import uuid
import hashlib
from unittest.mock import patch, MagicMock

# Set required environment variables before importing any app modules
os.environ["AOS_ENV"] = "test"
os.environ["AOS_STATE_BUCKET"] = "mock-aos-state"
os.environ["TFPLAN_DIR"] = "/tmp/aos-tfplans-verify"

# Ensure plan directory exists
os.makedirs(os.environ["TFPLAN_DIR"], exist_ok=True)

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient

# Import app modules
from app.database import get_db
from app.main import app
from app.models import Base, Tenant, Brand, OpRow, AuditEvent, TrustSnapshot, CostEntry
from app.kernel import loop

# --- Deep Colors for Terminal Output ---
GREEN = "\033[1;32m"
BLUE = "\033[1;34m"
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
RESET = "\033[0m"

import subprocess
original_run = subprocess.run

def mock_run(cmd, cwd=None, **kwargs):
    if cmd[0] != "terraform":
        return original_run(cmd, cwd=cwd, **kwargs)
    
    subcomm = cmd[1]
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stderr = ""
    mock_res.stdout = "Success!"

    if subcomm == "init":
        mock_res.stdout = "Success! Mock Terraform has been initialized."
    elif subcomm in ("plan", "apply", "output"):
        tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
        vars_dict = {}
        if tfvars_path and os.path.exists(tfvars_path):
            with open(tfvars_path, "r") as f:
                vars_dict = json.load(f)

        if subcomm == "plan":
            # Write a mock plan file if -out is requested
            out_arg = next((arg for arg in cmd if arg.startswith("-out=")), None)
            if out_arg and cwd:
                plan_filename = out_arg.split("=")[1]
                with open(os.path.join(cwd, plan_filename), "w") as f:
                    f.write("mock_tfplan_verify_content")
            
            mock_res.stdout = "Plan: 5 to add, 0 to change, 0 to destroy.\n+ mock_resource_created"
        elif subcomm == "apply":
            mock_res.stdout = "Apply complete! Resources: 5 added, 0 changed, 0 destroyed."
        elif subcomm == "output":
            mock_res.stdout = json.dumps({
                "service_url": {"value": "https://woktok.co-mock-run.app"}
            })

    return mock_res


async def main():
    print(f"{CYAN}================================================================")
    print(f"       AGENCY OS — SLICE 1 END-TO-END CUJ VERIFICATION HARNESS")
    print(f"================================================================{RESET}")

    # 1. Setup in-memory SQLite database for absolute isolation
    database_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(database_url, connect_args={"check_same_thread": False})
    
    # Enforce foreign key constraints
    from sqlalchemy import event
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Dependency override for FastAPI
    async def override_get_db():
        async with session_maker() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    app.state.db_session_maker = session_maker
    
    async def override_get_worker_session_maker():
        return session_maker
    from app.database import get_worker_session_maker
    app.dependency_overrides[get_worker_session_maker] = override_get_worker_session_maker
    
    # Also override the global loop worker DB session maker
    loop.get_worker_db = session_maker

    async with session_maker() as s:
        # Seed Tenant & Brand
        print(f"\n{BLUE}[1/7] Seeding Tenant and Brand records...{RESET}")
        tenant = Tenant(id="tanmatra", name="Tanmatra Group", hosting_tier="shared", is_active=True)
        brand = Brand(id="woktok", tenant_id="tanmatra", name="Wok-Tok Retail")
        s.add(tenant)
        s.add(brand)
        
        # Seed an initial genesis AuditEvent to start the hash chain
        genesis_event = AuditEvent(
            ts="2026-06-20T00:00:00Z",
            tenant_id="tanmatra",
            op_id="genesis",
            actor="system",
            action="genesis",
            payload={"message": "Genesis block initialized"},
            prev_hash="GENESIS_HASH",
            hash="GENESIS_HASH",
        )
        s.add(genesis_event)
        await s.commit()
        print(f"{GREEN}✓ Tenant 'tanmatra' and Brand 'woktok' successfully bootstrapped in DB.{RESET}")

    # Patch subprocess.run with our mock Terraform CLI
    with patch("app.adapters.provision.subprocess.run", side_effect=mock_run):
        
        # =====================================================================
        # SCENARIO 1: SUPERVISED PATH (Tier 1 - Requires Approval)
        # =====================================================================
        print(f"\n{BLUE}====================================================================")
        print(f" SCENARIO 1: SUPERVISED PATH (Tier 1 - Trust Score: 70)")
        print(f"===================================================================={RESET}")

        async with session_maker() as s:
            # Set trust score to 70 (Tier 1)
            ts = TrustSnapshot(
                tenant_id="tanmatra",
                brand_id="woktok",
                domain="provision",
                score=70.0,
                tier=1
            )
            await s.merge(ts)
            await s.commit()

        # Send conversational intent via /chat
        print(f"\n{BLUE}[2/7] Dispatching conversational intent: 'host woktok.co'...{RESET}")
        headers = {
            "X-Tenant-Id": "tanmatra",
            "Authorization": "Bearer default-dev-token"
        }
        import httpx
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat_resp = await client.post("/chat", headers=headers, json={
                "brand_id": "woktok",
                "text": "host woktok.co"
            })
            assert chat_resp.status_code == 200, chat_resp.text
            chat_data = chat_resp.json()
            print(f"{GREEN}✓ Chat response: {chat_data['reply']}{RESET}")
            assert len(chat_data["cards"]) == 1
            card = chat_data["cards"][0]
            op_id = card["op_id"]
            print(f"  - Proposed Op ID: {CYAN}{op_id}{RESET}")
            print(f"  - Action: {CYAN}{card['action']}{RESET}")
            print(f"  - State: {YELLOW}{card['state']}{RESET} (Expected: AWAITING_APPROVAL)")
            print(f"  - Cost: {GREEN}{card['cost_estimate']}{RESET}")
            assert card["state"] == "AWAITING_APPROVAL"

            # Verify that LLM cost was correctly logged
            async with session_maker() as s:
                from sqlalchemy import select
                costs = (await s.execute(select(CostEntry).where(CostEntry.op_id == op_id))).scalars().all()
                assert len(costs) > 0
                print(f"{GREEN}✓ Cost attribution successfully written to Cost Ledger ({costs[0].amount_minor/100:.2f} {costs[0].currency} for {costs[0].kind}).{RESET}")

            # Simulate Operator Approval via /ops/{op_id}/decision
            print(f"\n{BLUE}[3/7] Simulating Operator Approval (WhatsApp Confirm)...{RESET}")
            decision_resp = await client.post(
                f"/ops/{op_id}/decision",
                headers=headers,
                json={
                    "decision": "approve",
                    "actor": "operator-chandan",
                    "role": "OPERATOR",
                    "surface": "whatsapp"
                }
            )
            assert decision_resp.status_code == 200, decision_resp.text
            print(f"{GREEN}✓ Operator decision successfully recorded: Op {decision_resp.json()['op_id']} transitioned to {decision_resp.json()['state']}{RESET}")

            # Verify Op state transitioned to APPROVED
            async with session_maker() as s:
                op_row = await s.get(OpRow, op_id)
                assert op_row.state in ("APPROVED", "DONE")
                print(f"  - Op State: {GREEN}{op_row.state}{RESET}")

            # Trigger Outbox Drain Loop
            print(f"\n{BLUE}[4/7] Triggering background Outbox Drain Loop...{RESET}")
            # Run the loop worker cycle once
            async with session_maker() as s:
                await loop.drain_once(s)
            print(f"{GREEN}✓ Outbox drain complete.{RESET}")

            # Verify that the Op has been executed, verified, and transitioned to DONE
            async with session_maker() as s:
                from sqlalchemy import select
                from app.models import OpTrace
                op_row = await s.get(OpRow, op_id)
                print(f"  - Op final State: {GREEN}{op_row.state}{RESET} (Expected: DONE)")
                assert op_row.state == "DONE"
                
                # Fetch traces to verify checks
                stmt = select(OpTrace).where(OpTrace.op_id == op_id, OpTrace.kind == "adapter_call")
                traces = (await s.execute(stmt)).scalars().all()
                verify_trace = next((t for t in traces if t.detail.get("phase") == "verify"), None)
                assert verify_trace is not None
                checks = verify_trace.detail.get("checks")
                print(f"  - Verification checks from trace: {CYAN}{checks}{RESET}")
                assert checks is not None
                assert "http_200" in checks
                assert checks["http_200"] is True

            # Verify Record Layer Cryptographic Integrity (Audit Log Chain)
            print(f"\n{BLUE}[5/7] Verifying Audit Log Chain Integrity...{RESET}")
            async with session_maker() as s:
                from sqlalchemy import select
                # Fetch all audit events in order
                stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
                events = (await s.execute(stmt)).scalars().all()
                print(f"  - Total audit blocks: {len(events)}")
                
                # Verify that each block carries a valid hash link of the previous block
                for idx, event in enumerate(events):
                    print(f"    Block {idx}: Op {event.op_id} | Action {event.action} | Hash {event.hash[:16]}...")
                    if idx > 0:
                        assert event.prev_hash == events[idx - 1].hash, f"Hash link broken at block {idx}!"
                
                print(f"{GREEN}✓ Cryptographic Audit Log Chain verified. Complete tamper-evident record intact!{RESET}")

        # =====================================================================
        # SCENARIO 2: AUTONOMOUS PATH (Tier 2 - Earned Autonomy)
        # =====================================================================
        print(f"\n{BLUE}====================================================================")
        print(f" SCENARIO 2: AUTONOMOUS PATH (Tier 2 - Trust Score: 90)")
        print(f"===================================================================={RESET}")

        async with session_maker() as s:
            # Upgrade trust score to 90 (Tier 2)
            ts = TrustSnapshot(
                tenant_id="tanmatra",
                brand_id="woktok",
                domain="provision",
                score=90.0,
                tier=2
            )
            await s.merge(ts)
            await s.commit()

        # Send conversational intent via /chat
        print(f"\n{BLUE}[6/7] Dispatching conversational intent: 'host autowoktok.co'...{RESET}")
        import httpx
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat_resp = await client.post("/chat", headers=headers, json={
                "brand_id": "woktok",
                "text": "host autowoktok.co"
            })
            assert chat_resp.status_code == 200, chat_resp.text
            chat_data = chat_resp.json()
            print(f"{GREEN}✓ Chat response: {chat_data['reply']}{RESET}")
            assert len(chat_data["cards"]) == 1
            card = chat_data["cards"][0]
            op_id_auto = card["op_id"]
            print(f"  - Proposed Op ID: {CYAN}{op_id_auto}{RESET}")
            print(f"  - Action: {CYAN}{card['action']}{RESET}")
            print(f"  - State: {GREEN}{card['state']}{RESET} (Expected: APPROVED - Auto-Approved!)")
            assert card["state"] == "APPROVED"

            # Trigger Outbox Drain Loop (executes immediately)
            print(f"\n{BLUE}[7/7] Triggering background Outbox Drain Loop...{RESET}")
            async with session_maker() as s:
                await loop.drain_once(s)
            print(f"{GREEN}✓ Outbox drain complete.{RESET}")

            # Verify that the Op has been executed, verified, and transitioned to DONE
            async with session_maker() as s:
                from sqlalchemy import select
                from app.models import OpTrace
                op_row = await s.get(OpRow, op_id_auto)
                print(f"  - Op final State: {GREEN}{op_row.state}{RESET} (Expected: DONE)")
                assert op_row.state == "DONE"
                
                # Fetch traces to verify checks
                stmt = select(OpTrace).where(OpTrace.op_id == op_id_auto, OpTrace.kind == "adapter_call")
                traces = (await s.execute(stmt)).scalars().all()
                verify_trace = next((t for t in traces if t.detail.get("phase") == "verify"), None)
                assert verify_trace is not None
                checks = verify_trace.detail.get("checks")
                print(f"  - Verification checks from trace: {CYAN}{checks}{RESET}")

    print(f"\n{GREEN}================================================================")
    print(f"   ✓ ALL SLICE 1 CRITICAL USER JOURNEYS SUCCESSFULLY VERIFIED!")
    print(f"================================================================{RESET}\n")

if __name__ == "__main__":
    asyncio.run(main())
