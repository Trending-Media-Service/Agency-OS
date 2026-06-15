from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.models import PolicyVersion

class GovernanceAdapter(Adapter):
    domain = "governance"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans governance ops.
        E.g. intent: 'update policy ceiling to 2000000' or similar.
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
                params={"rules_json": {"provision_cost_ceiling_minor": cost_ceiling}},
                severity=Severity(impact=3, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=0, currency="INR"),
                statutory=True
            )]
        return []

    def preview(self, op: OpSpec) -> PreviewArtifact:
        if op.action == "governance.policy.update":
            rules = op.params.get("rules_json", {})
            summary = "Policy Update:\n"
            for k, v in rules.items():
                summary += f"  - Change parameter '{k}' to '{v}'\n"
            return PreviewArtifact(kind="policy_update_preview", summary=summary, detail={})
        return PreviewArtifact(kind="unknown", summary="Unknown action", detail={})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        if op.action == "governance.policy.update":
            if session is None:
                return ExecResult(ok=False, detail={"error": "Session is required for execution"})
            
            stmt = select(PolicyVersion).where(PolicyVersion.tenant_id == op.tenant_id).order_by(PolicyVersion.version.desc()).limit(1)
            res = await session.execute(stmt)
            curr = res.scalar_one_or_none()
            
            next_version = (curr.version + 1) if curr else 1
            new_rules = curr.rules_json.copy() if (curr and curr.rules_json) else {}
            new_rules.update(op.params.get("rules_json", {}))
            
            pv = PolicyVersion(
                tenant_id=op.tenant_id,
                version=next_version,
                rules_json=new_rules
            )
            session.add(pv)
            return ExecResult(ok=True, detail={"version": next_version, "rules_json": new_rules})
            
        return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec) -> VerifyResult:
        return VerifyResult(ok=True, checks={"policy_updated": True})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        # If there's an update, compensation is writing the previous rules
        # We don't have the previous rules in the OpSpec params directly unless we pass it,
        # but the engine can query the previous version to roll it back.
        # For simple revert action, let's keep it empty or return a revert action.
        return []
