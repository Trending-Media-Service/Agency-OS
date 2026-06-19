import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import OutboxItem

@pytest.mark.asyncio
async def test_outbox_tenant_id_cannot_be_null(session: AsyncSession):
    # Create an OutboxItem with tenant_id omitted/None
    item = OutboxItem(
        op_id="op-test-null-tenant",
        tenant_id=None,  # This should be forbidden now
        status="PENDING"
    )
    session.add(item)
    
    # Commit or flush should raise IntegrityError
    with pytest.raises(IntegrityError):
        await session.commit()
        
    await session.rollback()
