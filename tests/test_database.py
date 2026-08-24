import sqlite3

import pytest

from job_scheduler.database import (
    JobNotFoundError,
    connect_database,
    get_job,
    initialize_schema,
    insert_job,
    list_jobs,
)
from job_scheduler.models import JobState


@pytest.fixture
def database_path(tmp_path):
    return tmp_path / "test-scheduler.db"


@pytest.fixture
def connection(database_path):
    database_connection = connect_database(database_path)
    initialize_schema(database_connection)

    yield database_connection

    database_connection.close()


def test_schema_creates_jobs_table(connection):
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'jobs'
        """
    ).fetchone()

    assert row is not None
    assert row["name"] == "jobs"


def test_insert_job_creates_pending_job(connection):
    job = insert_job(
        connection=connection,
        command="echo hello",
        priority=10,
        max_attempts=4,
    )

    assert job.id > 0
    assert job.command == "echo hello"
    assert job.state == JobState.PENDING
    assert job.priority == 10
    assert job.attempts == 0
    assert job.max_attempts == 4
    assert job.cancel_requested is False


def test_job_survives_database_reconnection(database_path):
    first_connection = connect_database(database_path)
    initialize_schema(first_connection)

    created_job = insert_job(
        connection=first_connection,
        command="echo persistent",
    )

    first_connection.close()

    second_connection = connect_database(database_path)

    try:
        loaded_job = get_job(
            second_connection,
            created_job.id,
        )
    finally:
        second_connection.close()

    assert loaded_job.id == created_job.id
    assert loaded_job.command == "echo persistent"
    assert loaded_job.state == JobState.PENDING


def test_list_jobs_can_filter_by_state(connection):
    insert_job(connection, "echo first")
    insert_job(connection, "echo second")

    jobs = list_jobs(
        connection=connection,
        state=JobState.PENDING,
    )

    assert len(jobs) == 2

    for job in jobs:
        assert job.state == JobState.PENDING


def test_get_job_raises_error_for_unknown_job(connection):
    with pytest.raises(
        JobNotFoundError,
        match="Job 999 does not exist",
    ):
        get_job(connection, 999)


def test_empty_command_is_rejected(connection):
    with pytest.raises(
        ValueError,
        match="Command cannot be empty",
    ):
        insert_job(
            connection=connection,
            command="   ",
        )


def test_max_attempts_must_be_positive(connection):
    with pytest.raises(
        ValueError,
        match="max_attempts must be at least 1",
    ):
        insert_job(
            connection=connection,
            command="echo hello",
            max_attempts=0,
        )


def test_invalid_state_is_rejected_by_sqlite(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
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
            VALUES (
                'echo invalid',
                'SOMETHING_WRONG',
                0,
                0,
                3,
                0,
                0,
                0
            )
            """
        )