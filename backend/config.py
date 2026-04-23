"""Centralized configuration via pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # Base RTSP URL — sin credenciales embebidas.
    # Usar RTSP_USER / RTSP_PASS para autenticación (más seguro que embebir en la URL).
    camera_url: str = "rtsp://192.168.1.132:554/stream1"
    rtsp_user: str = ""
    rtsp_pass: str = ""

    # "tapo" enables PTZ/camera-control endpoints via pytapo.
    # Set to "generic" for any RTSP camera without vendor control.
    camera_driver: str = "tapo"

    # CORS — lista de orígenes permitidos, e.g. ["https://192.168.1.10:8000"].
    # Vacío = sin CORS cross-origin (acceso solo desde el mismo origen).
    cors_origins: list[str] = []

    # YOLO model file — swap for yolo26n.pt, yolov8s.pt, etc.
    # Must end in .pt and must not contain path traversal sequences.
    yolo_model_path: str = "yolov8n.pt"

    @field_validator("yolo_model_path")
    @classmethod
    def validate_yolo_model_path(cls, v: str) -> str:
        p = Path(v)
        if p.suffix.lower() != ".pt":
            raise ValueError("yolo_model_path must end in .pt")
        resolved = p.resolve()
        project_root = Path(__file__).parent.parent.resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            raise ValueError("yolo_model_path must be inside the project directory")
        return v
    yolo_confidence: float = 0.45
    # COCO class IDs to detect. Default [0] = person.
    yolo_classes: list[int] = [0]
    # Label shown in bounding-box overlay.
    detection_label: str = "person"

    db_path: str = "data/events.db"
    host: str = "0.0.0.0"
    port: int = 8000

    tapo_host: str = "192.168.1.132"
    tapo_user: str = "admin"
    tapo_pass: str = ""

    # Virtual counting line as fractions (0.0–1.0) of frame dimensions.
    # Default: horizontal line at vertical mid-point, full width.
    line_start_x_frac: float = 0.0
    line_start_y_frac: float = 0.5
    line_end_x_frac: float = 1.0
    line_end_y_frac: float = 0.5

    # Processing resolution (resize before YOLO). 0 = native camera resolution.
    process_width: int = 1280
    process_height: int = 720

    # Dashboard auth — leave empty to disable (default: open access on LAN)
    dashboard_user: str = ""
    dashboard_pass: str = ""

    # HTTPS — leave empty for plain HTTP. Set both to enable SSL.
    # Cert auto-generated on first run via backend/run.py.
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    # Clip recording + Google Drive upload
    clips_dir: str = "data/clips"
    gdrive_folder_id: str = "1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir"
    gdrive_credentials_path: str = "credentials.json"
    gdrive_token_path: str = "data/token.json"
    recording_fps: float = 15.0
    recording_tail_secs: float = 5.0
    # OpenCV VideoWriter fourcc string. "mp4v" is reliable on Windows; use "avc1" for H.264.
    recording_codec: str = "mp4v"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()


def build_rtsp_url(s: Settings) -> str:
    """Return RTSP URL with credentials injected from RTSP_USER/RTSP_PASS.
    Falls back to camera_url as-is when no separate credentials are configured."""
    if not s.rtsp_user:
        return s.camera_url
    from urllib.parse import urlparse, urlunparse
    p = urlparse(s.camera_url)
    netloc = f"{s.rtsp_user}:{s.rtsp_pass}@{p.hostname}"
    if p.port:
        netloc += f":{p.port}"
    return urlunparse(p._replace(netloc=netloc))


def mask_rtsp_url(url: str) -> str:
    """Replace credentials in RTSP URL with *** for safe logging."""
    from urllib.parse import urlparse, urlunparse
    p = urlparse(url)
    if p.username:
        netloc = f"***:***@{p.hostname}"
        if p.port:
            netloc += f":{p.port}"
        return urlunparse(p._replace(netloc=netloc))
    return url
