import logging
import io
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.observability import setup_logging, StructuredJsonFormatter, redact_text
from app.kernel import loop
from app.kernel.optypes import Money, OpSpec, Reversibility, Severity, OpState
from app.models import Tenant, Brand, OpRow

def test_pii_redaction_text():
    # Test phone number redaction in plain text
    raw_message = "Sending WhatsApp card to +919876543210 for approval"
    assert redact_text(raw_message) == "Sending WhatsApp card to [REDACTED] for approval"

    # Test international format
    assert redact_text("Call +12345678901 for support") == "Call [REDACTED] for support"


def test_logging_redaction_json():
    # Test redaction within StructuredJsonFormatter
    formatter = StructuredJsonFormatter()
    
    # Create a dummy LogRecord
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Triggered event for phone +919999999999",
        args=(),
        exc_info=None
    )
    
    # Add extra fields (e.g. extra={"to": "+918888888888", "token": "abc123secret"})
    record.to = "+918888888888"
    record.token = "abc123secret"
    record.regular_field = "safe_value"
    
    formatted_json = formatter.format(record)
    import json
    data = json.loads(formatted_json)
    
    assert data["message"] == "Triggered event for phone [REDACTED]"
    assert data["to"] == "[REDACTED]"
    assert data["token"] == "[REDACTED]"
    assert data["regular_field"] == "safe_value"


@pytest.mark.asyncio
async def test_sentry_tracing_in_drain(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # Bootstrap
    async with async_session() as s:
        tenant = Tenant(name="Sentry Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Sentry Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # Propose Op
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="manage",
        action="manage.backup.create",
        params={"db_name": "db1", "backup_file": "gs://bucket/backup.sql"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="tester")
        await s.commit()
        op_id = row.id

    # Transition to APPROVED
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        await loop.transition(s, db_row, OpState.PREVIEWED, actor="tester")
        await loop.decide(s, db_row, decision="approve", actor="chandan", role="AGENCY_OWNER", surface="web")
        await s.commit()

    # Mock Sentry SDK start_transaction and start_span
    mock_transaction = MagicMock()
    mock_span = MagicMock()

    with patch("sentry_sdk.start_transaction", return_value=mock_transaction) as mock_start_tx, \
         patch("sentry_sdk.start_span", return_value=mock_span) as mock_start_span:
        
        async with async_session() as s:
            processed = await loop.drain_once(s)
            await s.commit()
            assert processed == 1

        # Assert Sentry transaction was started for outbox drain
        mock_start_tx.assert_called()
        # Get the transaction trace operation from call arguments
        args, kwargs = mock_start_tx.call_args
        assert kwargs.get("op") == "outbox.drain"
        
        # Assert Sentry spans were opened for adapter execute and verify
        mock_start_span.assert_called()
        span_ops = [call_kwargs.get("op") for _, call_kwargs in mock_start_span.call_args_list]
        assert "adapter.execute" in span_ops
        assert "adapter.verify" in span_ops
