"""Orquestrador: download -> separação -> transcrição/legendas -> render.

Executa um job por vez (as etapas de ML são pesadas); os demais ficam na fila.
"""

from __future__ import annotations

import logging
import threading

from app.core.config import settings
from app.core.jobs import ErrorCode, JobStatus, Stage, job_store
from app.pipeline.tasks.download import DownloadFailure, download_audio

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()

# Peso de cada etapa no progresso geral (soma 100).
STAGE_WEIGHTS: dict[Stage, float] = {
    Stage.DOWNLOAD: 10,
    Stage.SEPARATE: 35,
    Stage.TRANSCRIBE: 40,
    Stage.RENDER: 15,
}
_ORDER = list(STAGE_WEIGHTS)


class StageFailure(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _overall(stage: Stage, stage_pct: float) -> float:
    done = sum(STAGE_WEIGHTS[s] for s in _ORDER[: _ORDER.index(stage)])
    return round(done + STAGE_WEIGHTS[stage] * stage_pct / 100, 1)


def _enter(job_id: str, stage: Stage) -> None:
    job_store.update(job_id, stage=stage, stage_progress=0.0, progress=_overall(stage, 0))


def run_karaoke_pipeline(job_id: str, video_id: str) -> None:
    job_dir = settings.storage_dir / job_id
    with _run_lock:  # fila: um pipeline por vez
        job_store.update(job_id, status=JobStatus.RUNNING)
        try:
            # 1. Download (44,1 kHz estéreo: a fonte do instrumental final)
            _enter(job_id, Stage.DOWNLOAD)
            original = download_audio(video_id, job_dir, sample_rate=44100, channels=2)

            # 2. Separação voz/instrumental
            _enter(job_id, Stage.SEPARATE)
            from app.pipeline.tasks.separate import AudioSeparator, SeparationError

            try:
                stems = AudioSeparator().separate(original, job_dir)
            except SeparationError as exc:
                raise StageFailure(ErrorCode.SEPARATION_FAILED, str(exc)) from exc

            # 3. Transcrição + alinhamento + legendas
            _enter(job_id, Stage.TRANSCRIBE)
            from app.pipeline.tasks.subtitles import SubtitleError, generate_karaoke_ass
            from app.pipeline.tasks.transcribe import TranscriptionError, WordTranscriber

            try:
                words = WordTranscriber().transcribe(stems["vocals"], job_dir / "words.json")
                if not words:
                    raise StageFailure(
                        ErrorCode.TRANSCRIPTION_FAILED, "Nenhuma letra foi detectada na faixa de voz."
                    )
                job = job_store.get(job_id)
                ass = generate_karaoke_ass(
                    job_dir / "words.json", job_dir / "karaoke.ass",
                    title=job.title if job else None, artist=job.artist if job else None,
                )
            except (TranscriptionError, SubtitleError) as exc:
                raise StageFailure(ErrorCode.TRANSCRIPTION_FAILED, str(exc)) from exc

            # 4. Render final
            _enter(job_id, Stage.RENDER)
            from app.pipeline.tasks.render import RenderError, render_karaoke_video

            def on_progress(pct: float) -> None:
                job_store.update(
                    job_id, stage_progress=pct, progress=_overall(Stage.RENDER, pct)
                )

            try:
                video = render_karaoke_video(
                    stems["instrumental"], ass, job_dir / "output_karaoke.mp4",
                    on_progress=on_progress,
                )
            except RenderError as exc:
                logger.error("Render falhou: %s\n%s", exc.message, exc.log_tail)
                raise StageFailure(ErrorCode.RENDER_FAILED, exc.message) from exc

        except DownloadFailure as exc:
            _fail(job_id, exc.code, exc.message)
        except StageFailure as exc:
            _fail(job_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - nunca deixar o job preso em RUNNING
            logger.exception("Pipeline falhou")
            _fail(job_id, ErrorCode.UNKNOWN, str(exc))
        else:
            job_store.update(
                job_id, status=JobStatus.COMPLETED, progress=100.0, stage_progress=100.0,
                output_path=str(video),
            )


def _fail(job_id: str, code: ErrorCode, message: str) -> None:
    job_store.update(job_id, status=JobStatus.FAILED, error_code=code, error_message=message)
