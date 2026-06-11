import datetime as dt
import os
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_terraform_cli():
    import json
    def mock_run(cmd, cwd=None, **kwargs):
        subcomm = cmd[1]
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stderr = ""

        if subcomm == "init":
            mock_res.stdout = "Success! Terraform has been initialized."
        elif subcomm == "plan":
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            vars_dict = {}
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)

            if "brand_id" in vars_dict:
                brand = vars_dict.get("brand_id", "example-brand")
                mock_res.stdout = f"Plan: 3 to add, 0 to change, 0 to destroy.\n+ project {brand}\n+ database db-{brand}"
            else:
                domain = vars_dict.get("domain", "example.in")
                mock_res.stdout = f"Plan: 5 to add, 0 to change, 0 to destroy.\n+ cloud_dns zone {domain}\n"
        elif subcomm == "apply":
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            vars_dict = {}
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)
            if vars_dict.get("domain") == "fail.in":
                mock_res.returncode = 1
                mock_res.stderr = "Terraform apply failed: simulated error"
                mock_res.stdout = "Apply failed!"
            else:
                mock_res.stdout = "Apply complete! Resources: 5 added, 0 changed, 0 destroyed."
        elif subcomm == "destroy":
            mock_res.stdout = "Destroy complete! Resources: 0 added, 0 changed, 5 destroyed."
        elif subcomm == "output":
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            vars_dict = {}
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)

            if "brand_id" in vars_dict:
                brand = vars_dict.get("brand_id", "example-brand")
                tier = vars_dict.get("tier", "shared")
                outputs = {
                    "project_id": {"type": "string", "value": f"aos-brand-{brand}" if tier == "dedicated" else "aos-shared-tier"},
                    "service_account_email": {"type": "string", "value": f"aos-deployer-{brand}@aos-brand-{brand}.iam.gserviceaccount.com" if tier == "dedicated" else "shared-sa@aos-shared-tier.iam.gserviceaccount.com"},
                    "db_connection_name": {"type": "string", "value": "" if tier == "dedicated" else "aos-shared-tier:asia-south1:aos-shared-postgres"}
                }
            else:
                domain = vars_dict.get("domain", "example.in")
                outputs = {
                    "service_url": {"type": "string", "value": f"https://web-{domain}"},
                    "dns_zone": {"type": "string", "value": f"zone-{domain}"},
                    "cert_id": {"type": "string", "value": "cert-123"}
                }
            mock_res.stdout = json.dumps(outputs)
        else:
            mock_res.stdout = ""
        return mock_res

    with patch("app.adapters.provision.subprocess.run", side_effect=mock_run) as mock:
        yield mock
