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

    def set_classes(self, classes: list[int]) -> None:
        """Cambia las clases activas en caliente, sin recargar el modelo.

        detect_sv() lee self._classes en CADA inferencia (linea 54) y Ultralytics aplica
        `classes` en el post-proceso de la llamada (models/yolo/detect/predict.py:54-58),
        no en la construccion del modelo: la siguiente inferencia ya usa el valor nuevo.
        Verificado en 27-RESEARCH.md Q3 — id(self._model) no cambia.

        Se muta el atributo en vez de reconstruir el PersonDetector (o de reiniciar el
        DetectionWorker) por el mismo motivo que PersonTracker.set_frame_rate muta
        max_time_lost: reconstruir tiraria el estado. Aqui el coste seria mayor todavia
        — WorkerSupervisor._check() cuenta cualquier parada como caida y tres cambios de
        configuracion en 60 s dejarian el worker en FAILED de forma permanente
        (supervisor.py:166-173).

        Escritor: el event loop (endpoint PUT /api/v2/detection/classes). Lector: el hilo
        de deteccion. NO hace falta lock, a diferencia de set_frame_rate: el rebind es un
        unico STORE_ATTR, atomico bajo el GIL, asi que el lector ve la lista vieja o la
        nueva, nunca una a medias. La regla dura es NUNCA mutar la lista in-place
        (append/clear) — eso si seria observable a medias. En el peor caso el detector usa
        las clases viejas durante un frame (<= 333 ms a 3 FPS).
        """
        self._classes = list(classes)

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
