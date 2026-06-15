import pytest
from unittest.mock import patch, MagicMock
from app.models import OpRow
from app.whatsapp import send_approval_card

@pytest.mark.asyncio
@patch("app.whatsapp.WHATSAPP_TOKEN", "mock_token")
@patch("app.whatsapp.WHATSAPP_PHONE_NUMBER_ID", "mock_phone_id")
@patch("app.whatsapp.WHATSAPP_APPROVER_PHONE", "mock_approver_phone")
async def test_send_approval_card_alert():
    # 1. Setup mock alert Op
    op = OpRow(
        id="op_alert_123",
        tenant_id="t1",
        brand_id="b1",
        action="grow.alert.dispatch",
        preview_summary="⚠️ Catalog mismatch: 10 critical items",
        params={"message": "Catalog mismatch: 10 critical items"},
        cost_amount_minor=0,
        cost_currency="INR",
        impact=1,
        reversibility="IRREVERSIBLE"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_alert_test"}]}

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        wamid = await send_approval_card(op)
        assert wamid == "wamid_alert_test"
        
        # Verify post arguments
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "mock_approver_phone"
        assert payload["type"] == "text"
        assert "⚠️ *Grow Alert Notification*" in payload["text"]["body"]
        assert "Catalog mismatch: 10 critical items" in payload["text"]["body"]


@pytest.mark.asyncio
@patch("app.whatsapp.WHATSAPP_TOKEN", "mock_token")
@patch("app.whatsapp.WHATSAPP_PHONE_NUMBER_ID", "mock_phone_id")
@patch("app.whatsapp.WHATSAPP_APPROVER_PHONE", "mock_approver_phone")
async def test_send_approval_card_bid_adjust():
    # 2. Setup mock bid adjust Op
    op = OpRow(
        id="op_bid_123",
        tenant_id="t1",
        brand_id="b1",
        action="grow.bid.adjust",
        preview_summary="Adjust bid from 50 to 200 INR",
        params={"campaign_id": "camp-1", "new_bid_minor": 20000},
        cost_amount_minor=0,
        cost_currency="INR",
        impact=1,
        reversibility="COMPENSATABLE"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_bid_test"}]}

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        wamid = await send_approval_card(op)
        assert wamid == "wamid_bid_test"
        
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["type"] == "template"
        
        body_params = payload["template"]["components"][0]["parameters"]
        # {{1}} Action title
        assert body_params[0]["text"] == "Grow: Bid Adjustment"
        # {{2}} Preview summary
        assert body_params[1]["text"] == "Adjust bid from 50 to 200 INR"
        # {{3}} Cost string override
        assert body_params[2]["text"] == "No immediate cost impact"
        # {{4}} Severity/Reversibility
        assert "Impact: 1" in body_params[3]["text"]


@pytest.mark.asyncio
@patch("app.whatsapp.WHATSAPP_TOKEN", "mock_token")
@patch("app.whatsapp.WHATSAPP_PHONE_NUMBER_ID", "mock_phone_id")
@patch("app.whatsapp.WHATSAPP_APPROVER_PHONE", "mock_approver_phone")
async def test_send_approval_card_budget_reallocate():
    # 3. Setup mock budget reallocation Op
    op = OpRow(
        id="op_reallocate_123",
        tenant_id="t1",
        brand_id="b1",
        action="grow.budget.reallocate",
        preview_summary="Transfer 1,000 INR from Google to Meta",
        params={"transfer_amount_minor": 100000},
        cost_amount_minor=0,
        cost_currency="INR",
        impact=2,
        reversibility="COMPENSATABLE"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_reallocate_test"}]}

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        wamid = await send_approval_card(op)
        assert wamid == "wamid_reallocate_test"
        
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        body_params = payload["template"]["components"][0]["parameters"]
        
        assert body_params[0]["text"] == "Grow: Budget Reallocation"
        assert body_params[2]["text"] == "0.00 INR (Cross-channel shift)"


@pytest.mark.asyncio
@patch("app.whatsapp.WHATSAPP_TOKEN", "mock_token")
@patch("app.whatsapp.WHATSAPP_PHONE_NUMBER_ID", "mock_phone_id")
@patch("app.whatsapp.WHATSAPP_APPROVER_PHONE", "mock_approver_phone")
async def test_send_approval_card_blocked():
    # 4. Setup mock blocked Op
    op = OpRow(
        id="op_blocked_123",
        tenant_id="t1",
        brand_id="b1",
        action="grow.budget.reallocate",
        state="BLOCKED",
        cost_amount_minor=0,
        cost_currency="INR",
        impact=2,
        reversibility="COMPENSATABLE"
    )

    # Mock DB Session returning a mock OpTrace
    from app.models import OpTrace
    mock_trace = OpTrace(
        op_id="op_blocked_123",
        tenant_id="t1",
        kind="gate",
        detail={
            "violations": [
                {
                    "rule_id": "grow_budget_transfer_cap",
                    "limit": "amount <= 50,000.00 INR",
                    "attempted": "60,000.00 INR",
                    "delta": "+10,000.00 INR over cap"
                }
            ]
        }
    )

    from unittest.mock import AsyncMock
    mock_session = AsyncMock()
    mock_exec_res = MagicMock()
    mock_exec_res.scalar_one_or_none.return_value = mock_trace
    mock_session.execute.return_value = mock_exec_res

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_blocked_test"}]}

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        wamid = await send_approval_card(op, session=mock_session)
        assert wamid == "wamid_blocked_test"
        
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["type"] == "text"
        
        body = payload["text"]["body"]
        assert "🛑 *Operation Blocked by Safety Guardrails*" in body
        assert "grow.budget.reallocate" in body
        assert "grow_budget_transfer_cap" in body
        assert "Limit:* amount <= 50,000.00 INR" in body
        assert "Attempted:* 60,000.00 INR" in body
        assert "Delta:* +10,000.00 INR over cap" in body

