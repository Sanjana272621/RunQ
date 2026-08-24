import sqlite3
import subprocess
from pathlib import Path

from job_scheduler.database import (
    finish_job,
    mark_job_cancelled,
    record_process_started,
)
from job_scheduler.models import Job


def execute_claimed_job(
    connection: sqlite3.Connection,
    job: Job,
    worker_id: str,
    logs_directory: Path,
    retry_base_delay: float,
) -> Job:
    """
    Execute one job that has already been claimed by the scheduler.

    The command's stdout and stderr are written to separate log files.
    The final job state is then stored in SQLite.
    """
    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    stdout_path = logs_directory / (
        f"job-{job.id}-attempt-{job.attempts}.out"
    )

    stderr_path = logs_directory / (
        f"job-{job.id}-attempt-{job.attempts}.err"
    )

    try:
        with stdout_path.open("wb") as stdout_file, (
            stderr_path.open("wb")
        ) as stderr_file:
            process = subprocess.Popen(
                job.command,
                shell=True,
                executable="/bin/bash",
                stdout=stdout_file,
                stderr=stderr_file,
            )

            record_process_started(
                connection=connection,
                job_id=job.id,
                worker_id=worker_id,
                pid=process.pid,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

            try:
                exit_code = process.wait()
            except KeyboardInterrupt:
                process.terminate()

                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

                mark_job_cancelled(
                    connection=connection,
                    job_id=job.id,
                )

                raise

    except OSError as error:
        return finish_job(
            connection=connection,
            job_id=job.id,
            exit_code=None,
            retry_base_delay=retry_base_delay,
            error_message=str(error),
        )

    error_message = None

    if exit_code != 0:
        error_message = (
            f"Command exited with code {exit_code}. "
            f"See stderr log: {stderr_path}"
        )

    return finish_job(
        connection=connection,
        job_id=job.id,
        exit_code=exit_code,
        retry_base_delay=retry_base_delay,
        error_message=error_message,
    )