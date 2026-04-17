"""Person detection using YOLOv8n with bounding-box overlay."""

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
    """Wraps YOLOv8n to detect persons (class 0) and annotate frames."""

    def __init__(self, model_path: str = "yolov8n.pt", confidence: float = 0.45) -> None:
        self._model = YOLO(model_path)
        self._confidence = confidence

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Return bounding boxes for persons detected in *frame*."""
        results = self._model(frame, classes=[0], conf=self._confidence, verbose=False)
        detections: list[Detection] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                detections.append(Detection(x1, y1, x2, y2, conf))
        return detections

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        """Run inference and return a supervision ``Detections`` object.

        Used by the tracker pipeline — avoids a second inference pass by
        converting the ultralytics result directly via ``from_ultralytics``.
        """
        results = self._model(frame, classes=[0], conf=self._confidence, verbose=False)
        return sv.Detections.from_ultralytics(results[0])

    def annotate(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """Draw green bounding boxes and confidence labels onto a copy of *frame*."""
        annotated = frame.copy()
        for det in detections:
            cv2.rectangle(annotated, (det.x1, det.y1), (det.x2, det.y2), (0, 255, 0), 2)
            label = f"person {det.confidence:.2f}"
            cv2.putText(
                annotated, label, (det.x1, det.y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
            )
        return annotated
