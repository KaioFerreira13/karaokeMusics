from pydantic import BaseModel, Field

from app.core.jobs import ErrorCode, JobStatus, Stage

VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Nome da música")


class SearchResult(BaseModel):
    id: str
    title: str
    duration: int | None = None
    uploader: str | None = None
    thumbnail_url: str | None = None


class DownloadRequest(BaseModel):
    video_id: str = Field(pattern=VIDEO_ID_PATTERN)


class DownloadResponse(BaseModel):
    job_id: str
    status: JobStatus


class KaraokeRequest(BaseModel):
    video_id: str = Field(pattern=VIDEO_ID_PATTERN)
    title: str | None = Field(default=None, max_length=300)
    artist: str | None = Field(default=None, max_length=300)


class JobResponse(BaseModel):
    job_id: str
    video_id: str
    title: str | None = None
    status: JobStatus
    stage: Stage | None = None
    stage_progress: float = 0.0
    progress: float = 0.0
    video_url: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    updated_at: str | None = None


class WordItem(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    word: str = Field(min_length=1)
    is_verse_start: bool | None = None


class SubtitlesUpdateRequest(BaseModel):
    words: list[WordItem]


class VerseResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    words: list[WordItem]


class SubtitlesResponse(BaseModel):
    job_id: str
    words: list[WordItem]
    verses: list[VerseResponse]
