import sqlite3
import time
from pathlib import Path

from job_scheduler.models import Job, JobState


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    command TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (
            state IN (
                'PENDING',
                'RUNNING',
                'RETRY_WAIT',
                'SUCCESS',
                'DEAD',
                'CANCELLED'
            )
        ),

    priority INTEGER NOT NULL DEFAULT 0,

    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),

    max_attempts INTEGER NOT NULL DEFAULT 3
        CHECK (max_attempts >= 1),

    available_at REAL NOT NULL,

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,

    worker_id TEXT,
    lease_expires_at REAL,

    pid INTEGER,
    exit_code INTEGER,

    cancel_requested INTEGER NOT NULL DEFAULT 0
        CHECK (cancel_requested IN (0, 1)),

    stdout_path TEXT,
    stderr_path TEXT,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_schedulable
ON jobs (
    state,
    available_at,
    priority DESC,
    created_at ASC
);
"""


class JobNotFoundError(Exception):
    #Raised when a requested job does not exist
    pass


def connect_database(database_path: Path) -> sqlite3.Connection:
    #connections wont be shared between worker threads 

    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database_path,
        timeout=5.0,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def row_to_job(row: sqlite3.Row) -> Job:
    #Convert one SQLite result row into a Job object

    return Job(
        id=row["id"],
        command=row["command"],
        state=JobState(row["state"]),
        priority=row["priority"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        available_at=row["available_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        worker_id=row["worker_id"],
        lease_expires_at=row["lease_expires_at"],
        pid=row["pid"],
        exit_code=row["exit_code"],
        cancel_requested=bool(row["cancel_requested"]),
        stdout_path=row["stdout_path"],
        stderr_path=row["stderr_path"],
        last_error=row["last_error"],
    )


def insert_job(
    connection: sqlite3.Connection,
    command: str,
    priority: int = 0,
    max_attempts: int = 3,
    available_at: float | None = None,
) -> Job:
    """Insert a new pending job and return it."""
    command = command.strip()

    if not command:
        raise ValueError("Command cannot be empty")

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    current_time = time.time()

    if available_at is None:
        available_at = current_time

    cursor = connection.execute(
        """
        INSERT INTO jobs (
            command,
            state,
            priority,
            attempts,
            max_attempts,
            available_at,
            created_at,
            updated_at
        )
        VALUES (?, 'PENDING', ?, 0, ?, ?, ?, ?)
        """,
        (
            command,
            priority,
            max_attempts,
            available_at,
            current_time,
            current_time,
        ),
    )

    connection.commit()

    job_id = cursor.lastrowid

    if job_id is None:
        raise RuntimeError("SQLite did not return a job ID")

    return get_job(connection, job_id)


def get_job(
    connection: sqlite3.Connection,
    job_id: int,
) -> Job:
    """Return one job by ID."""
    row = connection.execute(
        """
        SELECT *
        FROM jobs
        WHERE id = ?
        """,
        (job_id,),
    ).fetchone()

    if row is None:
        raise JobNotFoundError(f"Job {job_id} does not exist")

    return row_to_job(row)


def list_jobs(
    connection: sqlite3.Connection,
    state: JobState | None = None,
    limit: int = 100,
) -> list[Job]:
    
    if limit < 1:
        raise ValueError("limit must be at least 1")

    if state is None:
        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            WHERE state = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (state.value, limit),
        ).fetchall()

    return [row_to_job(row) for row in rows]