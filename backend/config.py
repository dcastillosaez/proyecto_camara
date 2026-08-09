"""Centralized configuration via pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

_MODEL_PATH_ALLOWED_SUFFIXES = {".pt", ".onnx"}


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

    # YOLO model file — swap for yolo26n.pt, yolov8s.pt, an ONNX export, etc.
    # Extension and path containment enforced below (SEC-16) — resolved relative
    # to the project root, never to the process cwd, so it can't be fooled by
    # launching uvicorn from an unexpected working directory.
    yolo_model_path: str = "yolov8n.pt"

    @field_validator("yolo_model_path")
    @classmethod
    def validate_yolo_model_path(cls, v: str) -> str:
        p = Path(v)
        if p.suffix.lower() not in _MODEL_PATH_ALLOWED_SUFFIXES:
            raise ValueError(
                f"yolo_model_path extension {p.suffix!r} not allowed. "
                f"Allowed: {sorted(_MODEL_PATH_ALLOWED_SUFFIXES)}"
            )
        project_root = Path(__file__).resolve().parent.parent
        resolved = p.resolve() if p.is_absolute() else (project_root / p).resolve()
        if not resolved.is_relative_to(project_root):
            raise ValueError(f"yolo_model_path must be inside the project directory: {resolved}")
        return v
    yolo_confidence: float = 0.45
    # COCO class IDs to detect. Default [0] = person.
    yolo_classes: list[int] = [0]
    # Label shown in bounding-box overlay.
    detection_label: str = "person"
    # YOLO inference size (imgsz). Fixed value = predictable CPU cost.
    yolo_imgsz: int = 640
    # FPS inicial que se pasa a ByteTrack; DetectionWorker lo re-sincroniza
    # en caliente con el FPS efectivo de AdaptiveRate (set_frame_rate).
    tracker_frame_rate: int = 15

    # --- Inferencia adaptativa (Fase 18) ---
    # DetectionWorker/RecognitionWorker ajustan su ritmo con AdaptiveRate
    # segun la latencia real, entre estos limites.
    detection_target_fps: float = 8.0
    detection_min_fps: float = 3.0
    detection_max_fps: float = 12.0
    recognition_target_fps: float = 2.0

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

    # --- Pre/post-buffer de grabacion (Fase 20) ---
    pre_buffer_secs: float = 10.0
    post_buffer_secs: float = 10.0
    pre_buffer_max_mb: int = 48
    pre_buffer_jpeg_quality: int = 85
    local_retention_days: int = 7
    upload_min_severity: str = "warning"  # info | warning | critical
    max_upload_attempts: int = 5
    upload_poll_secs: float = 30.0

    # --- Observabilidad (Fase 21) ---
    metrics_enabled: bool = True
    metrics_sample_secs: float = 5.0

    # --- Housekeeping centralizado (Fase 22 — PIPE-07) ---
    # Purga periodica de TrackRegistry/PersonRecognizer por cámara, ademas de
    # la que cada worker ya hace en su propio ciclo caliente (mas frecuente).
    housekeeping_secs: float = 60.0

    # Horario de acceso — fuera de este rango los crossing events se marcan como intrusión.
    # Requiere schedule_enabled=True; si está en False todos los eventos son "normales".
    schedule_enabled: bool = False
    schedule_start: str = "08:00"   # HH:MM (hora local)
    schedule_end: str = "22:00"     # HH:MM
    # Días activos: 0=lunes … 6=domingo (default: lunes–viernes)
    schedule_days: list[int] = [0, 1, 2, 3, 4]

    # Galería de capturas — crop de persona guardado al reconocerla (throttled)
    gallery_dir: str = "data/gallery"
    gallery_throttle_secs: float = 30.0

    # Phase 12 — Alerts
    alert_webhook_url: str = ""
    alert_telegram_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_on_intrusion: bool = True
    alert_on_unknown: bool = True
    alert_on_detection: bool = False
    alert_cooldown_secs: float = 60.0
    alert_count_threshold: int = 0  # 0 = disabled

    # Phase 16 — data retention (0 = disabled)
    events_retention_days: int = 30
    recordings_retention_days: int = 30
    # Personas anónimas de paso (sin nombre, 1 sola visita): días hasta
    # borrarlas de persons.db. Las personas con nombre nunca se tocan.
    persons_retention_days: int = 30

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
