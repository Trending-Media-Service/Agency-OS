import base64
import hashlib
import hmac
import pytest
from sqlalchemy import select

from app.models import Connection, OpRow, TrustSnapshot


def _generate_shopify_signature(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.fixture(autouse=True)
async def setup_connection_and_trust(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        async with s.begin():
            # Seed Shopify connection
            conn = Connection(
                tenant_id="tenant-webhook-test",
                brand_id="brand-shopify-test",
                provider="shopify",
                secret_ref="shopify-secret-key-123",
                config={"shop_url": "test-store.myshopify.com"}
            )
            s.add(conn)

            # Seed Trust Snapshot (Tier 1 - Supervised)
            snap = TrustSnapshot(
                tenant_id="tenant-webhook-test",
                brand_id="brand-shopify-test",
                domain="manage",
                score=75.0,
                tier=1
            )
            s.add(snap)


@pytest.mark.asyncio
async def test_shopify_webhook_proposes_op_successfully(client, db_engine):
    payload = b'{"id": 998877, "total_price": "149.99", "created_at": "2026-06-15T05:00:00Z"}'
    signature = _generate_shopify_signature(payload, "shopify-secret-key-123")

    headers = {
        "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Shop-Domain": "test-store.myshopify.com",
        "X-Shopify-Topic": "orders/create",
        "Content-Type": "application/json"
    }

    response = await client.post(
        "/webhooks/plugins/shopify",
        content=payload,
        headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert len(data["proposed_ops"]) == 1

    op_id = data["proposed_ops"][0]

    # Verify the Op exists in the database with the correct tenant context
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        # We query as admin/worker to bypass RLS since we don't have header injection in the direct DB check
        stmt = select(OpRow).where(OpRow.id == op_id)
        res = await s.execute(stmt)
        row = res.scalar_one_or_none()

        assert row is not None
        assert row.tenant_id == "tenant-webhook-test"
        assert row.brand_id == "brand-shopify-test"
        assert row.domain == "manage"
        assert row.action == "manage.shopify.sync_order"
        assert row.params["order_id"] == "998877"
        assert row.params["amount_minor"] == 14999
        # Tier 1 supervised -> goes to AWAITING_APPROVAL
        assert row.state == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_shopify_webhook_bad_signature_rejected(client):
    payload = b'{"id": 998877, "total_price": "149.99"}'
    headers = {
        "X-Shopify-Hmac-Sha256": "bad-signature-value-here",
        "X-Shopify-Shop-Domain": "test-store.myshopify.com",
        "X-Shopify-Topic": "orders/create",
        "Content-Type": "application/json"
    }

    response = await client.post(
        "/webhooks/plugins/shopify",
        content=payload,
        headers=headers
    )

    assert response.status_code == 401
    assert "signature mismatch" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_shopify_webhook_unknown_brand_rejected(client):
    payload = b'{"id": 998877, "total_price": "149.99"}'
    signature = _generate_shopify_signature(payload, "shopify-secret-key-123")
    headers = {
        "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Shop-Domain": "unknown-store.myshopify.com",
        "X-Shopify-Topic": "orders/create",
        "Content-Type": "application/json"
    }

    response = await client.post(
        "/webhooks/plugins/shopify",
        content=payload,
        headers=headers
    )

    assert response.status_code == 404
    assert "unknown brand connection" in response.json()["detail"].lower()
