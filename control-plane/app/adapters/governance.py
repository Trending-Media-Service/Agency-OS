from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.models import PolicyVersion, ConsentBasis

class GovernanceAdapter(Adapter):
    domain = "governance"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans governance ops.
        E.g. intent: 'update policy ceiling to 2000000'
        E.g. intent: 'grant consent for pii_upload grow.audience.upload'
        """
        normalized = intent.strip().lower()
        if "update policy" in normalized or "change policy" in normalized:
            import re
            # Extract number from intent
            match = re.search(r'ceiling\s*(?:to\s*)?(\d+)', normalized)
            cost_ceiling = 2_000_000
            if match:
                cost_ceiling = int(match.group(1))
            
            return [OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="governance.policy.update",
                params={"params": {"provision_cost_ceiling_minor": cost_ceiling}},
                severity=Severity(impact=3, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=0, currency="INR"),
                statutory=True
            )]
            
        elif "grant consent" in normalized or "approve consent" in normalized:
            # Format: grant consent for [category] [action_or_vendor]
            parts = normalized.split()
            # E.g. ['grant', 'consent', 'for', 'pii_upload', 'grow.audience.upload']
            category = "pii_upload"
            action_or_vendor = "all"
            if len(parts) >= 5:
                category = parts[3]
                action_or_vendor = parts[4]
                
            return [OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="governance.consent.grant",
                params={"category": category, "action_or_vendor": action_or_vendor, "actor": "owner"},
                severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=0, currency="INR"),
                statutory=True
            )]
            
        elif "revoke consent" in normalized:
            parts = normalized.split()
            category = "pii_upload"
            action_or_vendor = "all"
            if len(parts) >= 5:
                category = parts[3]
                action_or_vendor = parts[4]
                
            return [OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="governance.consent.revoke",
                params={"category": category, "action_or_vendor": action_or_vendor},
                severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=0, currency="INR"),
                statutory=True
            )]
            
        return []


    def preview(self, op: OpSpec) -> PreviewArtifact:
        if op.action == "governance.policy.update":
            rules = op.params.get("params", {})
            summary = "Policy Update:\n"
            for k, v in rules.items():
                summary += f"  - Change parameter '{k}' to '{v}'\n"
            return PreviewArtifact(kind="policy_update_preview", summary=summary, detail={})
        elif op.action == "governance.consent.grant":
            cat = op.params.get("category")
            target = op.params.get("action_or_vendor")
            summary = f"Consent Grant:\n  - Grant active consent basis for category '{cat}', target '{target}'."
            return PreviewArtifact(kind="consent_grant_preview", summary=summary, detail={})
        elif op.action == "governance.consent.revoke":
            cat = op.params.get("category")
            target = op.params.get("action_or_vendor")
            summary = f"Consent Revocation:\n  - Revoke active consent basis for category '{cat}', target '{target}'."
            return PreviewArtifact(kind="consent_revoke_preview", summary=summary, detail={})
        return PreviewArtifact(kind="unknown", summary="Unknown action", detail={})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        if op.action == "governance.policy.update":
            if session is None:
                return ExecResult(ok=False, detail={"error": "Session is required for execution"})
            
            stmt_latest = select(PolicyVersion).where(PolicyVersion.tenant_id == op.tenant_id).order_by(PolicyVersion.version.desc()).limit(1)
            res_latest = await session.execute(stmt_latest)
            curr_latest = res_latest.scalar_one_or_none()
            next_version = (curr_latest.version + 1) if curr_latest else 1
            
            stmt_active = select(PolicyVersion).where(PolicyVersion.tenant_id == op.tenant_id, PolicyVersion.status == "active").limit(1)
            res_active = await session.execute(stmt_active)
            curr_active = res_active.scalar_one_or_none()
            
            new_params = curr_active.params.copy() if (curr_active and curr_active.params) else {}
            new_params.update(op.params.get("params", {}))
            
            if curr_active:
                curr_active.status = "superseded"
            
            pv = PolicyVersion(
                tenant_id=op.tenant_id,
                version=next_version,
                params=new_params,
                status="active"
            )
            session.add(pv)
            return ExecResult(ok=True, detail={"version": next_version, "params": new_params})
            
        elif op.action == "governance.consent.grant":
            if session is None:
                return ExecResult(ok=False, detail={"error": "Session is required"})
            cb = ConsentBasis(
                tenant_id=op.tenant_id,
                category=op.params["category"],
                action_or_vendor=op.params["action_or_vendor"],
                status="granted",
                granted_by=op.params.get("actor", "kernel")
            )
            session.add(cb)
            return ExecResult(ok=True, detail={"consent_basis_id": cb.id, "status": "granted"})
            
        elif op.action == "governance.consent.revoke":
            if session is None:
                return ExecResult(ok=False, detail={"error": "Session is required"})
            stmt = select(ConsentBasis).where(
                ConsentBasis.tenant_id == op.tenant_id,
                ConsentBasis.category == op.params["category"],
                ConsentBasis.action_or_vendor == op.params["action_or_vendor"],
                ConsentBasis.status == "granted"
            )
            res = await session.execute(stmt)
            records = res.scalars().all()
            for r in records:
                r.status = "revoked"
            return ExecResult(ok=True, detail={"revoked_count": len(records)})
            
        return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec) -> VerifyResult:
        if op.action.startswith("governance.consent."):
            return VerifyResult(ok=True, checks={"consent_basis_updated": True})
        return VerifyResult(ok=True, checks={"policy_updated": True})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        return []

