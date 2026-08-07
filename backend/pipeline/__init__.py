"""Pipeline de video desacoplado: captura, broker y workers."""

from backend.pipeline.broker import Frame, FrameBroker, Subscription
from backend.pipeline.capture import CaptureHealth, CaptureWorker
from backend.pipeline.manager import CameraManager, CameraPipeline
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry, TrackState

__all__ = [
    "Frame",
    "FrameBroker",
    "Subscription",
    "CaptureHealth",
    "CaptureWorker",
    "CameraPipeline",
    "CameraManager",
    "AdaptiveRate",
    "TrackRegistry",
    "TrackState",
    "DetectionWorker",
]
