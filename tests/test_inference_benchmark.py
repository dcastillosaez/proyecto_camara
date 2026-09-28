"""Arnes de medicion CPU vs CUDA para el criterio 3 de la Fase 38 (>=3x FPS).

NO cierra el criterio: este .venv tiene torch 2.11.0+cpu y un build de onnxruntime sin
CUDA EP, y la Fase 38 no instala dependencias por decision del usuario (38-CONTEXT.md).
El test queda preparado y se SALTA limpiamente; el numero real se mide el dia que se
instale el stack GPU y se anota en 38-GPU-NOTES.md. No se inventa ni se estima.

Metodologia identica a TEST_multiclass_latency_under_15_percent (test_detector.py) y a
TEST_reid_latency_under_20ms: p50 sobre N repeticiones (nunca una sola llamada, el jitter
del planificador de Windows lo haria flaky) y las dos configuraciones medidas
INTERCALADAS, para que cualquier deriva de carga de la maquina se reparta por igual entre
ambas muestras en vez de sumarse entera a la segunda.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.detector import PersonDetector
from backend.inference.device import _torch_cuda_available

_BUS_JPG = Path(
    "F:/Documentos/IA/Proyecto_Camara/.venv/Lib/site-packages/ultralytics/assets/bus.jpg"
)
_MIN_SPEEDUP = 3.0      # criterio 3 del ROADMAP
_REPS = 30
_WARMUP = 5


@pytest.fixture(scope="module")
def bench_frame() -> np.ndarray:
    if not _BUS_JPG.exists():
        pytest.skip(f"{_BUS_JPG} ausente — no se puede medir latencia real")
    img = cv2.imread(str(_BUS_JPG))
    if img is None:
        pytest.skip(f"{_BUS_JPG} ilegible")
    return cv2.resize(img, (1280, 720))


def _sample(detector: PersonDetector, frame: np.ndarray, out: list[float]) -> None:
    t0 = time.perf_counter()
    detector.detect_sv(frame)
    out.append(time.perf_counter() - t0)


@pytest.mark.perf
def TEST_cuda_detection_is_at_least_3x_faster_than_cpu(bench_frame):
    """Criterio 3 del ROADMAP. Se salta sin CUDA — nunca falla por ausencia de GPU."""
    if not _torch_cuda_available():
        pytest.skip(
            "torch sin CUDA en este entorno (torch 2.11.0+cpu). El criterio 3 de la "
            "Fase 38 queda PENDIENTE por decision de alcance, no por fallo: ver "
            ".planning/phases/38-worker-de-inferencia-en-gpu-opcional/38-GPU-NOTES.md"
        )

    # device=None es la ruta CPU intacta: a ultralytics NO se le pasa "cpu", que
    # escribiria CUDA_VISIBLE_DEVICES="" en el proceso y cegaria al detector CUDA
    # construido justo despues (38-RESEARCH.md, Pitfall 1).
    cpu = PersonDetector(model_path="yolo26n.pt", confidence=0.45, device=None)
    gpu = PersonDetector(model_path="yolo26n.pt", confidence=0.45, device="cuda:0")
    if gpu.device_effective != "cuda":
        pytest.skip(f"El detector no quedo en CUDA: {gpu.fallback_reason}")

    for _ in range(_WARMUP):
        cpu.detect_sv(bench_frame)
        gpu.detect_sv(bench_frame)

    cpu_samples: list[float] = []
    gpu_samples: list[float] = []
    for _ in range(_REPS):
        _sample(cpu, bench_frame, cpu_samples)
        _sample(gpu, bench_frame, gpu_samples)

    cpu_p50 = statistics.median(cpu_samples)
    gpu_p50 = statistics.median(gpu_samples)
    speedup = cpu_p50 / gpu_p50
    print(
        f"\nCPU p50 = {cpu_p50 * 1000:.1f} ms ({1 / cpu_p50:.1f} FPS) | "
        f"CUDA p50 = {gpu_p50 * 1000:.1f} ms ({1 / gpu_p50:.1f} FPS) | "
        f"speedup = {speedup:.2f}x"
    )
    assert speedup >= _MIN_SPEEDUP, (
        f"speedup {speedup:.2f}x por debajo del criterio 3 ({_MIN_SPEEDUP}x)"
    )


def TEST_benchmark_harness_skips_without_cuda():
    """El arnes NO debe fallar en una maquina sin GPU — solo saltarse.

    Se invoca la funcion del test directamente (no via pytest) para comprobar que la
    primera sentencia es el skip y que nunca llega a cargar un modelo.
    """
    if _torch_cuda_available():
        pytest.skip("hay CUDA en esta maquina: este test solo cubre el camino sin GPU")
    with pytest.raises(pytest.skip.Exception):
        TEST_cuda_detection_is_at_least_3x_faster_than_cpu(
            np.zeros((720, 1280, 3), dtype=np.uint8)
        )
