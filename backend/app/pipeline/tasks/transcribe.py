"""Transcrição palavra-a-palavra (word-level) com WhisperX + forced alignment.

Uso isolado (CLI):
    python -m app.pipeline.tasks.transcribe caminho/vocals.wav [-o words.json]
        [--model medium|large-v3] [--language pt] [--device auto|cpu|cuda]

Saída: JSON  [{"start": 12.35, "end": 12.78, "word": "Você"}, ...]
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import re
import time
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.pipeline.tasks.separate import resolve_device

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Frases que o Whisper "alucina" em trechos sem fala (silêncio/instrumental).
HALLUCINATION_PATTERNS = [
    r"legendas? pela comunidade",
    r"amara\.org",
    r"obrigad[oa] por assistir",
    r"inscreva-?se",
    r"thanks? for watching",
    r"subscribe",
    r"subtitles? by",
    r"transcribed by",
    r"www\.",
    r"^[\W_]*$",
    r"^(m+|h+m+|a+h+|ah+|oh+|uh+)[\W_]*$",
]
_HALLUCINATION_RE = re.compile("|".join(HALLUCINATION_PATTERNS), re.IGNORECASE)


class TranscriptionError(Exception):
    pass


def _load_vocals(path: Path) -> np.ndarray:
    """Lê o WAV, converte para mono 16 kHz float32 (sem depender do ffmpeg no PATH)."""
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SAMPLE_RATE:
        import julius
        import torch

        mono = julius.resample_frac(torch.from_numpy(mono), sr, SAMPLE_RATE).numpy()
    return np.ascontiguousarray(mono, dtype=np.float32)


def _frame_rms(audio: np.ndarray, frame: int = 1600) -> np.ndarray:
    n = len(audio) // frame
    if n == 0:
        return np.array([float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0])
    frames = audio[: n * frame].reshape(n, frame)
    return np.sqrt((frames**2).mean(axis=1))


class WordTranscriber:
    """Transcreve + alinha foneticamente, retornando palavras com start/end."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
        batch_size: int = 8,
        vad_method: str = "silero",
        min_rel_db: float = -35.0,
        max_word_seconds: float = 8.0,
        release_after: bool = True,
    ) -> None:
        self.device = resolve_device(device)
        # large-v3 só é prático em GPU; em CPU o padrão é medium.
        self.model_name = (
            model_name or settings.whisper_model or ("large-v3" if self.device == "cuda" else "medium")
        )
        self.compute_type = compute_type or ("float16" if self.device == "cuda" else "int8")
        self.language = language
        self.batch_size = batch_size
        self.vad_method = vad_method
        self.min_rel_db = min_rel_db
        self.max_word_seconds = max_word_seconds
        self.release_after = release_after

    # ------------------------------------------------------------------ API
    def transcribe(self, vocals_path: str | Path, output_json: str | Path | None = None) -> list[dict]:
        import whisperx

        src = Path(vocals_path)
        if not src.is_file():
            raise TranscriptionError(f"Arquivo não encontrado: {src}")

        start = time.perf_counter()
        model = align_model = None
        try:
            audio = _load_vocals(src)
            if audio.size == 0 or not np.any(audio):
                raise TranscriptionError("Áudio vazio ou silencioso.")
            ref_level = self._reference_level(audio)

            logger.info("Carregando WhisperX '%s' (%s, %s)", self.model_name, self.device, self.compute_type)
            model = whisperx.load_model(
                self.model_name,
                self.device,
                compute_type=self.compute_type,
                language=self.language,
                vad_method=self.vad_method,
                # VAD mais sensível para canto (vogais sustentadas, voz suave)
                vad_options={"chunk_size": 30, "vad_onset": 0.4, "vad_offset": 0.3},
                asr_options={
                    "condition_on_previous_text": False,  # evita loops de repetição
                    "no_speech_threshold": 0.6,
                    "compression_ratio_threshold": 2.4,
                    "temperatures": [0.0, 0.2, 0.4],
                },
            )

            language = self.language or self._detect_language(model, audio)
            logger.info("Idioma: %s", language)

            logger.info("Transcrevendo...")
            result = model.transcribe(audio, batch_size=self.batch_size, language=language)
            segments = result.get("segments", [])
            segments = [s for s in segments if not self._is_hallucination(s.get("text", ""))]
            if not segments:
                logger.warning("Nenhuma fala detectada.")
                words: list[dict] = []
            else:
                logger.info("Alinhamento fonético (%d segmentos)", len(segments))
                align_model, metadata = whisperx.load_align_model(language_code=language, device=self.device)
                aligned = whisperx.align(
                    segments, align_model, metadata, audio, self.device, return_char_alignments=False
                )
                words = self._postprocess(aligned["segments"], audio, ref_level)
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"Falha na transcrição: {exc}") from exc
        finally:
            del model, align_model
            if self.release_after:
                self._free_memory()

        if output_json is None:
            output_json = src.parent / "words.json"
        out = Path(output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("%d palavras em %.1fs -> %s", len(words), time.perf_counter() - start, out)
        return words

    # ------------------------------------------------------------ internals
    @staticmethod
    def _reference_level(audio: np.ndarray) -> float:
        """Nível RMS típico de trechos cantados (percentil 90 dos frames de 0,1s)."""
        return float(np.percentile(_frame_rms(audio), 90)) + 1e-9

    def _detect_language(self, model, audio: np.ndarray) -> str:
        """Detecta o idioma na janela de 30s mais energética (o início costuma ser instrumental)."""
        win = 30 * SAMPLE_RATE
        try:
            rms = _frame_rms(audio)
            per_sec = max(1, SAMPLE_RATE // 1600)
            if len(audio) > win:
                kernel = np.ones(30 * per_sec)
                scores = np.convolve(rms, kernel, mode="valid")
                begin = int(np.argmax(scores)) * 1600
            else:
                begin = 0
            chunk = audio[begin : begin + win]
            lang, prob, _ = model.model.detect_language(chunk)
            logger.info("Idioma detectado: %s (%.2f)", lang, prob)
            return lang
        except Exception:  # noqa: BLE001
            logger.exception("Falha na detecção de idioma; usando 'pt'")
            return "pt"

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        return bool(_HALLUCINATION_RE.search(text.strip()))

    def _postprocess(self, segments: list[dict], audio: np.ndarray, ref_level: float) -> list[dict]:
        min_level = ref_level * (10 ** (self.min_rel_db / 20))
        words: list[dict] = []
        last_text, repeats = None, 0

        for seg in segments:
            text = seg.get("text", "").strip()
            # colapsa loops de repetição do modelo (mesma frase 3+ vezes seguidas sem timestamps novos)
            if text and text == last_text:
                repeats += 1
            else:
                last_text, repeats = text, 0
            if repeats >= 2 and len(text.split()) >= 3:
                continue

            seg_words = self._fill_missing(seg.get("words", []), seg.get("start"), seg.get("end"))
            if not seg_words:
                continue

            # descarta segmentos em trecho praticamente mudo (vazamento de instrumental)
            s0, s1 = seg_words[0]["start"], seg_words[-1]["end"]
            chunk = audio[int(s0 * SAMPLE_RATE) : int(s1 * SAMPLE_RATE)]
            if chunk.size and float(np.sqrt(np.mean(chunk**2))) < min_level:
                logger.info("Segmento descartado (silêncio): %r", text[:40])
                continue
            seg_words[0]["is_verse_start"] = True
            words.extend(seg_words)

        return self._normalize_timings(words)

    @staticmethod
    def _fill_missing(words: list[dict], seg_start, seg_end) -> list[dict]:
        """Palavras que o aligner não conseguiu (números, símbolos) recebem tempo interpolado."""
        items = [w for w in words if w.get("word", "").strip()]
        if not items:
            return []
        n = len(items)
        i = 0
        while i < n:
            if items[i].get("start") is not None and items[i].get("end") is not None:
                i += 1
                continue
            j = i
            while j < n and (items[j].get("start") is None or items[j].get("end") is None):
                j += 1
            left = items[i - 1]["end"] if i > 0 else (seg_start if seg_start is not None else None)
            right = items[j]["start"] if j < n else (seg_end if seg_end is not None else None)
            if left is None and right is None:
                return []
            left = left if left is not None else right
            right = right if right is not None else left
            step = (right - left) / (j - i)
            for k in range(i, j):
                items[k]["start"] = left + step * (k - i)
                items[k]["end"] = left + step * (k - i + 1)
            i = j
        return [{"start": float(w["start"]), "end": float(w["end"]), "word": w["word"].strip()} for w in items]

    def _normalize_timings(self, words: list[dict], min_duration: float = 0.05) -> list[dict]:
        """Ordem monotônica, sem sobreposição; mantém notas longas, mas limita aberrações."""
        words = sorted(words, key=lambda w: (w["start"], w["end"]))
        for i, w in enumerate(words):
            if w["end"] < w["start"]:
                w["end"] = w["start"]
            # palavra alongada pelo cantor: preserva a duração real, até um teto
            if w["end"] - w["start"] > self.max_word_seconds:
                w["end"] = w["start"] + self.max_word_seconds
            if i + 1 < len(words) and w["end"] > words[i + 1]["start"]:
                w["end"] = max(w["start"], words[i + 1]["start"])
            if w["end"] - w["start"] < min_duration:
                nxt = words[i + 1]["start"] if i + 1 < len(words) else float("inf")
                w["end"] = min(w["start"] + min_duration, nxt) if nxt > w["start"] else w["start"]
        return [
            {
                "start": round(w["start"], 2),
                "end": round(w["end"], 2),
                "word": w["word"],
                **({"is_verse_start": True} if w.get("is_verse_start") else {}),
            }
            for w in words
        ]

    @staticmethod
    def _free_memory() -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao limpar memória da GPU")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcrição palavra-a-palavra com WhisperX.")
    parser.add_argument("input", help="Caminho do vocals.wav")
    parser.add_argument("-o", "--output", help="JSON de saída (padrão: words.json ao lado do áudio)")
    parser.add_argument("--model", help="medium, large-v3, ... (padrão: automático por dispositivo)")
    parser.add_argument("--language", help="Código do idioma (ex.: pt, en). Padrão: detectar")
    parser.add_argument("--device", default="auto", help="auto, cpu ou cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    words = WordTranscriber(
        model_name=args.model, device=args.device, language=args.language, batch_size=args.batch_size
    ).transcribe(args.input, args.output)
    print(f"{len(words)} palavras")


if __name__ == "__main__":
    main()
