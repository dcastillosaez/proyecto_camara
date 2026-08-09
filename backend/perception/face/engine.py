"""FaceEngine — detection + landmark alignment + ArcFace embedding (buffalo_s).

Thin adapter over insightface.app.FaceAnalysis (SPEC_v2.md §5.4): insightface
already does detection (SCRFD), landmark alignment and ArcFace embedding in a
single FaceAnalysis.get() call — this module does not reimplement any of
that, it only translates insightface's Face objects into the project's own
FaceCandidate type and isolates the rest of the codebase from the
insightface API, same role backend/detector.py plays for ultralytics.

quality is intentionally left unset here: FaceQualityAssessor.assess() is a
separate step (backend/perception/face/quality.py) that a caller runs on the
crop + kps of a candidate that matters to it — detect() would otherwise pay
for quality assessment on every face in frame, including ones the caller
ends up ignoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.perception.face.quality import FaceQuality

try:
    from insightface.app import FaceAnalysis
except ImportError:
    FaceAnalysis = None  # noqa: N816 — degrades like backend.recognizer's face_recognition import


@dataclass
class FaceCandidate:
    bbox: tuple[int, int, int, int]
    kps: np.ndarray
    det_score: float
    quality: "FaceQuality | None" = None


class FaceEngine:
    """Detects faces and produces 512-d L2-normalized ArcFace embeddings.

    Degrades gracefully if insightface/onnxruntime aren't installed or the
    model fails to load — same contract as PersonRecognizer.available today.
    """

    def __init__(self, model_name: str = "buffalo_s", det_size: tuple[int, int] = (320, 320)) -> None:
        self._available = False
        self._app = None
        if FaceAnalysis is None:
            logger.warning("insightface not installed — face recognition disabled")
            return
        try:
            self._app = FaceAnalysis(name=model_name, providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=-1, det_size=det_size)
            self._available = True
        except Exception:
            logger.exception("FaceEngine: failed to load %s", model_name)

    @property
    def available(self) -> bool:
        return self._available

    def detect(self, frame: np.ndarray) -> list[FaceCandidate]:
        """Detect faces in a BGR frame. Empty list if none found or engine unavailable."""
        if not self._available:
            return []
        faces = self._app.get(frame)
        return [
            FaceCandidate(
                bbox=tuple(int(v) for v in f.bbox),
                kps=f.kps,
                det_score=float(f.det_score),
            )
            for f in faces
        ]

    def embed(self, frame: np.ndarray, cand: FaceCandidate | None) -> np.ndarray | None:
        """512-d L2-normalized ArcFace embedding for *cand* on *frame*.

        Calls the recognition sub-model directly (alignment via cand.kps +
        forward pass) instead of re-running full detection — verified to
        produce bit-identical output to FaceAnalysis.get()'s own embedding
        (23-CONTEXT.md) at a fraction of the cost.
        """
        if not self._available or cand is None:
            return None
        rec = self._app.models["recognition"]
        face_like = SimpleNamespace(kps=cand.kps, embedding=None)
        raw = rec.get(frame, face_like)
        return raw / np.linalg.norm(raw)
