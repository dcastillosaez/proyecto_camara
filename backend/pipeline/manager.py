"""CameraPipeline / CameraManager — agrupa broker y capture worker por camara.

Disenado para N camaras desde ahora (SPEC_v2.md), aunque en la Fase 17
solo se instancia con una sola ("cam1").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.pipeline.broker import FrameBroker
from backend.pipeline.capture import CaptureHealth, CaptureWorker


@dataclass
class CameraPipeline:
    """Agrupa el broker y el capture worker de UNA camara."""

    camera_id: str
    broker: FrameBroker
    capture: CaptureWorker

    def start(self) -> None:
        self.capture.start()

    def stop(self) -> None:
        self.capture.stop()
        self.broker.close()

    @property
    def health(self) -> CaptureHealth:
        return self.capture.health


class CameraManager:
    """Gestiona N pipelines de camara. En la Fase 17 solo se usa con una."""

    def __init__(self) -> None:
        self._pipelines: dict[str, CameraPipeline] = {}

    def add(
        self,
        camera_id: str,
        rtsp_url: str,
        process_size: tuple[int, int] | None = None,
    ) -> CameraPipeline:
        broker = FrameBroker()
        capture = CaptureWorker(camera_id, rtsp_url, broker, process_size=process_size)
        pipeline = CameraPipeline(camera_id=camera_id, broker=broker, capture=capture)
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
