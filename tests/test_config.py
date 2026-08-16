"""Tests for backend.config — validators, URL building, and masking."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import Settings, build_rtsp_url, mask_rtsp_url


# ---------------------------------------------------------------------------
# yolo_model_path validator
# ---------------------------------------------------------------------------

# ─── Extensión .pt válida dentro del proyecto ─────────────────────────────────
# El validador field_validator('yolo_model_path') comprueba que la extensión
# sea .pt y que la ruta resuelta quede dentro del directorio del proyecto.
# Un nombre de modelo estándar debe pasar sin error.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_000_valid_pt_extension_accepted():
    """A .pt path inside the project directory is accepted."""
    s = Settings(yolo_model_path="yolov8n.pt")
    assert s.yolo_model_path == "yolov8n.pt"


# ─── Extensión ONNX válida dentro del proyecto (Fase 22 — SEC-16) ────────────
# La Fase 23 sustituye los embeddings dlib por ArcFace, distribuido como .onnx.
# El validador acepta .pt y .onnx desde la Fase 22, para no bloquear esa
# migración con un validador demasiado estricto.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_000b_valid_onnx_extension_accepted():
    """A .onnx path inside the project directory is accepted."""
    s = Settings(yolo_model_path="models/arcface.onnx")
    assert s.yolo_model_path == "models/arcface.onnx"


# ─── Extensión no permitida es rechazada ──────────────────────────────────────
# Solo .pt y .onnx están permitidos. Cualquier otro formato (ejecutable,
# script, etc.) no debe poder configurarse como yolo_model_path. El validador
# debe lanzar ValidationError antes de que el servidor intente cargar el
# modelo, evitando errores en runtime.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_001_disallowed_extension_rejected():
    """A model path with a non-allowed extension raises ValidationError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="model.exe")


# ─── Extensión no permitida con .pt en el nombre también es rechazada ────────
# Alguien podría intentar eludir el validador con un nombre como
# 'yolov8n.pt.exe'. Path.suffix devuelve la última extensión (.exe), así
# que el validador debe rechazarlo igualmente.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_002_disallowed_extension_with_pt_in_name_rejected():
    """A disallowed-extension path is rejected even if it contains .pt elsewhere in name."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="yolov8n.pt.exe")


# ─── Path traversal con ../ es rechazado ──────────────────────────────────────
# El validador resuelve la ruta con Path.resolve() y comprueba que quede
# dentro del directorio raíz del proyecto usando relative_to(). Una ruta
# como '../../etc/passwd.pt' saldría del proyecto y debe ser rechazada,
# previniendo lectura de archivos arbitrarios del sistema operativo.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_003_path_traversal_rejected():
    """A path with ../ traversal is rejected."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="../../etc/passwd.pt")


# ---------------------------------------------------------------------------
# build_rtsp_url
# ---------------------------------------------------------------------------

# ─── Sin credenciales: URL devuelta sin modificar ────────────────────────────
# Si RTSP_USER está vacío, build_rtsp_url devuelve camera_url tal cual.
# Inyectar credenciales vacías (':@host') rompería la autenticación RTSP
# en cámaras que no requieren usuario.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_004_build_rtsp_url_no_credentials_returns_unchanged():
    """Returns camera_url unchanged when rtsp_user is empty."""
    s = Settings(camera_url="rtsp://192.168.1.1:554/stream1", rtsp_user="")
    assert build_rtsp_url(s) == "rtsp://192.168.1.1:554/stream1"


# ─── Credenciales inyectadas correctamente en el netloc ──────────────────────
# Cuando RTSP_USER y RTSP_PASS están configurados, build_rtsp_url construye
# la URL con formato 'rtsp://user:pass@host:port/path'. Esto permite separar
# las credenciales de la URL base en el .env sin exponerlas en logs.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_005_build_rtsp_url_injects_user_and_pass():
    """Injects user:pass into the netloc when rtsp_user is set."""
    s = Settings(
        camera_url="rtsp://192.168.1.1:554/stream1",
        rtsp_user="admin",
        rtsp_pass="secret",
    )
    url = build_rtsp_url(s)
    assert "admin:secret@" in url
    assert "192.168.1.1" in url
    assert "554" in url


# ─── El path del stream se preserva tras inyectar credenciales ───────────────
# La cámara Tapo C212 usa /stream1 (alta resolución) y /stream2 (720p).
# urlparse + urlunparse debe preservar el path; si se perdiera, OpenCV
# no podría conectar al stream correcto.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_006_build_rtsp_url_preserves_path():
    """Path component (/stream1) is preserved after credential injection."""
    s = Settings(
        camera_url="rtsp://192.168.1.1:554/stream1",
        rtsp_user="user",
        rtsp_pass="pass",
    )
    url = build_rtsp_url(s)
    assert url.endswith("/stream1")


# ---------------------------------------------------------------------------
# mask_rtsp_url
# ---------------------------------------------------------------------------

# ─── Credenciales reemplazadas por *** en el log ─────────────────────────────
# mask_rtsp_url se usa en los mensajes de log del servidor para no exponer
# usuario y contraseña en texto plano en uvicorn_startup.log ni en diag.log.
# La contraseña y el usuario no deben aparecer en la URL enmascarada.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_007_mask_rtsp_url_hides_password():
    """Credentials in RTSP URL are replaced with ***:***."""
    url = "rtsp://admin:secret@192.168.1.1:554/stream1"
    masked = mask_rtsp_url(url)
    assert "secret" not in masked
    assert "admin" not in masked
    assert "***" in masked


# ─── Host y path se preservan después del enmascaramiento ────────────────────
# El log debe seguir siendo útil para depuración: el operador necesita ver
# a qué IP y stream se está conectando aunque no vea las credenciales.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_008_mask_rtsp_url_preserves_host_and_path():
    """Host and path are preserved after masking."""
    url = "rtsp://admin:secret@192.168.1.1:554/stream1"
    masked = mask_rtsp_url(url)
    assert "192.168.1.1" in masked
    assert "/stream1" in masked


# ─── URL sin credenciales se devuelve igual ──────────────────────────────────
# Si la URL base no tiene usuario embebido, mask_rtsp_url no debe alterar
# nada (no añadir @, no truncar el host, no modificar el puerto).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_009_mask_rtsp_url_no_credentials_unchanged():
    """URL without credentials is returned unchanged."""
    url = "rtsp://192.168.1.1:554/stream1"
    assert mask_rtsp_url(url) == url


# ─── Robustez: no lanza excepción para URLs RTSP válidas ─────────────────────
# mask_rtsp_url puede recibir URLs con distinto formato (con/sin puerto,
# con/sin path). Ninguna URL válida debe causar una excepción; el resultado
# debe ser siempre un string no vacío.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_010_mask_rtsp_url_round_trip_consistency():
    """mask then check — masking never crashes for valid RTSP URLs."""
    for url in [
        "rtsp://192.168.1.1:554/stream1",
        "rtsp://user:pass@10.0.0.1:554/stream2",
        "rtsp://cam:abc123@192.168.0.100/live",
    ]:
        result = mask_rtsp_url(url)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Identidad temporal (Fase 24 — FACE-07..FACE-11)
# ---------------------------------------------------------------------------

# ─── Defaults de SPEC_v2.md §5.5 ──────────────────────────────────────────────
# Los 5 parámetros de la fase deben tener exactamente los defaults documentados
# en el SPEC para que TemporalVoter/IdentityStateMachine se comporten como se
# especificó sin necesidad de configuración explícita.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_defaults_match_spec():
    """Settings() expone los 5 parámetros de identidad con los defaults del SPEC."""
    s = Settings()
    assert s.identity_vote_window == 8
    assert s.identity_min_votes == 3
    assert s.identity_min_ratio == 0.6
    assert s.identity_lost_ttl_secs == 30.0
    assert s.identity_revalidate_after_secs == 120.0


# ─── Ventana menor que el mínimo de votos es rechazada ────────────────────────
# Si identity_vote_window < identity_min_votes, la votación nunca podría
# alcanzar el mínimo requerido: es una configuración imposible que debe abortar
# el arranque en vez de dejar la FSM sin confirmar nunca (ASVS V5).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_window_smaller_than_min_votes_rejected():
    """identity_vote_window < identity_min_votes lanza ValueError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(identity_vote_window=2, identity_min_votes=3)


# ─── Ratio fuera de (0, 1] es rechazado ────────────────────────────────────────
# identity_min_ratio es una proporción sobre el total de votos: 0.0 permitiría
# que cualquier voto (incluso ninguno) ganase, y valores > 1.0 harían que
# ninguna identidad pudiera confirmarse nunca.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_ratio_out_of_range_rejected():
    """identity_min_ratio fuera de (0, 1] lanza ValueError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(identity_min_ratio=0.0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(identity_min_ratio=1.5)


# ---------------------------------------------------------------------------
# Re-identificacion por apariencia (Fase 25 — REID-01..REID-04)
# ---------------------------------------------------------------------------

# ─── Defaults de SPEC_v2.md §5.6 / ADR-04 ─────────────────────────────────────
# reid_inherit_identity=False es el fail-safe de la fase: sin decision explicita
# del operador, ReID calcula y registra pero no altera identidades. No es una
# omision del plan, es la condicion de arranque exigida por T-25-17.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_reid_defaults_match_spec():
    """Settings() expone los 7 parametros reid_* con los defaults del SPEC."""
    s = Settings()
    assert s.reid_enabled is True
    assert s.reid_model_path == "models/reid/osnet_x0_25_msmt17_dyn.onnx"
    assert s.reid_inherit_window_secs == 15.0
    assert s.reid_similarity_threshold == 0.7
    assert s.reid_interval_secs == 2.0
    assert s.reid_inherit_identity is False
    assert s.reid_max_gallery_entries == 256


# ─── Umbral de similitud fuera de (0, 1] es rechazado ──────────────────────────
# 0.0 heredaria identidad de cualquier apariencia (falso positivo garantizado,
# criterio 2) y > 1.0 no la heredaria nunca (via ReID inutil).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_reid_similarity_threshold_out_of_range_rejected():
    """reid_similarity_threshold fuera de (0, 1] lanza ValueError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_similarity_threshold=0.0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_similarity_threshold=1.5)


# ─── Parametros temporales/de cota deben ser positivos ────────────────────────
# reid_interval_secs<=0 dejaria correr ReID en cada tick (criterio 5 roto);
# reid_inherit_window_secs<=0 invalidaria toda ventana de herencia; una cota de
# galeria menor que 1 dejaria la galeria inutilizable.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_reid_time_params_must_be_positive():
    """reid_inherit_window_secs, reid_interval_secs y reid_max_gallery_entries fuera de rango lanzan."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_inherit_window_secs=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_interval_secs=-1)
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_max_gallery_entries=0)


# ─── reid_model_path: extension permitida y contencion en el proyecto (SEC-16) ─
# Misma politica que yolo_model_path: solo .pt/.onnx y nunca fuera de
# _PROJECT_ROOT, para que la variable de entorno REID_MODEL_PATH no pueda
# apuntar a un fichero arbitrario del sistema (T-25-16).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_reid_model_path_rejects_bad_extension_and_traversal():
    """Extension no permitida y traversal fuera del proyecto lanzan; una ruta valida no."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_model_path="models/reid/x.txt")
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_model_path="../../etc/passwd.onnx")
    Settings(reid_model_path="models/reid/otro.onnx")


# ─── Defaults de SPEC_v2.md §5.7 (26-CONTEXT.md § Umbrales y reglas) ──────────
# loiter_require_zone=False NO es una omision del plan: es el fallback de D-02.
# Una instalacion limpia tiene cero zonas (get_zones() lee de BD y no hay
# seed), asi que sin este fallback LOITERING no se emitiria jamas y el
# criterio 1 del ROADMAP ("con umbrales configurables") no seria verificable.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_behavior_defaults_match_spec():
    """Settings() expone los 10 parametros behavior_* con los defaults del SPEC."""
    s = Settings()
    assert s.behavior_enabled is True
    assert s.loiter_secs == 120.0
    assert s.loiter_radius_px == 80.0
    assert s.loiter_require_zone is False
    assert s.run_speed_px_s == 350.0
    assert s.run_window_secs == 1.0
    assert s.immobile_secs == 60.0
    assert s.immobile_radius_px == 20.0
    assert s.crowd_threshold == 5
    assert s.behavior_max_tracks == 256


# ─── Umbrales de comportamiento fuera de rango son rechazados ────────────────
# Todos los umbrales temporales/espaciales deben ser > 0 (un umbral <= 0 no
# tiene interpretacion fisica). crowd_threshold=0 emitiria CROWD_DETECTED con
# la escena vacia; behavior_max_tracks=0 dejaria el analisis inutilizable.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_behavior_params_must_be_positive():
    """loiter_secs, immobile_secs, loiter_radius_px, run_speed_px_s, crowd_threshold y behavior_max_tracks <= 0 lanzan."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(loiter_secs=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(immobile_secs=-1)
    with pytest.raises((ValidationError, ValueError)):
        Settings(loiter_radius_px=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(run_speed_px_s=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(crowd_threshold=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(behavior_max_tracks=0)


# ─── run_window_secs esta acotado por el historial de centroides disponible ──
# centroid_history es un deque(maxlen=150) (tracking.py:47) y el escalon mas
# alto de AdaptiveRate es 12 FPS (rate.py:26), asi que 150 muestras cubren
# 12.5 s en el peor caso. Una ventana mayor no se podria calcular jamas.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_behavior_run_window_capped_by_history():
    """run_window_secs=13.0 lanza; run_window_secs=12.0 no lanza."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(run_window_secs=13.0)
    Settings(run_window_secs=12.0)
