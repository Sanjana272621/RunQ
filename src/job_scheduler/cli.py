import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from job_scheduler.database import (
    JobNotFoundError,
    connect_database,
    get_job,
    initialize_schema,
    insert_job,
    list_jobs,
)
from job_scheduler.models import Job, JobState


DEFAULT_DATABASE_PATH = Path(
    os.environ.get(
        "JOBSCHED_DB",
        "var/scheduler.db",
    )
)

DEFAULT_LOGS_DIRECTORY = Path(
    os.environ.get(
        "JOBSCHED_LOGS_DIR",
        "var/logs",
    )
)


def format_timestamp(timestamp: float | None) -> str:
    if timestamp is None:
        return "-"

    value = datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )

    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def shorten_command(
    command: str,
    maximum_length: int = 45,
) -> str:
    if len(command) <= maximum_length:
        return command

    return command[: maximum_length - 3] + "..."


def print_job_table(jobs: list[Job]) -> None:
    if not jobs:
        print("No jobs found.")
        return

    print(
        f"{'ID':<6}"
        f"{'STATE':<14}"
        f"{'PRIORITY':<10}"
        f"{'ATTEMPTS':<12}"
        f"COMMAND"
    )

    print("-" * 90)

    for job in jobs:
        attempts = f"{job.attempts}/{job.max_attempts}"

        print(
            f"{job.id:<6}"
            f"{job.state.value:<14}"
            f"{job.priority:<10}"
            f"{attempts:<12}"
            f"{shorten_command(job.command)}"
        )


def handle_init(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)

    try:
        initialize_schema(connection)
    finally:
        connection.close()

    print(f"Initialized scheduler database: {args.db}")
    return 0


def handle_add(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)

    try:
        initialize_schema(connection)

        job = insert_job(
            connection=connection,
            command=args.command,
            priority=args.priority,
            max_attempts=args.max_attempts,
        )
    finally:
        connection.close()

    print(f"Created job {job.id}")
    print(f"State: {job.state.value}")
    print(f"Priority: {job.priority}")
    print(f"Maximum attempts: {job.max_attempts}")
    print(f"Command: {job.command}")

    return 0


def handle_list(args: argparse.Namespace) -> int:
    selected_state = None

    if args.state is not None:
        selected_state = JobState(args.state)

    connection = connect_database(args.db)

    try:
        initialize_schema(connection)

        jobs = list_jobs(
            connection=connection,
            state=selected_state,
            limit=args.limit,
        )
    finally:
        connection.close()

    print_job_table(jobs)
    return 0


def handle_status(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)

    try:
        initialize_schema(connection)
        job = get_job(connection, args.job_id)
    finally:
        connection.close()

    print(f"Job ID: {job.id}")
    print(f"Command: {job.command}")
    print(f"State: {job.state.value}")
    print(f"Priority: {job.priority}")
    print(f"Attempts: {job.attempts}/{job.max_attempts}")
    print(f"Available at: {format_timestamp(job.available_at)}")
    print(f"Created at: {format_timestamp(job.created_at)}")
    print(f"Updated at: {format_timestamp(job.updated_at)}")
    print(f"Started at: {format_timestamp(job.started_at)}")
    print(f"Finished at: {format_timestamp(job.finished_at)}")
    print(f"Worker ID: {job.worker_id or '-'}")
    print(f"PID: {job.pid if job.pid is not None else '-'}")
    print(
        "Exit code: "
        f"{job.exit_code if job.exit_code is not None else '-'}"
    )
    print(f"Cancel requested: {job.cancel_requested}")
    print(f"Standard output: {job.stdout_path or '-'}")
    print(f"Standard error: {job.stderr_path or '-'}")
    print(f"Last error: {job.last_error or '-'}")

    return 0


def handle_run(args: argparse.Namespace) -> int:
    if args.workers != 1:
        raise ValueError(
            "The current version supports exactly one worker"
        )

    if args.poll_interval <= 0:
        raise ValueError(
            "poll_interval must be greater than zero"
        )

    if args.retry_base_delay < 0:
        raise ValueError(
            "retry_base_delay cannot be negative"
        )

    # Imported here so that init/add/list/status continue working
    # while the worker and scheduler are being developed.
    from job_scheduler.scheduler import run_scheduler

    return run_scheduler(
        database_path=args.db,
        logs_directory=args.logs_dir,
        run_once=args.once,
        poll_interval=args.poll_interval,
        retry_base_delay=args.retry_base_delay,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobsched",
        description="Persistent single-machine Linux job scheduler",
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="SQLite database path (default: var/scheduler.db)",
    )

    subparsers = parser.add_subparsers(
        dest="subcommand",
        required=True,
    )

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize the scheduler database",
    )
    init_parser.set_defaults(handler=handle_init)

    add_parser = subparsers.add_parser(
        "add",
        help="Submit a new job",
    )
    add_parser.add_argument(
        "--command",
        required=True,
        help="Shell command to execute",
    )
    add_parser.add_argument(
        "--priority",
        type=int,
        default=0,
        help="Job priority; higher numbers execute first",
    )
    add_parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum number of execution attempts",
    )
    add_parser.set_defaults(handler=handle_add)

    list_parser = subparsers.add_parser(
        "list",
        help="List jobs",
    )
    list_parser.add_argument(
        "--state",
        choices=[state.value for state in JobState],
        help="Only display jobs in this state",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of jobs to display",
    )
    list_parser.set_defaults(handler=handle_list)

    status_parser = subparsers.add_parser(
        "status",
        help="Show detailed information about one job",
    )
    status_parser.add_argument(
        "job_id",
        type=int,
        help="Job ID",
    )
    status_parser.set_defaults(handler=handle_status)

    # This block defines the missing run subcommand.
    run_parser = subparsers.add_parser(
        "run",
        help="Run the scheduler",
    )
    run_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of workers; currently only 1 is supported",
    )
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Execute at most one runnable job and exit",
    )
    run_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between checks for runnable jobs",
    )
    run_parser.add_argument(
        "--retry-base-delay",
        type=float,
        default=2.0,
        help="Base delay in seconds for exponential retries",
    )
    run_parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOGS_DIRECTORY,
        help="Directory for stdout and stderr logs",
    )
    run_parser.set_defaults(handler=handle_run)

    return parser


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    try:
        exit_code = args.handler(args)
    except JobNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        exit_code = 3
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        print("\nScheduler stopped.", file=sys.stderr)
        exit_code = 130

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()