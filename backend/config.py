"""Centralized configuration via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    camera_url: str = "rtsp://192.168.1.132:554/stream1"
    yolo_confidence: float = 0.45
    db_path: str = "data/events.db"
    host: str = "0.0.0.0"
    port: int = 8000

    tapo_host: str = "192.168.1.132"
    tapo_user: str = "admin"
    tapo_pass: str = ""

    # Virtual counting line — pixel coordinates for a 1280×720 stream.
    # Adjust if the camera resolution differs.
    line_start_x: int = 0
    line_start_y: int = 360
    line_end_x: int = 1280
    line_end_y: int = 360

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
