import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from app.core.config import settings
from app.core.jobs import ErrorCode, JobStatus, job_store

YOUTUBE_URL = "https://www.youtube.com/watch?v={id}"


class DownloadFailure(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def classify_error(raw: str) -> DownloadFailure:
    """Converte mensagens do yt-dlp em erros de domínio."""
    text = raw.lower()
    if "confirm your age" in text or "age-restricted" in text or "age restricted" in text:
        return DownloadFailure(ErrorCode.AGE_RESTRICTED, "Vídeo com restrição de idade.")
    if (
        "blocked" in text
        or "not available in your country" in text
        or "who has blocked it" in text
        or "copyright" in text
    ):
        return DownloadFailure(ErrorCode.BLOCKED, "Vídeo bloqueado (região ou direitos autorais).")
    if (
        "unavailable" in text
        or "private video" in text
        or "has been removed" in text
        or "does not exist" in text
        or "terminated" in text
    ):
        return DownloadFailure(ErrorCode.UNAVAILABLE, "Vídeo indisponível, privado ou removido.")
    return DownloadFailure(ErrorCode.UNKNOWN, raw.strip().splitlines()[-1] if raw.strip() else "Erro desconhecido.")


def _base_opts() -> dict:
    opts: dict = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if settings.ffmpeg_location:
        opts["ffmpeg_location"] = settings.ffmpeg_location
    return opts


def _thumbnail(entry: dict) -> str | None:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbs = entry.get("thumbnails") or []
    if thumbs and thumbs[-1].get("url"):
        return thumbs[-1]["url"]
    return f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"


def search_videos(query: str, limit: int | None = None) -> list[dict]:
    """Busca sem baixar nada (ytsearchN + extract_flat)."""
    n = limit or settings.search_results
    opts = {**_base_opts(), "extract_flat": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    except (DownloadError, ExtractorError) as exc:
        raise classify_error(str(exc)) from exc

    results = []
    for entry in (info or {}).get("entries", [])[:n]:
        if not entry or not entry.get("id"):
            continue
        duration = entry.get("duration")
        results.append(
            {
                "id": entry["id"],
                "title": entry.get("title") or "",
                "duration": int(duration) if duration else None,
                "uploader": entry.get("uploader") or entry.get("channel"),
                "thumbnail_url": _thumbnail(entry),
            }
        )
    return results


def download_audio(
    video_id: str, job_dir: Path, sample_rate: int = 16000, channels: int = 1
) -> Path:
    """Baixa o melhor áudio e converte para WAV em job_dir/original.wav (padrão: 16 kHz mono)."""
    if not shutil.which("ffmpeg") and not settings.ffmpeg_location:
        raise DownloadFailure(ErrorCode.FFMPEG_MISSING, "FFmpeg não encontrado no PATH.")

    job_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_base_opts(),
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "original.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "postprocessor_args": {"extractaudio": ["-ar", str(sample_rate), "-ac", str(channels)]},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([YOUTUBE_URL.format(id=video_id)])
    except (DownloadError, ExtractorError) as exc:
        raise classify_error(str(exc)) from exc

    output = job_dir / "original.wav"
    if not output.exists():
        raise DownloadFailure(ErrorCode.UNKNOWN, "O arquivo WAV não foi gerado.")
    return output


def run_download_job(job_id: str, video_id: str) -> None:
    """Executado em background: atualiza o status do job."""
    job_store.update(job_id, status=JobStatus.RUNNING)
    try:
        output = download_audio(video_id, settings.storage_dir / job_id)
    except DownloadFailure as exc:
        job_store.update(
            job_id, status=JobStatus.FAILED, error_code=exc.code, error_message=exc.message
        )
    except Exception as exc:  # noqa: BLE001 - nunca deixar o job preso em RUNNING
        job_store.update(
            job_id, status=JobStatus.FAILED, error_code=ErrorCode.UNKNOWN, error_message=str(exc)
        )
    else:
        job_store.update(job_id, status=JobStatus.COMPLETED, output_path=str(output))
