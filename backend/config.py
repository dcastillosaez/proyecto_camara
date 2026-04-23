"""Centralized configuration via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    camera_url: str = "rtsp://192.168.1.132:554/stream1"
    # "tapo" enables PTZ/camera-control endpoints via pytapo.
    # Set to "generic" for any RTSP camera without vendor control.
    camera_driver: str = "tapo"

    # YOLO model file — swap for yolo26n.pt, yolov8s.pt, etc.
    yolo_model_path: str = "yolov8n.pt"
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
