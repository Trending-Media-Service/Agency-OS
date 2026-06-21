"""Tests for the omnichannel governed wiring in the Grow adapter:

- CRM POAS bootstrapper (grow.crm_poas.bootstrap) -> GoogleAdsClient.bootstrap_offline_conversions
- GTM hygiene + tracking mismatch (grow.gtm.*, grow.tracking.audit_mismatch) -> GTMClient
- Storefront catalog/sales/webhooks (grow.storefront.*) -> IStorefrontAdapter / ShopifyStorefront
- gtm + shopify connection providers (connect/disconnect/verify/compensate)
- get_gtm_client / get_storefront_client factories
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select

from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection
from app.services.gtm import get_gtm_client, GTMClient
from app.services.storefront import get_storefront_client, IStorefrontAdapter
from app.services.shopify import ShopifyStorefront
from app.services.marketing import MockMarketingClient


@pytest.fixture
def adapter():
    return GrowAdapter()


def _op(action, params=None, tenant_id="t1", brand_id="b1"):
    return OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action=action,
        params=params or {},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0),
    )


# ---------------------------------------------------------------- factories

def test_gtm_factory_test_mode_is_mock():
    client = get_gtm_client()
    assert isinstance(client, GTMClient)
    assert client._is_mock is True


def test_gtm_factory_prod_requires_token(monkeypatch):
    monkeypatch.setenv("AOS_ENV", "production")
    with pytest.raises(ValueError) as exc:
        get_gtm_client(token=None)
    assert "Credentials (token) are required" in str(exc.value)


def test_storefront_factory_test_mode_is_mock():
    client = get_storefront_client(provider="shopify")
    assert isinstance(client, IStorefrontAdapter)
    assert isinstance(client, ShopifyStorefront)
    assert client._is_mock_mode() is True


def test_storefront_factory_prod_requires_token(monkeypatch):
    monkeypatch.setenv("AOS_ENV", "production")
    with pytest.raises(ValueError):
        get_storefront_client(provider="shopify", shop_url="x.myshopify.com", token=None)


def test_storefront_factory_unsupported_provider():
    with pytest.raises(ValueError) as exc:
        get_storefront_client(provider="woocommerce")
    assert "Unsupported storefront provider" in str(exc.value)


async def test_mock_marketing_bootstrap_offline_conversions():
    m = MockMarketingClient()
    res = await m.bootstrap_offline_conversions()
    assert res["success"] is True
    assert res["conversion_action_id"] == "mock-conversion-12345"


# ---------------------------------------------------------------- plan()

@pytest.mark.parametrize("intent,expected_action", [
    ("bootstrap conversions for crm poas", "grow.crm_poas.bootstrap"),
    ("activate poas tracking", "grow.crm_poas.bootstrap"),
    ("clean gtm workspace clutter", "grow.gtm.cleanup_clutter"),
    ("verify gtm container on the homepage", "grow.gtm.verify_onpage"),
    ("audit tracking mismatch", "grow.tracking.audit_mismatch"),
    ("audit product catalog skus", "grow.storefront.catalog_audit"),
    ("run sales analysis report", "grow.storefront.sales_analysis"),
    ("register poas webhook", "grow.storefront.register_poas_webhooks"),
])
def test_plan_routes_new_intents(adapter, intent, expected_action):
    ops = adapter.plan(intent, "t1", "b1")
    assert len(ops) == 1
    assert ops[0].action == expected_action


def test_plan_gtm_cleanup_extracts_container(adapter):
    ops = adapter.plan("clean gtm clutter on container GTM-ABC1234", "t1", "b1")
    assert ops[0].action == "grow.gtm.cleanup_clutter"
    assert ops[0].params["container_public_id"] == "GTM-ABC1234"


def test_plan_gtm_verify_extracts_url(adapter):
    ops = adapter.plan("verify gtm container at https://shop.example.com", "t1", "b1")
    assert ops[0].action == "grow.gtm.verify_onpage"
    assert ops[0].params["target_url"] == "https://shop.example.com"


def test_plan_gtm_connect(adapter):
    ops = adapter.plan("connect gtm with secret:gtm-secret-token", "t1", "b1")
    assert ops[0].action == "grow.gtm.connect"
    assert ops[0].params["provider"] == "gtm"
    assert ops[0].params["credential"] == "gtm-secret-token"


def test_plan_shopify_connect_extracts_shop_url(adapter):
    ops = adapter.plan("connect shopify with secret:shop-tok demo.myshopify.com", "t1", "b1")
    assert ops[0].action == "grow.shopify.connect"
    assert ops[0].params["provider"] == "shopify"
    assert ops[0].params["credential"] == "shop-tok"
    assert ops[0].params["config"]["shop_url"] == "demo.myshopify.com"


def test_plan_register_webhook_extracts_gateway(adapter):
    ops = adapter.plan("register poas webhook at https://sgtm.example.com/collect", "t1", "b1")
    assert ops[0].action == "grow.storefront.register_poas_webhooks"
    assert ops[0].params["gateway_url"] == "https://sgtm.example.com/collect"


# keep-existing-behaviour guard: "clean keywords" must still route to keyword cleanup
def test_plan_clean_keywords_not_shadowed(adapter):
    ops = adapter.plan("clean generic search keywords", "t1", "b1")
    assert ops[0].action == "grow.search.keyword_cleanup"


# ---------------------------------------------------------------- preview()

def test_preview_masks_gtm_credential(adapter):
    art = adapter.preview(_op("grow.gtm.connect", {"provider": "gtm", "credential": "topsecret"}))
    assert art.kind == "gtm_connect_preview"
    assert "****" in art.summary


def test_preview_storefront_catalog(adapter):
    art = adapter.preview(_op("grow.storefront.catalog_audit", {"provider": "shopify"}))
    assert art.kind == "storefront_catalog_audit_preview"


# ---------------------------------------------------------------- execute() (mock, no session)

async def test_execute_bootstrap(adapter):
    res = await adapter.execute(_op("grow.crm_poas.bootstrap", {"provider": "google-ads"}), "idem-boot")
    assert res.ok is True
    assert res.detail["conversion_action_id"] == "mock-conversion-12345"


async def test_execute_gtm_cleanup(adapter):
    op = _op("grow.gtm.cleanup_clutter", {"container_public_id": "GTM-ABC1234", "provider": "gtm"})
    res = await adapter.execute(op, "idem-clean")
    assert res.ok is True
    assert "Offline Conversion" in res.detail["deleted_tags"]


async def test_execute_gtm_cleanup_requires_container(adapter):
    res = await adapter.execute(_op("grow.gtm.cleanup_clutter", {"provider": "gtm"}), "idem-clean2")
    assert res.ok is False
    assert "container_public_id" in res.detail["error"]


async def test_execute_gtm_list_containers(adapter):
    res = await adapter.execute(_op("grow.gtm.list_containers", {"provider": "gtm"}), "idem-list")
    assert res.ok is True
    assert len(res.detail["containers"]) == 2


async def test_execute_gtm_verify_onpage(adapter):
    op = _op("grow.gtm.verify_onpage", {"target_url": "https://shop.example.com", "provider": "gtm"})
    with patch.object(GTMClient, "verify_onpage_gtm_container", new=AsyncMock(return_value=["GTM-LIVE99"])):
        res = await adapter.execute(op, "idem-verify")
    assert res.ok is True
    assert res.detail["onpage_containers"] == ["GTM-LIVE99"]


async def test_execute_gtm_verify_onpage_requires_url(adapter):
    res = await adapter.execute(_op("grow.gtm.verify_onpage", {"provider": "gtm"}), "idem-verify2")
    assert res.ok is False
    assert "target_url" in res.detail["error"]


async def test_execute_tracking_audit_detects_mismatch(adapter):
    op = _op("grow.tracking.audit_mismatch", {
        "container_public_id": "GTM-EXPECTED",
        "target_url": "https://shop.example.com",
        "provider": "gtm",
    })
    with patch.object(GTMClient, "verify_onpage_gtm_container", new=AsyncMock(return_value=["GTM-OTHER"])):
        res = await adapter.execute(op, "idem-audit")
    assert res.ok is True
    assert res.detail["mismatch"] is True
    assert res.detail["expected_container"] == "GTM-EXPECTED"


async def test_execute_tracking_audit_no_url_no_mismatch(adapter):
    res = await adapter.execute(_op("grow.tracking.audit_mismatch", {"provider": "gtm"}), "idem-audit2")
    assert res.ok is True
    assert res.detail["mismatch"] is False
    # mock list_containers exposes two containers
    assert len(res.detail["available_containers"]) == 2


async def test_execute_storefront_catalog_audit(adapter):
    res = await adapter.execute(_op("grow.storefront.catalog_audit", {"provider": "shopify"}), "idem-cat")
    assert res.ok is True
    assert res.detail["missing_barcode_count"] == 50


async def test_execute_storefront_sales_analysis(adapter):
    res = await adapter.execute(_op("grow.storefront.sales_analysis", {"provider": "shopify"}), "idem-sales")
    assert res.ok is True
    assert res.detail["total_sales"] == 78900.0


async def test_execute_storefront_register_webhook(adapter):
    op = _op("grow.storefront.register_poas_webhooks", {"provider": "shopify", "gateway_url": "https://sgtm.example.com/collect"})
    res = await adapter.execute(op, "idem-wh")
    assert res.ok is True
    assert res.detail["webhook_id"] == "mock_webhook_id"


async def test_execute_storefront_register_webhook_requires_gateway(adapter):
    res = await adapter.execute(_op("grow.storefront.register_poas_webhooks", {"provider": "shopify"}), "idem-wh2")
    assert res.ok is False
    assert "gateway_url" in res.detail["error"]


# ---------------------------------------------------------------- verify()

@pytest.mark.parametrize("action,check", [
    ("grow.crm_poas.bootstrap", "conversion_action_bootstrapped"),
    ("grow.gtm.cleanup_clutter", "workspace_cleaned"),
    ("grow.gtm.verify_onpage", "onpage_scanned"),
    ("grow.tracking.audit_mismatch", "tracking_audited"),
    ("grow.storefront.catalog_audit", "catalog_audited"),
    ("grow.storefront.register_poas_webhooks", "webhook_registered"),
])
async def test_verify_new_actions(adapter, action, check):
    verdict = await adapter.verify(_op(action))
    assert verdict.ok is True
    assert verdict.checks.get(check) is True


# ---------------------------------------------------------------- compensate()

def test_compensate_gtm_connect(adapter):
    comps = adapter.compensate(_op("grow.gtm.connect", {"provider": "gtm"}))
    assert len(comps) == 1
    assert comps[0].action == "grow.gtm.disconnect"
    assert comps[0].params["provider"] == "gtm"


def test_compensate_shopify_connect(adapter):
    comps = adapter.compensate(_op("grow.shopify.connect", {"provider": "shopify"}))
    assert len(comps) == 1
    assert comps[0].action == "grow.shopify.disconnect"
    assert comps[0].params["provider"] == "shopify"


# ---------------------------------------------------------------- connection lifecycle (with DB)

async def test_gtm_connect_execute_verify_disconnect(adapter, session):
    op = adapter.plan("connect gtm with secret:gtm-secret-token", "t1", "b1")[0]
    res = await adapter.execute(op, "idem-gtm-connect", session=session)
    assert res.ok is True

    stmt = select(Connection).where(
        Connection.tenant_id == "t1", Connection.brand_id == "b1", Connection.provider == "gtm"
    )
    conn = (await session.execute(stmt)).scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.credential

    verdict = await adapter.verify(op, session=session)
    assert verdict.ok is True
    assert verdict.checks["api_token_valid"] is True

    # compensate -> disconnect removes it
    disconnect_op = adapter.compensate(op)[0]
    res_d = await adapter.execute(disconnect_op, "idem-gtm-disconnect", session=session)
    assert res_d.ok is True
    conn2 = (await session.execute(stmt)).scalar_one_or_none()
    assert conn2 is None


async def test_shopify_connect_stores_shop_url(adapter, session):
    op = adapter.plan("connect shopify with secret:shop-tok demo.myshopify.com", "t1", "b1")[0]
    res = await adapter.execute(op, "idem-shop-connect", session=session)
    assert res.ok is True

    stmt = select(Connection).where(
        Connection.tenant_id == "t1", Connection.brand_id == "b1", Connection.provider == "shopify"
    )
    conn = (await session.execute(stmt)).scalar_one_or_none()
    assert conn is not None
    assert conn.config.get("shop_url") == "demo.myshopify.com"
