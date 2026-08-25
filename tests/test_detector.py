"""Tests for PersonDetector — bounding-box detection and frame annotation."""
from __future__ import annotations

import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
import supervision as sv

from backend.detector import Detection, PersonDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_yolo_box(x1: float, y1: float, x2: float, y2: float, conf: float):
    box = MagicMock()
    box.xyxy = [np.array([x1, y1, x2, y2], dtype=np.float32)]
    box.conf = [np.float32(conf)]
    return box


def _make_yolo_result(boxes):
    r = MagicMock()
    r.boxes = boxes
    return r


@pytest.fixture
def detector():
    """PersonDetector with a mocked YOLO backend (no weights loaded)."""
    with patch("backend.detector.YOLO") as MockYOLO:
        d = PersonDetector(model_path="yolov8n.pt", confidence=0.45)
        d._mock_model = MockYOLO.return_value
        yield d


@pytest.fixture
def blank_frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

# ─── Contrato: lista vacía sin detecciones ───────────────────────────────────
# Cuando el modelo YOLO no encuentra ningún objeto en el frame (r.boxes = []),
# detect() debe devolver [] en lugar de None o lanzar excepción.
# El mock devuelve un resultado vacío para aislar este comportamiento.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_030_detect_empty_when_no_boxes(detector, blank_frame):
    """detect() returns [] when the model produces no boxes."""
    detector._mock_model.return_value = [_make_yolo_result([])]
    assert detector.detect(blank_frame) == []


# ─── Conversión correcta de box YOLO a dataclass Detection ──────────────────
# detect() debe mapear xyxy (float32) a enteros y preservar la confianza.
# Se verifica que x1/y1/x2/y2 y confidence coinciden exactamente con los
# valores del mock (dentro de tolerancia float).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_031_detect_returns_detection_objects(detector, blank_frame):
    """detect() converts YOLO boxes to Detection dataclass instances."""
    box = _make_yolo_box(10.0, 20.0, 100.0, 200.0, 0.9)
    detector._mock_model.return_value = [_make_yolo_result([box])]
    result = detector.detect(blank_frame)
    assert len(result) == 1
    d = result[0]
    assert isinstance(d, Detection)
    assert (d.x1, d.y1, d.x2, d.y2) == (10, 20, 100, 200)
    assert abs(d.confidence - 0.9) < 1e-4


# ─── Múltiples detecciones en el mismo frame ─────────────────────────────────
# detect() itera sobre todos los boxes del resultado YOLO.
# Este test asegura que no se descarta ninguna detección cuando hay varias
# personas en escena simultáneamente.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_032_detect_multiple_boxes(detector, blank_frame):
    """detect() handles multiple boxes in one frame."""
    boxes = [_make_yolo_box(0, 0, 50, 50, 0.8), _make_yolo_box(60, 60, 120, 120, 0.7)]
    detector._mock_model.return_value = [_make_yolo_result(boxes)]
    assert len(detector.detect(blank_frame)) == 2


# ─── Parámetros transmitidos al modelo YOLO ──────────────────────────────────
# detect() debe reenviar al modelo: conf (umbral mínimo configurado),
# classes (lista de clases COCO a detectar, por defecto [0]=persona) y
# verbose=False para no contaminar los logs del servidor.
# Se comprueba mediante call_args después de la llamada.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_033_detect_passes_confidence_and_classes_to_model(detector, blank_frame):
    """detect() forwards configured confidence and classes to the YOLO call."""
    detector._mock_model.return_value = [_make_yolo_result([])]
    detector.detect(blank_frame)
    _, kwargs = detector._mock_model.call_args
    assert kwargs["conf"] == 0.45
    assert kwargs["classes"] == [0]
    assert kwargs["verbose"] is False


# ---------------------------------------------------------------------------
# detect_sv()
# ---------------------------------------------------------------------------

# ─── Integración con supervision: tipo de retorno ────────────────────────────
# detect_sv() alimenta el pipeline ByteTrack+LineZone de supervision.
# Debe devolver sv.Detections (no una lista de Detection) y delegar la
# conversión a sv.Detections.from_ultralytics con el resultado de YOLO[0].
# ─────────────────────────────────────────────────────────────────────────────
def TEST_034_detect_sv_returns_supervision_detections(detector, blank_frame):
    """detect_sv() returns a supervision.Detections object."""
    mock_result = MagicMock()
    detector._mock_model.return_value = [mock_result]
    with patch("backend.detector.sv.Detections.from_ultralytics", return_value=sv.Detections.empty()) as mock_from:
        result = detector.detect_sv(blank_frame)
    mock_from.assert_called_once_with(mock_result)
    assert isinstance(result, sv.Detections)


# ─── Coherencia de parámetros entre detect() y detect_sv() ──────────────────
# Ambos métodos deben usar el mismo umbral de confianza y verbose=False.
# Un valor distinto causaría que el pipeline de tracking detecte más/menos
# personas que el fallback de la fase 3.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_035_detect_sv_passes_correct_kwargs(detector, blank_frame):
    """detect_sv() uses the same confidence/classes as detect()."""
    mock_result = MagicMock()
    detector._mock_model.return_value = [mock_result]
    with patch("backend.detector.sv.Detections.from_ultralytics", return_value=sv.Detections.empty()):
        detector.detect_sv(blank_frame)
    _, kwargs = detector._mock_model.call_args
    assert kwargs["conf"] == 0.45
    assert kwargs["verbose"] is False


# ---------------------------------------------------------------------------
# annotate()
# ---------------------------------------------------------------------------

# ─── Inmutabilidad del frame original ────────────────────────────────────────
# annotate() trabaja sobre frame.copy() internamente. Si modificara el array
# original (in-place), el frame almacenado en RTSPStream._frame se corrompería
# en cada ciclo de detección, causando artefactos visuales acumulativos.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_036_annotate_does_not_mutate_original(detector, blank_frame):
    """annotate() must return a copy without modifying the input frame."""
    original = blank_frame.copy()
    det = Detection(x1=10, y1=10, x2=100, y2=100, confidence=0.8)
    annotated = detector.annotate(blank_frame, [det])
    np.testing.assert_array_equal(blank_frame, original)
    assert annotated is not blank_frame


# ─── Verificación visual: el box se dibuja ───────────────────────────────────
# annotate() llama a cv2.rectangle con color verde (0,255,0).
# Un frame negro de entrada debe tener al menos un píxel no nulo
# tras la anotación, lo que confirma que el dibujo se ejecutó.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_037_annotate_draws_non_black_pixels(detector, blank_frame):
    """annotate() paints green pixels where the bounding box is drawn."""
    det = Detection(x1=50, y1=50, x2=200, y2=200, confidence=0.75)
    annotated = detector.annotate(blank_frame, [det])
    assert annotated.max() > 0


# ─── Sin detecciones: copia pixel-perfect ────────────────────────────────────
# Con lista de detecciones vacía, annotate() no debe modificar ningún píxel.
# El frame de salida debe ser idéntico al de entrada (pero objeto distinto).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_038_annotate_empty_detections_returns_equal_copy(detector, blank_frame):
    """annotate() with no detections returns an unchanged copy."""
    annotated = detector.annotate(blank_frame, [])
    np.testing.assert_array_equal(annotated, blank_frame)


# ─── Preservación de dimensiones del frame ───────────────────────────────────
# annotate() no debe redimensionar ni recortar el frame.
# Cambiar shape rompería el encoder MJPEG y el VideoWriter del grabador.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_039_annotate_preserves_frame_shape(detector, blank_frame):
    """annotate() preserves input dimensions."""
    det = Detection(x1=0, y1=0, x2=100, y2=100, confidence=0.5)
    annotated = detector.annotate(blank_frame, [det])
    assert annotated.shape == blank_frame.shape


# ---------------------------------------------------------------------------
# set_classes()
# ---------------------------------------------------------------------------

# ─── Mutacion en caliente: sin recarga de modelo ─────────────────────────────
# set_classes() debe cambiar las clases que se pasan a la siguiente inferencia
# sin reconstruir self._model (27-RESEARCH.md Q3: id(self._model) no cambia).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_set_classes_changes_next_inference(detector, blank_frame):
    """set_classes([0, 24]) cambia las clases de detect_sv() sin recargar el modelo."""
    model_before = detector._model
    detector.set_classes([0, 24])
    mock_result = MagicMock()
    detector._mock_model.return_value = [mock_result]
    with patch("backend.detector.sv.Detections.from_ultralytics", return_value=sv.Detections.empty()):
        detector.detect_sv(blank_frame)
    _, kwargs = detector._mock_model.call_args
    assert kwargs["classes"] == [0, 24]
    assert detector._model is model_before


# ---------------------------------------------------------------------------
# Criterio 6 del ROADMAP (Fase 27): latencia con multiples clases activas
# ---------------------------------------------------------------------------

_BUS_JPG = Path("F:/Documentos/IA/Proyecto_Camara/.venv/Lib/site-packages/ultralytics/assets/bus.jpg")


@pytest.fixture(scope="module")
def real_detector() -> PersonDetector:
    if not _BUS_JPG.exists():
        pytest.skip(f"{_BUS_JPG} ausente — no se puede medir latencia real")
    return PersonDetector(model_path="yolo26n.pt", confidence=0.45)


@pytest.fixture(scope="module")
def bench_frame() -> np.ndarray:
    img = cv2.imread(str(_BUS_JPG))
    if img is None:
        pytest.skip(f"{_BUS_JPG} no se pudo leer con cv2.imread")
    return cv2.resize(img, (1280, 720))


@pytest.mark.perf
def TEST_multiclass_latency_under_15_percent(real_detector, bench_frame):
    """Criterio 6: activar las 6 clases del ROADMAP no puede subir la latencia de
    inferencia mas de un 15 %. Se mide el p50, no un maximo ni una sola llamada: el
    jitter del planificador de Windows en esta maquina compartida haria flaky un assert
    sobre una muestra (misma metodologia que TEST_reid_latency_under_20ms).

    Medido en 27-RESEARCH.md Q8 con yolo26n.pt sobre bus.jpg a 1280x720: 38,90 ms con 1
    clase y 40,74 ms con 6 (+4,7 %, margen 3x sobre el criterio). El coste marginal es
    practicamente cero porque `classes=` es un filtro de post-proceso dentro de la NMS
    (predict.py:54-58) y yolo26n es NMS-free.
    """
    def _measure(classes: list[int]) -> float:
        real_detector.set_classes(classes)
        for _ in range(5):
            real_detector.detect_sv(bench_frame)
        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            real_detector.detect_sv(bench_frame)
            samples.append(time.perf_counter() - t0)
        return statistics.median(samples)

    p50_1 = _measure([0])
    p50_6 = _measure([0, 1, 2, 3, 24, 28])
    assert p50_6 < 1.15 * p50_1, (
        f"criterio 6: p50 con 6 clases = {p50_6 * 1000:.2f} ms, con 1 clase = "
        f"{p50_1 * 1000:.2f} ms, se exige < 15% de subida "
        f"(medido en el research: 38,90 ms con 1 clase, 40,74 ms con 6)"
    )
