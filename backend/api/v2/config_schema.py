"""API v2 — esquema declarativo de configuracion runtime (Fase 32, SET-01..SET-04).

Este modulo NO expone ningun endpoint HTTP: es el contrato puro que consume
`backend/api/v2/config.py` (32-02) y, mas adelante, las vistas de Ajustes del
frontend. Describe los 112 campos reales de `backend.config.Settings` — label
en espanol llano, hint, tipo, rango, seccion, aplicacion en caliente y si es
secreto — agrupados en las 8 secciones fijas del UI-SPEC (Camara, Deteccion,
Tracking, Reconocimiento, Zonas, Reglas, Alertas, Almacenamiento).

Precedencia de valores (D-06, dos precedentes reales: `PUT /api/v2/detection/classes`
de la Fase 27 y el silenciado de alertas de la Fase 30): runtime (`app_config`,
via `ConfigRepo`) > `.env` > default del codigo. `resolve_origin()` decide esa
precedencia por campo sin persistir un cuarto estado en ningun sitio nuevo.

Aplicacion en caliente: solo tres campos (`yolo_classes`, `process_width`,
`process_height`) tienen una ruta real hoy (`CameraPipeline.set_detection_classes`/
`set_process_size`, `backend/pipeline/manager.py:322/329/386`). Todo lo demas es
`"restart_camera"` o `"restart_server"` — este modulo solo *senaliza*, no ejecuta
ningun reinicio (D-07).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldDef:
    key: str                      # nombre exacto en Settings y clave en app_config
    env: str                      # nombre de la env var (mayusculas)
    label: str                    # espanol llano, nunca el identificador Python
    hint: str = ""                # pista en prosa, opcional
    type: str = "str"             # "bool"|"int"|"float"|"enum"|"time"|"list_int"|"list_str"|"secret"|"readonly"
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    enum_values: tuple[str, ...] | None = None
    applies: str = "restart_camera"   # "hot" | "restart_camera" | "restart_server"
    secret: bool = False
    readonly: bool = False
    max_length: int | None = None     # solo para type="str"/"list_str" sin rango numerico


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    fields: tuple[FieldDef, ...] = ()
    # Grupos de solo lectura no respaldados por Settings (zonas definidas, reglas
    # cargadas) usan fields=() y se marcan con external_source:
    external_source: str | None = None   # "/api/v2/zones" | "/api/v2/lines" | "/api/v2/rules" | None


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    groups: tuple[Group, ...] = ()


ALL_SECTIONS: tuple[Section, ...] = (
    Section(
        key="camara",
        label="Cámara",
        groups=(
            Group(
                key="captura",
                label="Captura",
                fields=(
                    FieldDef(
                        key="camera_url", env="CAMERA_URL", label="URL RTSP de la cámara",
                        hint="Usa RTSP_USER / RTSP_PASS para autenticación en vez de embeber "
                             "credenciales en la URL; se muestra siempre enmascarada.",
                        type="readonly", default="rtsp://192.168.1.132:554/stream1",
                        applies="restart_camera", readonly=True,
                    ),
                    FieldDef(
                        key="camera_driver", env="CAMERA_DRIVER", label="Tipo de cámara",
                        hint="'tapo' habilita los endpoints PTZ vía pytapo; 'generic' para "
                             "cualquier cámara RTSP sin control de fabricante.",
                        type="enum", default="tapo", enum_values=("tapo", "generic"),
                        applies="restart_server",
                    ),
                    FieldDef(
                        key="rtsp_user", env="RTSP_USER", label="Usuario RTSP",
                        hint="Usuario para autenticación RTSP (más seguro que embeber "
                             "credenciales en la URL).",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="rtsp_pass", env="RTSP_PASS", label="Contraseña RTSP",
                        hint="Contraseña para autenticación RTSP.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="tapo_host", env="TAPO_HOST", label="IP de la cámara (PTZ)",
                        hint="Dirección IP de la cámara Tapo para los endpoints PTZ.",
                        type="str", default="192.168.1.132", applies="restart_camera",
                    ),
                    FieldDef(
                        key="tapo_user", env="TAPO_USER", label="Usuario Tapo (PTZ)",
                        hint="Usuario de la cuenta Tapo usada para PTZ.",
                        type="secret", default="admin", secret=True,
                    ),
                    FieldDef(
                        key="tapo_pass", env="TAPO_PASS", label="Contraseña Tapo (PTZ)",
                        hint="Contraseña de la cuenta Tapo usada para PTZ.",
                        type="secret", default="", secret=True,
                    ),
                ),
            ),
            Group(
                key="procesado",
                label="Procesado",
                fields=(
                    FieldDef(
                        key="process_width", env="PROCESS_WIDTH", label="Ancho de procesado",
                        hint="Ancho al que se redimensiona el frame antes de pasar por YOLO.",
                        type="int", default=1280, min=320, max=1920, step=16, applies="hot",
                    ),
                    FieldDef(
                        key="process_height", env="PROCESS_HEIGHT", label="Alto de procesado",
                        hint="Alto al que se redimensiona el frame antes de pasar por YOLO.",
                        type="int", default=720, min=180, max=1080, step=16, applies="hot",
                    ),
                ),
            ),
            Group(
                key="servidor",
                label="Servidor",
                fields=(
                    FieldDef(
                        key="host", env="HOST", label="Dirección de escucha",
                        hint="Interfaz de red en la que escucha el servidor "
                             "(0.0.0.0 = todas las interfaces).",
                        type="str", default="0.0.0.0", applies="restart_server",
                    ),
                    FieldDef(
                        key="port", env="PORT", label="Puerto",
                        hint="Puerto HTTP/HTTPS del servidor.",
                        type="int", default=8000, min=1, max=65535, applies="restart_server",
                    ),
                    FieldDef(
                        key="cors_origins", env="CORS_ORIGINS", label="Orígenes CORS permitidos",
                        hint="Orígenes permitidos para peticiones cross-origin; vacío = sin "
                             "CORS (acceso solo desde el mismo origen).",
                        type="list_str", default=[], applies="restart_server",
                    ),
                    FieldDef(
                        key="ssl_certfile", env="SSL_CERTFILE", label="Certificado SSL",
                        hint="Ruta al certificado SSL; vacío desactiva HTTPS.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="ssl_keyfile", env="SSL_KEYFILE", label="Clave privada SSL",
                        hint="Ruta a la clave privada SSL; vacío desactiva HTTPS.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="dashboard_user", env="DASHBOARD_USER", label="Usuario del dashboard",
                        hint="Usuario para proteger el dashboard; vacío = acceso abierto en LAN.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="dashboard_pass", env="DASHBOARD_PASS", label="Contraseña del dashboard",
                        hint="Contraseña del dashboard; vacío = acceso abierto en LAN.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="database_url", env="DATABASE_URL", label="URL de base de datos",
                        hint="Vacío = SQLite (por defecto). URL SQLAlchemy async completa "
                             "para usar PostgreSQL, p. ej. postgresql+asyncpg://usuario:"
                             "contraseña@host:5432/nombre_bd.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="redis_url", env="REDIS_URL", label="URL de Redis",
                        hint="Vacío = bus de eventos en memoria del proceso (por defecto). "
                             "Con una URL redis://host:6379/0 el bus usa pub/sub de Redis.",
                        type="secret", default="", secret=True,
                    ),
                ),
            ),
        ),
    ),
    Section(
        key="deteccion",
        label="Detección",
        groups=(
            Group(
                key="personas",
                label="Personas",
                fields=(
                    FieldDef(
                        key="yolo_model_path", env="YOLO_MODEL_PATH", label="Modelo YOLO",
                        hint="Debe tener extensión .pt o .onnx y quedar dentro del proyecto "
                             "(validate_yolo_model_path, config.py).",
                        type="str", default="yolo26n.pt", applies="restart_camera",
                    ),
                    FieldDef(
                        key="yolo_confidence", env="YOLO_CONFIDENCE",
                        label="Confianza mínima de detección",
                        hint="Por debajo de este valor YOLO descarta la detección.",
                        type="float", default=0.45, min=0.05, max=0.95, step=0.05,
                        applies="restart_camera",
                    ),
                    FieldDef(
                        key="yolo_classes", env="YOLO_CLASSES", label="Clases detectadas",
                        hint="Ids de clases COCO detectadas; una lista vacía ciega el "
                             "sistema (0 detecciones, no las 80).",
                        type="list_int", default=[0], applies="hot",
                    ),
                    FieldDef(
                        key="detection_label", env="DETECTION_LABEL",
                        label="Etiqueta en el overlay",
                        hint="Texto mostrado sobre la caja delimitadora de la detección.",
                        type="str", default="person", max_length=40, applies="restart_camera",
                    ),
                    FieldDef(
                        key="yolo_imgsz", env="YOLO_IMGSZ",
                        label="Tamaño de inferencia (imgsz)",
                        hint="Tamaño de entrada de YOLO; valor fijo por coste de CPU predecible.",
                        type="int", default=640, min=320, max=1280, step=32,
                        applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="objetos",
                label="Objetos",
                fields=(
                    FieldDef(
                        key="objects_enabled", env="OBJECTS_ENABLED", label="Detectar objetos",
                        hint="Activa el seguimiento de objetos (maletas, mochilas, vehículos).",
                        type="bool", default=True, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_class_ids", env="OBJECT_CLASS_IDS",
                        label="Clases de objeto vigiladas",
                        hint="Ids COCO 0-79 vigilados como objeto, sin la clase 0 (persona).",
                        type="list_int", default=[1, 2, 3, 24, 28], applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_left_secs", env="OBJECT_LEFT_SECS",
                        label="Segundos inmóvil para 'abandonado'",
                        hint="Segundos sin persona cerca para marcar un objeto como abandonado.",
                        type="float", default=60.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_still_radius_px", env="OBJECT_STILL_RADIUS_PX",
                        label="Radio de quietud (px)",
                        hint="Radio en píxeles dentro del cual un objeto se considera quieto.",
                        type="float", default=20.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_person_radius_px", env="OBJECT_PERSON_RADIUS_PX",
                        label="Radio de proximidad a persona (px)",
                        hint="Radio en píxeles para considerar una persona 'cerca' del objeto.",
                        type="float", default=150.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_person_radius_ratio", env="OBJECT_PERSON_RADIUS_RATIO",
                        label="Ratio de proximidad sobre alto de persona",
                        hint="Escala el radio de proximidad según el alto de la persona detectada.",
                        type="float", default=0.5, min=0.0, max=2.0, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_warmup_secs", env="OBJECT_WARMUP_SECS",
                        label="Segundos de calentamiento del tracker",
                        hint="Segundos de calentamiento antes de evaluar un objeto recién visto.",
                        type="float", default=10.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_gone_secs", env="OBJECT_GONE_SECS",
                        label="Segundos de gracia antes de 'retirado'",
                        hint="Segundos de gracia antes de marcar un objeto como retirado.",
                        type="float", default=3.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_person_window_secs", env="OBJECT_PERSON_WINDOW_SECS",
                        label="Ventana de persona cercana (s)",
                        hint="Ventana de tiempo para considerar 'persona cercana reciente'.",
                        type="float", default=10.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="object_max_tracks", env="OBJECT_MAX_TRACKS",
                        label="Máximo de objetos en seguimiento",
                        hint="Máximo de objetos en seguimiento simultáneo.",
                        type="int", default=256, min=1, applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="contexto",
                label="Contexto de escena",
                fields=(
                    FieldDef(
                        key="context_baseline_days", env="CONTEXT_BASELINE_DAYS",
                        label="Días de referencia",
                        hint="Días de historial usados como referencia de actividad normal.",
                        type="int", default=7, min=1, max=90, applies="restart_camera",
                    ),
                    FieldDef(
                        key="context_min_sample_days", env="CONTEXT_MIN_SAMPLE_DAYS",
                        label="Días mínimos de muestra",
                        hint="Días mínimos de muestra antes de emitir un veredicto de contexto.",
                        type="int", default=3, min=1, applies="restart_camera",
                    ),
                    FieldDef(
                        key="context_low_ratio", env="CONTEXT_LOW_RATIO",
                        label="Umbral de actividad baja",
                        hint="Por debajo de este ratio sobre el baseline, la actividad es baja; "
                             "debe ser menor que el umbral alto.",
                        type="float", default=0.5, applies="restart_camera",
                    ),
                    FieldDef(
                        key="context_high_ratio", env="CONTEXT_HIGH_RATIO",
                        label="Umbral de actividad alta",
                        hint="Por encima de este ratio sobre el baseline, la actividad es alta; "
                             "debe ser mayor que el umbral bajo.",
                        type="float", default=1.5, applies="restart_camera",
                    ),
                ),
            ),
        ),
    ),
    Section(
        key="tracking",
        label="Tracking",
        groups=(
            Group(
                key="seguimiento",
                label="Seguimiento",
                fields=(
                    FieldDef(
                        key="tracker_frame_rate", env="TRACKER_FRAME_RATE",
                        label="FPS inicial de seguimiento",
                        hint="FPS inicial pasado a ByteTrack; se resincroniza en caliente con "
                             "el FPS efectivo.",
                        type="int", default=15, min=1, max=60, applies="restart_camera",
                    ),
                    FieldDef(
                        key="detection_target_fps", env="DETECTION_TARGET_FPS",
                        label="FPS objetivo de detección",
                        hint="FPS objetivo del ajuste adaptativo de detección.",
                        type="float", default=8.0, min=1, max=30, applies="restart_camera",
                    ),
                    FieldDef(
                        key="detection_min_fps", env="DETECTION_MIN_FPS",
                        label="FPS mínimo de detección",
                        hint="FPS mínimo permitido por el ajuste adaptativo.",
                        type="float", default=3.0, min=1, max=30, applies="restart_camera",
                    ),
                    FieldDef(
                        key="detection_max_fps", env="DETECTION_MAX_FPS",
                        label="FPS máximo de detección",
                        hint="FPS máximo permitido por el ajuste adaptativo.",
                        type="float", default=12.0, min=1, max=30, applies="restart_camera",
                    ),
                    FieldDef(
                        key="recognition_target_fps", env="RECOGNITION_TARGET_FPS",
                        label="FPS objetivo de reconocimiento",
                        hint="FPS objetivo del ajuste adaptativo de reconocimiento facial.",
                        type="float", default=2.0, min=0.5, max=10, applies="restart_camera",
                    ),
                    FieldDef(
                        key="housekeeping_secs", env="HOUSEKEEPING_SECS",
                        label="Intervalo de limpieza de tracks (s)",
                        hint="Intervalo de limpieza periódica de tracks y reconocedor por cámara.",
                        type="float", default=60.0, min=1, max=3600, applies="restart_camera",
                    ),
                    FieldDef(
                        key="cpu_budget_warn_pct", env="CPU_BUDGET_WARN_PCT",
                        label="Umbral de aviso de CPU (%)",
                        hint="% de un core equivalente, sumado entre todas las cámaras, a partir "
                             "del cual la interfaz avisa de coste de CPU excesivo (estimación, no "
                             "medición real del sistema operativo).",
                        type="float", default=200.0, min=10, max=3200, applies="hot",
                    ),
                ),
            ),
            Group(
                key="comportamiento",
                label="Comportamiento",
                fields=(
                    FieldDef(
                        key="behavior_enabled", env="BEHAVIOR_ENABLED",
                        label="Detectar comportamientos",
                        hint="Activa la detección de merodeo, carrera, inmovilidad y "
                             "aglomeración.",
                        type="bool", default=True, applies="restart_camera",
                    ),
                    FieldDef(
                        key="loiter_secs", env="LOITER_SECS", label="Segundos para 'merodeo'",
                        hint="Segundos de permanencia para marcar merodeo.",
                        type="float", default=120.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="loiter_radius_px", env="LOITER_RADIUS_PX",
                        label="Radio de merodeo (px)",
                        hint="Radio en píxeles dentro del cual se considera la misma zona de "
                             "merodeo.",
                        type="float", default=80.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="loiter_require_zone", env="LOITER_REQUIRE_ZONE",
                        label="Exigir zona para merodeo",
                        hint="Exige que el merodeo ocurra dentro de una zona definida.",
                        type="bool", default=False, applies="restart_camera",
                    ),
                    FieldDef(
                        key="run_speed_px_s", env="RUN_SPEED_PX_S",
                        label="Velocidad mínima de carrera (px/s)",
                        hint="Velocidad mínima en píxeles/segundo para marcar carrera.",
                        type="float", default=350.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="run_window_secs", env="RUN_WINDOW_SECS",
                        label="Ventana de cálculo de velocidad (s)",
                        hint="No puede superar 12.0 s — cota real del historial de tracking "
                             "(config.py:359-365).",
                        type="float", default=1.0, min=0.01, max=12.0,
                        applies="restart_camera",
                    ),
                    FieldDef(
                        key="immobile_secs", env="IMMOBILE_SECS",
                        label="Segundos para 'inmóvil'",
                        hint="Segundos sin moverse para marcar inmovilidad.",
                        type="float", default=60.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="immobile_radius_px", env="IMMOBILE_RADIUS_PX",
                        label="Radio de inmovilidad (px)",
                        hint="Radio en píxeles dentro del cual se considera que no hubo "
                             "movimiento.",
                        type="float", default=20.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="crowd_threshold", env="CROWD_THRESHOLD",
                        label="Personas para 'aglomeración'",
                        hint="Número de personas simultáneas para marcar aglomeración.",
                        type="int", default=5, min=1, applies="restart_camera",
                    ),
                    FieldDef(
                        key="behavior_max_tracks", env="BEHAVIOR_MAX_TRACKS",
                        label="Máximo de tracks con historial de comportamiento",
                        hint="Máximo de tracks con historial de comportamiento en memoria.",
                        type="int", default=256, min=1, applies="restart_camera",
                    ),
                ),
            ),
        ),
    ),
    Section(
        key="reconocimiento",
        label="Reconocimiento",
        groups=(
            Group(
                key="rostro",
                label="Rostro",
                fields=(
                    FieldDef(
                        key="face_min_size_px", env="FACE_MIN_SIZE_PX",
                        label="Tamaño mínimo de rostro (px)",
                        hint="Tamaño mínimo en píxeles del rostro detectado para procesarlo.",
                        type="int", default=60, min=1, max=1000, applies="restart_camera",
                    ),
                    FieldDef(
                        key="face_max_blur", env="FACE_MAX_BLUR",
                        label="Desenfoque máximo admitido",
                        hint="Desenfoque máximo admitido antes de descartar el rostro.",
                        type="float", default=100.0, min=0, max=1000, applies="restart_camera",
                    ),
                    FieldDef(
                        key="face_max_yaw_deg", env="FACE_MAX_YAW_DEG",
                        label="Ángulo de perfil máximo (°)",
                        hint="Ángulo de perfil máximo admitido antes de descartar el rostro.",
                        type="float", default=40.0, min=0, max=90, applies="restart_camera",
                    ),
                    FieldDef(
                        key="face_match_threshold", env="FACE_MATCH_THRESHOLD",
                        label="Umbral de coincidencia facial",
                        hint="Umbral de similitud para considerar coincidencia facial.",
                        type="float", default=0.45, min=0.01, max=1.0, applies="restart_camera",
                    ),
                    FieldDef(
                        key="face_confirm_threshold", env="FACE_CONFIRM_THRESHOLD",
                        label="Umbral de confirmación facial",
                        hint="Umbral de similitud para confirmar identidad facial.",
                        type="float", default=0.55, min=0.01, max=1.0, applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="identidad",
                label="Identidad temporal",
                fields=(
                    FieldDef(
                        key="identity_vote_window", env="IDENTITY_VOTE_WINDOW",
                        label="Ventana de votación (frames)",
                        hint="Debe ser >= votos mínimos para confirmar (config.py:313-318).",
                        type="int", default=8, min=1, applies="restart_camera",
                    ),
                    FieldDef(
                        key="identity_min_votes", env="IDENTITY_MIN_VOTES",
                        label="Votos mínimos para confirmar",
                        hint="Votos mínimos coincidentes para confirmar una identidad.",
                        type="int", default=3, min=1, applies="restart_camera",
                    ),
                    FieldDef(
                        key="identity_min_ratio", env="IDENTITY_MIN_RATIO",
                        label="Proporción mínima de votos",
                        hint="Proporción mínima de votos coincidentes sobre el total de la "
                             "ventana.",
                        type="float", default=0.6, min=0.01, max=1.0, applies="restart_camera",
                    ),
                    FieldDef(
                        key="identity_lost_ttl_secs", env="IDENTITY_LOST_TTL_SECS",
                        label="Segundos antes de dar por perdida la identidad",
                        hint="Segundos sin reconocer antes de dar la identidad por perdida.",
                        type="float", default=30.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="identity_revalidate_after_secs",
                        env="IDENTITY_REVALIDATE_AFTER_SECS",
                        label="Segundos entre revalidaciones",
                        hint="Segundos entre revalidaciones periódicas de una identidad "
                             "confirmada.",
                        type="float", default=120.0, min=0.01, applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="reid",
                label="Re-identificación",
                fields=(
                    FieldDef(
                        key="reid_enabled", env="REID_ENABLED",
                        label="Activar re-identificación",
                        hint="Activa la re-identificación por apariencia.",
                        type="bool", default=True, applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_model_path", env="REID_MODEL_PATH",
                        label="Modelo de re-identificación",
                        hint="Debe tener extensión .pt o .onnx y quedar dentro del proyecto "
                             "(validate_reid_model_path, config.py).",
                        type="str", default="models/reid/osnet_x0_25_msmt17_dyn.onnx",
                        applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_inherit_window_secs", env="REID_INHERIT_WINDOW_SECS",
                        label="Ventana de herencia (s)",
                        hint="Ventana en la que la apariencia puede heredar una identidad "
                             "perdida.",
                        type="float", default=15.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_similarity_threshold", env="REID_SIMILARITY_THRESHOLD",
                        label="Umbral de similitud",
                        hint="Umbral de similitud coseno entre embeddings de apariencia.",
                        type="float", default=0.7, min=0.01, max=1.0, applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_interval_secs", env="REID_INTERVAL_SECS",
                        label="Intervalo mínimo entre inferencias (s)",
                        hint="Intervalo mínimo entre inferencias ReID de un mismo track.",
                        type="float", default=2.0, min=0.01, applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_inherit_identity", env="REID_INHERIT_IDENTITY",
                        label="Aplicar herencia automáticamente",
                        hint="Aplica automáticamente la herencia de identidad por ReID; por "
                             "defecto solo se audita sin aplicar.",
                        type="bool", default=False, applies="restart_camera",
                    ),
                    FieldDef(
                        key="reid_max_gallery_entries", env="REID_MAX_GALLERY_ENTRIES",
                        label="Máximo de entradas en galería",
                        hint="Máximo de entradas en la galería de apariencia.",
                        type="int", default=256, min=1, applies="restart_camera",
                    ),
                ),
            ),
        ),
    ),
    Section(
        key="zonas",
        label="Zonas",
        groups=(
            Group(
                key="lineas_definidas",
                label="Líneas definidas",
                external_source="/api/v2/lines",
            ),
            Group(
                key="zonas_definidas",
                label="Zonas definidas",
                external_source="/api/v2/zones",
            ),
        ),
    ),
    Section(
        key="reglas",
        label="Reglas",
        groups=(
            Group(
                key="horario",
                label="Horario de acceso",
                fields=(
                    FieldDef(
                        key="schedule_enabled", env="SCHEDULE_ENABLED",
                        label="Aplicar horario de acceso",
                        hint="Aplica el horario de acceso a los cruces de línea; fuera de "
                             "rango se marcan como intrusión.",
                        type="bool", default=False, applies="restart_camera",
                    ),
                    FieldDef(
                        key="schedule_start", env="SCHEDULE_START", label="Hora de inicio",
                        hint="Hora de inicio del horario permitido (HH:MM, hora local).",
                        type="time", default="08:00", applies="restart_camera",
                    ),
                    FieldDef(
                        key="schedule_end", env="SCHEDULE_END", label="Hora de fin",
                        hint="Hora de fin del horario permitido (HH:MM, hora local).",
                        type="time", default="22:00", applies="restart_camera",
                    ),
                    FieldDef(
                        key="schedule_days", env="SCHEDULE_DAYS", label="Días activos",
                        hint="0=lunes … 6=domingo.",
                        type="list_int", default=[0, 1, 2, 3, 4], applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="reglas_cargadas",
                label="Reglas cargadas",
                external_source="/api/v2/rules",
            ),
        ),
    ),
    Section(
        key="alertas",
        label="Alertas",
        groups=(
            Group(
                key="canales",
                label="Canales",
                fields=(
                    FieldDef(
                        key="alert_webhook_url", env="ALERT_WEBHOOK_URL",
                        label="URL de webhook",
                        hint="URL de webhook al que se envían las alertas.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="alert_telegram_token", env="ALERT_TELEGRAM_TOKEN",
                        label="Token de bot de Telegram",
                        hint="Token del bot de Telegram usado para enviar alertas.",
                        type="secret", default="", secret=True,
                    ),
                    FieldDef(
                        key="alert_telegram_chat_id", env="ALERT_TELEGRAM_CHAT_ID",
                        label="Chat ID de Telegram",
                        hint="Chat ID de Telegram al que se envían las alertas.",
                        type="str", default="", applies="restart_server",
                    ),
                ),
            ),
            Group(
                key="disparadores",
                label="Disparadores",
                fields=(
                    FieldDef(
                        key="alert_on_intrusion", env="ALERT_ON_INTRUSION",
                        label="Avisar en intrusión",
                        hint="Avisa cuando se detecta una intrusión.",
                        type="bool", default=True, applies="restart_server",
                    ),
                    FieldDef(
                        key="alert_on_unknown", env="ALERT_ON_UNKNOWN",
                        label="Avisar en desconocido",
                        hint="Avisa cuando se detecta una persona desconocida.",
                        type="bool", default=True, applies="restart_server",
                    ),
                    FieldDef(
                        key="alert_on_detection", env="ALERT_ON_DETECTION",
                        label="Avisar en cada detección",
                        hint="Avisa en cada detección; ruidoso, desactivado por defecto.",
                        type="bool", default=False, applies="restart_server",
                    ),
                    FieldDef(
                        key="alert_cooldown_secs", env="ALERT_COOLDOWN_SECS",
                        label="Segundos entre avisos repetidos",
                        hint="Segundos mínimos entre avisos repetidos de la misma regla.",
                        type="float", default=60.0, min=0, max=3600, applies="restart_server",
                    ),
                    FieldDef(
                        key="alert_count_threshold", env="ALERT_COUNT_THRESHOLD",
                        label="Umbral de conteo (0 = desactivado)",
                        hint="Número de eventos para disparar una alerta por umbral; 0 "
                             "desactiva esta comprobación.",
                        type="int", default=0, min=0, max=1000, applies="restart_server",
                    ),
                ),
            ),
        ),
    ),
    Section(
        key="almacenamiento",
        label="Almacenamiento",
        groups=(
            Group(
                key="grabacion",
                label="Grabación",
                fields=(
                    FieldDef(
                        key="db_path", env="DB_PATH", label="Ruta de la base de datos",
                        hint="Ruta del fichero SQLite de eventos.",
                        type="str", default="data/events.db", applies="restart_server",
                    ),
                    FieldDef(
                        key="clips_dir", env="CLIPS_DIR", label="Carpeta de clips",
                        hint="Carpeta donde se guardan los clips grabados.",
                        type="str", default="data/clips", applies="restart_camera",
                    ),
                    FieldDef(
                        key="recording_fps", env="RECORDING_FPS", label="FPS de grabación",
                        hint="FPS con el que se graban los clips.",
                        type="float", default=15.0, min=1, max=30, applies="restart_camera",
                    ),
                    FieldDef(
                        key="recording_tail_secs", env="RECORDING_TAIL_SECS",
                        label="Cola tras última detección (s)",
                        hint="Segundos de grabación tras la última detección.",
                        type="float", default=5.0, min=0, max=60, applies="restart_camera",
                    ),
                    FieldDef(
                        key="recording_codec", env="RECORDING_CODEC", label="Códec de vídeo",
                        hint="mp4v es fiable en Windows; avc1 da H.264.",
                        type="enum", default="mp4v", enum_values=("mp4v", "avc1"),
                        applies="restart_camera",
                    ),
                    FieldDef(
                        key="gdrive_folder_id", env="GDRIVE_FOLDER_ID",
                        label="ID de carpeta de Google Drive",
                        hint="Id de la carpeta de Google Drive donde se suben los clips.",
                        type="str", default="1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir",
                        applies="restart_server",
                    ),
                    FieldDef(
                        key="gdrive_credentials_path", env="GDRIVE_CREDENTIALS_PATH",
                        label="Credenciales de Google Drive",
                        hint="Ruta al fichero de credenciales de la API de Google Drive.",
                        type="secret", default="credentials.json", secret=True,
                    ),
                    FieldDef(
                        key="gdrive_token_path", env="GDRIVE_TOKEN_PATH",
                        label="Token de Google Drive",
                        hint="Ruta al token OAuth de Google Drive.",
                        type="secret", default="data/token.json", secret=True,
                    ),
                    FieldDef(
                        key="max_upload_attempts", env="MAX_UPLOAD_ATTEMPTS",
                        label="Intentos máximos de subida",
                        hint="Intentos máximos de subida de un clip antes de desistir.",
                        type="int", default=5, min=1, max=20, applies="restart_server",
                    ),
                    FieldDef(
                        key="upload_poll_secs", env="UPLOAD_POLL_SECS",
                        label="Intervalo de sondeo de subida (s)",
                        hint="Intervalo de sondeo de la cola de subida a Drive.",
                        type="float", default=30.0, min=1, max=300, applies="restart_server",
                    ),
                ),
            ),
            Group(
                key="buffer",
                label="Buffer",
                fields=(
                    FieldDef(
                        key="pre_buffer_secs", env="PRE_BUFFER_SECS",
                        label="Segundos de pre-buffer",
                        hint="Segundos de vídeo previos a la detección incluidos en el clip.",
                        type="float", default=10.0, min=0, max=60, applies="restart_camera",
                    ),
                    FieldDef(
                        key="post_buffer_secs", env="POST_BUFFER_SECS",
                        label="Segundos de post-buffer",
                        hint="Segundos de vídeo posteriores a la detección incluidos en el clip.",
                        type="float", default=10.0, min=0, max=60, applies="restart_camera",
                    ),
                    FieldDef(
                        key="pre_buffer_max_mb", env="PRE_BUFFER_MAX_MB",
                        label="Tamaño máximo del pre-buffer (MB)",
                        hint="Tamaño máximo en memoria del pre-buffer antes de descartar "
                             "frames antiguos.",
                        type="int", default=48, min=1, max=512, applies="restart_camera",
                    ),
                    FieldDef(
                        key="pre_buffer_jpeg_quality", env="PRE_BUFFER_JPEG_QUALITY",
                        label="Calidad JPEG del pre-buffer",
                        hint="Calidad JPEG usada para los frames del pre-buffer.",
                        type="int", default=85, min=1, max=100, applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="retencion",
                label="Retención",
                fields=(
                    FieldDef(
                        key="local_retention_days", env="LOCAL_RETENTION_DAYS",
                        label="Retención local de clips (días)",
                        hint="Días que se conservan los clips localmente antes de purgarlos.",
                        type="int", default=7, min=0, max=3650, applies="restart_server",
                    ),
                    FieldDef(
                        key="events_retention_days", env="EVENTS_RETENTION_DAYS",
                        label="Retención de eventos (días, 0=desactivado)",
                        hint="Días que se conservan los eventos en BD; 0 desactiva la purga.",
                        type="int", default=30, min=0, max=3650, applies="restart_server",
                    ),
                    FieldDef(
                        key="recordings_retention_days", env="RECORDINGS_RETENTION_DAYS",
                        label="Retención de grabaciones (días, 0=desactivado)",
                        hint="Días que se conservan los registros de grabaciones; 0 desactiva "
                             "la purga.",
                        type="int", default=30, min=0, max=3650, applies="restart_server",
                    ),
                    FieldDef(
                        key="persons_retention_days", env="PERSONS_RETENTION_DAYS",
                        label="Retención de personas anónimas (días)",
                        hint="Días que se conservan las personas anónimas sin nombre antes de "
                             "borrarlas.",
                        type="int", default=30, min=0, max=3650, applies="restart_server",
                    ),
                    FieldDef(
                        key="upload_min_severity", env="UPLOAD_MIN_SEVERITY",
                        label="Subir clips a Drive desde severidad",
                        hint="Severidad mínima del evento para subir su clip a Google Drive.",
                        type="enum", default="warning",
                        enum_values=("info", "warning", "critical"), applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="capturas",
                label="Capturas",
                fields=(
                    FieldDef(
                        key="gallery_dir", env="GALLERY_DIR",
                        label="Carpeta de galería de rostros",
                        hint="Carpeta donde se guardan los recortes de rostro de la galería.",
                        type="str", default="data/gallery", applies="restart_camera",
                    ),
                    FieldDef(
                        key="gallery_throttle_secs", env="GALLERY_THROTTLE_SECS",
                        label="Intervalo entre capturas de galería (s)",
                        hint="Intervalo mínimo entre capturas de galería de la misma persona.",
                        type="float", default=30.0, min=0, max=3600, applies="restart_camera",
                    ),
                    FieldDef(
                        key="snapshot_enabled", env="SNAPSHOT_ENABLED",
                        label="Guardar snapshot de evento",
                        hint="Guarda una miniatura del evento al detectarlo.",
                        type="bool", default=True, applies="restart_camera",
                    ),
                    FieldDef(
                        key="snapshot_dir", env="SNAPSHOT_DIR", label="Carpeta de snapshots",
                        hint="Debe quedar dentro del proyecto — se sirve por StaticFiles "
                             "(validate_snapshot_dir, config.py).",
                        type="str", default="data/snapshots", applies="restart_camera",
                    ),
                    FieldDef(
                        key="snapshot_max_width", env="SNAPSHOT_MAX_WIDTH",
                        label="Ancho máximo del snapshot (px)",
                        hint="Por debajo el recorte no se reconoce y por encima deja de ser "
                             "una miniatura (config.py: [64, 1920]).",
                        type="int", default=320, min=64, max=1920, applies="restart_camera",
                    ),
                    FieldDef(
                        key="snapshot_min_interval_secs", env="SNAPSHOT_MIN_INTERVAL_SECS",
                        label="Intervalo mínimo entre snapshots (s)",
                        hint="Throttle por (camera_id, track_id) para no saturar el disco.",
                        type="float", default=5.0, min=0, max=3600, applies="restart_camera",
                    ),
                    FieldDef(
                        key="snapshot_retention_days", env="SNAPSHOT_RETENTION_DAYS",
                        label="Retención de snapshots (días, 0=sin purga)",
                        hint="Días que se conservan los snapshots; 0 desactiva la purga.",
                        type="int", default=30, min=0, max=3650, applies="restart_camera",
                    ),
                ),
            ),
            Group(
                key="metricas",
                label="Métricas",
                fields=(
                    FieldDef(
                        key="metrics_enabled", env="METRICS_ENABLED",
                        label="Activar métricas Prometheus",
                        hint="Activa la exposición de métricas Prometheus.",
                        type="bool", default=True, applies="restart_server",
                    ),
                    FieldDef(
                        key="metrics_sample_secs", env="METRICS_SAMPLE_SECS",
                        label="Intervalo de muestreo (s)",
                        hint="Intervalo de muestreo de las métricas de sistema.",
                        type="float", default=5.0, min=1, max=60, applies="restart_server",
                    ),
                ),
            ),
        ),
    ),
)


_FIELDS_BY_KEY: dict[str, FieldDef] = {}


def _rebuild_index() -> None:
    """Reconstruye el indice `_FIELDS_BY_KEY` a partir de ALL_SECTIONS.

    Se llama una vez a nivel de modulo, tras definir ALL_SECTIONS con datos.
    """
    _FIELDS_BY_KEY.clear()
    for section in ALL_SECTIONS:
        for group in section.groups:
            for f in group.fields:
                _FIELDS_BY_KEY[f.key] = f


_rebuild_index()


def all_fields() -> list[FieldDef]:
    """Aplana ALL_SECTIONS a una lista de FieldDef, para lookup por key."""
    return list(_FIELDS_BY_KEY.values())


def field_by_key(key: str) -> FieldDef | None:
    return _FIELDS_BY_KEY.get(key)


def resolve_origin(field: FieldDef, overrides: dict[str, Any], settings: Any) -> tuple[Any, str]:
    """Devuelve (valor_efectivo, origin) con origin en {"runtime","env","default"}.

    Tres vias, en este orden:
    1. runtime: la clave esta en `overrides` (app_config via ConfigRepo.get_all()).
    2. env: no esta en overrides pero el valor actual de Settings difiere del default
       declarado en el esquema (vino de una env var / .env).
    3. default: coincide con el default del esquema.

    Caso especial `camera_url`: el valor devuelto (en cualquiera de las tres vias)
    SIEMPRE pasa por `mask_rtsp_url()` antes de salir de esta funcion — nunca se
    devuelve la URL cruda. La mascara se aplica DESPUES de decidir `origin` sobre el
    valor sin enmascarar, para que enmascarar no afecte la comparacion `!=` contra el
    default (que tampoco lleva credenciales embebidas).
    """
    if field.key in overrides:
        value, origin = overrides[field.key], "runtime"
    else:
        current = getattr(settings, field.key, field.default)
        if current != field.default:
            value, origin = current, "env"
        else:
            value, origin = current, "default"

    if field.key == "camera_url":
        from backend.config import mask_rtsp_url
        value = mask_rtsp_url(value)

    return value, origin


def build_candidate_settings(settings: Any, overrides: dict[str, Any], changes: dict[str, Any]) -> Any:
    """Construye un Settings candidato = overrides + changes aplicados sobre defaults.

    Usa el CONSTRUCTOR completo (no `model_copy`): en pydantic 2.13.1 (instalado,
    verificado en esta sesion), `model_copy(update=...)` es una copia superficial que
    NO re-ejecuta los `model_validator(mode="after")` de `Settings`. El constructor
    si los re-ejecuta, lo que permite detectar invariantes cruzados (identidad, reid,
    behavior, object, snapshot — `backend/config.py:309-407`) sin reimplementarlos en
    el router (32-02, SET-03/D-10).

    Lanza `pydantic.ValidationError` si algun `model_validator` rechaza la combinacion.
    """
    from backend.config import Settings

    base = settings.model_dump()
    base.update(overrides)      # runtime ya persistido
    base.update(changes)        # cambios propuestos en este PUT
    return Settings(**base)     # constructor completo -> SI re-ejecuta field_validator y model_validator
