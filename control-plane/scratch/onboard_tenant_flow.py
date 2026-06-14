import os
import sys
import asyncio
import logging
import datetime as dt

# Set env to test to enable mock terraform and mock Vertex AI
os.environ["AOS_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///control_plane_onboarding_test.db"

# Setup Mock for subprocess.run to intercept terraform CLI calls
import subprocess
from unittest.mock import MagicMock

original_run = subprocess.run

def mock_subprocess_run(cmd, cwd=None, **kwargs):
    if not isinstance(cmd, list) or cmd[0] != "terraform":
        return original_run(cmd, cwd=cwd, **kwargs)
    
    subcomm = cmd[1]
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stderr = ""
    
    import json
    vars_dict = {}
    if cwd:
        tfvars_path = os.path.join(cwd, "terraform.tfvars.json")
        if os.path.exists(tfvars_path):
            try:
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)
            except:
                pass
                
    recipe = "unknown"
    if "db_connection_name" in vars_dict:
        recipe = "n8n"
    elif "bucket_name" in vars_dict:
        recipe = "static-host"
    elif "domain" in vars_dict or "custom_domain" in vars_dict:
        recipe = "web-host"
    elif "project_id" in vars_dict:
        recipe = "webapp-postgres"
    elif "brand_id" in vars_dict:
        recipe = "brand-baseline"
    elif "db_name" in vars_dict:
        recipe = "postgres-db"

    if subcomm == "init":
        mock_res.stdout = "Success! Terraform has been initialized."
    elif subcomm == "plan":
        if os.environ.get("SIMULATE_DRIFT") == "1":
            mock_res.returncode = 2
            mock_res.stdout = "drift detected!"
        else:
            mock_res.stdout = "Plan: 3 to add, 0 to change, 0 to destroy."
    elif subcomm == "apply":
        mock_res.stdout = "Apply complete! Resources: added, 0 changed, 0 destroyed."
    elif subcomm == "output":
        if recipe == "brand-baseline":
            brand = vars_dict.get("brand_id", "example-brand")
            mock_res.stdout = json.dumps({
                "project_id": {"value": f"aos-brand-{brand}"},
                "service_account_email": {"value": f"aos-deployer-{brand}@aos-brand-{brand}.iam.gserviceaccount.com"},
                "db_connection_name": {"value": "aos-shared-tier:asia-south1:aos-shared-postgres"}
            })
        elif recipe == "webapp-postgres":
            mock_res.stdout = json.dumps({
                "frontend_url": {"value": "https://tanmatra-mock-url.run.app"},
                "api_url": {"value": "https://wellness-foods-mock-url.run.app"},
                "db_connection_name": {"value": "aos-brand-b1:asia-south2:brand-b1-db"}
            })
        elif recipe == "web-host":
            mock_res.stdout = json.dumps({
                "service_url": {"value": "https://web-mock.in"},
                "lb_ip": {"value": "34.120.15.22"}
            })
        elif recipe == "static-host":
            mock_res.stdout = json.dumps({
                "bucket_url": {"value": "https://storage.googleapis.com/static-bucket"},
                "cdn_url": {"value": "https://static-cdn.in"}
            })
        else:
            mock_res.stdout = "{}"
            
    return mock_res

# Patch subprocess.run
subprocess.run = mock_subprocess_run

# Setup Mock for urllib.request.urlopen to prevent outbound HTTP requests in tests
import urllib.request
def mock_urlopen(req, *args, **kwargs):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp

urllib.request.urlopen = mock_urlopen

# Adjust python path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import Base, Tenant, Brand, OpRow, Order, TrustSnapshot, TrustEvent, Connection
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money, OpState
from app.kernel.services import audit_verify, trust_score
from app.adapters.provision import ProvisionAdapter
from app.adapters.grow import GrowAdapter
from app.adapters.manage import ManageAdapter

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OnboardingFlow")

async def run_flow():
    # 1. Initialize Engine and Create Tables
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 2. Setup Tenant & Brand
        logger.info("Step 1: Setting up Tenant 'Trendingmediagroup.in' and Brand 'Tanmatra'")
        tenant = Tenant(id="t_trending_media", name="Trendingmediagroup.in")
        brand = Brand(id="b_tanmatra", tenant_id="t_trending_media", name="Tanmatra")
        session.add(tenant)
        session.add(brand)
        await session.commit()
        
        tenant_id = tenant.id
        brand_id = brand.id
        
        # 3. Plan Bootstrap Saga
        logger.info("Step 2: Planning Monorepo Bootstrap Saga for Tanmatra")
        prov_adapter = ProvisionAdapter()
        intent = "onboard brand tanmatra monorepo tanmatra.food"
        planned_ops = prov_adapter.plan(intent, tenant_id, brand_id)
        
        logger.info(f"Planned {len(planned_ops)} Operations for the bootstrap saga:")
        for op in planned_ops:
            logger.info(f"  - Action: {op.action}, Sequence: {op.sequence_order}")
            
        # 4. Save and execute each Op in sequence
        logger.info("Step 3: Executing Bootstrap Saga Operations")
        parent_op = planned_ops[0]
        child_ops = planned_ops[1:]
        
        # Insert parent Op
        parent_row = OpRow(
            id=parent_op.id,
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain=parent_op.domain,
            action=parent_op.action,
            params=parent_op.params,
            state="APPROVED",
            impact=parent_op.severity.impact,
            reversibility=parent_op.severity.reversibility.value,
            idem_key=f"idem_{parent_op.id}"
        )
        session.add(parent_row)
        await session.commit()
        
        # Execute children in sequence order
        for op in sorted(child_ops, key=lambda o: o.sequence_order):
            logger.info(f"Executing Child Op: {op.action} (Sequence {op.sequence_order})")
            
            # 4a. Transition to PROPOSED and approve
            op_row = OpRow(
                id=op.id,
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=op.domain,
                action=op.action,
                params=op.params,
                state="APPROVED",
                parent_op_id=op.parent_op_id,
                sequence_order=op.sequence_order,
                impact=op.severity.impact,
                reversibility=op.severity.reversibility.value,
                idem_key=f"idem_{op.id}"
            )
            session.add(op_row)
            await session.commit()
            
            # 4b. Execute
            exec_res = await prov_adapter.execute(op, f"idem_{op.id}", session=session)
            if not exec_res.ok:
                logger.error(f"Execution failed for {op.action}: {exec_res.detail}")
                return
            logger.info(f"Execution Success: {op.action}. Detail: {exec_res.detail}")
            
            # 4c. Verify
            ver_res = await prov_adapter.verify(op)
            if not ver_res.ok:
                logger.error(f"Verification failed for {op.action}: {ver_res.checks}")
                return
            logger.info(f"Verification Success: {op.action}. Checks: {ver_res.checks}")
            
            # Update row state to DONE
            op_row.state = "DONE"
            await session.commit()
            
        parent_row.state = "DONE"
        await session.commit()
        logger.info("Monorepo Bootstrap Saga Completed Successfully!")
        
        # 5. Provision Growth (Ad Campaign)
        logger.info("Step 4: Provisioning Growth Ad Campaign")
        grow_adapter = GrowAdapter()
        grow_intent = "create campaign winter-sale budget 5000"
        grow_ops = grow_adapter.plan(grow_intent, tenant_id, brand_id)
        assert len(grow_ops) == 1
        grow_op = grow_ops[0]
        
        grow_row = OpRow(
            id=grow_op.id,
            tenant_id=tenant_id,
            brand_id=grow_op.brand_id,
            domain=grow_op.domain,
            action=grow_op.action,
            params=grow_op.params,
            state="APPROVED",
            impact=grow_op.severity.impact,
            reversibility=grow_op.severity.reversibility.value,
            idem_key=f"idem_{grow_op.id}"
        )
        session.add(grow_row)
        await session.commit()
        
        # Execute Grow campaign
        grow_exec = await grow_adapter.execute(grow_op, f"idem_{grow_op.id}", session=session)
        assert grow_exec.ok is True
        logger.info(f"Grow Campaign Execution Success: {grow_exec.detail}")
        
        grow_ver = await grow_adapter.verify(grow_op)
        assert grow_ver.ok is True
        logger.info(f"Grow Campaign Verification Success: {grow_ver.checks}")
        
        grow_row.state = "DONE"
        await session.commit()
        
        # 6. Run Manage (Drift Detection)
        logger.info("Step 5: Running Infrastructure Drift Detection")
        manage_adapter = ManageAdapter()
        manage_ops = manage_adapter.plan("check drift", tenant_id, brand_id)
        assert len(manage_ops) == 1
        manage_op = manage_ops[0]
        
        manage_row = OpRow(
            id=manage_op.id,
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain=manage_op.domain,
            action=manage_op.action,
            params=manage_op.params,
            state="APPROVED",
            impact=manage_op.severity.impact,
            reversibility=manage_op.severity.reversibility.value,
            idem_key=f"idem_{manage_op.id}"
        )
        session.add(manage_row)
        await session.commit()
        
        # Run drift check (simulate drift)
        os.environ["SIMULATE_DRIFT"] = "1"
        drift_res = await manage_adapter.execute(manage_op, f"idem_{manage_op.id}", session=session)
        assert drift_res.ok is True
        logger.info(f"Drift Detection Complete: {drift_res.detail['message']}")
        assert len(drift_res.detail["drifted_op_ids"]) > 0
        
        manage_row.state = "DONE"
        await session.commit()
        
        # 7. Trust Evaluation and Snapshots
        logger.info("Step 6: Running Trust Score Calculation")
        # Add a simulated order to create positive campaign attribution ROI
        campaign_id = grow_op.params["campaign_id"]
        order = Order(
            tenant_id=tenant_id,
            brand_id=brand_id,
            amount_minor=1200000, # 12,000 INR revenue vs 5,000 INR budget (positive ROI)
            attributed_campaign_id=campaign_id
        )
        session.add(order)
        
        # Add a mock connection status
        conn = Connection(
            tenant_id=tenant_id,
            brand_id=brand_id,
            provider="shopify",
            secret_ref="mock-token",
            config={"shop_url": "tanmatra.myshopify.com"}
        )
        session.add(conn)
        await session.commit()
        
        # Trigger trust updates
        # Calculate trust score manually to verify
        # Base signals
        signals = {"gtm_present": True, "pixel_present": True, "capi_dedup_rate": 0.8}
        events = [("verified_success", dt.datetime.now(dt.timezone.utc))]
        
        score = trust_score(signals, events)
        logger.info(f"Calculated dynamic brand trust score: {score:.2f}")
        
        # Save snapshot
        snapshot = TrustSnapshot(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            score=score,
            tier=1,
            ts=dt.datetime.now(dt.timezone.utc)
        )
        session.add(snapshot)
        await session.commit()
        
        # 8. Verify Audit Chain
        logger.info("Step 7: Verifying Integrity of the Audit Trail Chain")
        ok, bad_id = await audit_verify(session)
        assert ok is True
        logger.info("Audit chain verification PASSED - Zero tampering detected.")
        
        logger.info("--- ONBOARDING & LIFECYCLE SIMULATION COMPLETED SUCCESSFULLY! ---")

if __name__ == "__main__":
    asyncio.run(run_flow())
