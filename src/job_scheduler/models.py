from dataclasses import dataclass
from enum import Enum


class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCESS = "SUCCESS"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobState.SUCCESS,
            JobState.DEAD,
            JobState.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    command: str
    state: JobState
    priority: int
    attempts: int
    max_attempts: int
    available_at: float
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None
    worker_id: str | None
    lease_expires_at: float | None
    pid: int | None
    exit_code: int | None
    cancel_requested: bool
    stdout_path: str | None
    stderr_path: str | None
    last_error: str | None