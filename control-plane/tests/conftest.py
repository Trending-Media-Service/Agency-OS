import datetime as dt
import os
os.environ["AOS_ENV"] = "test"
import pytest
import subprocess
import tempfile
import shutil
import pathlib
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base
from httpx import ASGITransport, AsyncClient
import app.main as mainmod
from app.database import get_db, get_worker_db, get_worker_session_maker

original_run = subprocess.run

@pytest.fixture
def run_git():
    def _run(args, **kwargs):
        # Force safe.bareRepository=all for all git commands in tests
        cmd = ["git", "-c", "safe.bareRepository=all"] + args
        return subprocess.run(cmd, **kwargs)
    return _run

@pytest.fixture
def temp_git_remote(run_git):
    """Creates a temporary git repository to act as a remote."""
    temp_dir = tempfile.mkdtemp()
    remote_path = os.path.join(temp_dir, "remote.git")
    
    # Initialize bare repo
    run_git(["init", "--bare", remote_path], check=True, capture_output=True)
    run_git(["-C", remote_path, "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)
    
    # Clone it locally to commit initial file
    clone_path = os.path.join(temp_dir, "clone")
    run_git(["clone", remote_path, clone_path], check=True, capture_output=True)
    
    # Create initial files
    src_dir = os.path.join(clone_path, "src")
    os.makedirs(src_dir, exist_ok=True)
    app_js = os.path.join(src_dir, "App.js")
    with open(app_js, "w") as f:
        f.write("function App() {\n  return <Hero color=\"red\" />;\n}\n")
        
    # package.json
    package_json = os.path.join(clone_path, "package.json")
    with open(package_json, "w") as f:
        f.write('{\n  "name": "brand-site",\n  "version": "1.0.0",\n  "scripts": {\n    "test:smoke": "node run_smoke.js"\n  }\n}\n')
        
    # run_smoke.js
    run_smoke = os.path.join(clone_path, "run_smoke.js")
    with open(run_smoke, "w") as f:
        f.write('const baseUrl = process.env.BASE_URL || "http://localhost:3000";\nconsole.log(`Running smoke tests against ${baseUrl}...`);\nif (baseUrl.includes("fail-smoke")) {\n  console.error("Smoke tests failed: simulated failure");\n  process.exit(1);\n}\nconsole.log("Smoke tests passed");\nprocess.exit(0);\n')
        
    # Commit and push
    run_git(["config", "user.email", "test@test.com"], cwd=clone_path, check=True)
    run_git(["config", "user.name", "Test User"], cwd=clone_path, check=True)
    run_git(["add", "-A"], cwd=clone_path, check=True)
    run_git(["commit", "-m", "initial commit"], cwd=clone_path, check=True)
    run_git(["branch", "-M", "main"], cwd=clone_path, check=True)
    run_git(["push", "origin", "main"], cwd=clone_path, check=True)
    
    yield remote_path
    
    shutil.rmtree(temp_dir)

@pytest.fixture(autouse=True)
def mock_terraform_cli():
    import json
    def mock_run(cmd, cwd=None, **kwargs):
        if cmd[0] != "terraform":
            return original_run(cmd, cwd=cwd, **kwargs)
        subcomm = cmd[1]
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stderr = ""

        if subcomm == "init":
            mock_res.stdout = "Success! Terraform has been initialized."
        elif subcomm in ("plan", "apply", "output"):
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            vars_dict = {}
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)

            # Determine recipe
            if "db_connection_name" in vars_dict:
                recipe = "n8n"
            elif "gtm_container_config" in vars_dict:
                recipe = "sgtm-capi"
            elif "webhook_url" in vars_dict:
                recipe = "payment-gateway"
            elif "dkim_record" in vars_dict:
                recipe = "email-dns"
            elif "bucket_name" in vars_dict:
                recipe = "static-host"
            elif "domain" in vars_dict or "custom_domain" in vars_dict:
                recipe = "web-host"
            elif "project_id" in vars_dict:
                recipe = "webapp-postgres"
            elif "brand_id" in vars_dict:
                recipe = "brand-baseline"
            elif "db_name" in vars_dict:
                recipe = "postgres-db"
            else:
                recipe = "unknown"

            if subcomm == "plan":
                # Write a mock plan file if -out is requested
                out_arg = next((arg for arg in cmd if arg.startswith("-out=")), None)
                if out_arg and cwd:
                    plan_filename = out_arg.split("=")[1]
                    with open(os.path.join(cwd, plan_filename), "w") as f:
                        f.write("mock_tfplan_content")

                if os.environ.get("SIMULATE_DRIFT") == "1":
                    mock_res.returncode = 2
                    mock_res.stdout = "Note: Objects have changed outside Terraform.\n~ resource \"cloud_dns\" \"zone\" {\n    TTL = 300 -> 3600 (drifted)\n  }\nPlan: 0 to add, 1 to change, 0 to destroy."
                else:
                    if recipe == "brand-baseline":
                        brand = vars_dict.get("brand_id", "example-brand")
                        enable_dw = vars_dict.get("enable_data_warehouse", False)
                        bq_part = "\n+ bigquery dataset moat_warehouse" if enable_dw else ""
                        mock_res.stdout = f"Plan: 3 to add, 0 to change, 0 to destroy.\n+ project {brand}\n+ database db-{brand}{bq_part}"
                    elif recipe == "webapp-postgres":
                        mock_res.stdout = "Plan: 8 to add, 0 to change, 0 to destroy.\n+ sql_instance postgres\n+ secret db_url\n+ artifact_registry repo"
                    elif recipe == "web-host":
                        domain = vars_dict.get("domain") or vars_dict.get("custom_domain", "example.in")
                        mock_res.stdout = f"Plan: 5 to add, 0 to change, 0 to destroy.\n+ cloud_dns zone {domain}\n"
                    elif recipe == "sgtm-capi":
                        mock_res.stdout = "Plan: 5 to add, 0 to change, 0 to destroy.\n+ google_cloud_run_service sgtm\n+ google_secret_manager_secret capi_token\n+ google_secret_manager_secret capi_pixel"
                    elif recipe == "payment-gateway":
                        mock_res.stdout = "Plan: 3 to add, 0 to change, 0 to destroy.\n+ google_secret_manager_secret webhook_secret\n+ random_id webhook_id"
                    elif recipe == "email-dns":
                        mock_res.stdout = "Plan: 3 to add, 0 to change, 0 to destroy.\n+ google_dns_record_set mx\n+ google_dns_record_set spf\n+ google_dns_record_set dkim"
                    elif recipe == "static-host":
                        mock_res.stdout = "Plan: 2 to add, 0 to change, 0 to destroy.\n+ google_storage_bucket static_bucket\n+ google_storage_bucket_iam_member public_read"
                    elif recipe == "n8n":
                        mock_res.stdout = "Plan: 2 to add, 0 to change, 0 to destroy.\n+ cloud_run n8n-service\n"
                    elif recipe == "postgres-db":
                        db_name = vars_dict.get("db_name", "brand-db")
                        mock_res.stdout = f"Plan: 1 to add, 0 to change, 0 to destroy.\n+ neon_database {db_name}\n"
                    else:
                        mock_res.stdout = "Plan: 0 to add"
            elif subcomm == "apply":
                domain = vars_dict.get("domain") or vars_dict.get("custom_domain")
                if domain == "fail.in" or vars_dict.get("project_id") == "fail-project":
                    mock_res.returncode = 1
                    mock_res.stderr = "Terraform apply failed: simulated error"
                    mock_res.stdout = "Apply failed!"
                else:
                    mock_res.stdout = "Apply complete! Resources: added, 0 changed, 0 destroyed."
            elif subcomm == "output":
                if recipe == "brand-baseline":
                    brand = vars_dict.get("brand_id", "example-brand")
                    tier = vars_dict.get("tier", "shared")
                    outputs = {
                        "project_id": {"type": "string", "value": f"aos-brand-{brand}" if tier == "dedicated" else "aos-shared-tier"},
                        "service_account_email": {"type": "string", "value": f"aos-deployer-{brand}@aos-brand-{brand}.iam.gserviceaccount.com" if tier == "dedicated" else "shared-sa@aos-shared-tier.iam.gserviceaccount.com"},
                        "db_connection_name": {"type": "string", "value": "" if tier == "dedicated" else "aos-shared-tier:asia-south1:aos-shared-postgres"}
                    }
                elif recipe == "web-host":
                    domain = vars_dict.get("domain") or vars_dict.get("custom_domain", "example.in")
                    outputs = {
                        "service_url": {"type": "string", "value": f"https://web-{domain}"},
                        "lb_ip": {"type": "string", "value": "34.120.15.22"}
                    }
                elif recipe == "sgtm-capi":
                    outputs = {
                        "sgtm_url": {"type": "string", "value": "https://sgtm-container-123.run.app"},
                        "dns_verified": {"type": "bool", "value": True}
                    }
                elif recipe == "payment-gateway":
                    provider = vars_dict.get("provider", "stripe")
                    outputs = {
                        "webhook_id": {"type": "string", "value": "wh_stripe_12345"},
                        "webhook_secret_ref": {"type": "string", "value": f"projects/123/secrets/payment-{provider}-webhook-signing-key"},
                        "status": {"type": "string", "value": "active"}
                    }
                elif recipe == "webapp-postgres":
                    outputs = {
                        "frontend_url": {"type": "string", "value": "https://tanmatra-mock-url.run.app"},
                        "api_url": {"type": "string", "value": "https://wellness-foods-mock-url.run.app"},
                        "db_connection_name": {"type": "string", "value": "aos-brand-b1:asia-south2:brand-b1-db"}
                    }
                elif recipe == "email-dns":
                    outputs = {
                        "dns_verified": {"type": "bool", "value": True}
                    }
                elif recipe == "static-host":
                    bucket = vars_dict.get("bucket_name", "brand-bucket")
                    domain = vars_dict.get("domain", "brand.in")
                    outputs = {
                        "bucket_url": {"type": "string", "value": f"https://storage.googleapis.com/{bucket}"},
                        "cdn_url": {"type": "string", "value": f"https://static-{domain}"}
                    }
                elif recipe == "n8n":
                    outputs = {
                        "service_url": {"type": "string", "value": "https://n8n-service-123.run.app"}
                    }
                elif recipe == "postgres-db":
                    db_name = vars_dict.get("db_name", "brand-db")
                    outputs = {
                        "connection_uri": {"type": "string", "value": f"postgresql://aos-user:mock-pass@neon-host.in/{db_name}"},
                        "db_host": {"type": "string", "value": "neon-host.in"}
                    }
                else:
                    outputs = {}
                mock_res.stdout = json.dumps(outputs)
        elif subcomm == "destroy":
            mock_res.stdout = "Destroy complete! Resources: 0 added, 0 changed, 5 destroyed."
        else:
            mock_res.stdout = ""
        return mock_res

    with patch("app.adapters.provision.subprocess.run", side_effect=mock_run) as mock:
        yield mock


@pytest.fixture()
async def db_file():
    temp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(temp_dir) / "test.db"
    yield f"sqlite+aiosqlite:///{db_path}"
    shutil.rmtree(temp_dir)


@pytest.fixture()
async def db_engine(db_file):
    engine = create_async_engine(db_file)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        yield s


@pytest.fixture()
async def client(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as s:
            await s.begin()
            try:
                yield s
                if s.in_transaction():
                    await s.commit()
            except Exception:
                if s.in_transaction():
                    await s.rollback()
                raise

    async def override_get_worker_session_maker():
        return async_session

    mainmod.app.dependency_overrides[get_db] = override_get_db
    mainmod.app.dependency_overrides[get_worker_db] = override_get_db
    mainmod.app.dependency_overrides[get_worker_session_maker] = override_get_worker_session_maker
    async with AsyncClient(transport=ASGITransport(app=mainmod.app), base_url="http://test") as ac:
        yield ac
    mainmod.app.dependency_overrides.clear()
