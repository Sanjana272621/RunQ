import os
import socket
import time
from pathlib import Path

from job_scheduler.database import (
    claim_next_job,
    connect_database,
    initialize_schema,
)
from job_scheduler.worker import execute_claimed_job


def create_worker_id() -> str:
    """Create a readable identifier for this worker."""
    hostname = socket.gethostname()
    process_id = os.getpid()

    return (
        f"{hostname}:"
        f"{process_id}:"
        "worker-1"
    )


def run_scheduler(
    database_path: Path,
    logs_directory: Path,
    run_once: bool = False,
    poll_interval: float = 0.5,
    retry_base_delay: float = 2.0,
) -> int:
    """
    Run a single scheduler worker.

    With run_once=True, claim at most one job and exit.

    With run_once=False, keep polling until Ctrl+C.
    """
    worker_id = create_worker_id()

    connection = connect_database(
        database_path
    )

    initialize_schema(connection)

    print(
        f"Scheduler started with worker "
        f"{worker_id}"
    )

    try:
        while True:
            job = claim_next_job(
                connection=connection,
                worker_id=worker_id,
            )

            if job is None:
                if run_once:
                    print("No runnable jobs.")
                    return 0

                time.sleep(poll_interval)
                continue

            print(
                f"Claimed job {job.id}: "
                f"attempt "
                f"{job.attempts}/"
                f"{job.max_attempts}"
            )

            result = execute_claimed_job(
                connection=connection,
                job=job,
                worker_id=worker_id,
                logs_directory=logs_directory,
                retry_base_delay=(
                    retry_base_delay
                ),
            )

            print(
                f"Job {result.id} "
                f"finished attempt "
                f"{result.attempts} "
                f"with state "
                f"{result.state.value}"
            )

            if run_once:
                return 0

    finally:
        connection.close()