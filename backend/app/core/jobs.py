import threading
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCode(str, Enum):
    UNAVAILABLE = "video_unavailable"
    AGE_RESTRICTED = "age_restricted"
    BLOCKED = "video_blocked"
    FFMPEG_MISSING = "ffmpeg_missing"
    SEPARATION_FAILED = "separation_failed"
    TRANSCRIPTION_FAILED = "transcription_failed"
    RENDER_FAILED = "render_failed"
    UNKNOWN = "unknown_error"


class Stage(str, Enum):
    """Etapas sequenciais do pipeline completo (na ordem de execução)."""

    DOWNLOAD = "download"
    SEPARATE = "separate"
    TRANSCRIBE = "transcribe"
    RENDER = "render"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    job_id: str
    video_id: str
    title: str | None = None
    artist: str | None = None
    status: JobStatus = JobStatus.PENDING
    stage: Stage | None = None  # etapa em andamento (None = na fila)
    stage_progress: float = 0.0  # 0-100 dentro da etapa (0 se indeterminado)
    progress: float = 0.0  # 0-100 geral
    output_path: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class JobStore:
    """Store em memória, thread-safe (suficiente para o MVP; trocável por DB depois)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, video_id: str, title: str | None = None, artist: str | None = None) -> Job:
        job = Job(job_id=uuid.uuid4().hex, video_id=video_id, title=title, artist=artist)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = _now()


job_store = JobStore()
