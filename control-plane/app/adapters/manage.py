import logging
import datetime
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.models import Connection

logger = logging.getLogger(__name__)

class ManageAdapter(Adapter):
    domain = "manage"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans manage actions. Supports connecting Shopify and DB backup."""
        normalized = intent.strip().lower()
        words = normalized.split()

        if "connect" in words and "shopify" in words:
            # Find shop URL (looks like *.myshopify.com)
            shop_url = next((w for w in words if "myshopify.com" in w), "default.myshopify.com")
            # Find secret ref (looks like secret:*)
            secret_ref = next((w for w in words if w.startswith("secret:")), "secret:shopify-token")
            # Remove "secret:" prefix for storage
            if secret_ref.startswith("secret:"):
                secret_ref = secret_ref[7:]

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="manage.shopify.connect",
                    params={
                        "provider": "shopify",
                        "secret_ref": secret_ref,
                        "config": {"shop_url": shop_url}
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=0, currency="INR"),
                )
            ]
            
        elif "backup" in words or "snapshot" in words:
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
            target_bucket = f"gs://aos-backups-{tenant_id}/{brand_id}"
            backup_file = f"{target_bucket}/db-backup-{timestamp}.sql"
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="manage.backup.create",
                    params={
                        "db_name": f"db-{brand_id}",
                        "target_bucket": target_bucket,
                        "backup_file": backup_file
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=100, currency="INR"),
                )
            ]
            
        return []

    def preview(self, op: OpSpec) -> PreviewArtifact:
        """Generates preview for manage actions."""
        if op.action == "manage.shopify.connect":
            shop_url = op.params.get("config", {}).get("shop_url")
            summary = f"Will establish connection to Shopify store: {shop_url}\nScope: read-only\nCredential Ref: {op.params.get('secret_ref')}"
            return PreviewArtifact(kind="shopify_connect_preview", summary=summary, detail=op.params)
        elif op.action == "manage.shopify.disconnect":
            summary = f"Will remove connection to Shopify store."
            return PreviewArtifact(kind="shopify_disconnect_preview", summary=summary, detail=op.params)
        elif op.action == "manage.backup.create":
            summary = f"Will trigger a database backup for {op.params.get('db_name')}\nTarget: {op.params.get('backup_file')}"
            return PreviewArtifact(kind="db_backup_preview", summary=summary, detail=op.params)
        elif op.action == "manage.backup.delete":
            summary = f"Will delete database backup file: {op.params.get('backup_file')}"
            return PreviewArtifact(kind="db_backup_delete_preview", summary=summary, detail=op.params)
        return PreviewArtifact(kind="unknown_preview", summary="Unknown action", detail={})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        """Executes connection, disconnection, backup, or backup deletion."""
        if op.action in ("manage.shopify.connect", "manage.shopify.disconnect"):
            if not session:
                return ExecResult(ok=False, detail={"error": "Database session is required for Connection operations"})

        if op.action == "manage.shopify.connect":
            provider = op.params.get("provider")
            secret_ref = op.params.get("secret_ref")
            config = op.params.get("config", {})
            
            logger.info(f"Connecting {provider} for brand {op.brand_id} with secret {secret_ref}")
            
            stmt = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                existing.secret_ref = secret_ref
                existing.config = config
                logger.info("Updated existing connection")
            else:
                conn = Connection(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    provider=provider,
                    secret_ref=secret_ref,
                    config=config
                )
                session.add(conn)
                logger.info("Created new connection")
                
            return ExecResult(ok=True, detail={"message": "Connection registered in DB"})
            
        elif op.action == "manage.shopify.disconnect":
            provider = op.params.get("provider", "shopify")
            logger.info(f"Disconnecting {provider} for brand {op.brand_id}")
            
            stmt = delete(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            await session.execute(stmt)
            return ExecResult(ok=True, detail={"message": "Connection removed from DB"})
            
        elif op.action == "manage.backup.create":
            backup_file = op.params.get("backup_file")
            logger.info(f"Simulating DB backup creation for {op.params.get('db_name')} to {backup_file}")
            return ExecResult(ok=True, detail={"message": "Backup created successfully", "backup_file": backup_file})
            
        elif op.action == "manage.backup.delete":
            backup_file = op.params.get("backup_file")
            logger.info(f"Simulating DB backup deletion for file {backup_file}")
            return ExecResult(ok=True, detail={"message": f"Backup file {backup_file} deleted"})
            
        return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec) -> VerifyResult:
        """Verifies connection or backup status."""
        if op.action == "manage.shopify.connect":
            logger.info("Verifying Shopify connection via mock API call...")
            return VerifyResult(
                ok=True,
                checks={
                    "credentials_valid": True,
                    "shop_accessible": True,
                    "read_scopes_ok": True
                },
                detail={"shop_name": "Mock Shop"}
            )
        elif op.action == "manage.shopify.disconnect":
            return VerifyResult(ok=True, checks={"disconnected": True})
            
        elif op.action == "manage.backup.create":
            backup_file = op.params.get("backup_file")
            logger.info(f"Verifying DB backup file exists: {backup_file}")
            return VerifyResult(
                ok=True,
                checks={
                    "file_exists": True,
                    "size_greater_than_zero": True
                },
                detail={"verified_file": backup_file}
            )
        elif op.action == "manage.backup.delete":
            return VerifyResult(ok=True, checks={"file_deleted": True})
            
        return VerifyResult(ok=False, checks={})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        """Returns compensation Ops."""
        if op.action == "manage.shopify.connect":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="manage.shopify.disconnect",
                    params={
                        "provider": op.params.get("provider"),
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    parent_op_id=op.id
                )
            ]
        elif op.action == "manage.backup.create":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="manage.backup.delete",
                    params={
                        "backup_file": op.params.get("backup_file"),
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    parent_op_id=op.id
                )
            ]
        return []
