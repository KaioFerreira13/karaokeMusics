from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KARAOKE_")

    storage_dir: Path = BACKEND_DIR / "storage"
    search_results: int = 5
    # Opcional: caminho da pasta que contém ffmpeg/ffprobe, se não estiverem no PATH.
    ffmpeg_location: str | None = None
    # Modelo Whisper (medium, large-v3...). None = automático: large-v3 em GPU, medium em CPU.
    whisper_model: str | None = None


settings = Settings()
