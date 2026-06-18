import pytest
import os
from app.services.marketing import get_marketing_client, MockMarketingClient

def test_marketing_factory_mock_mode(monkeypatch):
    # Case 1: In test environment, the factory always returns the Mock client
    monkeypatch.setenv("AOS_ENV", "test")
    client = get_marketing_client("google-ads")
    assert isinstance(client, MockMarketingClient)
    assert client.provider == "google-ads"

def test_marketing_factory_missing_credentials(monkeypatch):
    # Case 2: In production/development, requesting a real channel without credentials raises ValueError
    monkeypatch.setenv("AOS_ENV", "production")
    with pytest.raises(ValueError) as exc:
        get_marketing_client("google-ads", token=None)
    assert "Credentials (token) are required" in str(exc.value)

def test_marketing_factory_real_client_not_implemented(monkeypatch):
    # Case 3: In production/development, requesting a real channel with credentials raises NotImplementedError in this phase
    monkeypatch.setenv("AOS_ENV", "production")
    with pytest.raises(NotImplementedError) as exc:
        get_marketing_client("google-ads", token="google-oauth-token-123")
    assert "Real integration for provider google-ads is not implemented" in str(exc.value)

def test_marketing_factory_unsupported_provider(monkeypatch):
    monkeypatch.setenv("AOS_ENV", "production")
    with pytest.raises(ValueError) as exc:
        get_marketing_client("unknown-provider", token="some-token")
    assert "Unsupported marketing provider" in str(exc.value)
