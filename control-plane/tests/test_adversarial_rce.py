import os
import shutil
import tempfile
import pytest
from app.adapters.build import BuildAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.fixture
def run_git_local():
    import subprocess
    def _run(args, **kwargs):
        cmd = ["git", "-c", "safe.bareRepository=all"] + args
        return subprocess.run(cmd, **kwargs)
    return _run

def test_build_adapter_rce_exploit(run_git_local, mock_urlopen_globally):
    """Adversarial test demonstrating Remote Code Execution (RCE) in BuildAdapter.preview.
    The build adapter runs 'npm run test:smoke' from the cloned repository directly
    on the host machine without any sandboxing or verification of the script content,
    allowing a malicious repository to execute arbitrary commands.
    """
    # 1. Setup a temporary directory for the malicious repo
    temp_dir = tempfile.mkdtemp()
    remote_path = os.path.join(temp_dir, "malicious_remote.git")
    
    # Initialize bare repo
    run_git_local(["init", "--bare", remote_path], check=True, capture_output=True)
    run_git_local(["-C", remote_path, "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)
    
    # Clone locally to commit malicious package.json
    clone_path = os.path.join(temp_dir, "clone")
    run_git_local(["clone", remote_path, clone_path], check=True, capture_output=True)
    
    # Create marker file path inside workspace scratch directory
    workspace_root = "/google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS"
    marker_file = os.path.join(workspace_root, "control-plane/scratch/rce_poc_success.txt")
    
    # Ensure marker file does not exist initially
    if os.path.exists(marker_file):
        os.remove(marker_file)
        
    # Write malicious package.json that runs an arbitrary shell command (touching the marker file)
    package_json = os.path.join(clone_path, "package.json")
    with open(package_json, "w") as f:
        # We write a simple script that touches our marker file
        f.write(f'''{{
  "name": "malicious-brand-site",
  "version": "1.0.0",
  "scripts": {{
    "test:smoke": "touch {marker_file}"
  }}
}}''')
        
    # Commit and push
    run_git_local(["config", "user.email", "attacker@exploit.com"], cwd=clone_path, check=True)
    run_git_local(["config", "user.name", "Attacker"], cwd=clone_path, check=True)
    run_git_local(["add", "package.json"], cwd=clone_path, check=True)
    run_git_local(["commit", "-m", "add malicious smoke test"], cwd=clone_path, check=True)
    run_git_local(["branch", "-M", "main"], cwd=clone_path, check=True)
    run_git_local(["push", "origin", "main"], cwd=clone_path, check=True)
    
    # 2. Run the build adapter preview on this repository
    adapter = BuildAdapter()
    op = OpSpec(
        id="op_rce_exploit",
        tenant_id="t1",
        brand_id="b1",
        domain="build",
        action="build.deliver",
        params={
            "intent": "exploit rce",
            "branch_name": "aos-build-exploit",
            "repo": remote_path
        },
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(amount_minor=1000, currency="INR"),
    )
    
    try:
        # This will clone the repo, checkout branch, and perform the secure HTTP check
        preview_art = adapter.preview(op)
        
        # 3. Assert that the marker file was NOT created, confirming exploit is BLOCKED!
        assert not os.path.exists(marker_file), "RCE exploit succeeded: marker file was created!"
        assert preview_art.kind == "build_preview"
        # Assert that the HTTP staging check was actually called
        assert mock_urlopen_globally.called, "Staging URL HTTP check was not invoked!"
        print("\n[+] SUCCESS: Remote Code Execution exploit blocked and secure HTTP check verified successfully!")
        
    finally:
        # Cleanup
        if os.path.exists(marker_file):
            os.remove(marker_file)
        shutil.rmtree(temp_dir)
