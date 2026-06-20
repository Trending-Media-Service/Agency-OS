import pytest
import os
import shutil
from dataclasses import replace
from sqlalchemy import select
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.adapters.grow import GrowAdapter
from app.models import Connection
from app.services.secrets import SecretManagerClient
from app.services.storage import GcsClient

@pytest.fixture
def grow_adapter():
    return GrowAdapter()

@pytest.fixture
def base_op():
    return OpSpec(
        id="op_premium_test_123",
        tenant_id="tenant_premium_123",
        brand_id="brand_premium_123",
        domain="grow",
        action="grow.alert.dispatch",
        params={},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

@pytest.mark.asyncio
async def test_grow_premium_dv360_connect(grow_adapter, base_op, session):
    """Test that grow.dv360.connect securely stores credentials in Secret Manager
    and registers the DV360 programmatic connection in the database.
    """
    op = replace(base_op, 
        action="grow.dv360.connect",
        params={
            "advertiser_id": "dv-adv-999",
            "secret_ref": "dv360-oauth-refresh-token-mock",
            "sync_audiences": ["high_intent_search"]
        }
    )

    # Execute connection
    res = await grow_adapter.execute(op, "idem_dv360_conn", session=session)
    assert res.ok is True
    assert res.detail["provider"] == "dv360"
    assert "registered in DB and Secret Manager" in res.detail["message"]

    # Verify database entry
    stmt = select(Connection).where(
        Connection.tenant_id == op.tenant_id,
        Connection.brand_id == op.brand_id,
        Connection.provider == "dv360"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert conn.status == "unverified"
    assert conn.config["advertiser_id"] == "dv-adv-999"
    assert "high_intent_search" in conn.config["sync_audiences"]

    # Verify Secret Manager storage
    secrets_client = SecretManagerClient()
    token = await secrets_client.read_secret(conn.credential)
    assert token == "dv360-oauth-refresh-token-mock"

    # Verify adapter verification lifecycle
    v_res = await grow_adapter.verify(op, session=session)
    assert v_res.ok is True
    assert v_res.checks["connection_active"] is True
    assert v_res.checks["token_valid"] is True


@pytest.mark.asyncio
async def test_grow_premium_youtube_creator_connect(grow_adapter, base_op, session):
    """Test that grow.youtube_creator.connect registers the channel connection in the database
    without attempting to write credentials to Secret Manager (since YouTube Creator is configuration-based).
    """
    op = replace(base_op, 
        action="grow.youtube_creator.connect",
        params={
            "channel_id": "yt-channel-777",
            "amplification_mode": "shorts_ctv_bidding",
            "sync_creator_analytics": True
        }
    )

    # Execute connection
    res = await grow_adapter.execute(op, "idem_yt_conn", session=session)
    assert res.ok is True
    assert res.detail["provider"] == "youtube_creator"

    # Verify database entry
    stmt = select(Connection).where(
        Connection.tenant_id == op.tenant_id,
        Connection.brand_id == op.brand_id,
        Connection.provider == "youtube_creator"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert conn.status == "active"  # YouTube creator defaults to active configuration
    assert conn.credential is None  # Omitted credentials
    assert conn.config["channel_id"] == "yt-channel-777"
    assert conn.config["amplification_mode"] == "shorts_ctv_bidding"
    assert conn.config["sync_creator_analytics"] is True

    # Verify adapter verification lifecycle
    v_res = await grow_adapter.verify(op, session=session)
    assert v_res.ok is True
    assert v_res.checks["connection_active"] is True


@pytest.mark.asyncio
async def test_grow_premium_meridian_mmm_audit(grow_adapter, base_op, session):
    """Test that grow.meridian_mmm.audit runs the CFO-ready Marketing Mix Model audit,
    generates a premium HTML report, and uploads it to GCS.
    """
    GcsClient.clear()
    op = replace(base_op, 
        action="grow.meridian_mmm.audit",
        params={"lookback_days": 180}
    )

    res = await grow_adapter.execute(op, "idem_mmm_audit", session=session)
    assert res.ok is True
    assert res.detail["storage_status"] == "ok"
    assert res.detail["incrementality_ratio"] == 0.150  # Default baseline when no data in DB
    assert res.detail["roi_multiplier"] == 3.5          # Default baseline when no data in DB
    assert res.detail["report_url"].startswith("gs://aos-reports-")
    assert "meridian-mmm-audit-" in res.detail["report_url"]

    # Verify that it was successfully saved in the mock GCS client
    gcs = GcsClient()
    from app.adapters.grow import _parse_gcs_url
    bucket, blob = _parse_gcs_url(res.detail["report_url"])
    content = await gcs.download_as_string(bucket, blob)
    assert "Meridian Marketing Mix Modeling (MMM) Audit" in content
    assert "CFO Budget Defense Multiplier" in content
    assert "Lookback Period:</strong> 180 days" in content


@pytest.mark.asyncio
async def test_grow_premium_meridian_mmm_audit_dynamic(grow_adapter, base_op, session):
    """Test that grow.meridian_mmm.audit dynamically computes genuine ROI and incrementality
    based on actual SpendFact and Order records seeded in the database.
    """
    GcsClient.clear()
    tid, bid = base_op.tenant_id, base_op.brand_id
    
    from app.models import Campaign, SpendFact, Order
    import datetime as dt
    
    campaign = Campaign(id="camp-mmm-1", tenant_id=tid, brand_id=bid, name="Google Search Ads", platform="google")
    session.add(campaign)
    
    # Media Spend: 10,000 INR (1,000,000 minor units)
    spend = SpendFact(
        id="spend-mmm-1",
        tenant_id=tid,
        campaign_id="camp-mmm-1",
        amount_minor=1000000,
        date=dt.date.today()
    )
    session.add(spend)
    
    # Attributed Revenue: 52,500 INR (5,250,000 minor units) -> ROI: 5.25!
    order = Order(
        id="order-mmm-1",
        tenant_id=tid,
        brand_id=bid,
        amount_minor=5250000,
        currency="INR",
        attributed_campaign_id="camp-mmm-1",
        placed_at=dt.datetime.now(dt.timezone.utc)
    )
    session.add(order)
    await session.commit()
    
    op = replace(base_op, 
        action="grow.meridian_mmm.audit",
        params={"lookback_days": 30}
    )
    
    res = await grow_adapter.execute(op, "idem_mmm_dynamic", session=session)
    assert res.ok is True
    assert res.detail["storage_status"] == "ok"
    
    # Assert dynamic calculation: ROI = 5250000 / 1000000 = 5.25!
    assert res.detail["roi_multiplier"] == 5.25
    # Incrementality = 0.10 + 0.02 * 5.25 = 0.205!
    assert res.detail["incrementality_ratio"] == 0.205
    
    # Verify report content contains dynamic ROI
    gcs = GcsClient()
    from app.adapters.grow import _parse_gcs_url
    bucket, blob = _parse_gcs_url(res.detail["report_url"])
    content = await gcs.download_as_string(bucket, blob)
    assert "5.25x ROI Multiplier" in content
    assert "+20.5% Incrementality" in content


@pytest.mark.asyncio
async def test_grow_premium_meridian_mmm_audit_degraded_flow(grow_adapter, base_op, session, monkeypatch):
    """Test that grow.meridian_mmm.audit falls back to writing a local HTML report
    in the scratch/fallback_reports directory if GCS is completely unreachable.
    """
    op = replace(base_op, 
        action="grow.meridian_mmm.audit",
        params={"lookback_days": 60}
    )

    # Force GCS Outage
    gcs_instance = GcsClient()
    async def mock_upload_outage(*args, **kwargs):
        raise Exception("Mock GCS Outage Network Timeout")
    monkeypatch.setattr(gcs_instance, "upload_from_string", mock_upload_outage)
    monkeypatch.setattr("app.adapters.grow.GcsClient", lambda *a, **kw: gcs_instance)

    # Clear local fallback directory
    fallback_dir = os.path.join(os.path.dirname(__file__), "../scratch/fallback_reports")
    if os.path.exists(fallback_dir):
        shutil.rmtree(fallback_dir)

    res = await grow_adapter.execute(op, "idem_mmm_outage", session=session)
    assert res.ok is True
    assert res.detail["storage_status"] == "degraded"
    assert "GCS upload failed" in res.detail["message"]
    assert "fallback_file" in res.detail
    # Assert correct local fallback file URL scheme
    assert res.detail["report_url"].startswith("file://")
    
    # Assert local fallback file is written and valid
    fallback_path = res.detail["fallback_file"]
    assert os.path.exists(fallback_path)
    with open(fallback_path, "r") as f:
        content = f.read()
    assert "Meridian Marketing Mix Modeling (MMM) Audit" in content
    assert "Lookback Period:</strong> 60 days" in content


@pytest.mark.asyncio
async def test_grow_premium_ai_readiness_audit(grow_adapter, base_op, session):
    """Test that grow.ai_readiness.audit dynamically scans campaigns in the database,
    computes precise heuristic scores, and returns recommendations.
    """
    tid, bid = base_op.tenant_id, base_op.brand_id
    from app.models import Campaign, SpendFact
    import datetime as dt
    
    # Seed a campaign with smart bidding and broad match, and active spend
    campaign = Campaign(
        id="camp-test-ai-1",
        tenant_id=tid,
        brand_id=bid,
        name="Search Campaign - Broad Match & smart_bidding (PMax)",
        platform="google",
        status="active"
    )
    session.add(campaign)
    
    spend = SpendFact(
        id="spend-ai-1",
        tenant_id=tid,
        campaign_id="camp-test-ai-1",
        amount_minor=50000,
        date=dt.date.today()
    )
    session.add(spend)
    await session.commit()
    
    op = replace(base_op, 
        action="grow.ai_readiness.audit",
        params={"campaign_id": "camp-test-ai-1"}
    )

    res = await grow_adapter.execute(op, "idem_ai_audit", session=session)
    assert res.ok is True
    assert res.detail["campaign_id"] == "camp-test-ai-1"
    
    # All 4 checks pass (broad name, long name, smart/pmax name, active spend) -> Score: 100%!
    assert res.detail["score"] == 100.0
    assert res.detail["checks"]["smart_bidding_enabled"] is True
    assert res.detail["checks"]["ai_assets_complete"] is True
    assert len(res.detail["recommendations"]) == 0

