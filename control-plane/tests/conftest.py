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
            domain = "example.in"
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)
                    domain = vars_dict.get("domain", "example.in")
            mock_res.stdout = f"Plan: 5 to add, 0 to change, 0 to destroy.\n+ cloud_dns zone {domain}\n"
        elif subcomm == "apply":
            mock_res.stdout = "Apply complete! Resources: 5 added, 0 changed, 0 destroyed."
        elif subcomm == "destroy":
            mock_res.stdout = "Destroy complete! Resources: 0 added, 0 changed, 5 destroyed."
        elif subcomm == "output":
            domain = "example.in"
            tfvars_path = os.path.join(cwd, "terraform.tfvars.json") if cwd else None
            if tfvars_path and os.path.exists(tfvars_path):
                with open(tfvars_path, "r") as f:
                    vars_dict = json.load(f)
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
