"""CameraPipeline / CameraManager — arma y supervisa los workers de cada camara.

CameraPipeline es la fachada que sustituye a RTSPStream: la capa web habla
con ella y no conoce a los workers individuales. Disenado para N camaras
desde el principio (SPEC_v2.md), aunque en el bloque A solo se instancia
con una ("cam1").
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from backend.pipeline.broker import FrameBroker
from backend.pipeline.capture import CaptureHealth, CaptureWorker
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.recognition import RecognitionWorker
from backend.pipeline.recording import RecordingWorker
from backend.pipeline.streaming import StreamingWorker
from backend.pipeline.supervisor import WorkerSupervisor
from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.recognizer import PersonRecognizer
    from backend.tracker import PersonTracker

logger = logging.getLogger(__name__)


class CameraPipeline:
    """Broker + workers + supervisor de UNA camara, con la fachada que consume la API."""

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        process_size: tuple[int, int] | None = None,
        detector: PersonDetector | None = None,
        tracker: PersonTracker | None = None,
        recognizer: PersonRecognizer | None = None,
        event_engine: EventEngine | None = None,
        is_intrusion: Callable[[], bool] | None = None,
        recording_config: dict[str, Any] | None = None,
        on_identified: Callable[[np.ndarray, int], None] | None = None,
        detection_fps: tuple[float, float, float] = (8.0, 3.0, 12.0),
        recognition_fps: float = 2.0,
        supervisor_interval: float = 5.0,
    ) -> None:
        self.camera_id = camera_id
        self.broker = FrameBroker()
        self.registry = TrackRegistry()
        self.tracker = tracker
        self.detector = detector
        self.recognizer = recognizer

        self._process_size = process_size
        self._rtsp_url = rtsp_url

        self.capture = CaptureWorker(camera_id, rtsp_url, self.broker, process_size=process_size)
        self.supervisor = WorkerSupervisor(interval=supervisor_interval)
        self.supervisor.register("capture", lambda: self.capture)

        target, lo, hi = detection_fps
        self.detection: DetectionWorker | None = None
        self.streaming: StreamingWorker | None = None
        self.recording: RecordingWorker | None = None
        self.recognition: RecognitionWorker | None = None

        if detector is not None and tracker is not None:
            def _make_detection() -> DetectionWorker:
                self.detection = DetectionWorker(
                    self.broker.subscribe("detector", replace=True),
                    detector, tracker, self.registry,
                    AdaptiveRate(target_fps=target, min_fps=lo, max_fps=hi),
                    event_engine=event_engine,
                    is_intrusion=is_intrusion,
                )
                return self.detection

            self.supervisor.register("detector", _make_detection)

            def _make_streaming() -> StreamingWorker:
                clients = self.streaming.stats["clients"] if self.streaming else 0
                self.streaming = StreamingWorker(
                    self.broker.subscribe("streaming", replace=True), self.registry, tracker
                )
                # Un reinicio no debe dejar de servir a los clientes ya conectados
                for _ in range(clients):
                    self.streaming.client_connected()
                return self.streaming

            self.supervisor.register("streaming", _make_streaming)

        if recording_config is not None:
            def _make_recording() -> RecordingWorker:
                self.recording = RecordingWorker(
                    self.broker.subscribe("recording", replace=True),
                    self.registry,
                    **recording_config,
                )
                return self.recording

            self.supervisor.register("recording", _make_recording)

        if recognizer is not None and getattr(recognizer, "available", False):
            def _make_recognition() -> RecognitionWorker:
                self.recognition = RecognitionWorker(
                    self.broker.subscribe("recognition", replace=True),
                    self.registry, recognizer,
                    AdaptiveRate(target_fps=recognition_fps,
                                 min_fps=recognition_fps, max_fps=recognition_fps),
                    on_identified=on_identified,
                )
                return self.recognition

            self.supervisor.register("recognition", _make_recognition)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.supervisor.start_all()
        logger.info("CameraPipeline %s: workers arrancados", self.camera_id)

    def stop(self) -> None:
        self.supervisor.stop_all()
        self.broker.close()
        logger.info("CameraPipeline %s: workers detenidos", self.camera_id)

    # ------------------------------------------------------------------
    # Fachada consumida por la capa web (sustituye a RTSPStream)
    # ------------------------------------------------------------------

    @property
    def health(self) -> CaptureHealth:
        return self.capture.health

    @property
    def degraded(self) -> bool:
        return self.supervisor.degraded

    def worker_status(self) -> dict[str, str]:
        return {name: st.value for name, st in self.supervisor.status().items()}

    def get_frame(self) -> np.ndarray | None:
        """Ultimo frame crudo capturado (para snapshots puntuales)."""
        frame = self.broker.latest()
        return frame.image if frame is not None else None

    def get_jpeg(self) -> bytes | None:
        return self.streaming.get_jpeg() if self.streaming else None

    def client_connected(self) -> None:
        if self.streaming:
            self.streaming.client_connected()

    def client_disconnected(self) -> None:
        if self.streaming:
            self.streaming.client_disconnected()

    def get_live_count(self) -> int:
        return len(self.registry.active_ids())

    def get_detections(self) -> list[dict]:
        return [
            {
                "x1": s.bbox[0], "y1": s.bbox[1], "x2": s.bbox[2], "y2": s.bbox[3],
                "confidence": s.confidence,
            }
            for s in self.registry.snapshot().values()
        ]

    def get_counts(self) -> dict[str, int]:
        if self.tracker is None:
            return {"in": 0, "out": 0, "total": 0}
        return self.tracker.get_counts()

    def get_fps(self) -> float:
        """FPS de captura (el ritmo al que se sirve el video)."""
        return self.capture.health.fps

    def get_detection_fps(self) -> float:
        """FPS efectivo de inferencia — deliberadamente distinto del de captura."""
        if self.detection is None:
            return 0.0
        return float(self.detection.stats.get("effective_fps", 0.0))

    def set_zones(self, zones: list[dict]) -> None:
        if self.detection:
            self.detection.set_zones(zones)

    def get_zone_stats(self) -> list[dict]:
        return self.detection.get_zone_stats() if self.detection else []

    def get_heatmap(self) -> np.ndarray | None:
        frame = self.get_frame()
        if frame is None or self.detection is None:
            return None
        return self.detection.compose_heatmap(frame)

    def get_native_resolution(self) -> tuple[int, int]:
        return self.capture.health.native_resolution or (0, 0)

    def get_process_size(self) -> tuple[int, int]:
        return self._process_size or (0, 0)

    def set_process_size(self, w: int, h: int) -> None:
        """Cambia la resolucion de proceso reiniciando el CaptureWorker."""
        self._process_size = (w, h) if (w > 0 and h > 0) else None
        self.capture.stop()
        self.capture = CaptureWorker(
            self.camera_id, self._rtsp_url, self.broker, process_size=self._process_size
        )
        self.capture.start()

    def stats(self) -> dict:
        out: dict[str, Any] = {
            "workers": self.worker_status(),
            "degraded": self.degraded,
            "broker": self.broker.stats(),
        }
        if self.detection:
            out["detection"] = self.detection.stats
        if self.streaming:
            out["streaming"] = self.streaming.stats
        if self.recognition:
            out["recognition"] = self.recognition.stats
        return out


class CameraManager:
    """Gestiona N pipelines de camara."""

    def __init__(self) -> None:
        self._pipelines: dict[str, CameraPipeline] = {}

    def add(self, camera_id: str, rtsp_url: str, **kwargs) -> CameraPipeline:
        pipeline = CameraPipeline(camera_id, rtsp_url, **kwargs)
        self._pipelines[camera_id] = pipeline
        return pipeline

    def get(self, camera_id: str) -> CameraPipeline | None:
        return self._pipelines.get(camera_id)

    def all(self) -> list[CameraPipeline]:
        return list(self._pipelines.values())

    def start_all(self) -> None:
        for pipeline in self._pipelines.values():
            pipeline.start()

    def stop_all(self) -> None:
        for pipeline in self._pipelines.values():
            pipeline.stop()
