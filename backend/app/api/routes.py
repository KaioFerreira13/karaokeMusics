import json
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
    SubtitlesResponse,
    SubtitlesUpdateRequest,
    VerseResponse,
    WordItem,
)
from app.core.config import settings
from app.core.jobs import ErrorCode, Job, JobStatus, Stage, job_store
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
    ts = int(job.updated_at.timestamp()) if job.updated_at else 0
    video_url = f"/api/jobs/{job.job_id}/video?v={ts}" if job.status == JobStatus.COMPLETED else None
    return JobResponse(
        **job.model_dump(exclude={"output_path", "created_at", "updated_at"}),
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
        video_url=video_url,
    )


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
    job = job_store.create(body.video_id, body.title, body.artist)
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
def get_video(job_id: str, download: bool = False, v: str | None = None):
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
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/jobs/{job_id}/subtitles", response_model=SubtitlesResponse)
def get_subtitles(job_id: str):
    """Retorna as palavras e versos da legenda transcrita para visualização e edição."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job não encontrado.")

    words_file = settings.storage_dir / job_id / "words.json"
    if not words_file.is_file():
        raise HTTPException(404, "Arquivo de transcrição (words.json) não encontrado.")

    try:
        raw = json.loads(words_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Erro ao ler transcrição: {exc}") from exc

    words = [
        {
            "start": float(w["start"]),
            "end": float(w["end"]),
            "word": str(w["word"]).strip(),
            **({"is_verse_start": True} if w.get("is_verse_start") else {}),
        }
        for w in raw
        if w.get("word") and float(w.get("end", 0)) >= float(w.get("start", 0)) >= 0
    ]
    words.sort(key=lambda w: (w["start"], w["end"]))

    from app.pipeline.tasks.subtitles import split_into_verses

    raw_verses = split_into_verses(words)
    verses = [
        VerseResponse(
            index=i + 1,
            start=v[0]["start"],
            end=v[-1]["end"],
            text=" ".join(w["word"] for w in v),
            words=[WordItem(**w) for w in v],
        )
        for i, v in enumerate(raw_verses)
    ]

    return SubtitlesResponse(
        job_id=job_id,
        words=[WordItem(**w) for w in words],
        verses=verses,
    )


@router.put("/jobs/{job_id}/subtitles", response_model=JobResponse, status_code=202)
def update_subtitles(job_id: str, body: SubtitlesUpdateRequest, background: BackgroundTasks):
    """Atualiza a letra/tempos e inicia a re-renderização rápida do vídeo em background."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job não encontrado.")
    if job.status == JobStatus.RUNNING:
        raise HTTPException(409, "O processamento já está em andamento.")

    instrumental_path = settings.storage_dir / job_id / "instrumental.wav"
    if not instrumental_path.is_file():
        raise HTTPException(400, "Arquivo instrumental.wav não encontrado para re-renderização.")

    words_data = [w.model_dump(exclude_none=True) for w in body.words]
    words_data.sort(key=lambda w: (w["start"], w["end"]))

    job_store.update(
        job_id,
        status=JobStatus.RUNNING,
        stage=Stage.RENDER,
        stage_progress=0.0,
        progress=85.0,
        error_code=None,
        error_message=None,
    )

    from app.pipeline.runner import rerender_karaoke

    background.add_task(rerender_karaoke, job_id, words_data)
    updated = job_store.get(job_id)
    return _to_response(updated)

