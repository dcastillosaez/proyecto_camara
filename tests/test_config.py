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
