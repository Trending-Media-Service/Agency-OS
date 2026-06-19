# Feature 2 OAuth Flow and Token Rotation tests
import datetime as dt
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import select
from httpx import AsyncClient, HTTPStatusError
from fastapi import HTTPException, Request

from app.models import Connection, AuditEvent
from app.database import get_db
import app.main as mainmod

# ---------------------------------------------------------
# Tier 1: OAuth Token Refresh and OIDC Worker Auth
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_oauth_refresh_service_success(session, mock_secrets_client):
    """Test 11: Verify OAuth refresh token service successfully rotates tokens."""
    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    mock_secrets_client.read_secret.return_value = "old-refresh-token"
    mock_secrets_client.write_secret.return_value = "projects/test-project/secrets/s1/versions/2"

    # Mock the token exchange endpoint
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600
        }
        mock_post.return_value = mock_resp

        service = OauthService()
        result = await service.refresh_token(
            tenant_id="t1",
            brand_id="b1",
            provider="shopify",
            refresh_token_ref="projects/test-project/secrets/s1/versions/1"
        )

        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
        assert mock_secrets_client.write_secret.call_count == 2  # One for access, one for refresh

@pytest.mark.asyncio
async def test_oauth_refresh_service_revoked_token(session, mock_secrets_client):
    """Test 12: Verify refresh failure due to revoked token marks connection in error."""
    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/test-project/secrets/s1/versions/1", status="active"
    )
    session.add(conn)
    await session.commit()

    mock_secrets_client.read_secret.return_value = "revoked-refresh-token"

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        mock_post.return_value = mock_resp

        service = OauthService()
        with pytest.raises(Exception):
            await service.refresh_token(
                tenant_id="t1",
                brand_id="b1",
                provider="shopify",
                refresh_token_ref=conn.credential
            )

@pytest.mark.asyncio
async def test_verify_worker_auth_valid_oidc(mock_oidc_verification):
    """Test 13: Verify OIDC authentication dependency accepts valid scheduler tokens."""
    mock_oidc_verification.return_value = {
        "iss": "https://accounts.google.com",
        "email": "scheduler-worker@aos.iam.gserviceaccount.com",
        "aud": "http://test/tasks/refresh-tokens"
    }

    request = MagicMock(spec=Request)
    request.url = MagicMock()
    request.url.scheme = "http"
    request.url.netloc = "test"
    request.url.path = "/tasks/refresh-tokens"

    # Override env in app.main
    with patch("app.main.AOS_ENV", "production"), \
         patch("app.main.WORKER_SA", "scheduler-worker@aos.iam.gserviceaccount.com"):
        # Should not raise exception
        await mainmod.verify_worker_auth(request, authorization="Bearer valid-token")

@pytest.mark.asyncio
async def test_verify_worker_auth_invalid_audience(mock_oidc_verification):
    """Test 14: Verify OIDC auth rejects tokens with incorrect audience."""
    def mock_verify(token, request, audience=None):
        if audience != "http://test/tasks/refresh-tokens":
            raise ValueError("Token focus audience mismatch")
        return {
            "iss": "https://accounts.google.com",
            "email": "scheduler-worker@aos.iam.gserviceaccount.com",
            "aud": audience
        }
    mock_oidc_verification.side_effect = mock_verify

    request = MagicMock(spec=Request)
    request.url = MagicMock()
    request.url.scheme = "http"
    request.url.netloc = "test"
    request.url.path = "/tasks/invalid-path"

    with patch("app.main.AOS_ENV", "production"), \
         patch("app.main.WORKER_SA", "scheduler-worker@aos.iam.gserviceaccount.com"):
        with pytest.raises(HTTPException) as exc:
            await mainmod.verify_worker_auth(request, authorization="Bearer invalid-token")
        assert exc.value.status_code == 401

@pytest.mark.asyncio
async def test_refresh_tokens_task_endpoint_empty_db(client):
    """Test 15: Verify that calling refresh-tokens task on empty DB completes with 200."""
    # Ensure worker auth bypasses in test env, or pass dummy header
    resp = await client.post("/tasks/refresh-tokens")
    # If endpoint not implemented yet, it will return 404, which is expected Red state
    if resp.status_code == 404:
        pytest.skip("Endpoint /tasks/refresh-tokens not implemented yet (expected Red state)")
    assert resp.status_code == 200

# ---------------------------------------------------------
# Tier 2: OAuth Security and State Handlers
# ---------------------------------------------------------

def test_oauth_state_signing_integrity():
    """Test 21: Verify that generated OAuth state contains a cryptographically secure signature."""
    try:
        from app.services.oauth import generate_oauth_state, verify_oauth_state
    except ImportError:
        pytest.skip("State signing functions not implemented yet (expected Red state)")

    tenant_id = "t1"
    brand_id = "b1"
    redirect_uri = "https://app.agencyos.com/callback"
    
    state = generate_oauth_state(tenant_id, brand_id, redirect_uri)
    assert state is not None
    
    # Valid verification
    payload = verify_oauth_state(state)
    assert payload["tenant_id"] == tenant_id
    assert payload["brand_id"] == brand_id
    assert payload["redirect_uri"] == redirect_uri

    # Invalid signature
    tampered_state = state[:-5] + "aaaaa"
    with pytest.raises(ValueError, match="Invalid state signature"):
        verify_oauth_state(tampered_state)

def test_oauth_state_expiration():
    """Test 22: Verify that OAuth state tokens expire after a predefined duration (15 mins)."""
    try:
        from app.services.oauth import generate_oauth_state, verify_oauth_state
    except ImportError:
        pytest.skip("State signing functions not implemented yet (expected Red state)")

    state = generate_oauth_state("t1", "b1", "https://app.agencyos.com/callback")
    
    # Verify immediately succeeds
    assert verify_oauth_state(state) is not None

    # Fast forward time by 16 minutes
    future_time = dt.datetime.utcnow() + dt.timedelta(minutes=16)
    with patch("datetime.datetime") as mock_dt:
        mock_dt.utcnow.return_value = future_time
        # Re-mocking timezone-aware utcnow if needed, otherwise standard
        with pytest.raises(ValueError, match="State token expired"):
            verify_oauth_state(state)

def test_open_redirect_helper_validation():
    """Test 23: Verify that redirect URI helper rejects domains outside the allowed pattern."""
    try:
        from app.services.oauth import validate_redirect_uri
    except ImportError:
        pytest.skip("Redirect validation helper not implemented yet (expected Red state)")

    # Allowed domain pattern: *.agencyos.com or localhost
    assert validate_redirect_uri("https://app.agencyos.com/dashboard") is True
    assert validate_redirect_uri("http://localhost:3000/callback") is True
    
    # Forbidden domains
    assert validate_redirect_uri("https://attacker.com") is False
    assert validate_redirect_uri("https://app.agencyos.com.attacker.com/bypass") is False
    assert validate_redirect_uri("https://attacker.com/app.agencyos.com") is False

@pytest.mark.asyncio
async def test_oauth_authorize_redirect_generation(client):
    """Test 24: Verify authorize endpoint generates a valid provider redirect URI with signed state."""
    resp = await client.get(
        "/connections/oauth/authorize?provider=shopify&brand_id=b1&redirect_uri=https://app.agencyos.com/callback",
        headers={"X-Tenant-ID": "t1"}
    )
    if resp.status_code == 404:
        pytest.skip("Authorize endpoint not implemented yet (expected Red state)")
    
    assert resp.status_code == 302
    location = resp.headers.get("location")
    assert "myshopify.com/admin/oauth/authorize" in location or "shopify" in location
    assert "state=" in location
    assert "redirect_uri=" in location

@pytest.mark.asyncio
async def test_oauth_callback_missing_state(client):
    """Test 25: Verify callback endpoint rejects requests missing state parameter."""
    resp = await client.get("/connections/oauth/callback?code=123456")
    if resp.status_code == 404:
        pytest.skip("Callback endpoint not implemented yet (expected Red state)")
    assert resp.status_code == 400
    assert "Missing state" in resp.text

# ---------------------------------------------------------
# Tier 2: Token Rotation and Scheduler Resiliency
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_periodic_token_rotation_flow(session, mock_secrets_client):
    """Test 36: Verify periodic task identifies expiring tokens and rotates them."""
    # Seed a connection with an expiring token (e.g. last_rotated_at is old)
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="google-ads",
        credential="projects/test-project/secrets/ads-secret/versions/1",
        config={"refresh_token": "rt-123"},
        status="active"
    )
    # Mocking rotation interval check if stored in a last_rotated_at column
    if hasattr(Connection, "last_rotated_at"):
        conn.last_rotated_at = dt.datetime.utcnow() - dt.timedelta(days=10)
    
    session.add(conn)
    await session.commit()

    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    with patch("app.services.oauth.OauthService.refresh_token") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600
        }
        
        # Call rotation runner
        from app.tasks.rotation import rotate_expiring_tokens
        await rotate_expiring_tokens(session)
        
        mock_refresh.assert_called_once()
        await session.refresh(conn)
        assert conn.status == "active"

@pytest.mark.asyncio
async def test_scheduler_batch_resiliency(session, mock_secrets_client):
    """Test 37: Verify failure in one connection's rotation does not abort the entire batch."""
    conn1 = Connection(tenant_id="t1", brand_id="b1", provider="shopify", credential="c1", status="active")
    conn2 = Connection(tenant_id="t1", brand_id="b1", provider="google-ads", credential="c2", status="active")
    if hasattr(Connection, "last_rotated_at"):
        conn1.last_rotated_at = dt.datetime.utcnow() - dt.timedelta(days=10)
        conn2.last_rotated_at = dt.datetime.utcnow() - dt.timedelta(days=10)
    session.add_all([conn1, conn2])
    await session.commit()

    try:
        from app.tasks.rotation import rotate_expiring_tokens
    except ImportError:
        pytest.skip("Rotation tasks not implemented yet (expected Red state)")

    # Mock rotation to fail for conn1 and succeed for conn2
    async def mock_rotate(tenant_id, brand_id, provider, credential):
        if provider == "shopify":
            raise Exception("Shopify rotation failed!")
        return {"access_token": "new-access", "refresh_token": "new-refresh"}

    with patch("app.services.oauth.OauthService.refresh_token", side_effect=mock_rotate):
        await rotate_expiring_tokens(session)
        
        await session.refresh(conn1)
        await session.refresh(conn2)
        # conn1 should be in error status, but conn2 should remain active/successfully rotated
        assert conn1.status == "error"
        assert conn2.status == "active"

@pytest.mark.asyncio
async def test_scheduler_auth_enforcement(client):
    """Test 38: Verify that worker task endpoints return 401 unauthorized if no OIDC header is passed."""
    # Ensure WORKER_SA is configured to force verification
    with patch("app.main.WORKER_SA", "scheduler-worker@aos.iam.gserviceaccount.com"), \
         patch("app.main.AOS_ENV", "production"):
        resp = await client.post("/tasks/drain-outbox")
        assert resp.status_code == 401

@pytest.mark.asyncio
async def test_auto_refresh_retries_during_audits(session, mock_secrets_client):
    """Test 39: Verify that active audits automatically refresh tokens on auth errors and retry."""
    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="google-search-console",
        credential="projects/test-project/secrets/sc-secret/versions/1", status="active"
    )
    session.add(conn)
    await session.commit()

    mock_secrets_client.read_secret.return_value = "expired-token"

    # Spy on refresh_token
    with patch("app.services.oauth.OauthService.refresh_token") as mock_refresh, \
         patch("httpx.AsyncClient.send") as mock_send:
        
        mock_refresh.return_value = {"access_token": "fresh-token", "refresh_token": "fresh-refresh"}
        
        # First API call returns 401, second returns 200
        resp1 = MagicMock()
        resp1.status_code = 401
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"rows": []}
        mock_send.side_effect = [resp1, resp2]

        from app.services.google_audit import GoogleSearchConsoleAudit
        audit = GoogleSearchConsoleAudit(tenant_id="t1", brand_id="b1", session=session)
        # Run audit
        try:
            await audit.run()
        except Exception:
            # If the audit runner is not set up to auto-retry yet, it might raise an exception
            pass
            
        # Assert that refresh_token was triggered automatically on 401
        mock_refresh.assert_called_once()

@pytest.mark.asyncio
async def test_db_session_rollback_on_rotation_db_failure(session, mock_secrets_client):
    """Test 40: Verify database rollback on rotation database write failure."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/test-project/secrets/s1/versions/1", status="active"
    )
    session.add(conn)
    await session.commit()

    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    # Simulate database crash during rotation update
    with patch("app.services.oauth.OauthService.refresh_token") as mock_refresh, \
         patch.object(session, "commit", side_effect=Exception("Database connection lost!")):
        
        mock_refresh.return_value = {"access_token": "new-access", "refresh_token": "new-refresh"}
        
        from app.tasks.rotation import rotate_expiring_tokens
        with pytest.raises(Exception):
            await rotate_expiring_tokens(session)
            
        # Verify transaction rolled back (conn remains in active status, not updated)
        await session.rollback()
        await session.refresh(conn)
        assert conn.status == "active"

@pytest.mark.asyncio
async def test_rotation_prunes_old_versions(session, mock_secrets_client):
    """Test 41: Verify rotation prunes old secret versions in Secret Manager."""
    try:
        from app.services.oauth import OauthService
    except ImportError:
        pytest.skip("OauthService not implemented yet (expected Red state)")

    # We don't reassign the mock attribute, as it is already patched on SecretManagerClient in conftest
    
    service = OauthService()
    # Mocking internal prune logic if implemented, or call it directly
    if hasattr(service, "prune_old_versions"):
        await service.prune_old_versions("projects/test-project/secrets/s1/versions/2")
        mock_secrets_client.delete_secret.assert_called_with("projects/test-project/secrets/s1/versions/1")
    else:
        pytest.skip("Pruning old secret versions not implemented yet (expected Red state)")

# ---------------------------------------------------------
# Tier 2: End-to-End OAuth Scenarios and Security
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_oauth_flow(client, session, mock_secrets_client):
    """Test 48: Verify full OAuth flow: authorize redirect, code callback, token exchange, and active state."""
    # Step 1: GET /connections/oauth/authorize
    auth_resp = await client.get(
        "/connections/oauth/authorize?provider=shopify&brand_id=b1&redirect_uri=https://app.agencyos.com/callback",
        headers={"X-Tenant-ID": "t1"}
    )
    if auth_resp.status_code == 404:
        pytest.skip("OAuth endpoints not implemented yet (expected Red state)")
        
    assert auth_resp.status_code == 302
    location = auth_resp.headers.get("location")
    
    # Extract state from redirect location
    import urllib.parse as urlparse
    parsed = urlparse.urlparse(location)
    queries = urlparse.parse_qs(parsed.query)
    state = queries["state"][0]
    
    # Step 2: GET /connections/oauth/callback with state and code
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "shpat_mock_access_token",
            "refresh_token": "mock_refresh_token",
            "expires_in": 3600
        }
        mock_post.return_value = mock_resp
        
        callback_resp = await client.get(
            f"/connections/oauth/callback?code=mock_auth_code&state={state}"
        )
        assert callback_resp.status_code == 200
        
        # Check Connection record created and is active
        stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
        res = await session.execute(stmt)
        conn = res.scalar_one()
        assert conn.status == "active"
        assert conn.credential is not None

@pytest.mark.asyncio
async def test_callback_code_exchange_failure(client, session):
    """Test 49: Verify callback handles token exchange failure gracefully, showing error page."""
    # Step 1: Generate a valid state
    try:
        from app.services.oauth import generate_oauth_state
        state = generate_oauth_state("t1", "b1", "https://app.agencyos.com/callback")
    except ImportError:
        pytest.skip("State signing functions not implemented yet (expected Red state)")

    # Step 2: Callback with code but token exchange fails
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_grant", "error_description": "Authorization code expired."}
        mock_post.return_value = mock_resp
        
        resp = await client.get(f"/connections/oauth/callback?code=expired_code&state={state}")
        if resp.status_code == 404:
            pytest.skip("Callback endpoint not implemented yet (expected Red state)")
            
        assert resp.status_code == 400
        assert "Authorization code expired" in resp.text

@pytest.mark.asyncio
async def test_cross_tenant_session_attack(client, session):
    """Test 50: Verify that state tokens generated for tenant A cannot be used by tenant B (state hijacking protection)."""
    try:
        from app.services.oauth import generate_oauth_state
        # Generate state for tenant A
        state_tenant_A = generate_oauth_state("tenant-A", "b1", "https://app.agencyos.com/callback")
    except ImportError:
        pytest.skip("State signing functions not implemented yet (expected Red state)")

    # Callback is invoked, but caller's active session/context is tenant B
    # Callback endpoint should verify the tenant context matches the state payload
    resp = await client.get(
        f"/connections/oauth/callback?code=mock_code&state={state_tenant_A}",
        headers={"X-Tenant-ID": "tenant-B"}
    )
    if resp.status_code == 404:
        pytest.skip("Callback endpoint not implemented yet (expected Red state)")
        
    # Should reject the callback with 400 Bad Request / state mismatch
    assert resp.status_code == 400
    assert "Tenant mismatch" in resp.text or "state" in resp.text.lower()

@pytest.mark.asyncio
async def test_connection_scope_verification(client, session):
    """Test 51: Verify callback rejects token exchanges that don't return all required scopes."""
    try:
        from app.services.oauth import generate_oauth_state
        state = generate_oauth_state("t1", "b1", "https://app.agencyos.com/callback")
    except ImportError:
        pytest.skip("State signing functions not implemented yet (expected Red state)")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Shopify callback returns scopes, let's return limited scopes
        mock_resp.json.return_value = {
            "access_token": "mock_token",
            "scope": "read_products",  # Missing write_products
            "expires_in": 3600
        }
        mock_post.return_value = mock_resp
        
        resp = await client.get(f"/connections/oauth/callback?code=mock_code&state={state}")
        if resp.status_code == 404:
            pytest.skip("Callback endpoint not implemented yet (expected Red state)")
            
        assert resp.status_code == 400
        assert "scope" in resp.text.lower() or "permission" in resp.text.lower()

def test_open_redirect_bypass_payloads():
    """Test 52: Verify redirect URI validation rejects advanced open redirect bypass payloads."""
    try:
        from app.services.oauth import validate_redirect_uri
    except ImportError:
        pytest.skip("Redirect validation helper not implemented yet (expected Red state)")

    # Bypasses using subdomains or path traversal
    assert validate_redirect_uri("https://app.agencyos.com.attacker.com/bypass") is False
    assert validate_redirect_uri("https://attacker.com/app.agencyos.com") is False
    assert validate_redirect_uri("https://app.agencyos.com@attacker.com/bypass") is False
    assert validate_redirect_uri("https://app.agencyos.com\\@attacker.com/bypass") is False
    assert validate_redirect_uri("https://localhost.attacker.com") is False
