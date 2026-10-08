from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.api.schemas import (
    DownloadRequest,
    DownloadResponse,
    JobResponse,
    KaraokeRequest,
    SearchRequest,
    SearchResult,
)
from app.core.jobs import ErrorCode, Job, JobStatus, job_store
from app.pipeline.runner import run_karaoke_pipeline
from app.pipeline.tasks.download import DownloadFailure, run_download_job, search_videos

router = APIRouter(prefix="/api")

_SEARCH_STATUS = {
    ErrorCode.UNKNOWN: 502,
    ErrorCode.UNAVAILABLE: 404,
    ErrorCode.AGE_RESTRICTED: 403,
    ErrorCode.BLOCKED: 403,
}


def _to_response(job: Job) -> JobResponse:
    video_url = f"/api/jobs/{job.job_id}/video" if job.status == JobStatus.COMPLETED else None
    return JobResponse(**job.model_dump(exclude={"output_path", "created_at", "updated_at"}), video_url=video_url)


@router.post("/search", response_model=list[SearchResult])
def search(body: SearchRequest):
    try:
        return search_videos(body.query)
    except DownloadFailure as exc:
        raise HTTPException(_SEARCH_STATUS.get(exc.code, 502), exc.message) from exc


@router.post("/download", response_model=DownloadResponse, status_code=202)
def download(body: DownloadRequest, background: BackgroundTasks):
    """Apenas baixa o áudio (original.wav 16 kHz mono)."""
    job = job_store.create(body.video_id)
    background.add_task(run_download_job, job.job_id, body.video_id)
    return DownloadResponse(job_id=job.job_id, status=job.status)


@router.post("/jobs", response_model=JobResponse, status_code=202)
def create_karaoke_job(body: KaraokeRequest, background: BackgroundTasks):
    """Pipeline completo: download -> separação -> letra -> vídeo final."""
    job = job_store.create(body.video_id, body.title)
    background.add_task(run_karaoke_pipeline, job.job_id, body.video_id)
    return _to_response(job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
@router.get("/status/{job_id}", response_model=JobResponse, include_in_schema=False)
def get_job(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job não encontrado.")
    return _to_response(job)


@router.get("/jobs/{job_id}/video")
def get_video(job_id: str, download: bool = False):
    job = job_store.get(job_id)
    if job is None or job.status != JobStatus.COMPLETED or not job.output_path:
        raise HTTPException(404, "Vídeo ainda não disponível.")
    path = Path(job.output_path)
    if not path.is_file():
        raise HTTPException(404, "Arquivo de vídeo não encontrado.")
    name = "".join(c for c in (job.title or "karaoke") if c.isalnum() or c in " -_")[:80].strip() or "karaoke"
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{name}.mp4",
        content_disposition_type="attachment" if download else "inline",
    )
