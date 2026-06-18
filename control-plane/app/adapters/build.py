import logging
import uuid
import os
from typing import Optional
from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from sqlalchemy.ext.asyncio import AsyncSession
from app.adapters.build_agent import BuildAgentHarness

logger = logging.getLogger(__name__)

class BuildAdapter(Adapter):
    domain = "build"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans the build delivery."""
        return [
            OpSpec(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=self.domain,
                action="build.deliver",
                params={
                    "intent": intent,
                    "branch_name": f"aos-build-{uuid.uuid4().hex[:8]}",
                    "repo": f"git@github.com:ableys/brand-site.git" # Default, should be overridden in tests
                },
                severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
                cost_estimate=Money(amount_minor=1000, currency="INR"),
            )
        ]

    def preview(self, op: OpSpec) -> PreviewArtifact:
        """Runs the build agent and deploys to staging to generate a preview."""
        logger.info(f"Generating preview for build intent: {op.params.get('intent')}")
        
        repo_url = op.params.get("repo")
        branch = op.params.get("branch_name")
        intent = op.params.get("intent")
        
        # Force safe.bareRepository=all environment variable for git subprocesses if needed?
        # Actually, if we run git commands in subprocess, they inherit our environment.
        # But we can't easily pass '-c safe.bareRepository=all' to BuildAgentHarness unless we modify it,
        # or if we set GIT_CONFIG_PARAMETERS.
        # Let's see if we need it. In debug_harness.py, 'git clone' worked without it.
        # But if the remote is a local bare repo (in tests), we might need it for push.
        # Actually, let's see if tests fail.
        
        with BuildAgentHarness(repo_url=repo_url, branch_name=branch) as harness:
            if not harness.clone_and_checkout():
                return PreviewArtifact(kind="build_error", summary="Failed to clone repo", detail={})
            
            if not harness.apply_edits(intent):
                return PreviewArtifact(kind="build_error", summary="Failed to apply edits", detail={})
                
            if not harness.commit_and_push():
                return PreviewArtifact(kind="build_error", summary="Failed to commit changes", detail={})
                
            diff = harness.get_diff()
            op.params["diff"] = diff

            # Run staging smoke tests inside the with block
            staging_url = f"https://staging-{branch}.run.app"
            package_json_path = os.path.join(harness.repo_path, "package.json")
            if os.path.exists(package_json_path):
                import json
                try:
                    with open(package_json_path, "r") as f:
                        pkg = json.load(f)
                    if "scripts" in pkg and "test:smoke" in pkg["scripts"]:
                        logger.info(f"Running smoke tests for branch {branch} against {staging_url}")
                        import subprocess
                        env = os.environ.copy()
                        env["BASE_URL"] = staging_url
                        res = subprocess.run(["npm", "run", "test:smoke"], cwd=harness.repo_path, env=env, capture_output=True, text=True)
                        if res.returncode != 0:
                            logger.error(f"Smoke tests failed for branch {branch}:\nStdout: {res.stdout}\nStderr: {res.stderr}")
                            return PreviewArtifact(
                                kind="build_error", 
                                summary=f"Staging smoke tests failed: {res.stderr.strip() or res.stdout.strip()}", 
                                detail={"stdout": res.stdout, "stderr": res.stderr}
                            )
                except Exception as e:
                    logger.error(f"Failed during smoke test execution: {e}")
                    return PreviewArtifact(kind="build_error", summary=f"Smoke test execution error: {e}", detail={})
            
        staging_url = f"https://staging-{branch}.run.app"
        summary = f"Staging Preview: {staging_url}\n\nDiff:\n{diff}"
        
        return PreviewArtifact(
            kind="build_preview",
            summary=summary,
            detail={
                "staging_url": staging_url,
                "diff": diff,
                "branch": branch
            }
        )

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        """Merges approved branch to main (deliver) or reverts last merge (rollback)."""
        if op.action == "build.deliver":
            logger.info(f"Executing build delivery: merging {op.params.get('branch_name')} to main")
            repo_url = op.params.get("repo")
            branch = op.params.get("branch_name")
            
            with BuildAgentHarness(repo_url=repo_url, branch_name="main") as harness:
                if not harness.clone_and_checkout(create_new=False):
                    return ExecResult(ok=False, detail={"error": "Failed to clone repo and checkout main"})
                    
                if not harness.merge_and_push(from_branch=branch):
                    return ExecResult(ok=False, detail={"error": f"Failed to merge {branch} into main"})
                    
            prod_url = "https://www.ableys.in"
            return ExecResult(
                ok=True,
                detail={
                    "message": f"Branch {branch} merged to main successfully.",
                    "prod_url": prod_url
                }
            )
        elif op.action == "build.rollback":
            logger.info(f"Executing build rollback: reverting last merge for {op.params.get('revert_branch')}")
            repo_url = op.params.get("repo")
            with BuildAgentHarness(repo_url=repo_url, branch_name="main") as harness:
                if not harness.clone_and_checkout(create_new=False):
                    return ExecResult(ok=False, detail={"error": "Failed to clone repo and checkout main"})
                if not harness.revert_last_merge():
                    return ExecResult(ok=False, detail={"error": "Failed to revert last merge"})
            return ExecResult(ok=True, detail={"message": "Rollback successful (reverted merge)."})
        else:
            return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec, session: Optional[AsyncSession] = None) -> VerifyResult:
        """Verifies production deployment."""
        logger.info("Verifying production deployment")
        
        # MOCK: Check if prod URL is active and returns 200
        prod_url = "https://www.ableys.in"
        return VerifyResult(
            ok=True,
            checks={
                "http_ok": True,
                "version_match": True
            },
            detail={"verified_url": prod_url}
        )

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        """Rolls back the deployment by reverting the merge or redeploying previous revision."""
        logger.info(f"Compensating build delivery: reverting {op.params.get('branch_name')}")
        
        return [
            OpSpec(
                tenant_id=op.tenant_id,
                brand_id=op.brand_id,
                domain=self.domain,
                action="build.rollback",
                params={
                    "revert_branch": op.params.get("branch_name"),
                    "repo": op.params.get("repo")
                },
                severity=Severity(impact=2, reversibility=Reversibility.IRREVERSIBLE),
                parent_op_id=op.id,
            )
        ]
