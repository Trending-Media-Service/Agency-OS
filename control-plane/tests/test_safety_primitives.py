import pytest
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Tenant, Brand, OpRow, OutboxItem, CircuitBreakerRow
from app.kernel import loop
from app.kernel.optypes import OpState, OpSpec, Severity, Reversibility, Money

class FailingAdapter:
    domain = "failing_domain"
    async def execute(self, op, idem_key, session=None):
        raise RuntimeError("Adapter failure simulation!")
    async def verify(self, op):
        from app.kernel.optypes import VerifyResult
        return VerifyResult(ok=False)

class SuccessAdapter:
    domain = "success_domain"
    async def execute(self, op, idem_key, session=None):
        from app.kernel.optypes import ExecResult
        return ExecResult(ok=True)
    async def verify(self, op):
        from app.kernel.optypes import VerifyResult
        return VerifyResult(ok=True, checks={"status": True})

@pytest.fixture(autouse=True)
def register_test_adapters():
    from app.kernel import loop
    loop.register(FailingAdapter())
    loop.register(SuccessAdapter())
    yield


@pytest.mark.asyncio
async def test_circuit_breaker_tripping_and_blocking(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="Safety Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Safety Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

    # We want to trigger 3 consecutive failures to trip the circuit breaker.
    # We will insert 4 proposed and approved ops.
    op_ids = [f"op_fail_{i}" for i in range(1, 5)]

    async with async_session() as s:
        for op_id in op_ids:
            # Insert approved op
            op = OpRow(
                id=op_id, tenant_id=tid, brand_id=bid, domain="failing_domain",
                action="failing_domain.action.test", params={"test": "1"},
                state="APPROVED", impact=1, reversibility="REVERSIBLE", statutory=False,
                idem_key=f"idem_{op_id}"
            )
            s.add(op)
            # Add to outbox
            s.add(OutboxItem(op_id=op_id, status="PENDING"))
        await s.commit()

    # Run outbox drain:
    # 1st attempt: fails -> consecutive_failures = 1
    # 2nd attempt: fails -> consecutive_failures = 2
    # 3rd attempt: fails -> consecutive_failures = 3 -> trips (OPEN)
    # 4th attempt: should short-circuit immediately to BLOCKED (outbox DEAD)
    async with async_session() as s:
        # Drain items
        processed = await loop.drain_once(s)
        # It processes all 4 items!
        assert processed == 4
        await s.commit()

    # Verify Database state of circuit breaker and ops
    async with async_session() as s:
        # Check breaker state
        stmt_cb = select(CircuitBreakerRow).where(
            CircuitBreakerRow.tenant_id == tid,
            CircuitBreakerRow.brand_id == bid,
            CircuitBreakerRow.domain == "failing_domain"
        )
        res_cb = await s.execute(stmt_cb)
        breaker = res_cb.scalar_one()
        assert breaker.state == "OPEN"
        assert breaker.consecutive_failures == 3 # Tripped at 3

        # Verify Op states
        # First 3 ops failed during execution, so they will be transitioned to retry state
        # In drain_once, if item.attempts < 5, they remain PENDING/EXECUTING?
        # Actually, when they fail, they are set to PENDING in outbox, but their Op state in DB remains EXECUTING/VERIFYING?
        # Wait, inside loop.py line 241, we only transition OpState to PARTIAL when attempts >= 5!
        # So first 3 ops failed but are still in EXECUTING/VERIFYING state in DB (since attempts < 5).
        # But let's check the 4th op: it should have short-circuited to BLOCKED immediately!
        stmt_op4 = select(OpRow).where(OpRow.id == "op_fail_4")
        res_op4 = await s.execute(stmt_op4)
        op4 = res_op4.scalar_one()
        assert op4.state == "BLOCKED"
        # Check the outbox status of the 4th item: it is set to DEAD
        stmt_out4 = select(OutboxItem).where(OutboxItem.op_id == "op_fail_4")
        res_out4 = await s.execute(stmt_out4)
        out4 = res_out4.scalar_one()
        assert out4.status == "DEAD"


@pytest.mark.asyncio
async def test_circuit_breaker_auto_reset(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="Safety Tenant 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Safety Brand 2")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Insert a pre-tripped (OPEN) breaker in DB
        # Tripped 20 minutes ago (1200 seconds ago)
        tripped_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)
        breaker = CircuitBreakerRow(
            tenant_id=tid, brand_id=bid, domain="success_domain",
            consecutive_failures=3, state="OPEN", tripped_at=tripped_at
        )
        s.add(breaker)

        # Propose and approve an Op in the success domain
        op = OpRow(
            id="op_success_1", tenant_id=tid, brand_id=bid, domain="success_domain",
            action="success_domain.action.test", params={"test": "ok"},
            state="APPROVED", impact=1, reversibility="REVERSIBLE", statutory=False,
            idem_key="idem_success_1"
        )
        s.add(op)
        s.add(OutboxItem(op_id="op_success_1", status="PENDING"))
        await s.commit()

    # 2. Run drain_once. Since breaker tripped_at is > 15 minutes ago, it should auto-reset (testing HALF_OPEN)
    # and execute the success adapter successfully, setting state to CLOSED (and resetting consecutive failures)
    async with async_session() as s:
        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # 3. Assertions
    async with async_session() as s:
        # Breaker should be reset to CLOSED
        stmt_cb = select(CircuitBreakerRow).where(
            CircuitBreakerRow.tenant_id == tid,
            CircuitBreakerRow.brand_id == bid,
            CircuitBreakerRow.domain == "success_domain"
        )
        res_cb = await s.execute(stmt_cb)
        breaker = res_cb.scalar_one()
        assert breaker.state == "CLOSED"
        assert breaker.consecutive_failures == 0

        # Op should be DONE
        stmt_op = select(OpRow).where(OpRow.id == "op_success_1")
        res_op = await s.execute(stmt_op)
        op = res_op.scalar_one()
        assert op.state == "DONE"


@pytest.mark.asyncio
async def test_cooldown_blocking(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="Safety Tenant 3", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Safety Brand 3")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Insert a DONE Op in success domain (cooldown baseline execution)
        op_done = OpRow(
            id="op_done_1", tenant_id=tid, brand_id=bid, domain="success_domain",
            action="success_domain.action.test", params={"target_db": "my_db"},
            state="DONE", impact=1, reversibility="REVERSIBLE", statutory=False,
            idem_key="idem_done_1", created_at=dt.datetime.now(dt.timezone.utc)
        )
        s.add(op_done)

        # Propose and approve the duplicate Op (targeting same parameters within lookback window)
        op_dup = OpRow(
            id="op_dup_1", tenant_id=tid, brand_id=bid, domain="success_domain",
            action="success_domain.action.test", params={"target_db": "my_db"},
            state="APPROVED", impact=1, reversibility="REVERSIBLE", statutory=False,
            idem_key="idem_dup_1", created_at=dt.datetime.now(dt.timezone.utc)
        )
        s.add(op_dup)
        s.add(OutboxItem(op_id="op_dup_1", status="PENDING"))
        await s.commit()

    # 2. Run drain_once. The duplicate Op should get blocked by cooldown and transition to BLOCKED
    async with async_session() as s:
        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # 3. Assertions
    async with async_session() as s:
        stmt_op = select(OpRow).where(OpRow.id == "op_dup_1")
        res_op = await s.execute(stmt_op)
        op = res_op.scalar_one()
        assert op.state == "BLOCKED"

        stmt_out = select(OutboxItem).where(OutboxItem.op_id == "op_dup_1")
        res_out = await s.execute(stmt_out)
        out = res_out.scalar_one()
        assert out.status == "DEAD"


@pytest.mark.asyncio
async def test_cooldown_fail_open_failsafe(db_engine, monkeypatch):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="Safety Tenant 4", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Safety Brand 4")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Propose and approve an Op
        op = OpRow(
            id="op_failsafe_1", tenant_id=tid, brand_id=bid, domain="success_domain",
            action="success_domain.action.test", params={"target_db": "failsafe_db"},
            state="APPROVED", impact=1, reversibility="REVERSIBLE", statutory=False,
            idem_key="idem_failsafe_1"
        )
        s.add(op)
        s.add(OutboxItem(op_id="op_failsafe_1", status="PENDING"))
        await s.commit()

    # 2. Run drain_once. Mock session.execute to fail on cooldown check queries.
    # Fail-open should capture it and return True (allowing execution)
    async with async_session() as s:
        orig_execute = s.execute
        async def mock_execute(statement, *args, **kwargs):
            if "ops" in str(statement) and "DONE" in str(statement):
                raise RuntimeError("Simulated Database Connection Failure!")
            return await orig_execute(statement, *args, **kwargs)
        s.execute = mock_execute

        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # 3. Assertions: Op should be completed successfully (DONE)
    async with async_session() as s:
        stmt_op = select(OpRow).where(OpRow.id == "op_failsafe_1")
        res_op = await s.execute(stmt_op)
        op = res_op.scalar_one()
        assert op.state == "DONE"
