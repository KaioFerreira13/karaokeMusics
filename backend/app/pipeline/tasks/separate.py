"""Separação de voz/instrumental com Meta Demucs (htdemucs, modo two-stems).

Uso isolado (CLI):
    python -m app.pipeline.tasks.separate caminho/original.wav [-o pasta_saida] [--device cpu|cuda]

Equivalente ao CLI nativo do Demucs:
    demucs -n htdemucs --two-stems=vocals -o saida original.wav
"""

from __future__ import annotations

import argparse
import gc
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_NAME = "htdemucs"
VOCALS = "vocals"


class SeparationError(Exception):
    pass


def resolve_device(preferred: str | None = None) -> str:
    """Usa CUDA se disponível; caso contrário cai para CPU."""
    import torch

    if preferred and preferred != "auto":
        if preferred.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("CUDA solicitada mas indisponível; usando CPU.")
            return "cpu"
        return preferred
    return "cuda" if torch.cuda.is_available() else "cpu"


class AudioSeparator:
    """Separa um áudio em vocals.wav e instrumental.wav.

    O modelo é carregado sob demanda e liberado ao final de cada `separate`
    (release_after=True) para devolver VRAM/RAM.
    """

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        device: str | None = None,
        shifts: int = 1,
        segment: int | None = None,
        release_after: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = resolve_device(device)
        self.shifts = shifts
        self.segment = segment
        self.release_after = release_after
        self._model = None

    # -- modelo -----------------------------------------------------------
    def _load_model(self):
        from demucs.pretrained import get_model

        if self._model is None:
            logger.info("Carregando modelo %s em %s", self.model_name, self.device)
            self._model = get_model(self.model_name)
            self._model.eval()
        return self._model

    def release(self) -> None:
        """Descarta o modelo e limpa caches de RAM e VRAM."""
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:  # noqa: BLE001 - limpeza nunca deve mascarar o erro real
            logger.exception("Falha ao limpar memória da GPU")
        logger.info("Memória liberada")

    # -- inferência ---------------------------------------------------------
    def separate(self, input_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
        import numpy as np
        import soundfile as sf
        import torch
        from demucs.apply import apply_model

        src = Path(input_path)
        if not src.is_file():
            raise SeparationError(f"Arquivo não encontrado: {src}")
        out_dir = Path(output_dir) if output_dir else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        start = time.perf_counter()
        try:
            model = self._load_model()
            sr = model.samplerate

            data, file_sr = sf.read(str(src), dtype="float32", always_2d=True)  # (n, ch)
            wav = torch.from_numpy(data.T.copy())  # (ch, n)
            if file_sr != sr:
                import julius

                logger.info("Reamostrando %d Hz -> %d Hz", file_sr, sr)
                wav = julius.resample_frac(wav, file_sr, sr)
            if wav.shape[0] == 1:  # modelo espera estéreo
                wav = wav.repeat(2, 1)
            wav = wav[: model.audio_channels]

            ref = wav.mean(0)
            norm = (wav - ref.mean()) / (ref.std() + 1e-8)

            logger.info("Separando %s (device=%s)", src.name, self.device)
            with torch.inference_mode():
                sources = apply_model(
                    model,
                    norm[None],
                    device=self.device,
                    shifts=self.shifts,
                    split=True,
                    overlap=0.25,
                    segment=self.segment,
                    progress=False,
                )[0]
            sources = sources * (ref.std() + 1e-8) + ref.mean()

            names = list(model.sources)
            vocals = sources[names.index(VOCALS)]
            # two-stems: instrumental = soma de todas as outras fontes
            instrumental = sum(sources[i] for i, n in enumerate(names) if n != VOCALS)

            outputs = {
                "vocals": out_dir / "vocals.wav",
                "instrumental": out_dir / "instrumental.wav",
            }
            for key, stem in (("vocals", vocals), ("instrumental", instrumental)):
                audio = stem.detach().cpu().numpy().T
                audio = np.clip(audio, -1.0, 1.0)
                sf.write(str(outputs[key]), audio, sr, subtype="PCM_16")
        except torch.cuda.OutOfMemoryError as exc:
            raise SeparationError(
                "Sem memória de GPU. Tente device='cpu' ou um 'segment' menor."
            ) from exc
        except SeparationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SeparationError(f"Falha na separação: {exc}") from exc
        finally:
            if self.release_after:
                self.release()

        logger.info("Separação concluída em %.1fs", time.perf_counter() - start)
        return outputs


def run_separation_job(input_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    """Atalho funcional para uso no pipeline."""
    return AudioSeparator().separate(input_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Separa voz e instrumental com Demucs.")
    parser.add_argument("input", help="Caminho do original.wav")
    parser.add_argument("-o", "--output", help="Pasta de saída (padrão: pasta do arquivo)")
    parser.add_argument("--device", default="auto", help="auto, cpu ou cuda")
    parser.add_argument("--shifts", type=int, default=1)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = AudioSeparator(device=args.device, shifts=args.shifts).separate(args.input, args.output)
    for name, path in result.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
