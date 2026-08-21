"""Centralized configuration via pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_MODEL_PATH_ALLOWED_SUFFIXES = {".pt", ".onnx"}

# Raíz del proyecto (directorio que contiene backend/). Todo lo que deba ser
# estable frente al cwd del proceso se ancla aquí, no al directorio de trabajo.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    # Fijado a yolo26n.pt por decision de stack (CLAUDE.md, D-03): a diferencia
    # de yolov8n.pt es end2end=True (NMS-free), lo que cambia la ruta de
    # post-proceso sobre la que se mide el criterio 6 de la Fase 27.
    yolo_model_path: str = "yolo26n.pt"

    @field_validator("yolo_model_path")
    @classmethod
    def validate_yolo_model_path(cls, v: str) -> str:
        p = Path(v)
        if p.suffix.lower() not in _MODEL_PATH_ALLOWED_SUFFIXES:
            raise ValueError(
                f"yolo_model_path extension {p.suffix!r} not allowed. "
                f"Allowed: {sorted(_MODEL_PATH_ALLOWED_SUFFIXES)}"
            )
        resolved = p.resolve() if p.is_absolute() else (_PROJECT_ROOT / p).resolve()
        if not resolved.is_relative_to(_PROJECT_ROOT):
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

    # --- Reconocimiento facial ArcFace (Fase 23 — FACE-01..03) ---
    # Defaults de SPEC_v2.md §5.4 — no son los mismos umbrales que usaba dlib
    # (distancia euclídea vs. similitud coseno, no comparables directamente).
    face_min_size_px: int = 60
    face_max_blur: float = 100.0
    face_max_yaw_deg: float = 40.0
    face_match_threshold: float = 0.45
    face_confirm_threshold: float = 0.55

    # --- Identidad temporal (Fase 24 — FACE-07..FACE-11) ---
    # Defaults de SPEC_v2.md §5.5. `face_confirm_threshold` (arriba, Fase 23) se
    # reutiliza como umbral de "confianza de identidad baja": por debajo de el, un
    # track CONFIRMED vuelve a pasar por reconocimiento sin esperar a la
    # revalidacion periodica (FACE-11). Es la confianza agregada del
    # TemporalVoter, no la confianza de deteccion de YOLO.
    identity_vote_window: int = 8
    identity_min_votes: int = 3
    identity_min_ratio: float = 0.6
    identity_lost_ttl_secs: float = 30.0
    identity_revalidate_after_secs: float = 120.0

    # --- Re-identificacion por apariencia (Fase 25 — REID-01..REID-04) ---
    # Defaults de SPEC_v2.md §5.6 / ADR-04. reid_inherit_window_secs es MAS CORTA
    # que identity_lost_ttl_secs (30 s) a proposito: la apariencia es menos fiable
    # que la votacion facial y debe caducar antes. reid_inherit_identity arranca en
    # False (modo solo-observacion): ReID calcula y registra la decision de herencia
    # sin aplicarla, para poder auditar la tasa de falsos positivos con datos reales
    # antes de activarla. El modelo lo produce scripts/fetch_models.py; si falta,
    # ReIDEngine.available queda a False y la via ReID es no-op.
    reid_enabled: bool = True
    reid_model_path: str = "models/reid/osnet_x0_25_msmt17_dyn.onnx"
    reid_inherit_window_secs: float = 15.0
    reid_similarity_threshold: float = 0.7
    reid_interval_secs: float = 2.0
    reid_inherit_identity: bool = False
    reid_max_gallery_entries: int = 256

    # --- Analisis de comportamiento (Fase 26 — BEH-01..BEH-05) ---
    # Defaults locked de SPEC_v2.md §5.7 (26-CONTEXT.md § Umbrales y reglas). Los
    # umbrales temporales estan en SEGUNDOS y los espaciales en PIXELES DEL FRAME
    # PROCESADO (process_width x process_height, 1280x720 por defecto): cambiar la
    # resolucion de proceso cambia el significado de loiter_radius_px, run_speed_px_s
    # e immobile_radius_px, que ademas no estan calibrados contra una escena real
    # (26-RESEARCH.md § Environment Availability: la calibracion con camara real es un
    # checkpoint manual abierto).
    # loiter_require_zone=False es el fallback de D-02: una instalacion limpia tiene
    # cero zonas (get_zones() lee de BD y no hay seed), asi que sin el LOITERING no se
    # emitiria nunca. A True exige zona explicita.
    # Los cuatro comportamientos salen con Severity.INFO por defecto del catalogo
    # (types.py:49-57, D-01): subirlos a WARNING activaria la subida automatica de
    # clips a Drive (upload_min_severity="warning", config.py:115 -> recording.py:309).
    behavior_enabled: bool = True
    loiter_secs: float = 120.0
    loiter_radius_px: float = 80.0
    loiter_require_zone: bool = False
    run_speed_px_s: float = 350.0
    run_window_secs: float = 1.0
    immobile_secs: float = 60.0
    immobile_radius_px: float = 20.0
    crowd_threshold: int = 5
    behavior_max_tracks: int = 256

    # --- Multi-clase y objetos (Fase 27 — BEH-06/BEH-07) ---
    # (a) Los umbrales espaciales estan en PIXELES DEL FRAME PROCESADO
    #     (process_width x process_height, 1280x720 por defecto) y NO estan calibrados
    #     contra una escena real: object_person_radius_px=150 es 1,9 x loiter_radius_px
    #     y ~media altura de persona a media distancia, una propuesta razonada
    #     (27-RESEARCH.md Q1, Assumption A1). La calibracion con camara es el checkpoint
    #     manual de 27-11.
    # (b) OJO, AL REVES QUE EL BLOQUE DE LA FASE 26: OBJECT_LEFT sale con
    #     Severity.WARNING por defecto del catalogo (types.py:55), asi que cruza
    #     upload_min_severity="warning" (config.py:115 -> recording.py:309) y SUBE CLIPS A
    #     GOOGLE DRIVE desde el primer evento. Es intencional (un objeto abandonado es lo
    #     que quieres grabado), pero un radio mal calibrado consume cuota de Drive.
    #     Valvula de escape sin tocar codigo: subir upload_min_severity a "critical".
    # (c) yolo_classes=[] CIEGA el sistema en silencio: verificado, classes=[] devuelve 0
    #     detecciones (no las 80, que es lo que hace classes=None). Por eso el endpoint
    #     PUT la rechaza con 400 y el arranque trata una fila vacia de app_config como
    #     ausente (27-RESEARCH Pitfall 3).
    # object_person_radius_ratio corrige la escala: radio = max(px, ratio * alto_bbox),
    # asi que una persona cerca de la camara (500 px de alto) tiene un "cerca" de 250 px
    # y una lejana se queda en el suelo de 150 px.
    object_class_ids: list[int] = [1, 2, 3, 24, 28]   # bicycle, car, motorcycle, backpack, suitcase
    object_left_secs: float = 60.0
    object_still_radius_px: float = 20.0
    object_person_radius_px: float = 150.0
    object_person_radius_ratio: float = 0.5
    object_warmup_secs: float = 10.0
    object_gone_secs: float = 3.0
    object_person_window_secs: float = 10.0
    object_max_tracks: int = 256
    objects_enabled: bool = True

    # --- Contexto de escena (Fase 27 — BEH-08/BEH-09) ---
    # El baseline se calcula sobre unique_tracks (personas distintas por minuto), NO sobre
    # detections: detections acumula len(active_track_ids) una vez por FRAME PROCESADO
    # (engine.py:281), asi que depende del FPS que AdaptiveRate haya elegido y no es
    # comparable entre dias (27-RESEARCH H-5). context_min_sample_days=3 hace que un
    # sistema recien instalado diga "unknown" en vez de inventarse un veredicto con
    # AVG sobre una sola muestra (Pitfall 8). Los ratios 0,5/1,5 son la parte de menor
    # confianza de la fase (Assumption A4): dos floats, triviales de ajustar con datos.
    context_baseline_days: int = 7
    context_min_sample_days: int = 3
    context_low_ratio: float = 0.5
    context_high_ratio: float = 1.5

    @field_validator("reid_model_path")
    @classmethod
    def validate_reid_model_path(cls, v: str) -> str:
        p = Path(v)
        if p.suffix.lower() not in _MODEL_PATH_ALLOWED_SUFFIXES:
            raise ValueError(
                f"reid_model_path extension {p.suffix!r} not allowed. "
                f"Allowed: {sorted(_MODEL_PATH_ALLOWED_SUFFIXES)}"
            )
        resolved = p.resolve() if p.is_absolute() else (_PROJECT_ROOT / p).resolve()
        if not resolved.is_relative_to(_PROJECT_ROOT):
            raise ValueError(f"reid_model_path must be inside the project directory: {resolved}")
        return v

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

    # --- Snapshot de evento (Fase 30, OPS-07/OPS-08) ---
    # snapshot_path existia en el contrato Event desde la Fase 19 pero NADIE lo escribia:
    # sin esto la miniatura de la linea temporal cae siempre al marcador y "Marcar como
    # persona" no puede precargar el recorte del evento (30-RESEARCH.md Hallazgo 4).
    snapshot_enabled: bool = True
    snapshot_dir: str = "data/snapshots"
    snapshot_max_width: int = 320            # px; el recorte se reescala si es mas ancho
    snapshot_min_interval_secs: float = 5.0  # throttle por (camera_id, track_id)
    snapshot_retention_days: int = 30

    @field_validator("snapshot_dir")
    @classmethod
    def validate_snapshot_dir(cls, v: str) -> str:
        """El directorio de snapshots debe quedar dentro del proyecto (SEC-16).

        Se sirve por StaticFiles bajo /snapshots: un valor fuera del arbol del
        proyecto convertiria ese mount en una fuga de ficheros arbitrarios (T-30-12).
        """
        p = Path(v)
        resolved = p.resolve() if p.is_absolute() else (_PROJECT_ROOT / p).resolve()
        if not resolved.is_relative_to(_PROJECT_ROOT):
            raise ValueError(f"snapshot_dir must be inside the project directory: {resolved}")
        return v

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

    # env_file anclado a la raíz del proyecto: si fuese la ruta relativa ".env",
    # arrancar uvicorn desde otro directorio dejaría las credenciales vacías
    # (RTSP sin auth, PTZ devolviendo 502 "Invalid authentication data").
    model_config = {"env_file": _PROJECT_ROOT / ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_identity_params(self) -> "Settings":
        if self.identity_min_votes < 1:
            raise ValueError("identity_min_votes debe ser >= 1")
        if self.identity_vote_window < self.identity_min_votes:
            raise ValueError(
                f"identity_vote_window ({self.identity_vote_window}) no puede ser menor "
                f"que identity_min_votes ({self.identity_min_votes}): la votacion nunca "
                f"alcanzaria el minimo"
            )
        if not 0.0 < self.identity_min_ratio <= 1.0:
            raise ValueError("identity_min_ratio debe estar en (0, 1]")
        if self.identity_lost_ttl_secs <= 0:
            raise ValueError("identity_lost_ttl_secs debe ser > 0")
        if self.identity_revalidate_after_secs <= 0:
            raise ValueError("identity_revalidate_after_secs debe ser > 0")
        return self

    @model_validator(mode="after")
    def validate_reid_params(self) -> "Settings":
        if not 0.0 < self.reid_similarity_threshold <= 1.0:
            raise ValueError(
                "reid_similarity_threshold debe estar en (0, 1]: es un coseno entre "
                "embeddings normalizados; 0.0 heredaria identidad de cualquier "
                "apariencia y valores > 1.0 no heredarian nunca"
            )
        if self.reid_inherit_window_secs <= 0:
            raise ValueError("reid_inherit_window_secs debe ser > 0")
        if self.reid_interval_secs <= 0:
            raise ValueError(
                "reid_interval_secs debe ser > 0: es el minimo entre inferencias "
                "ReID de un mismo track (criterio 5); 0 dejaria correr ReID en cada tick"
            )
        if self.reid_max_gallery_entries < 1:
            raise ValueError("reid_max_gallery_entries debe ser >= 1")
        return self

    @model_validator(mode="after")
    def validate_behavior_params(self) -> "Settings":
        for name in ("loiter_secs", "run_window_secs", "immobile_secs",
                     "loiter_radius_px", "run_speed_px_s", "immobile_radius_px"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        if self.crowd_threshold < 1:
            raise ValueError(
                "crowd_threshold debe ser >= 1: con 0 se emitiria CROWD_DETECTED "
                "con la escena vacia"
            )
        if self.behavior_max_tracks < 1:
            raise ValueError("behavior_max_tracks debe ser >= 1")
        if self.run_window_secs > 12.0:
            raise ValueError(
                "run_window_secs no puede superar 12.0 s: centroid_history solo "
                "garantiza 12.5 s de historial a 12 FPS (tracking.py:47 history_len=150, "
                "rate.py:26 AdaptiveRate.STEPS[0]=12.0); una ventana mayor no se podria "
                "calcular y RUNNING no se emitiria nunca"
            )
        return self

    @model_validator(mode="after")
    def validate_object_params(self) -> "Settings":
        for name in ("object_left_secs", "object_still_radius_px",
                     "object_person_radius_px", "object_warmup_secs",
                     "object_gone_secs", "object_person_window_secs"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        if not 0 <= self.object_person_radius_ratio <= 2.0:
            raise ValueError("object_person_radius_ratio debe estar en [0, 2]")
        if any(not 0 <= c <= 79 for c in self.object_class_ids):
            raise ValueError("object_class_ids deben ser ids COCO validos (0-79)")
        if 0 in self.object_class_ids:
            raise ValueError(
                "la clase 0 (person) no puede estar en object_class_ids: las personas "
                "van al PersonTracker (LineZone + identidad + comportamiento), no al "
                "tracker de objetos"
            )
        if self.object_max_tracks < 1:
            raise ValueError("object_max_tracks debe ser >= 1")
        if not self.context_low_ratio < self.context_high_ratio:
            raise ValueError("context_low_ratio debe ser menor que context_high_ratio")
        if not 1 <= self.context_baseline_days <= 90:
            raise ValueError("context_baseline_days debe estar en [1, 90]")
        if self.context_min_sample_days < 1:
            raise ValueError("context_min_sample_days debe ser >= 1")
        return self

    @model_validator(mode="after")
    def validate_snapshot_params(self) -> "Settings":
        """Rangos del snapshot de evento — cota de disco y de CPU (T-30-13)."""
        if not 64 <= self.snapshot_max_width <= 1920:
            raise ValueError(
                "snapshot_max_width debe estar en [64, 1920]: por debajo el recorte "
                "no se reconoce y por encima deja de ser una miniatura"
            )
        if not 0.0 <= self.snapshot_min_interval_secs <= 3600.0:
            raise ValueError("snapshot_min_interval_secs debe estar en [0, 3600]")
        if not 0 <= self.snapshot_retention_days <= 3650:
            raise ValueError("snapshot_retention_days debe estar en [0, 3650] (0 = sin purga)")
        return self


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
