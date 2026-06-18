import pytest
from sqlalchemy import select
from app.adapters.presence import PresenceAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection

@pytest.fixture
def adapter():
    return PresenceAdapter()

# WordPress Tests
@pytest.fixture
def wp_connect_intent():
    return "connect wordpress blog blog.mybrand.com with secret:wp-secret-key"

@pytest.fixture
def wp_connect_op(adapter, wp_connect_intent):
    ops = adapter.plan(wp_connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_presence_wp_connect_plan(adapter, wp_connect_intent):
    ops = adapter.plan(wp_connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "presence.wordpress.connect"
    assert op.params["provider"] == "wordpress"
    assert op.params["secret_ref"] == "wp-secret-key"
    assert op.params["config"]["url"] == "blog.mybrand.com"

def test_presence_wp_connect_preview(adapter, wp_connect_op):
    preview_art = adapter.preview(wp_connect_op)
    assert preview_art.kind == "wordpress_connect_preview"
    assert "blog.mybrand.com" in preview_art.summary
    assert "wp-secret-key" in preview_art.summary

async def test_presence_wp_connect_execute(adapter, wp_connect_op, session):
    res = await adapter.execute(wp_connect_op, "idem_wp_connect_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "wordpress"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.secret_ref
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.secret_ref)
    assert val == "wp-secret-key"
    assert conn.scope == "read"
    assert conn.config["url"] == "blog.mybrand.com"

@pytest.mark.asyncio
async def test_presence_wp_connect_verify(adapter, wp_connect_op, session):
    await adapter.execute(wp_connect_op, "idem_wp_verify_setup_123", session=session)
    verdict = await adapter.verify(wp_connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["connection_valid"] is True
    assert verdict.checks["site_reachable"] is True

def test_presence_wp_compensate(adapter, wp_connect_op):
    compensations = adapter.compensate(wp_connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "presence.wordpress.disconnect"
    assert comp.params["provider"] == "wordpress"

async def test_presence_wp_execute_disconnect(adapter, wp_connect_op, session):
    # 1. Seed connection
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="wordpress",
        secret_ref="wp-secret-key",
        config={"url": "blog.mybrand.com"}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Compensate
    compensations = adapter.compensate(wp_connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_wp_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "wordpress"
    )
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None


# Web (Static/Headless) Tests
@pytest.fixture
def web_connect_intent():
    return "connect website www.mybrand.com with secret:vercel-token-123"

@pytest.fixture
def web_connect_op(adapter, web_connect_intent):
    ops = adapter.plan(web_connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_presence_web_connect_plan(adapter, web_connect_intent):
    ops = adapter.plan(web_connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "presence.web.connect"
    assert op.params["provider"] == "web"
    assert op.params["secret_ref"] == "vercel-token-123"
    assert op.params["config"]["url"] == "www.mybrand.com"

def test_presence_web_connect_preview(adapter, web_connect_op):
    preview_art = adapter.preview(web_connect_op)
    assert preview_art.kind == "web_connect_preview"
    assert "www.mybrand.com" in preview_art.summary
    assert "vercel-token-123" in preview_art.summary

async def test_presence_web_connect_execute(adapter, web_connect_op, session):
    res = await adapter.execute(web_connect_op, "idem_web_connect_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "web"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.secret_ref
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.secret_ref)
    assert val == "vercel-token-123"
    assert conn.scope == "read"
    assert conn.config["url"] == "www.mybrand.com"
 
@pytest.mark.asyncio
async def test_presence_web_connect_verify(adapter, web_connect_op, session):
    await adapter.execute(web_connect_op, "idem_web_verify_setup_123", session=session)
    verdict = await adapter.verify(web_connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["connection_valid"] is True

def test_presence_web_compensate(adapter, web_connect_op):
    compensations = adapter.compensate(web_connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "presence.web.disconnect"
    assert comp.params["provider"] == "web"

async def test_presence_web_execute_disconnect(adapter, web_connect_op, session):
    # 1. Seed connection
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="web",
        secret_ref="vercel-token-123",
        config={"url": "www.mybrand.com"}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Compensate
    compensations = adapter.compensate(web_connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_web_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "web"
    )
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None


# Google Services Tests
@pytest.fixture
def google_connect_intent():
    return "connect google gsc merchant center with secret:google-oauth-token-999"

@pytest.fixture
def google_connect_op(adapter, google_connect_intent):
    ops = adapter.plan(google_connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_presence_google_connect_plan(adapter, google_connect_intent):
    ops = adapter.plan(google_connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "presence.google.connect"
    assert op.params["provider"] == "google"
    assert op.params["secret_ref"] == "google-oauth-token-999"
    assert op.params["config"] == {}

def test_presence_google_connect_preview(adapter, google_connect_op):
    preview_art = adapter.preview(google_connect_op)
    assert preview_art.kind == "google_connect_preview"
    assert "Google Services" in preview_art.summary
    assert "google-oauth-token-999" in preview_art.summary

async def test_presence_google_connect_execute(adapter, google_connect_op, session):
    res = await adapter.execute(google_connect_op, "idem_google_connect_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "google"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.secret_ref
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.secret_ref)
    assert val == "google-oauth-token-999"
    assert conn.scope == "search_console,merchant_center"
    assert conn.config.get("scopes") == ["search_console", "merchant_center"]

@pytest.mark.asyncio
async def test_presence_google_connect_verify(adapter, google_connect_op, session):
    await adapter.execute(google_connect_op, "idem_google_verify_setup_123", session=session)
    verdict = await adapter.verify(google_connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["connection_valid"] is True

def test_presence_google_compensate(adapter, google_connect_op):
    compensations = adapter.compensate(google_connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "presence.google.disconnect"
    assert comp.params["provider"] == "google"

async def test_presence_google_execute_disconnect(adapter, google_connect_op, session):
    # 1. Seed connection
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="google",
        secret_ref="google-oauth-token-999",
        config={}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Compensate
    compensations = adapter.compensate(google_connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_google_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "google"
    )
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None
