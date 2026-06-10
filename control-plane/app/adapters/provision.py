import os
import shutil
import tempfile
import json
import logging
import subprocess
import yaml
import importlib.util
from typing import Optional

from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter

logger = logging.getLogger(__name__)

RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../recipes"))


class ProvisionAdapter(Adapter):
    domain = "provision"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Simple intent parser: extracts domain name and plans web-host creation."""
        # Clean up commas and split
        words = intent.replace(",", " ").split()
        # Find first word containing a dot (excluding leading dot)
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
        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            
            # Run init
            code, out, err = self._run_terraform(op, ["init", "-input=false", "-no-color"], temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Init failed: {err}", detail={"stderr": err})
                
            # Run plan
            code, out, err = self._run_terraform(op, ["plan", "-no-color", "-input=false"], temp_dir)
            if code != 0:
                return PreviewArtifact(kind="terraform_plan_error", summary=f"Plan failed: {err}", detail={"stderr": err})
                
            return PreviewArtifact(kind="terraform_plan", summary=out, detail={"stdout": out})

    def execute(self, op: OpSpec, idem_key: str) -> ExecResult:
        """Runs terraform apply or destroy based on the action."""
        action_parts = op.action.split(".")
        verb = action_parts[-1] # create | destroy
        
        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            
            # Run init
            code, out, err = self._run_terraform(op, ["init", "-input=false", "-no-color"], temp_dir)
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
                        
            return ExecResult(ok=True, detail={"stdout": out, "outputs": outputs})

    def verify(self, op: OpSpec) -> VerifyResult:
        """Executes verification checks defined in checks.py using execute outputs."""
        # We need the outputs from execution. But verify() receives op.
        # How does verify get outputs?
        # Wait, in E2E tests, the Execution result is saved, but where are outputs stored?
        # Let's check loop.py drain_once / _execute_and_verify.
        # Ah! In loop.py, verify does NOT receive execution results directly in the signature.
        # The verify method: `def verify(self, op: OpSpec) -> VerifyResult: ...`
        # But wait!
        # If verify needs outputs, how does it access them?
        # In a real environment, we can run `terraform output -json` again!
        # Yes! We can just prepare the directory again, run init, and read `terraform output -json`!
        # This is stateless and robust, since the state is in the backend (GCS or local).
        # Let's do that!
        
        recipe = op.params.get("recipe")
        version = op.params.get("version")
        recipe_path = os.path.join(RECIPES_ROOT, recipe, version)
        checks_file = os.path.join(recipe_path, "checks.py")
        
        if not os.path.exists(checks_file):
            logger.info(f"No checks.py found for recipe {recipe} {version}. Assuming OK.")
            return VerifyResult(ok=True, checks={})
            
        with tempfile.TemporaryDirectory() as temp_dir:
            self._prepare_dir(op, temp_dir)
            # Run init
            code, out, err = self._run_terraform(op, ["init", "-input=false", "-no-color"], temp_dir)
            if code != 0:
                return VerifyResult(ok=False, checks={}, detail={"error": f"Init failed for verify: {err}"})
                
            # Read outputs
            code_out, out_out, err_out = self._run_terraform(op, ["output", "-json"], temp_dir)
            if code_out != 0:
                # If destroy was executed, outputs might be empty or error out.
                # If it's a destroy, verification might be different (e.g. check domain is gone).
                # But checks.py is usually for post-apply.
                # Let's see if we should skip checks if it is a destroy action.
                action_parts = op.action.split(".")
                if action_parts[-1] == "destroy":
                     return VerifyResult(ok=True, checks={"destroyed": True})
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
        recipe = op.params.get("recipe")
        version = op.params.get("version")
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
            # Key identifier is domain name (if exists) or recipe name
            identifier = op.params.get("domain", "default")
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
                
        vars_file = os.path.join(temp_dir, "terraform.tfvars.json")
        with open(vars_file, "w") as f:
            json.dump(var_values, f)

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
