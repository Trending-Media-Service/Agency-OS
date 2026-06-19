import os
import shutil
import tempfile
import json
import logging
import subprocess
import yaml
import importlib.util
import uuid
import re
import asyncio
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money, CostSpec
from app.kernel.loop import Adapter

logger = logging.getLogger(__name__)

RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../recipes"))

# Terraform plans are persisted between an Op's preview and its execute. The
# container runs as a non-root user, so the previous repo-root expression
# resolved to "/tfplans" (not creatable -> PermissionError on provision preview).
# Default to a writable temp dir; override with TFPLAN_DIR (e.g. a mounted volume).
TFPLAN_DIR = os.getenv("TFPLAN_DIR") or os.path.join(tempfile.gettempdir(), "aos-tfplans")


class ProvisionAdapter(Adapter):
    domain = "provision"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans provisioning actions. Supports brand bootstrap and single web host."""
        words = intent.replace(",", " ").split()
        normalized = intent.strip().lower()

        # Check if intent is for email DNS setup
        if any(w in normalized for w in ["email", "dns", "mx", "spf", "dkim"]):
            domain_name = next((w for w in words if "." in w and not w.startswith(".")), "example.in")
            return [OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="provision.email_dns.create",
                params={
                    "domain": domain_name,
                    "project_id": f"aos-brand-{brand_id}",
                    "dkim_record": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ",
                    "recipe": "email-dns",
                    "version": "0.1.0"
                },
                severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                cost_estimate=Money(amount_minor=0, currency="INR")
            )]

        # Check if intent is for static website hosting
        if any(w in normalized for w in ["static"]):
            domain_name = next((w for w in words if "." in w and not w.startswith(".")), "example.in")
            bucket_name = f"static-bucket-{domain_name.replace('.', '-')}"
            return [OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="provision.static_host.create",
                params={
                    "domain": domain_name,
                    "project_id": f"aos-brand-{brand_id}",
                    "bucket_name": bucket_name,
                    "recipe": "static-host",
                    "version": "0.1.0"
                },
                severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                cost_estimate=Money(amount_minor=50_000, currency="INR")
            )]

        # Check if this is a brand bootstrap intent (e.g. "onboard brand ableys" or "bootstrap brand woktok.co")
        if any(w in normalized for w in ["bootstrap", "onboard"]):
            # Find the brand name: look for next word after "brand"
            brand_name = "default-brand"
            if "brand" in words:
                idx = words.index("brand")
                if idx + 1 < len(words):
                    brand_name = words[idx + 1]

            # Find first word containing a dot for the domain name
            domain_name = next((w for w in words if "." in w and not w.startswith(".")), f"{brand_name}.in")

            parent_id = uuid.uuid4().hex

            # 1. Parent Saga wrapper Op
            has_db = any(w in normalized for w in ["database", "postgres", "db"])
            is_monorepo = any(w in normalized for w in ["monorepo", "multi-service"])
            
            if is_monorepo:
                api_domain = f"api.{domain_name}"
                console_domain = f"console.{domain_name}"
                web_domain = domain_name
                
                preview_summary = (
                    f"Saga: Onboard Monorepo Brand '{brand_name}'\n"
                    f"  - Step 1: Create project/shared DB slot (brand-baseline)\n"
                    f"  - Step 2: Deploy Express API Backend (webapp-postgres to {api_domain})\n"
                    f"  - Step 3: Deploy Vite Web Landing (static-host to {web_domain})\n"
                    f"  - Step 4: Deploy Vite Console Dashboard (static-host to {console_domain})"
                )
            elif has_db:
                preview_summary = f"Saga: Onboard Brand '{brand_name}' with Database\n  - Step 1: Create project/shared DB slot (brand-baseline)\n  - Step 2: Deploy multi-service app + Cloud SQL Postgres (webapp-postgres)"
            else:
                preview_summary = f"Saga: Onboard Brand '{brand_name}'\n  - Step 1: Create project/shared DB slot (brand-baseline)\n  - Step 2: Deploy Cloud Run web host ({domain_name})"

            parent_spec = OpSpec(
                id=parent_id,
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="provision.brand_bootstrap.create",
                params={
                    "brand_name": brand_name,
                    "domain": domain_name,
                    "recipe": "brand-bootstrap",
                    "preview_summary": preview_summary
                },
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=350_000 if is_monorepo else 250_000, currency="INR"),
            )

            # 2. Child 1: brand-baseline recipe (GCP project setup or shared DB slot)
            tier = "dedicated" if "dedicated" in normalized else "shared"
            baseline_params = {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "tier": tier,
                "recipe": "brand-baseline",
                "version": "0.1.0"
            }
            if tier == "dedicated":
                baseline_params["billing_account"] = "012E0F-7A4F33-26EDD8"
                baseline_params["folder_id"] = "338402544084" # tenants folder ID
                tmg_project = next((w for w in words if "-tmg" in w), "")
                if tmg_project:
                    baseline_params["custom_project_id"] = tmg_project

            child1 = OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="provision.brand_baseline.create",
                params=baseline_params,
                severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                parent_op_id=parent_id,
                sequence_order=1,
                cost_estimate=Money(amount_minor=0, currency="INR"),
            )

            # 3. Handle Child Ops
            if is_monorepo:
                child2_api = OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.webapp_postgres.create",
                    params={
                        "project_id": f"brand-{brand_name}-tmg",
                        "brand_id": brand_id,
                        "tenant_id": tenant_id,
                        "recipe": "webapp-postgres",
                        "version": "0.1.0",
                        "custom_domain": api_domain
                    },
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=parent_id,
                    sequence_order=2,
                    cost_estimate=Money(amount_minor=250_000, currency="INR"),
                )
                
                child3_web = OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.static_host.create",
                    params={
                        "domain": web_domain,
                        "recipe": "static-host",
                        "version": "0.1.0",
                        "bucket_name": f"aos-{brand_name}-web-landing"
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=parent_id,
                    sequence_order=3,
                    cost_estimate=Money(amount_minor=50_000, currency="INR"),
                )
                
                child4_console = OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.static_host.create",
                    params={
                        "domain": console_domain,
                        "recipe": "static-host",
                        "version": "0.1.0",
                        "bucket_name": f"aos-{brand_name}-console-web"
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=parent_id,
                    sequence_order=4,
                    cost_estimate=Money(amount_minor=50_000, currency="INR"),
                )
                
                return [parent_spec, child1, child2_api, child3_web, child4_console]

            elif has_db:
                child2 = OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.webapp_postgres.create",
                    params={
                        "project_id": f"brand-{brand_name}-tmg",
                        "brand_id": brand_id,
                        "tenant_id": tenant_id,
                        "recipe": "webapp-postgres",
                        "version": "0.1.0"
                    },
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=parent_id,
                    sequence_order=2,
                    cost_estimate=Money(amount_minor=250_000, currency="INR"),
                )
            else:
                child2 = OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.web_host.create",
                    params={"domain": domain_name, "recipe": "web-host", "version": "0.1.0"},
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=parent_id,
                    sequence_order=2,
                    cost_estimate=Money(amount_minor=250_000, currency="INR"),
                )

            return [parent_spec, child1, child2]

        # Check if this is an OSS tool intent (e.g. "install n8n" or "deploy n8n")
        if "n8n" in normalized:
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.n8n.create",
                    params={
                        "recipe": "n8n",
                        "version": "0.1.0",
                        "project_id": "aos-shared-tier",
                        "db_connection_name": "aos-shared-tier:asia-south1:aos-shared-postgres",
                        "db_name": f"db-{brand_id}",
                        "db_user": f"user-{brand_id}",
                        "db_password": "mock-password"
                    },
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=300_000, currency="INR"),
                )
            ]

        # Check if this is a postgres database intent (e.g. "deploy database" or "provision db")
        if any(w in normalized for w in ["database", "postgres", "db"]):
            db_name = f"db_{brand_id}"
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="provision.postgres_db.create",
                    params={
                        "recipe": "postgres-db",
                        "version": "0.1.0",
                        "db_name": db_name,
                        "tier": "shared"
                    },
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=0, currency="INR"),
                )
            ]

        # Normal single web host intent (backwards compatibility)
        domain_name = next((w for w in words if "." in w and not w.startswith(".")), "example.in")
        return [OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain=self.domain,
            action="provision.web_host.create",
            params={"domain": domain_name, "recipe": "web-host", "version": "0.1.0"},
            severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
            cost_estimate=Money(amount_minor=250_000, currency="INR"),
        )]

    def preview(self, op: OpSpec) -> PreviewArtifact:
        """Runs terraform init & plan and returns the plan output."""
        if op.action == "provision.brand_bootstrap.create":
            summary = op.params.get("preview_summary", "Brand bootstrap sequential saga")
            return PreviewArtifact(kind="saga_preview", summary=summary, detail={})

        action_parts = op.action.split(".")
        verb = action_parts[-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)

            # Run init
            code, out, err = self._run_terraform(op, self._get_init_args(op), temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Init failed: {err}", detail={"stderr": err})

            # Run plan (use -destroy if verb is destroy)
            plan_args = ["plan", "-no-color", "-input=false", "-out=tfplan"]
            if verb == "destroy":
                plan_args.append("-destroy")

            code, out, err = self._run_terraform(op, plan_args, temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Plan failed: {err}", detail={"stderr": err})

            # Save plan persistently
            persistent_plan_dir = TFPLAN_DIR
            os.makedirs(persistent_plan_dir, exist_ok=True)
            plan_file_path = os.path.join(persistent_plan_dir, f"{op.id}.tfplan")
            shutil.copy2(os.path.join(temp_dir, "tfplan"), plan_file_path)
            logger.info(f"Saved terraform plan to {plan_file_path}")

            return PreviewArtifact(kind="terraform_plan", summary=out, detail={"stdout": out})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        """Runs terraform apply or destroy based on the action, using saved plan if available."""
        if op.action in ("provision.brand_bootstrap.create", "provision.brand_bootstrap.destroy"):
            logger.info(f"Saga parent operation {op.action} executed successfully (no-op).")
            return ExecResult(ok=True, detail={"message": "Saga parent logical operation completed."})

        action_parts = op.action.split(".")
        verb = action_parts[-1] # create | destroy
        
        persistent_plan_dir = TFPLAN_DIR
        plan_file_path = os.path.join(persistent_plan_dir, f"{op.id}.tfplan")
        has_saved_plan = os.path.exists(plan_file_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            
            # Run init (non-blocking)
            code, out, err = await asyncio.to_thread(self._run_terraform, op, self._get_init_args(op), temp_dir)
            if code != 0:
                return ExecResult(ok=False, detail={"error": f"Init failed: {err}"})
                
            if has_saved_plan:
                # Copy plan to temp dir and apply it
                shutil.copy2(plan_file_path, os.path.join(temp_dir, "tfplan"))
                logger.info(f"Applying saved terraform plan for Op {op.id}")
                code, out, err = await asyncio.to_thread(self._run_terraform, op, ["apply", "-input=false", "-no-color", "tfplan"], temp_dir)
                try:
                    os.remove(plan_file_path)
                except OSError:
                    pass
            else:
                # Fallback: run apply/destroy with auto-approve (non-blocking)
                if verb in ("create", "apply", "update"):
                    code, out, err = await asyncio.to_thread(self._run_terraform, op, ["apply", "-auto-approve", "-input=false", "-no-color"], temp_dir)
                elif verb == "destroy":
                    code, out, err = await asyncio.to_thread(self._run_terraform, op, ["destroy", "-auto-approve", "-input=false", "-no-color"], temp_dir)
                else:
                    return ExecResult(ok=False, detail={"error": f"Unknown action verb: {verb}"})
                
            if code != 0:
                return ExecResult(ok=False, detail={"error": f"Execution failed: {err}", "stdout": out})

            # If baseline was created or updated successfully, update the Tenant's hosting_tier in DB
            if "brand_baseline" in op.action and session:
                from app.models import Tenant
                from sqlalchemy import select
                stmt = select(Tenant).where(Tenant.id == op.tenant_id)
                res = await session.execute(stmt)
                tenant = res.scalar_one_or_none()
                if tenant:
                    tenant.hosting_tier = op.params.get("tier", "shared")
                    logger.info(f"Successfully updated Tenant {op.tenant_id} hosting_tier in DB to {tenant.hosting_tier}")
                
            # Read outputs
            outputs = {}
            if verb in ("create", "update"):
                code_out, out_out, err_out = await asyncio.to_thread(self._run_terraform, op, ["output", "-json"], temp_dir)
                if code_out == 0:
                    try:
                        tf_outputs = json.loads(out_out)
                        outputs = {k: v.get("value") for k, v in tf_outputs.items()}
                    except Exception as e:
                        logger.error(f"Failed to parse terraform outputs: {e}")
                        
            # Simulate execution costs to test cost ledger ingestion
            costs = []
            if verb in ("create", "apply", "update"):
                costs.append(CostSpec(kind="api_call", amount_minor=2000, currency="INR", meta={"service": "dns_provider", "action": "zone_register"}))
                costs.append(CostSpec(kind="api_call", amount_minor=150, currency="INR", meta={"service": "gcp_iam", "action": "service_account_create"}))
                
                # Parse recipe cost estimate
                recipe = op.params.get("recipe", "web-host")
                version = op.params.get("version", "0.1.0")
                recipe_path = os.path.join(RECIPES_ROOT, recipe, version)
                yaml_file = os.path.join(recipe_path, "recipe.yaml")
                if os.path.exists(yaml_file):
                    try:
                        with open(yaml_file, "r") as f:
                            recipe_meta = yaml.safe_load(f)
                            cost_est = recipe_meta.get("cost_estimate_monthly")
                            if cost_est:
                                costs.append(CostSpec(
                                    kind="gcp_resource",
                                    amount_minor=cost_est.get("amount_minor", 0),
                                    currency=cost_est.get("currency", "INR"),
                                    meta={"recipe": recipe, "version": version}
                                ))
                    except Exception as e:
                        logger.error(f"Failed to read cost estimate from recipe.yaml: {e}")

            return ExecResult(ok=True, detail={"stdout": out, "outputs": outputs}, costs=costs)

    async def verify(self, op: OpSpec, session: Optional[AsyncSession] = None) -> VerifyResult:
        """Executes verification checks defined in checks.py using execute outputs."""
        action_parts = op.action.split(".")
        verb = action_parts[-1]
        if verb == "destroy":
            return VerifyResult(ok=True, checks={"destroyed": True})

        recipe = op.params.get("recipe", "web-host")
        version = op.params.get("version", "0.1.0")
        recipe_path = os.path.join(RECIPES_ROOT, recipe, version)
        checks_file = os.path.join(recipe_path, "checks.py")

        if not os.path.exists(checks_file):
            logger.info(f"No checks.py found for recipe {recipe} {version}. Assuming OK.")
            return VerifyResult(ok=True, checks={})

        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            # Run init
            code, out, err = await asyncio.to_thread(self._run_terraform, op, self._get_init_args(op), temp_dir)
            if code != 0:
                return VerifyResult(ok=False, checks={}, detail={"error": f"Init failed for verify: {err}"})

            # Read outputs (non-blocking)
            code_out, out_out, err_out = await asyncio.to_thread(self._run_terraform, op, ["output", "-json"], temp_dir)
            if code_out != 0:
                return VerifyResult(ok=False, checks={}, detail={"error": f"Failed to read outputs: {err_out}"})
                
            outputs = {}
            try:
                tf_outputs = json.loads(out_out)
                outputs = {k: v.get("value") for k, v in tf_outputs.items()}
            except Exception as e:
                 return VerifyResult(ok=False, checks={}, detail={"error": f"Failed to parse outputs: {e}"})

            # Dynamically load checks.py
            try:
                spec = importlib.util.spec_from_file_location("recipe_checks", checks_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Run verify function
                check_results = module.verify(op.params, outputs)
                all_ok = all(check_results.values())
                return VerifyResult(ok=all_ok, checks=check_results)
            except Exception as e:
                logger.error(f"Error executing checks.py: {e}", exc_info=True)
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        """Returns the compensating destroy Op for this create Op."""
        if op.action == "provision.brand_bootstrap.create":
            # Logical parent Saga has no direct compensation itself; its rollback is driven
            # by children cascading rollbacks.
            return []

        action_parts = op.action.split(".")
        verb = action_parts[-1]

        if verb == "create":
            destroy_action = ".".join(action_parts[:-1] + ["destroy"])
            return [OpSpec(
                tenant_id=op.tenant_id,
                brand_id=op.brand_id,
                domain=op.domain,
                action=destroy_action,
                params=op.params,
                severity=Severity(impact=op.severity.impact, reversibility=Reversibility.IRREVERSIBLE),
                parent_op_id=op.id,
            )]
        return []

    def _prepare_dir(self, op: OpSpec, temp_dir: str):
        """Copies recipe files and writes backend.tf & variables."""
        recipe = op.params.get("recipe", "web-host")
        version = op.params.get("version", "0.1.0")
        recipe_path = os.path.join(RECIPES_ROOT, recipe, version)
        
        if not os.path.exists(recipe_path):
            raise FileNotFoundError(f"Recipe path not found: {recipe_path}")
            
        # Copy tf files (exclude recipe.yaml and checks.py to be clean, but copying everything is fine too)
        for item in os.listdir(recipe_path):
            s = os.path.join(recipe_path, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            elif not item.startswith(".") and item not in ("recipe.yaml", "checks.py"):
                shutil.copy2(s, d)
                
        # Generate backend.tf
        state_bucket = os.getenv("AOS_STATE_BUCKET")
        backend_file = os.path.join(temp_dir, "backend.tf")
        
        if state_bucket:
            # GCS backend configuration
            # Key identifier is domain name (if exists) or recipe name
            identifier = op.params.get("domain") or op.params.get("custom_domain") or "default"
            prefix = f"provision/{op.tenant_id}/{op.brand_id}/{recipe}/{identifier}/state"
            hcl = f"""
terraform {{
  backend "gcs" {{
    bucket = "{state_bucket}"
    prefix = "{prefix}"
  }}
}}
"""
        else:
            # Local backend for testing/fallback
            hcl = """
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""
        with open(backend_file, "w") as f:
            f.write(hcl)
            
        # Write variables
        # Read recipe.yaml to find defined inputs
        yaml_file = os.path.join(recipe_path, "recipe.yaml")
        inputs = {}
        if os.path.exists(yaml_file):
            try:
                with open(yaml_file, "r") as f:
                    recipe_meta = yaml.safe_load(f)
                    inputs = recipe_meta.get("inputs", {})
            except Exception as e:
                logger.error(f"Failed to read recipe.yaml: {e}")
                
        # Filter op.params to only include keys defined in recipe inputs
        var_values = {}
        for key in inputs.keys():
            if key in op.params:
                var_values[key] = op.params[key]
            elif key == "custom_domain" and "domain" in op.params:
                var_values["custom_domain"] = op.params["domain"]
            elif key == "project_id" and "project_id" not in op.params:
                resolved = self._resolve_project_id_from_baseline(op)
                var_values["project_id"] = resolved or os.getenv("GCP_PROJECT") or f"aos-brand-{op.brand_id}"
                
        vars_file = os.path.join(temp_dir, "terraform.tfvars.json")
        logger.info(f"TFVARS generated for Op {op.action}: {json.dumps(var_values)}")
        with open(vars_file, "w") as f:
            json.dump(var_values, f)

    def _resolve_project_id_from_baseline(self, op: OpSpec) -> Optional[str]:
        """Reads the parent brand-baseline remote state from GCS and parses the project_id output."""
        state_bucket = os.getenv("AOS_STATE_BUCKET")
        if not state_bucket:
            return None
            
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(state_bucket)
            blob_path = f"provision/{op.tenant_id}/{op.brand_id}/brand-baseline/default/state/default.tfstate"
            blob = bucket.blob(blob_path)
            
            if blob.exists():
                content = blob.download_as_text()
                state_data = json.loads(content)
                project_id = state_data.get("outputs", {}).get("project_id", {}).get("value")
                if project_id:
                    logger.info(f"Resolved parent project ID '{project_id}' from baseline state in GCS for brand '{op.brand_id}'")
                    return project_id
            else:
                logger.warning(f"Baseline state file not found in GCS: gs://{state_bucket}/{blob_path}")
        except Exception as e:
            logger.warning(f"Failed to resolve project ID from GCS baseline state using client library: {e}")
        return None

    def _get_init_args(self, op: OpSpec) -> list[str]:
        args = ["init", "-input=false", "-no-color"]
        state_bucket = os.getenv("AOS_STATE_BUCKET")
        if not state_bucket:
            if os.getenv("AOS_ENV") != "test":
                raise ValueError("AOS_STATE_BUCKET environment variable must be set in production to prevent state corruption.")
            return args

        recipe = op.params.get("recipe", "web-host")
        identifier = op.params.get("domain") or op.params.get("custom_domain") or "default"
        prefix = f"provision/{op.tenant_id}/{op.brand_id}/{recipe}/{identifier}/state"
        args.append(f"-backend-config=bucket={state_bucket}")
        args.append(f"-backend-config=prefix={prefix}")
        return args

    def _run_terraform(self, op: OpSpec, args: list[str], cwd: str) -> tuple[int, str, str]:
        """Runs terraform CLI and captures outputs."""
        # Verify if terraform is installed
        # In a real environment, we can check this once on startup.
        cmd = ["terraform"] + args
        try:
            res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            return res.returncode, res.stdout, res.stderr
        except FileNotFoundError:
            # If terraform is not found (e.g. locally), check if we are in testing dry-run
            # We can mock this behavior
            logger.error("Terraform CLI not found in PATH")
            return 127, "", "terraform executable not found in PATH"
