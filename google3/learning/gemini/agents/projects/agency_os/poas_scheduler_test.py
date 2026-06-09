# POAS Scheduler unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import poas_scheduler

class PoasSchedulerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.scheduler = poas_scheduler.PoasScheduler()

    def test_register_and_run_poas_daily(self):
        self.scheduler.register_job(
            job_id="j1",
            name="Daily Spend Update",
            cron_expression="0 0 * * *",
            target_task="poas_daily",
            payload={"tenant_id": "t1"}
        )

        self.assertLen(self.scheduler.pending_jobs, 1)
        self.assertEqual(self.scheduler.pending_jobs[0]["status"], "PENDING")

        logs = self.scheduler.trigger_scheduled_sweeps("2026-06-08T00:00:00Z")
        self.assertLen(logs, 1)
        self.assertEqual(logs[0]["status"], "SUCCESS")
        self.assertEqual(logs[0]["task"], "poas_daily")
        self.assertEqual(self.scheduler.pending_jobs[0]["status"], "COMPLETED")

    def test_run_unknown_task_failure(self):
        self.scheduler.register_job(
            job_id="j2",
            name="Invalid Job",
            cron_expression="* * * * *",
            target_task="bad_task",
            payload={}
        )

        logs = self.scheduler.trigger_scheduled_sweeps("2026-06-08T12:00:00Z")
        self.assertLen(logs, 1)
        self.assertEqual(logs[0]["status"], "FAILED")
        self.assertEqual(self.scheduler.pending_jobs[0]["status"], "FAILED")

if __name__ == "__main__":
    absltest.main()
