"""Tests for backend.config — validators, URL building, and masking."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import Settings, build_rtsp_url, mask_rtsp_url


# ---------------------------------------------------------------------------
# yolo_model_path validator
# ---------------------------------------------------------------------------

def test_valid_pt_extension_accepted():
    """A .pt path inside the project directory is accepted."""
    s = Settings(yolo_model_path="yolov8n.pt")
    assert s.yolo_model_path == "yolov8n.pt"


def test_non_pt_extension_rejected():
    """A model path not ending in .pt raises ValidationError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="model.onnx")


def test_non_pt_extension_onnx_rejected():
    """An .onnx path is rejected even if it contains .pt elsewhere in name."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="yolov8n.pt.onnx")


def test_path_traversal_rejected():
    """A path with ../ traversal is rejected."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(yolo_model_path="../../etc/passwd.pt")


# ---------------------------------------------------------------------------
# build_rtsp_url
# ---------------------------------------------------------------------------

def test_build_rtsp_url_no_credentials_returns_unchanged():
    """Returns camera_url unchanged when rtsp_user is empty."""
    s = Settings(camera_url="rtsp://192.168.1.1:554/stream1", rtsp_user="")
    assert build_rtsp_url(s) == "rtsp://192.168.1.1:554/stream1"


def test_build_rtsp_url_injects_user_and_pass():
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


def test_build_rtsp_url_preserves_path():
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

def test_mask_rtsp_url_hides_password():
    """Credentials in RTSP URL are replaced with ***:***."""
    url = "rtsp://admin:secret@192.168.1.1:554/stream1"
    masked = mask_rtsp_url(url)
    assert "secret" not in masked
    assert "admin" not in masked
    assert "***" in masked


def test_mask_rtsp_url_preserves_host_and_path():
    """Host and path are preserved after masking."""
    url = "rtsp://admin:secret@192.168.1.1:554/stream1"
    masked = mask_rtsp_url(url)
    assert "192.168.1.1" in masked
    assert "/stream1" in masked


def test_mask_rtsp_url_no_credentials_unchanged():
    """URL without credentials is returned unchanged."""
    url = "rtsp://192.168.1.1:554/stream1"
    assert mask_rtsp_url(url) == url


def test_mask_rtsp_url_round_trip_consistency():
    """mask then check — masking never crashes for valid RTSP URLs."""
    for url in [
        "rtsp://192.168.1.1:554/stream1",
        "rtsp://user:pass@10.0.0.1:554/stream2",
        "rtsp://cam:abc123@192.168.0.100/live",
    ]:
        result = mask_rtsp_url(url)
        assert isinstance(result, str)
        assert len(result) > 0
