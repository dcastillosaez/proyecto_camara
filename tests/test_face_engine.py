"""Tests for backend.perception.face.engine.FaceEngine — real inference on buffalo_s.

Uses skimage.data.astronaut() (Eileen Collins, NASA Great Images, public
domain, bundled with scikit-image — a transitive dependency of insightface
already installed for exactly this purpose) as the one real face fixture,
fetched at test time rather than stored as a repo asset. No synthetic/AI
-generated face is used to validate a detector trained on real faces.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.perception.face.engine import FaceCandidate, FaceEngine

pytestmark = pytest.mark.filterwarnings("ignore:.*estimate.*deprecated.*:FutureWarning")


@pytest.fixture(scope="module")
def engine() -> FaceEngine:
    return FaceEngine()


@pytest.fixture(scope="module")
def real_face_bgr() -> np.ndarray:
    import skimage.data as data
    return cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)


def TEST_engine_loads_buffalo_s(engine):
    """Instantiating FaceEngine loads buffalo_s without raising and reports availability."""
    assert engine.available is True


def TEST_detect_returns_empty_on_blank_frame(engine):
    """A frame with no face returns an empty list, not an exception."""
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    assert engine.detect(blank) == []


def TEST_detect_returns_face_candidate_with_expected_fields(engine, real_face_bgr):
    """A frame with a real face yields at least one FaceCandidate with sane fields."""
    candidates = engine.detect(real_face_bgr)
    assert len(candidates) >= 1
    cand = candidates[0]
    assert isinstance(cand, FaceCandidate)
    x1, y1, x2, y2 = cand.bbox
    assert x2 > x1 and y2 > y1
    assert cand.kps.shape == (5, 2)
    assert 0.0 <= cand.det_score <= 1.0


def TEST_embed_returns_512d_l2_normalized(engine, real_face_bgr):
    """embed() on a detected face returns a 512-d vector with unit L2 norm."""
    cand = engine.detect(real_face_bgr)[0]
    emb = engine.embed(real_face_bgr, cand)
    assert emb.shape == (512,)
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-3


def TEST_engine_unavailable_degrades_gracefully(monkeypatch):
    """If the underlying model fails to load, detect()/embed() return empty/None, never raise."""
    import backend.perception.face.engine as engine_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated model load failure")

    monkeypatch.setattr(engine_module, "FaceAnalysis", _boom)
    broken = FaceEngine()
    assert broken.available is False
    assert broken.detect(np.zeros((10, 10, 3), dtype=np.uint8)) == []
    assert broken.embed(np.zeros((10, 10, 3), dtype=np.uint8), cand=None) is None


# ---------------------------------------------------------------------------
# Fase 38 (SCALE-11/SCALE-12): providers y ctx_id en FaceEngine
# ---------------------------------------------------------------------------

def _fake_face_analysis(active: str, record: dict):
    class _Sess:
        def get_providers(self):
            return [active]

    class _Model:
        session = _Sess()

    class _FakeFA:
        def __init__(self, **kwargs):
            record["init"] = kwargs
            self.models = {"detection": _Model(), "recognition": _Model()}

        def prepare(self, **kwargs):
            record["prepare"] = kwargs

    return _FakeFA


def TEST_face_engine_device_defaults_to_cpu_providers(monkeypatch):
    import backend.perception.face.engine as engine_module

    rec: dict = {}
    monkeypatch.setattr(engine_module, "FaceAnalysis", _fake_face_analysis("CPUExecutionProvider", rec))
    eng = FaceEngine()
    assert rec["init"]["providers"] == ["CPUExecutionProvider"]
    assert rec["prepare"]["ctx_id"] == -1
    assert (eng.device_requested, eng.device_effective) == ("cpu", "cpu")
    assert eng.fallback_reason is None


def TEST_face_engine_device_cuda_sets_ctx_id_zero(monkeypatch):
    import backend.perception.face.engine as engine_module

    rec: dict = {}
    monkeypatch.setattr(engine_module, "FaceAnalysis", _fake_face_analysis("CUDAExecutionProvider", rec))
    eng = FaceEngine(providers=("CUDAExecutionProvider", "CPUExecutionProvider"))
    assert rec["init"]["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert rec["prepare"]["ctx_id"] == 0
    assert eng.device_effective == "cuda"
    assert eng.fallback_reason is None


def TEST_face_engine_device_detects_silent_cpu_fallback(monkeypatch):
    import backend.perception.face.engine as engine_module

    rec: dict = {}
    monkeypatch.setattr(engine_module, "FaceAnalysis", _fake_face_analysis("CPUExecutionProvider", rec))
    eng = FaceEngine(providers=("CUDAExecutionProvider", "CPUExecutionProvider"))
    assert eng.available is True
    assert eng.device_effective == "cpu"
    assert eng.fallback_reason
