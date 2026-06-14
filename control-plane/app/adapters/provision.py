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
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money, CostSpec
from app.kernel.loop import Adapter

logger = logging.getLogger(__name__)

RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../recipes"))


class ProvisionAdapter(Adapter):
    domain = "provision"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans provisioning actions. Supports brand bootstrap and single web host."""
        words = intent.replace(",", " ").split()
        normalized = intent.strip().lower()

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
                    "preview_summary": f"Saga: Onboard Brand '{brand_name}'\n  - Step 1: Create project/shared DB slot (brand-baseline)\n  - Step 2: Deploy Cloud Run web host ({domain_name})"
                },
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=250_000, currency="INR"), # sum of children
            )

            # 2. Child 1: brand-baseline recipe (GCP project setup or shared DB slot)
            child1 = OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="provision.brand_baseline.create",
                params={"brand_id": brand_id, "tier": "shared", "recipe": "brand-baseline", "version": "0.1.0"},
                severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                parent_op_id=parent_id,
                sequence_order=1,
                cost_estimate=Money(amount_minor=0, currency="INR"),
            )

            # 3. Child 2: web-host recipe (Cloud Run deployment)
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

        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)

            # Run init
            code, out, err = self._run_terraform(op, self._get_init_args(op), temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Init failed: {err}", detail={"stderr": err})

            # Run plan
            code, out, err = self._run_terraform(op, ["plan", "-no-color", "-input=false"], temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Plan failed: {err}", detail={"stderr": err})

            return PreviewArtifact(kind="terraform_plan", summary=out, detail={"stdout": out})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        """Runs terraform apply or destroy based on the action."""
        action_parts = op.action.split(".")
        verb = action_parts[-1] # create | destroy
        
        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            
            # Run init
            code, out, err = self._run_terraform(op, self._get_init_args(op), temp_dir)
            if code != 0:
                return ExecResult(ok=False, detail={"error": f"Init failed: {err}"})
                
            if verb == "create":
                # Run apply
                code, out, err = self._run_terraform(op, ["apply", "-auto-approve", "-input=false", "-no-color"], temp_dir)
            elif verb == "destroy":
                # Run destroy
                code, out, err = self._run_terraform(op, ["destroy", "-auto-approve", "-input=false", "-no-color"], temp_dir)
            else:
                return ExecResult(ok=False, detail={"error": f"Unknown action verb: {verb}"})
                
            if code != 0:
                return ExecResult(ok=False, detail={"error": f"Execution failed: {err}", "stdout": out})
                
            # Read outputs
            outputs = {}
            if verb == "create":
                code_out, out_out, err_out = self._run_terraform(op, ["output", "-json"], temp_dir)
                if code_out == 0:
                    try:
                        tf_outputs = json.loads(out_out)
                        outputs = {k: v.get("value") for k, v in tf_outputs.items()}
                    except Exception as e:
                        logger.error(f"Failed to parse terraform outputs: {e}")
                        
            # Simulate execution costs to test cost ledger ingestion
            costs = []
            if verb == "create":
                costs.append(CostSpec(kind="api_call", amount_minor=2000, currency="INR", meta={"service": "dns_provider", "action": "zone_register"}))
                costs.append(CostSpec(kind="api_call", amount_minor=150, currency="INR", meta={"service": "gcp_iam", "action": "service_account_create"}))

            return ExecResult(ok=True, detail={"stdout": out, "outputs": outputs}, costs=costs)

    async def verify(self, op: OpSpec) -> VerifyResult:
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
            code, out, err = self._run_terraform(op, self._get_init_args(op), temp_dir)
            if code != 0:
                return VerifyResult(ok=False, checks={}, detail={"error": f"Init failed for verify: {err}"})

            # Read outputs
            code_out, out_out, err_out = self._run_terraform(op, ["output", "-json"], temp_dir)
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

    def _state_identifier(self, op: OpSpec) -> str:
        """Single source for the per-Op Terraform state path segment, so the
        generated backend.tf and the `-backend-config` init flag never diverge."""
        return op.params.get("domain") or op.params.get("custom_domain") or "default"

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
            elif item.endswith(".tf"): # Only copy HCL files
                shutil.copy2(s, d)
                
        # Generate backend.tf
        state_bucket = os.getenv("AOS_STATE_BUCKET")
        backend_file = os.path.join(temp_dir, "backend.tf")
        
        if state_bucket:
            # GCS backend configuration
            # Key identifier unified via _state_identifier (see helper)
            identifier = self._state_identifier(op)
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
                var_values["project_id"] = f"aos-brand-{op.brand_id}"
                
        vars_file = os.path.join(temp_dir, "terraform.tfvars.json")
        with open(vars_file, "w") as f:
            json.dump(var_values, f)

    def _get_init_args(self, op: OpSpec) -> list[str]:
        args = ["init", "-input=false", "-no-color"]
        state_bucket = os.getenv("AOS_STATE_BUCKET")
        if not state_bucket:
            if os.getenv("AOS_ENV") != "test":
                raise ValueError("AOS_STATE_BUCKET environment variable must be set in production to prevent state corruption.")
            return args

        recipe = op.params.get("recipe", "web-host")
        identifier = self._state_identifier(op)
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
