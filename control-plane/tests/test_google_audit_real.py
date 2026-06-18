import pytest
from unittest.mock import patch, MagicMock
from app.services.google_audit import GoogleAuditClient

@pytest.fixture
def real_client():
    config = {
        "site_url": "https://active-brand-site.com",
        "merchant_id": "987654321",
        "api_url": "https://shoppingcontent.googleapis.com/content/v2.1"
    }
    client = GoogleAuditClient(token="real-google-oauth-token", config=config)
    client._is_mock = False
    return client

@pytest.mark.asyncio
async def test_google_audit_real_search_console(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "crawlState": "SUCCESSFUL"
                }
            }
        }
        mock_post.return_value = mock_resp

        res = await real_client.run_search_console_audit()
        assert res["status"] == "healthy"
        assert res["findings"]["crawl_errors"] == 0
        assert res["findings"]["indexing_status"] == "indexed"
        assert res["findings"]["site_url_indexed"] is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        headers = kwargs["headers"]
        payload = kwargs["json"]

        assert url == "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
        assert headers["Authorization"] == "Bearer real-google-oauth-token"
        assert payload["inspectionUrl"] == "https://active-brand-site.com"

@pytest.mark.asyncio
async def test_google_audit_real_search_console_degraded(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "FAIL",
                    "crawlState": "FAILED"
                }
            }
        }
        mock_post.return_value = mock_resp

        res = await real_client.run_search_console_audit()
        assert res["status"] == "degraded"
        assert res["findings"]["crawl_errors"] == 1
        assert res["findings"]["indexing_status"] == "partially_indexed"
        assert res["findings"]["site_url_indexed"] is False

@pytest.mark.asyncio
async def test_google_audit_real_merchant_center(real_client):
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resources": [
                {
                    "id": "prod-1",
                    "destinationStatuses": [{"destination": "Shopping", "status": "approved"}]
                },
                {
                    "id": "prod-2",
                    "destinationStatuses": [{"destination": "Shopping", "status": "disapproved"}]
                },
                {
                    "id": "prod-3",
                    "destinationStatuses": [{"destination": "Shopping", "status": "approved"}]
                }
            ]
        }
        mock_get.return_value = mock_resp

        res = await real_client.run_merchant_center_audit()
        assert res["status"] == "degraded"
        assert res["findings"]["disapproved_products"] == 1
        assert res["findings"]["active_items"] == 2
        assert res["findings"]["feed_sync_status"] == "failed_mismatches"

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        url = args[0]
        headers = kwargs["headers"]

        assert url == "https://shoppingcontent.googleapis.com/content/v2.1/987654321/productstatuses"
        assert headers["Authorization"] == "Bearer real-google-oauth-token"


@pytest.mark.asyncio
async def test_google_audit_real_refresh_success(monkeypatch):
    config = {
        "site_url": "https://active-brand-site.com",
        "refresh_token": "refresh-token-123",
        "client_id": "client-id-abc",
        "client_secret": "client-secret-xyz"
    }
    client = GoogleAuditClient(token="expired-token", config=config)
    client._is_mock = False

    # Mock response calls for POST
    # 1st POST: GSC inspect -> returns 401
    # 2nd POST: OAuth refresh -> returns 200 (access_token="new-token-999")
    # 3rd POST: GSC inspect retry -> returns 200 (verdict="PASS")
    with patch("httpx.AsyncClient.post") as mock_post:
        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_refresh_200 = MagicMock()
        resp_refresh_200.status_code = 200
        resp_refresh_200.json.return_value = {"access_token": "new-token-999"}

        resp_inspect_200 = MagicMock()
        resp_inspect_200.status_code = 200
        resp_inspect_200.json.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "crawlState": "SUCCESSFUL"
                }
            }
        }

        mock_post.side_effect = [resp_401, resp_refresh_200, resp_inspect_200]

        res = await client.run_search_console_audit()
        assert res["status"] == "healthy"
        assert client.token == "new-token-999"
        assert client.headers["Authorization"] == "Bearer new-token-999"
        
        # Verify 3 POST requests were made
        assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_google_audit_real_retry_success(real_client, monkeypatch):
    import asyncio
    sleep_calls = []
    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock responses: 429 -> 503 -> 200
        resp_429 = MagicMock()
        resp_429.status_code = 429
        
        resp_503 = MagicMock()
        resp_503.status_code = 503
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "crawlState": "SUCCESSFUL"
                }
            }
        }
        
        mock_post.side_effect = [resp_429, resp_503, resp_200]

        res = await real_client.run_search_console_audit()
        assert res["status"] == "healthy"
        
        assert mock_post.call_count == 3
        assert len(sleep_calls) == 2
