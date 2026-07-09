"""Object detection via a configurable YOLO model with bounding-box overlay."""

from dataclasses import dataclass

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO


@dataclass
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float


class PersonDetector:
    """Wraps a YOLO model to detect objects and annotate frames."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence: float = 0.45,
        classes: list[int] | None = None,
        label: str = "person",
        imgsz: int = 640,
    ) -> None:
        self._model = YOLO(model_path)
        self._confidence = confidence
        self._classes = classes if classes is not None else [0]
        self._label = label
        self._imgsz = imgsz

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Return bounding boxes for objects detected in *frame*."""
        results = self._model(
            frame, classes=self._classes, conf=self._confidence,
            imgsz=self._imgsz, verbose=False,
        )
        detections: list[Detection] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                detections.append(Detection(x1, y1, x2, y2, conf))
        return detections

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        """Run inference and return a supervision ``Detections`` object."""
        results = self._model(
            frame, classes=self._classes, conf=self._confidence,
            imgsz=self._imgsz, verbose=False,
        )
        return sv.Detections.from_ultralytics(results[0])

    def annotate(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """Draw green bounding boxes and confidence labels onto a copy of *frame*."""
        annotated = frame.copy()
        for det in detections:
            cv2.rectangle(annotated, (det.x1, det.y1), (det.x2, det.y2), (0, 255, 0), 2)
            label = f"{self._label} {det.confidence:.2f}"
            cv2.putText(
                annotated, label, (det.x1, det.y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
            )
        return annotated
