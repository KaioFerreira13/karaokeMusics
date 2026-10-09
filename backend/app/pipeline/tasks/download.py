import json
import re
import urllib.request
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


# Busca do YouTube Music com o filtro "Músicas" (parâmetro params). O yt-dlp só devolve
# título/ID nesse modo, então consultamos a API direto para obter artista e duração.
YTM_SEARCH_URL = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
YTM_SONGS_PARAMS = "EgWKAQIIAWoKEAkQBRAKEAMQBA=="
MIN_SONG_SECONDS = 60
MAX_SONG_SECONDS = 10 * 60
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TYPE_LABELS = {"música", "musica", "song", "canção", "vídeo", "video"}
_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def _parse_duration(text: str) -> int | None:
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _walk_items(node):
    if isinstance(node, dict):
        if "musicResponsiveListItemRenderer" in node:
            yield node["musicResponsiveListItemRenderer"]
        for value in node.values():
            yield from _walk_items(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_items(value)


def _parse_ytm_item(item: dict) -> dict | None:
    video_id = (
        item.get("playlistItemData", {}).get("videoId")
        or item.get("overlay", {})
        .get("musicItemThumbnailOverlayRenderer", {})
        .get("content", {})
        .get("musicPlayButtonRenderer", {})
        .get("playNavigationEndpoint", {})
        .get("watchEndpoint", {})
        .get("videoId")
    )
    if not video_id or not _VIDEO_ID_RE.match(video_id):
        return None  # canais, álbuns, playlists não têm videoId de música
    columns = item.get("flexColumns") or []

    def runs(i: int) -> list[str]:
        try:
            cell = columns[i]["musicResponsiveListItemFlexColumnRenderer"]["text"]
            return [r.get("text", "") for r in cell.get("runs", [])]
        except (IndexError, KeyError):
            return []

    title = "".join(runs(0)).strip()
    # Segunda coluna: Tipo • Artista(s) • Álbum • Duração
    parts, current = [], []
    for text in runs(1):
        if text.strip() == "•":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(text)
    parts.append("".join(current).strip())
    duration = next((d for p in reversed(parts) if (d := _parse_duration(p))), None)
    if parts and parts[0].lower() in _TYPE_LABELS:
        parts = parts[1:]  # remove rótulo de tipo (ex.: "Música"), quando presente
    artist = parts[0] if parts else None
    return {"id": video_id, "title": title, "duration": duration, "uploader": artist or None}


def _ytm_search(query: str, n: int) -> list[dict]:
    body = {
        "context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20250101.01.00", "hl": "pt", "gl": "BR"}},
        "query": query,
        "params": YTM_SONGS_PARAMS,
    }
    req = urllib.request.Request(
        YTM_SEARCH_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://music.youtube.com",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.load(res)
    seen: set[str] = set()
    out = []
    for item in _walk_items(data):
        song = _parse_ytm_item(item)
        if song and song["id"] not in seen:
            seen.add(song["id"])
            out.append(song)
        if len(out) >= n:
            break
    return out


def _is_song_entry(entry: dict | None) -> bool:
    """Descarta canais, playlists e vídeos fora da duração de uma música (busca comum)."""
    if not entry or not _VIDEO_ID_RE.match(entry.get("id") or ""):
        return False
    if entry.get("_type") == "playlist" or "/channel/" in (entry.get("url") or ""):
        return False
    duration = entry.get("duration")
    return bool(duration) and MIN_SONG_SECONDS <= duration <= MAX_SONG_SECONDS


def _youtube_search(query: str, n: int) -> list[dict]:
    """Reserva: busca comum do YouTube, filtrada."""
    opts = {**_base_opts(), "extract_flat": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n * 4}:{query}", download=False)
    except (DownloadError, ExtractorError) as exc:
        raise classify_error(str(exc)) from exc
    out = []
    for e in (info or {}).get("entries", []):
        if _is_song_entry(e):
            out.append(
                {
                    "id": e["id"],
                    "title": e.get("title") or "",
                    "duration": int(e["duration"]),
                    "uploader": (e.get("uploader") or e.get("channel") or "").removesuffix(" - Topic") or None,
                    "thumbnail_url": _thumbnail(e),
                }
            )
        if len(out) >= n:
            break
    return out


def search_videos(query: str, limit: int | None = None) -> list[dict]:
    """Busca somente músicas: YouTube Music (filtro Músicas) com fallback na busca comum filtrada."""
    n = limit or settings.search_results
    try:
        results = _ytm_search(query, n)
    except (OSError, ValueError):
        results = []
    if not results:
        return _youtube_search(query, n)
    for r in results:
        r["thumbnail_url"] = f"https://i.ytimg.com/vi/{r['id']}/hqdefault.jpg"
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
