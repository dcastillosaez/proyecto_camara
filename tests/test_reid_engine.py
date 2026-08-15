"""Tests for backend.perception.reid.engine.ReIDEngine — inferencia real con OSNet.

Dos decisiones no obvias:
(a) se usa una imagen real de skimage.data, nunca ruido aleatorio — con ruido
    el coseno entre dos embeddings independientes de OSNet sale 0,991
    (colapso fuera de distribucion, medido en el research de la Fase 25);
(b) los tests hacen pytest.skip si el modelo no esta presente, porque a
    diferencia de insightface aqui no hay autodescarga (scripts/fetch_models.py
    es un paso manual/CI, no se ejecuta en __init__).
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.perception.reid.engine import ReIDEngine

MODEL_PATH = Path("models/reid/osnet_x0_25_msmt17_dyn.onnx")


@pytest.fixture(scope="module")
def engine() -> ReIDEngine:
    if not MODEL_PATH.exists():
        pytest.skip(
            f"{MODEL_PATH} ausente — ejecutar scripts/fetch_models.py. "
            "Sin autodescarga (a diferencia de insightface), skip, nunca fallo."
        )
    e = ReIDEngine(str(MODEL_PATH))
    if not e.available:
        pytest.skip("ReIDEngine no disponible con el modelo presente")
    return e


@pytest.fixture(scope="module")
def person_crop_bgr() -> np.ndarray:
    import skimage.data as data
    return cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)


def TEST_reid_embedding_is_512d_l2_normalized(engine, person_crop_bgr):
    """Criterio 1 (forma): embed() devuelve 512D float32 con norma L2 = 1."""
    emb = engine.embed(person_crop_bgr)
    assert emb.shape == (512,)
    assert emb.dtype == np.float32
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-3


def TEST_reid_latency_under_20ms(engine, person_crop_bgr):
    """Criterio 1 (latencia). Se mide p50, no un maximo ni una sola llamada:
    el p95 medido en el research sube a ~30 ms por jitter del planificador de
    Windows en esta maquina compartida, un assert sobre una sola llamada seria
    flaky."""
    for _ in range(5):                       # warmup: la primera inferencia paga la
        engine.embed(person_crop_bgr)        # inicializacion de los kernels de ORT
    samples = []
    for _ in range(30):                      # >= 30 iteraciones
        t0 = time.perf_counter()
        engine.embed(person_crop_bgr)
        samples.append(time.perf_counter() - t0)
    p50 = statistics.median(samples)
    assert p50 < 0.020, (
        f"criterio 1: p50 de embed() = {p50 * 1000:.2f} ms, se exige < 20 ms "
        f"(medido en el research: 5,50 ms; 84,5 ms si el eje batch sigue fijo a 16)"
    )


def TEST_reid_engine_degrades_gracefully():
    """Sin modelo, available=False y embed() devuelve None, nunca lanza."""
    broken = ReIDEngine("no/such/path.onnx")
    assert broken.available is False
    assert broken.embed(np.zeros((10, 10, 3), dtype=np.uint8)) is None
    assert broken.embed(None) is None


def TEST_reid_engine_rejects_fixed_batch(monkeypatch):
    """Pitfall 1: sin esta guarda, un modelo con batch fijo a 16 costaria 84,5 ms
    por inferencia en vez de 4,97 ms — el criterio 1 fallaria por 4x."""
    import backend.perception.reid.engine as engine_module

    class _FakeIO:
        def __init__(self, name, shape):
            self.name = name
            self.shape = shape

    class _FakeSession:
        def __init__(self, *a, **kw): ...
        def get_inputs(self):  return [_FakeIO("input", [16, 3, 256, 128])]
        def get_outputs(self): return [_FakeIO("output", [16, 512])]

    monkeypatch.setattr(engine_module.ort, "InferenceSession", _FakeSession)
    assert ReIDEngine("cualquier.onnx").available is False
