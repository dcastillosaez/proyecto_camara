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

from backend.perception.behavior import BehaviorAnalyzer
from backend.perception.face.identity import IdentityStateMachine, TemporalVoter
from backend.perception.objects import ObjectAnalyzer
from backend.perception.reid.engine import ReIDEngine
from backend.perception.reid.gallery import TrackGallery
from backend.pipeline.broker import FrameBroker
from backend.pipeline.capture import CaptureHealth, CaptureWorker
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.recognition import RecognitionWorker
from backend.pipeline.recording import RecordingWorker
from backend.pipeline.streaming import StreamingWorker
from backend.pipeline.supervisor import WorkerSupervisor
from backend.pipeline.tracking import TrackRegistry
from backend.tracker import ObjectTracker

if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.observability.latency import LatencyTracker
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
        latency_tracker: LatencyTracker | None = None,
        is_intrusion: Callable[[], bool] | None = None,
        recording_config: dict[str, Any] | None = None,
        on_identified: Callable[[np.ndarray, int], None] | None = None,
        detection_fps: tuple[float, float, float] = (8.0, 3.0, 12.0),
        recognition_fps: float = 2.0,
        supervisor_interval: float = 5.0,
        identity_vote_window: int = 8,
        identity_min_votes: int = 3,
        identity_min_ratio: float = 0.6,
        identity_lost_ttl: float = 30.0,
        identity_revalidate_after: float = 120.0,
        identity_low_confidence: float = 0.55,
        reid_enabled: bool = True,
        reid_model_path: str = "models/reid/osnet_x0_25_msmt17_dyn.onnx",
        reid_inherit_window: float = 15.0,
        reid_similarity_threshold: float = 0.7,
        reid_interval: float = 2.0,
        reid_inherit: bool = False,
        reid_max_gallery_entries: int = 256,
        behavior_enabled: bool = True,
        loiter_secs: float = 120.0,
        loiter_radius_px: float = 80.0,
        loiter_require_zone: bool = False,
        run_speed_px_s: float = 350.0,
        run_window_secs: float = 1.0,
        immobile_secs: float = 60.0,
        immobile_radius_px: float = 20.0,
        crowd_threshold: int = 5,
        behavior_max_tracks: int = 256,
        objects_enabled: bool = True,
        object_class_ids: list[int] | None = None,
        object_left_secs: float = 60.0,
        object_still_radius_px: float = 20.0,
        object_person_radius_px: float = 150.0,
        object_person_radius_ratio: float = 0.5,
        object_warmup_secs: float = 10.0,
        object_gone_secs: float = 3.0,
        object_person_window_secs: float = 10.0,
        object_max_tracks: int = 256,
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
        self.identity_fsm: IdentityStateMachine | None = None
        self.reid_engine: "ReIDEngine | None" = None
        self.reid_gallery: "TrackGallery | None" = None
        self.behavior: "BehaviorAnalyzer | None" = None
        self.objects: "ObjectAnalyzer | None" = None
        self.object_tracker: "ObjectTracker | None" = None

        if behavior_enabled:
            # El analizador vive FUERA de la factoria: WorkerSupervisor la re-ejecuta en
            # cada reinicio del DetectionWorker, y construirlo dentro borraria todas las
            # anclas y latches — una persona con 100 s de inmovilidad acumulada volveria a
            # empezar el contador y los cuatro latches se re-armarian, provocando una
            # rafaga de eventos duplicados en el frame siguiente. Mismo motivo que la FSM
            # de identidad (Fase 24) y la galeria de apariencia (Fase 25).
            self.behavior = BehaviorAnalyzer(
                loiter_secs=loiter_secs,
                loiter_radius_px=loiter_radius_px,
                loiter_require_zone=loiter_require_zone,
                run_speed_px_s=run_speed_px_s,
                run_window_secs=run_window_secs,
                immobile_secs=immobile_secs,
                immobile_radius_px=immobile_radius_px,
                crowd_threshold=crowd_threshold,
                max_tracks=behavior_max_tracks,
            )

        if objects_enabled:
            # Analizador y tracker viven FUERA de la factoria: WorkerSupervisor la
            # re-ejecuta en cada reinicio del DetectionWorker, y construirlos dentro
            # borraria las anclas, los latches, la marca de arranque y el contador de ids
            # de objeto. El agravante de esta fase respecto a la 26: reconstruirlos reabre
            # la ventana de warmup y reinicia los track_id, asi que TODO el mobiliario fijo
            # volveria a "aparecer" y a los 60 s se emitiria una rafaga de OBJECT_LEFT —
            # que es Severity.WARNING (types.py:55) y por tanto SUBE UN CLIP A GOOGLE DRIVE
            # POR CADA MUEBLE. Mismo motivo que la FSM de identidad (Fase 24), la galeria
            # de apariencia (Fase 25) y el BehaviorAnalyzer (Fase 26).
            self.object_tracker = ObjectTracker(frame_rate=int(target))
            self.objects = ObjectAnalyzer(
                left_secs=object_left_secs,
                still_radius_px=object_still_radius_px,
                person_radius_px=object_person_radius_px,
                person_radius_ratio=object_person_radius_ratio,
                warmup_secs=object_warmup_secs,
                gone_secs=object_gone_secs,
                person_window_secs=object_person_window_secs,
                max_tracks=object_max_tracks,
            )

        if detector is not None and tracker is not None:
            def _make_detection() -> DetectionWorker:
                self.detection = DetectionWorker(
                    self.broker.subscribe("detector", replace=True),
                    detector, tracker, self.registry,
                    AdaptiveRate(target_fps=target, min_fps=lo, max_fps=hi),
                    event_engine=event_engine,
                    is_intrusion=is_intrusion,
                    camera_id=camera_id,
                    latency_tracker=latency_tracker,
                    behavior=self.behavior,
                    objects=self.objects,
                    object_tracker=self.object_tracker,
                    object_class_ids=set(object_class_ids or []),
                )
                return self.detection

            self.supervisor.register("detector", _make_detection)

            def _make_streaming() -> StreamingWorker:
                clients = self.streaming.stats["clients"] if self.streaming else 0
                self.streaming = StreamingWorker(
                    self.broker.subscribe("streaming", replace=True), self.registry, tracker,
                    object_boxes=self.get_object_boxes,  # NUEVO (Fase 27): solo lectura
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
            # La FSM vive FUERA de la factoria: WorkerSupervisor la re-ejecuta en cada
            # reinicio del worker, y construirla dentro perderia toda la identidad ya
            # confirmada. Mismo motivo por el que _make_streaming rescata `clients`.
            self.identity_fsm = IdentityStateMachine(
                TemporalVoter(
                    window=identity_vote_window,
                    min_votes=identity_min_votes,
                    min_ratio=identity_min_ratio,
                ),
                lost_ttl=identity_lost_ttl,
                revalidate_after=identity_revalidate_after,
                low_confidence=identity_low_confidence,
            )

            if reid_enabled:
                # Motor y galeria viven FUERA de la factoria por el mismo motivo que
                # la FSM: el WorkerSupervisor re-ejecuta la factoria en cada reinicio
                # del worker, y construirlos dentro vaciaria la galeria de apariencia
                # (perdiendo la continuidad de identidad justo tras un reinicio) y
                # recargaria el ONNX cada vez.
                self.reid_engine = ReIDEngine(reid_model_path)
                self.reid_gallery = TrackGallery(
                    inherit_window=reid_inherit_window,
                    similarity_threshold=reid_similarity_threshold,
                    interval=reid_interval,
                    max_entries=reid_max_gallery_entries,
                )

            def _make_recognition() -> RecognitionWorker:
                self.recognition = RecognitionWorker(
                    self.broker.subscribe("recognition", replace=True),
                    self.registry, recognizer,
                    AdaptiveRate(target_fps=recognition_fps,
                                 min_fps=recognition_fps, max_fps=recognition_fps),
                    identity_fsm=self.identity_fsm,
                    event_engine=event_engine,
                    on_identified=on_identified,
                    reid_engine=self.reid_engine,
                    reid_gallery=self.reid_gallery,
                    reid_inherit=reid_inherit,
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

    def set_detection_classes(self, classes: list[int]) -> None:
        """Aplica las clases activas al detector y al reparto persona/objeto.

        NO reinicia el DetectionWorker, a diferencia de set_process_size (que si reinicia
        el CaptureWorker): WorkerSupervisor._check() cuenta cualquier parada como caida y
        tres cambios de configuracion en 60 s lo marcarian FAILED de forma permanente,
        con el pipeline en modo degradado (supervisor.py:166-173). El detector lee
        self._classes en cada inferencia, asi que basta con mutarlo.
        """
        if self.detector is not None:
            self.detector.set_classes(classes)
        if self.detection is not None:
            self.detection.set_object_classes({c for c in classes if c != 0})

    def get_object_stats(self) -> list[dict]:
        return self.detection.get_object_stats() if self.detection else []

    def get_object_boxes(self) -> list[dict]:
        return self.detection.get_object_boxes() if self.detection else []

    def get_person_boxes(self) -> list[dict]:
        """Bboxes de personas normalizados 0-1, solo lectura (OPS-05, 29-RESEARCH.md Pattern 2).

        Filtra por frame_ids() (visibles en el frame actual), no por snapshot()
        completo -- de lo contrario se dibujarian boxes fantasma de tracks que
        llevan hasta 30s sin verse (TrackRegistry.prune ttl, Pitfall 2)."""
        w, h = self.get_process_size()
        if w <= 0 or h <= 0:
            w, h = self.get_native_resolution()
        if w <= 0 or h <= 0:
            return []
        visible = self.registry.frame_ids()
        out: list[dict] = []
        for tid, ts in self.registry.snapshot().items():
            if tid not in visible:
                continue
            x1, y1, x2, y2 = ts.bbox
            out.append({
                "track_id": tid,
                "bbox": [x1 / w, y1 / h, x2 / w, y2 / h],
                "identity_state": ts.identity_state.value,
                "person_name": ts.person_name,
            })
        return out

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
