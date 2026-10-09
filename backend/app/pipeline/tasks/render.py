"""Composição do vídeo final do karaokê: fundo estático + instrumental + legendas .ass.

Uso isolado (CLI):
    python -m app.pipeline.tasks.render instrumental.wav karaoke.ass -o output_karaoke.mp4
        [-b background.png] [--preset fast] [--crf 20]

Comando FFmpeg equivalente (resumo):
    ffmpeg -y -loop 1 -framerate 30 -i background.png -i instrumental.wav \\
      -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,ass=karaoke.ass,format=yuv420p" \\
      -c:v libx264 -preset fast -tune stillimage -crf 20 -c:a aac -b:a 192k -shortest \\
      -movflags +faststart output_karaoke.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float], None]  # recebe 0.0 - 100.0

# Fundo padrão do vídeo (backend/assets/background.jpg); se não existir, usa cor sólida.
DEFAULT_BACKGROUND = Path(__file__).resolve().parents[3] / "assets" / "background.jpg"


class RenderError(Exception):
    def __init__(self, message: str, log_tail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.log_tail = log_tail


def _binary(name: str) -> str:
    """Localiza ffmpeg/ffprobe: KARAOKE_FFMPEG_LOCATION primeiro, depois PATH."""
    if settings.ffmpeg_location:
        for candidate in (name, f"{name}.exe"):
            path = Path(settings.ffmpeg_location) / candidate
            if path.is_file():
                return str(path)
    found = shutil.which(name)
    if not found:
        raise RenderError(f"{name} não encontrado. Instale o FFmpeg e/ou defina KARAOKE_FFMPEG_LOCATION.")
    return found


def probe_duration(audio: Path) -> float:
    """Duração em segundos via ffprobe."""
    try:
        out = subprocess.run(
            [
                _binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(audio),
            ],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        duration = float(out)
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise RenderError(f"Não foi possível ler a duração de {audio.name}.") from exc
    if duration <= 0:
        raise RenderError("O áudio instrumental está vazio.")
    return duration


def _escape_filter_path(name: str) -> str:
    """Escapa um valor de opção de filtro do FFmpeg (aspas, ':', ',', '[', ']', ';', '\\')."""
    for ch in ("\\", ":", "'", ",", "[", "]", ";"):
        name = name.replace(ch, "\\" + ch)
    return name


def build_command(
    instrumental: Path,
    ass_name: str,
    output: Path,
    background: Path | None,
    *,
    width: int,
    height: int,
    fps: int,
    preset: str,
    crf: int,
    audio_bitrate: str,
    bg_color: str,
    ffmpeg: str,
    duration: float,
) -> list[str]:
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin"]
    if background:
        cmd += ["-loop", "1", "-framerate", str(fps), "-i", str(background)]
        fit = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
    else:  # cor sólida
        cmd += ["-f", "lavfi", "-i", f"color=c={bg_color}:s={width}x{height}:r={fps}"]
        fit = ""
    cmd += ["-i", str(instrumental)]
    vf = f"{fit}ass={_escape_filter_path(ass_name)},format=yuv420p"
    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-tune", "stillimage", "-crf", str(crf),
        "-r", str(fps),
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-shortest", "-t", f"{duration:.3f}",  # -t garante duração exata (só -shortest estoura)
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(output),
    ]
    return cmd


def render_karaoke_video(
    instrumental: str | Path,
    subtitles: str | Path,
    output: str | Path,
    background: str | Path | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    preset: str = "fast",
    crf: int = 20,
    audio_bitrate: str = "192k",
    bg_color: str = "0x101020",
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Renderiza o MP4 final. Bloqueia a thread chamadora (use a versão async ou BackgroundTasks).

    - background=None usa cor sólida `bg_color`.
    - O vídeo dura exatamente o áudio (-loop 1 + -shortest).
    - Escreve em arquivo parcial e só renomeia ao terminar com sucesso.
    """
    inst = Path(instrumental).resolve()
    ass = Path(subtitles).resolve()
    out = Path(output).resolve()
    if background is None and DEFAULT_BACKGROUND.is_file():
        background = DEFAULT_BACKGROUND
    bg = Path(background).resolve() if background else None
    for label, p in (("Instrumental", inst), ("Legenda", ass), ("Fundo", bg)):
        if p is not None and not p.is_file():
            raise RenderError(f"{label} não encontrado: {p}")

    duration = probe_duration(inst)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".part" + out.suffix)

    # O filtro ass recebe só o nome do arquivo e o processo roda na pasta dele:
    # evita o inferno de escapar "C:\..." dentro de -vf no Windows.
    cmd = build_command(
        inst, ass.name, partial, bg,
        width=width, height=height, fps=fps, preset=preset, crf=crf,
        audio_bitrate=audio_bitrate, bg_color=bg_color, ffmpeg=_binary("ffmpeg"), duration=duration,
    )
    logger.info("FFmpeg: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd, cwd=ass.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    stderr_tail: collections.deque[str] = collections.deque(maxlen=40)

    def drain_stderr() -> None:  # evita deadlock do pipe e guarda o final do log
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_tail.append(line.rstrip())

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()

    last_pct = -1.0
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
                pct = min(99.0, max(0.0, int(value) / 1_000_000 / duration * 100))
                if on_progress and pct - last_pct >= 1.0:
                    last_pct = pct
                    on_progress(round(pct, 1))
        code = proc.wait()
    except BaseException:
        proc.kill()
        partial.unlink(missing_ok=True)
        raise
    finally:
        reader.join(timeout=2)

    if code != 0:
        partial.unlink(missing_ok=True)
        tail = "\n".join(stderr_tail)
        raise RenderError(f"FFmpeg falhou (código {code}).", tail)

    os.replace(partial, out)
    if on_progress:
        on_progress(100.0)
    logger.info("Vídeo gerado: %s", out)
    return out


async def render_karaoke_video_async(*args, **kwargs) -> Path:
    """Versão não bloqueante para código async (roda em thread; independe do tipo de event loop)."""
    return await asyncio.to_thread(render_karaoke_video, *args, **kwargs)


def main() -> None:
    p = argparse.ArgumentParser(description="Renderiza o vídeo final do karaokê.")
    p.add_argument("instrumental")
    p.add_argument("subtitles")
    p.add_argument("-o", "--output", default="output_karaoke.mp4")
    p.add_argument("-b", "--background", help="PNG de fundo (padrão: cor sólida)")
    p.add_argument("--preset", default="fast")
    p.add_argument("--crf", type=int, default=20)
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = render_karaoke_video(
            a.instrumental, a.subtitles, a.output, a.background, preset=a.preset, crf=a.crf,
            on_progress=lambda pct: print(f"\rProgresso: {pct:5.1f}%", end="", flush=True),
        )
    except RenderError as exc:
        print(f"\nErro: {exc.message}\n{exc.log_tail}")
        raise SystemExit(1) from exc
    print(f"\n{result}")


if __name__ == "__main__":
    main()
