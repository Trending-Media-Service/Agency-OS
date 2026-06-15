import logging
from typing import Optional
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.models import BrandProperty

logger = logging.getLogger(__name__)


class PresenceAdapter(Adapter):
    domain = "presence"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        normalized = intent.strip().lower()
        ops = []

        if any(w in normalized for w in ["search console", "gsc"]):
            ops.append(OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain="presence",
                action="presence.search_console.audit",
                params={"brand_id": brand_id},
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(0)
            ))
        elif any(w in normalized for w in ["merchant center", "gmc", "feed"]):
            ops.append(OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain="presence",
                action="presence.merchant_center.audit",
                params={"brand_id": brand_id},
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(0)
            ))

        return ops

    def preview(self, op: OpSpec) -> PreviewArtifact:
        if op.action == "presence.search_console.audit":
            summary = "Will run Google Search Console audit checking page indexing rates, crawling status warnings, and search queries."
            return PreviewArtifact(kind="summary", summary=summary, detail=op.params)
        elif op.action == "presence.merchant_center.audit":
            summary = "Will run Google Merchant Center audit checking active products, product feed formatting, and sync status warnings."
            return PreviewArtifact(kind="summary", summary=summary, detail=op.params)
        elif op.action == "presence.alert_dispatch":
            summary = f"Alert Dispatch: {op.params.get('alert_type')} ({op.params.get('severity')}) - {op.params.get('disapproved_products', 0)} disapproved items."
            return PreviewArtifact(kind="summary", summary=summary, detail=op.params)
        return PreviewArtifact(kind="summary", summary="Unknown Presence Action", detail=op.params)

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        if not session:
            return ExecResult(ok=False, detail={"error": "Database session is required for Presence audits"})

        now = dt.datetime.now(dt.timezone.utc)

        if op.action == "presence.search_console.audit":
            # 1. Fetch or create property record
            stmt = select(BrandProperty).where(
                BrandProperty.brand_id == op.brand_id,
                BrandProperty.type == "search_console"
            )
            res = await session.execute(stmt)
            prop = res.scalar_one_or_none()

            if not prop:
                prop = BrandProperty(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    type="search_console",
                    provider="google",
                    connection_ref="secret/gsc-oauth"
                )
                session.add(prop)

            # 2. Mock audit run finding warnings
            prop.status = "degraded"
            prop.last_checked = now
            prop.findings = {
                "crawl_errors": 4,
                "indexing_status": "partially_indexed",
                "indexed_pages": 412,
                "warnings": ["Missing schema.org markup on blog pages"]
            }

            return ExecResult(ok=True, detail={"message": "GSC Audit completed", "status": prop.status, "findings": prop.findings})

        elif op.action == "presence.merchant_center.audit":
            # 1. Fetch or create property record
            stmt = select(BrandProperty).where(
                BrandProperty.brand_id == op.brand_id,
                BrandProperty.type == "merchant_feed"
            )
            res = await session.execute(stmt)
            prop = res.scalar_one_or_none()

            if not prop:
                prop = BrandProperty(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    type="merchant_feed",
                    provider="google",
                    connection_ref="secret/gmc-oauth"
                )
                session.add(prop)

            # 2. Mock audit run
            disapproved = op.params.get("simulate_disapproved_products", 0)
            prop.status = "healthy" if disapproved == 0 else "degraded"
            prop.last_checked = now
            prop.findings = {
                "disapproved_products": disapproved,
                "feed_sync_status": "success" if disapproved == 0 else "failed_mismatches",
                "active_items": 128
            }

            if disapproved > 0:
                from app.kernel import loop
                from app.kernel.optypes import Severity, Reversibility, Money, OpState

                alert_op = OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain="presence",
                    action="presence.alert_dispatch",
                    params={
                        "alert_type": "gmc_critical_mismatches",
                        "severity": "CRITICAL" if disapproved >= 5 else "WARNING",
                        "disapproved_products": disapproved
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                    cost_estimate=Money(0)
                )
                alert_row = await loop.propose(session, alert_op, actor="presence_audit")
                await loop.transition(session, alert_row, OpState.PREVIEWED, actor="presence_audit")
                await loop.transition(session, alert_row, OpState.APPROVED, actor="presence_audit")
                loop.enqueue(session, alert_row.id)

            return ExecResult(ok=True, detail={"message": "GMC Audit completed", "status": prop.status, "findings": prop.findings})

        elif op.action == "presence.alert_dispatch":
            return ExecResult(ok=True, detail={"status": "alert_dispatched"})

        return ExecResult(ok=False, detail={"error": f"Unknown presence action: {op.action}"})

    async def verify(self, op: OpSpec) -> VerifyResult:
        if op.action == "presence.alert_dispatch":
            return VerifyResult(ok=True, checks={"alert_sent": True})
        return VerifyResult(ok=True, checks={"audit_run": True})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        return []
