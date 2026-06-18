import pytest
from unittest.mock import patch, MagicMock
from app.services.google_ads import GoogleAdsClient

@pytest.fixture
def real_client():
    config = {
        "developer_token": "dev-token-123",
        "customer_id": "cust-999-888",
        "api_url": "https://googleads.googleapis.com/v17"
    }
    # Passing a token that doesn't trigger mock mode
    return GoogleAdsClient(token="real-oauth-token-abc", config=config)

@pytest.mark.asyncio
async def test_google_ads_real_create_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock successful response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"resourceName": "customers/cust-999-888/campaigns/camp-123"}
        mock_post.return_value = mock_resp

        ok = await real_client.create_campaign("camp-123", "Summer Sale", 100000, 5000)
        assert ok is True

        # Verify correct HTTP call was made
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        headers = kwargs["headers"]
        payload = kwargs["json"]

        assert url == "https://googleads.googleapis.com/v17/customers/cust-999-888/campaigns:mutate"
        assert headers["Authorization"] == "Bearer real-oauth-token-abc"
        assert headers["developer-token"] == "dev-token-123"
        assert headers["login-customer-id"] == "cust-999-888"
        assert payload["operations"][0]["create"]["name"] == "Summer Sale"

@pytest.mark.asyncio
async def test_google_ads_real_update_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok = await real_client.update_campaign("camp-123", status="ACTIVE")
        assert ok is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://googleads.googleapis.com/v17/customers/cust-999-888/campaigns:mutate"
        assert payload["operations"][0]["update"]["status"] == "ENABLED"
        assert payload["operations"][0]["update"]["resourceName"] == "customers/cust-999-888/campaigns/camp-123"

@pytest.mark.asyncio
async def test_google_ads_real_delete_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok = await real_client.delete_campaign("camp-123")
        assert ok is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://googleads.googleapis.com/v17/customers/cust-999-888/campaigns:mutate"
        assert payload["operations"][0]["remove"] == "customers/cust-999-888/campaigns/camp-123"

@pytest.mark.asyncio
async def test_google_ads_real_get_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "campaign": {
                        "id": "camp-123",
                        "name": "Summer Sale",
                        "status": "ENABLED"
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        camp = await real_client.get_campaign("camp-123")
        assert camp is not None
        assert camp["id"] == "camp-123"
        assert camp["name"] == "Summer Sale"
        assert camp["status"] == "ACTIVE"

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://googleads.googleapis.com/v17/customers/cust-999-888/googleAds:search"
        assert "SELECT campaign.id" in payload["query"]

@pytest.mark.asyncio
async def test_google_ads_real_get_performance(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "metrics": {
                        "impressions": "15000",
                        "clicks": "450",
                        "costMicros": "125000000", # 125 USD (minor = 12500)
                        "conversions": "8.0",
                        "conversionsValue": "375.0" # 375 USD (minor = 37500)
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        perf = await real_client.get_performance("camp-123")
        assert perf is not None
        assert perf["impressions"] == 15000
        assert perf["clicks"] == 450
        assert perf["spend_minor"] == 12500
        assert perf["revenue_minor"] == 37500
        assert perf["conversions"] == 8
        assert perf["roi"] == 3.0 # 375 / 125

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://googleads.googleapis.com/v17/customers/cust-999-888/googleAds:search"
        assert "metrics.impressions" in payload["query"]


@pytest.mark.asyncio
async def test_google_ads_real_retry_success(real_client, monkeypatch):
    import asyncio
    # Mock asyncio.sleep to avoid waiting in tests
    sleep_calls = []
    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock responses: 429 -> 503 -> 200
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        
        mock_resp_503 = MagicMock()
        mock_resp_503.status_code = 503
        
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"resourceName": "customers/cust-999-888/campaigns/camp-123"}
        
        mock_post.side_effect = [mock_resp_429, mock_resp_503, mock_resp_200]

        ok = await real_client.create_campaign("camp-123", "Summer Sale", 100000, 5000)
        assert ok is True
        
        # Verify 3 POST calls were made
        assert mock_post.call_count == 3
        # Verify sleep was called twice with exponential backoff (base_delay = 1.0, so delays are around 1s and 2s)
        assert len(sleep_calls) == 2
        assert sleep_calls[0] > 0
        assert sleep_calls[1] > 0

@pytest.mark.asyncio
async def test_google_ads_real_campaign_id_injection_protection(real_client):
    unsafe_campaign_ids = [
        "camp-123'; DROP TABLE campaign;--",
        "camp-123; SELECT * FROM campaign",
        "camp-123'",
        "camp-123\"",
        "camp-123<script>",
    ]
    for unsafe_id in unsafe_campaign_ids:
        # Should raise ValueError before making any network calls
        with pytest.raises(ValueError) as exc:
            await real_client.get_campaign(unsafe_id)
        assert "Invalid/unsafe campaign_id format" in str(exc.value)

        with pytest.raises(ValueError) as exc:
            await real_client.get_performance(unsafe_id)
        assert "Invalid/unsafe campaign_id format" in str(exc.value)

        with pytest.raises(ValueError) as exc:
            await real_client.update_campaign(unsafe_id, status="ACTIVE")
        assert "Invalid/unsafe campaign_id format" in str(exc.value)

        with pytest.raises(ValueError) as exc:
            await real_client.delete_campaign(unsafe_id)
        assert "Invalid/unsafe campaign_id format" in str(exc.value)
