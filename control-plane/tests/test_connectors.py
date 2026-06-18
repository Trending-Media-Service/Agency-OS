import pytest
from app.adapters.connectors import get_connector
from app.services.secrets import SecretManagerClient

@pytest.mark.asyncio
async def test_universal_connector_resolution_and_secrets():
    # 1. Write a secret credential in Secret Manager mock registry
    secret_ref = "projects/aos-control-plane/secrets/stripe-test-api-key/versions/latest"
    secrets_client = SecretManagerClient()
    await secrets_client.write_secret("stripe-test-api-key", "sk_live_stripe_secret_999")

    # 2. Resolve connector via get_connector
    config = {"api_url": "https://api.stripe.com/v1"}
    connector = await get_connector(
        provider="stripe",
        secret_ref=secret_ref,
        config=config
    )

    # 3. Assert connector resolved and token was successfully decrypted!
    assert connector is not None
    assert connector.provider == "stripe"
    assert connector.token == "sk_live_stripe_secret_999"
    assert connector.api_url == "https://api.stripe.com/v1"


@pytest.mark.asyncio
async def test_stripe_connector_operations():
    config = {}
    connector = await get_connector(
        provider="stripe",
        secret_ref="mock-stripe-secret",
        config=config
    )
    assert connector is not None
    assert await connector.verify_connection() is True

    # Run charge creation
    charge = await connector.create_charge(amount_minor=1500, currency="USD", description="Test Charge")
    assert charge["status"] == "succeeded"
    assert charge["amount"] == 1500
    assert charge["id"] == "ch_mock_12345"


@pytest.mark.asyncio
async def test_razorpay_connector_operations():
    config = {}
    connector = await get_connector(
        provider="razorpay",
        secret_ref="mock-razorpay-secret",
        config=config
    )
    assert connector is not None
    assert await connector.verify_connection() is True

    order = await connector.create_order(amount_minor=50000, currency="INR")
    assert order["status"] == "created"
    assert order["amount"] == 50000
    assert order["id"] == "order_mock_54321"


@pytest.mark.asyncio
async def test_jira_connector_operations():
    config = {"domain": "trending-media"}
    connector = await get_connector(
        provider="jira",
        secret_ref="mock-jira-secret",
        config=config
    )
    assert connector is not None
    assert await connector.verify_connection() is True

    issue = await connector.create_issue(summary="Fix OAuth Bypass", description="Security issue F3", project_key="SEC")
    assert issue["key"] == "SEC-42"
    assert issue["id"] == "10001"


@pytest.mark.asyncio
async def test_aws_connector_operations():
    config = {"region": "ap-south-1"}
    connector = await get_connector(
        provider="aws",
        secret_ref="mock-aws-secret",
        config=config
    )
    assert connector is not None
    assert await connector.verify_connection() is True
    assert await connector.check_bucket_exists("my-aos-bucket") is True


@pytest.mark.asyncio
async def test_directus_connector_operations():
    config = {"url": "http://localhost:8055"}
    connector = await get_connector(
        provider="directus",
        secret_ref="mock-directus-secret",
        config=config
    )
    assert connector is not None
    assert await connector.verify_connection() is True

    items = await connector.fetch_collection("posts")
    assert len(items) == 2
    assert items[0]["title"] == "Mock Post 1"
