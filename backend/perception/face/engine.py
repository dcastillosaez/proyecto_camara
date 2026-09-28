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

    # buffalo_s ships 5 sub-models; this project only needs detection (bbox +
    # 5-point kps) and recognition (the 512d embedding). Loading genderage
    # and the dense 2d/3d landmark models too costs ~10-20x more per call
    # for outputs nothing here reads — measured empirically (23-01-SUMMARY.md
    # Task 4): ~300ms vs ~15-40ms per detect() on this CPU for the same image.
    _ALLOWED_MODULES = ["detection", "recognition"]

    def __init__(
        self,
        model_name: str = "buffalo_s",
        det_size: tuple[int, int] = (320, 320),
        providers: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self._available = False
        self._app = None
        # Fase 38 (SCALE-11/SCALE-12). providers=None => la ruta CPU de la Fase 37.
        # ctx_id se DERIVA de providers y no es parametro: con ctx_id < 0,
        # ArcFaceONNX.prepare y SCRFD.prepare hacen set_providers(['CPUExecutionProvider'])
        # y deshacen la eleccion en silencio (arcface_onnx.py:61-63, retinaface.py:133-135).
        # Pedir CUDA y olvidar el ctx_id es el bug que esta derivacion hace imposible.
        self._providers = list(providers) if providers else ["CPUExecutionProvider"]
        self.device_requested = (
            "cuda" if self._providers[0] == "CUDAExecutionProvider" else "cpu"
        )
        self.device_effective = "cpu"
        self.fallback_reason: str | None = None
        ctx_id = 0 if self.device_requested == "cuda" else -1
        if FaceAnalysis is None:
            logger.warning("insightface not installed — face recognition disabled")
            return
        try:
            self._app = FaceAnalysis(
                name=model_name, providers=self._providers,
                allowed_modules=self._ALLOWED_MODULES,
            )
            self._app.prepare(ctx_id=ctx_id, det_size=det_size)
            self._available = True
            effective = self._effective_provider()
            self.device_effective = (
                "cuda" if effective == "CUDAExecutionProvider" else "cpu"
            )
            if self.device_effective != self.device_requested:
                self.fallback_reason = (
                    f"insightface quedo en {effective}: pedido={self._providers[0]}"
                )
                logger.warning("FaceEngine: %s", self.fallback_reason)
        except Exception:
            logger.exception("FaceEngine: failed to load %s", model_name)

    def _effective_provider(self) -> str:
        """Provider realmente activo en el sub-modelo de reconocimiento.

        ONNXRuntime no lanza cuando descarta un provider (38-RESEARCH.md Q2): leerlo
        de la sesion es la unica forma fiable de saber donde quedo el motor.
        """
        try:
            model = self._app.models.get("recognition") or self._app.models.get("detection")
            return model.session.get_providers()[0]
        except Exception:
            return "CPUExecutionProvider"

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
