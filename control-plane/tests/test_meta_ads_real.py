import pytest
from unittest.mock import patch, MagicMock
from app.services.meta_ads import MetaAdsClient

@pytest.fixture
def real_client():
    config = {
        "ad_account_id": "act_1234567890",
        "api_url": "https://graph.facebook.com/v19.0"
    }
    # Passing a token that doesn't trigger mock mode
    return MetaAdsClient(token="real-facebook-token-xyz", config=config)

@pytest.mark.asyncio
async def test_meta_ads_real_create_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock successful response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "meta-camp-123"}
        mock_post.return_value = mock_resp

        ok = await real_client.create_campaign("camp-123", "Spring Promo", 150000, 4500)
        assert ok is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        headers = kwargs["headers"]
        payload = kwargs["json"]

        assert url == "https://graph.facebook.com/v19.0/act_1234567890/campaigns"
        assert headers["Authorization"] == "Bearer real-facebook-token-xyz"
        assert payload["name"] == "Spring Promo"
        assert payload["objective"] == "OUTCOME_TRAFFIC"
        assert payload["daily_budget"] == 150000

@pytest.mark.asyncio
async def test_meta_ads_real_update_campaign(real_client):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok = await real_client.update_campaign("meta-camp-123", status="PAUSED", budget_minor=200000)
        assert ok is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://graph.facebook.com/v19.0/meta-camp-123"
        assert payload["status"] == "PAUSED"
        assert payload["daily_budget"] == 200000

@pytest.mark.asyncio
async def test_meta_ads_real_delete_campaign(real_client):
    with patch("httpx.AsyncClient.delete") as mock_delete:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_delete.return_value = mock_resp

        ok = await real_client.delete_campaign("meta-camp-123")
        assert ok is True

        mock_delete.assert_called_once()
        args, kwargs = mock_delete.call_args
        url = args[0]
        assert url == "https://graph.facebook.com/v19.0/meta-camp-123"

@pytest.mark.asyncio
async def test_meta_ads_real_get_campaign(real_client):
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "meta-camp-123",
            "name": "Spring Promo",
            "status": "ACTIVE",
            "daily_budget": "150000"
        }
        mock_get.return_value = mock_resp

        camp = await real_client.get_campaign("meta-camp-123")
        assert camp is not None
        assert camp["id"] == "meta-camp-123"
        assert camp["name"] == "Spring Promo"
        assert camp["status"] == "ACTIVE"
        assert camp["budget_minor"] == 150000

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        url = args[0]
        params = kwargs["params"]

        assert url == "https://graph.facebook.com/v19.0/meta-camp-123"
        assert "id,name,status" in params["fields"]

@pytest.mark.asyncio
async def test_meta_ads_real_get_performance(real_client):
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "impressions": "25000",
                    "clicks": "680",
                    "spend": "180.50", # 180.50 USD (minor = 18050)
                    "actions": [
                        {"action_type": "lead", "value": "4"},
                        {"action_type": "purchase", "value": "2"}
                    ],
                    "action_values": [
                        {"action_type": "purchase", "value": "120.00"}
                    ]
                }
            ]
        }
        mock_get.return_value = mock_resp

        perf = await real_client.get_performance("meta-camp-123")
        assert perf is not None
        assert perf["impressions"] == 25000
        assert perf["clicks"] == 680
        assert perf["spend_minor"] == 18050
        assert perf["conversions"] == 6 # 4 leads + 2 purchases
        # Real value 120.00 USD (minor = 12000)
        assert perf["revenue_minor"] == 12000
        assert perf["roi"] == 12000.0 / 18050.0

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        url = args[0]
        params = kwargs["params"]

        assert url == "https://graph.facebook.com/v19.0/meta-camp-123/insights"
        assert "impressions,clicks,spend" in params["fields"]

@pytest.mark.asyncio
async def test_meta_ads_real_get_performance_no_value(real_client):
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "impressions": "25000",
                    "clicks": "680",
                    "spend": "180.50",
                    "actions": [
                        {"action_type": "link_click", "value": "320"}
                    ]
                }
            ]
        }
        mock_get.return_value = mock_resp

        perf = await real_client.get_performance("meta-camp-123")
        assert perf is not None
        assert perf["revenue_minor"] is None # No fabrication!
        assert perf["roi"] is None

@pytest.mark.asyncio
async def test_meta_ads_real_retry_success(real_client, monkeypatch):
    import asyncio
    sleep_calls = []
    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock responses: 429 -> 500 -> 200
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"id": "meta-camp-123"}
        
        mock_post.side_effect = [mock_resp_429, mock_resp_500, mock_resp_200]

        ok = await real_client.create_campaign("camp-123", "Spring Promo", 150000, 4500)
        assert ok is True
        
        assert mock_post.call_count == 3
        assert len(sleep_calls) == 2

@pytest.mark.asyncio
async def test_meta_ads_real_campaign_id_injection_protection(real_client):
    unsafe_campaign_ids = [
        "meta-camp-123'; DROP TABLE campaign;--",
        "meta-camp-123; SELECT * FROM campaign",
        "meta-camp-123'",
        "meta-camp-123\"",
        "meta-camp-123<script>",
    ]
    for unsafe_id in unsafe_campaign_ids:
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
