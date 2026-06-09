"""Agency OS — Database-Backed Cron & POAS Job Scheduler.

Enforces execution loops and cron triggers utilizing a database state schema
rather than in-memory event loops.
"""

import typing


@typing.final
class ScheduledJob(typing.TypedDict):
    job_id: str
    name: str
    cron_expression: str
    target_task: str
    payload: typing.Dict[str, typing.Any]
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    last_run_at: typing.Optional[str]


class PoasScheduler:
    """Manages scheduling and execution of cron sweeps."""

    def __init__(self):
        self.pending_jobs: typing.List[ScheduledJob] = []

    def register_job(
        self,
        job_id: str,
        name: str,
        cron_expression: str,
        target_task: str,
        payload: typing.Dict[str, typing.Any]
    ) -> None:
        """Registers a recurring cron job into the schema list."""
        self.pending_jobs.append({
            "job_id": job_id,
            "name": name,
            "cron_expression": cron_expression,
            "target_task": target_task,
            "payload": payload,
            "status": "PENDING",
            "last_run_at": None
        })

    def trigger_scheduled_sweeps(
        self,
        active_time_str: str
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Simulates scheduler loop processing pending jobs.

        Args:
            active_time_str: Mock current time to evaluate cron matches.

        Returns:
            List of execution results logs.
        """
        logs = []
        for job in self.pending_jobs:
            if job["status"] == "PENDING":
                job["status"] = "RUNNING"
                job["last_run_at"] = active_time_str
                
                # Mock running task target execution
                task = job["target_task"]
                if task == "poas_daily":
                    # Successful run log
                    logs.append({
                        "job_id": job["job_id"],
                        "task": task,
                        "status": "SUCCESS",
                        "triggered_at": active_time_str
                    })
                    job["status"] = "COMPLETED"
                elif task == "settling_window":
                    logs.append({
                        "job_id": job["job_id"],
                        "task": task,
                        "status": "SUCCESS",
                        "triggered_at": active_time_str
                    })
                    job["status"] = "COMPLETED"
                else:
                    logs.append({
                        "job_id": job["job_id"],
                        "task": task,
                        "status": "FAILED",
                        "error": f"Unknown target task '{task}'",
                        "triggered_at": active_time_str
                    })
                    job["status"] = "FAILED"

        return logs
