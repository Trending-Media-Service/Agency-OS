# GCP Provisioner unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import gcp_provisioner

class GcpProvisionerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.provisioner = gcp_provisioner.GcpProvisioner("test-project")

    def test_provision_tenant_success(self):
        manifest = self.provisioner.provision_tenant_resources("test-brand-123")
        self.assertEqual(manifest["status"], "PROVISIONED")
        self.assertEqual(manifest["gcp_project"], "test-project")
        self.assertEqual(manifest["cloud_sql"]["instance_name"], "db-test-brand-123")
        self.assertEqual(manifest["cloud_run"]["service_name"], "ingestion-webhook-test-brand-123")
        self.assertIn("https://ingestion-webhook-test-brand-123-uc.a.run.app", manifest["cloud_run"]["endpoint"])
        self.assertEqual(manifest["kms"]["keyring_name"], "keyring-test-brand-123")

    def test_provision_tenant_invalid_id_raises(self):
        # spaces are invalid
        with self.assertRaises(ValueError):
            self.provisioner.provision_tenant_resources("test brand")

        # SQL inject vectors are invalid
        with self.assertRaises(ValueError):
            self.provisioner.provision_tenant_resources("test; DROP TABLE users;")

        # special symbols are invalid
        with self.assertRaises(ValueError):
            self.provisioner.provision_tenant_resources("test_brand$")

    def test_deprovision_tenant_success(self):
        success = self.provisioner.deprovision_tenant_resources("test-brand")
        self.assertTrue(success)

if __name__ == "__main__":
    absltest.main()
