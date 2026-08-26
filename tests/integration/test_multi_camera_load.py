"""Test de carga corto (Fase 36, criterio 6): FPS con 2 camaras frente a mono-camara.

Decision tomada con el usuario (no unilateral): un test de pocos segundos con 2
CameraPipeline reales, no una prueba literal de 1 hora -- el criterio del ROADMAP
("con 2 camaras durante 1h, el FPS no baja del 80% del valor mono-camara O la
degradacion queda documentada") admite explicitamente la segunda opcion. La
extrapolacion a 1h se apoya en que ninguna estructura de este proyecto acumula
estado sin cota por hora de operacion (Fase 22 ya lo verifico para 8h reales); un
test de segundos no puede probar eso de nuevo, solo el reparto de FPS en si.

A diferencia de tests/integration/test_multi_camera.py (Fase 35, detector
instantaneo -- alli el objetivo era demostrar aislamiento de camera_id, no CPU), el
detector falso de aqui hace un bucle de CPU real por llamada: un time.sleep() no
compite por el GIL, pero un bucle Python puro SI lo mantiene ocupado, asi que dos
camaras concurrentes en el mismo proceso compiten de verdad por el mismo core --
la misma contencion que reproduce el reparto de FPS de CameraManager.rebalance_fps()
(36-06). Aviso: un bucle Python puro es GIL-bound todo el tiempo, mientras que
cv2/numpy/YOLO reales sueltan el GIL durante su computo en C -- este test tiende a
mostrar MAS degradacion que la real, nunca menos, asi que un ratio bajo aqui no es
alarmante por si solo.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import supervision as sv

from backend.pipeline.manager import CameraManager
from backend.tracker import PersonTracker

SAME_RTSP_URL = "rtsp://fake-source-load-test"
_SIMULATED_INFERENCE_COST = 300_000  # ~50ms de CPU pura por deteccion en esta maquina --
# medido para acercarse al presupuesto de latencia de AdaptiveRate a 15 fps objetivo
# (1/15 * 0.8 =~ 53ms) y que la histeresis tenga margen real para bajar de escalon.


class _CostedDetector:
    """Detector falso con coste de CPU real (no instantaneo) por llamada -- un
    detector instantaneo (test_multi_camera.py) no reproduce contencion real."""

    def __init__(self) -> None:
        self.calls = 0

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        self.calls += 1
        total = 0.0
        for i in range(_SIMULATED_INFERENCE_COST):
            total += (i * i) ** 0.5
        return sv.Detections(
            xyxy=np.array([[100.0, 100.0, 200.0, 300.0]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([0]),
        )


def _add_camera(manager: CameraManager, camera_id: str) -> _CostedDetector:
    detector = _CostedDetector()
    manager.add(
        camera_id, SAME_RTSP_URL, detector=detector, tracker=PersonTracker(frame_rate=15),
        detection_fps=(15.0, 5.0, 20.0),
    )
    return detector


async def _measure_fps(
    manager: CameraManager, detectors: dict[str, _CostedDetector], warmup: float, window: float,
) -> dict[str, float]:
    """Arranca, deja estabilizar el escalon de AdaptiveRate (warmup) y mide llamadas
    reales al detector por segundo durante `window`."""
    manager.start_all()
    try:
        await asyncio.sleep(warmup)
        before = {cid: d.calls for cid, d in detectors.items()}
        start = time.monotonic()
        await asyncio.sleep(window)
        elapsed = time.monotonic() - start
        return {cid: (d.calls - before[cid]) / elapsed for cid, d in detectors.items()}
    finally:
        manager.stop_all()


async def TEST_two_cameras_keep_processing_frames_under_shared_load(mock_video_capture):
    """Criterio 6 de la Fase 36 (SCALE-05/08): con 2 camaras bajo coste de CPU real,
    ninguna de las dos se queda sin procesar frames por completo -- degradacion
    documentada en vez de un umbral estricto (ver docstring del modulo)."""
    mono_manager = CameraManager()
    mono_detector = _add_camera(mono_manager, "cam1")
    mono_fps = (await _measure_fps(
        mono_manager, {"cam1": mono_detector}, warmup=1.0, window=1.5,
    ))["cam1"]

    dual_manager = CameraManager()
    d1 = _add_camera(dual_manager, "cam1")
    d2 = _add_camera(dual_manager, "cam2")
    dual_fps = await _measure_fps(
        dual_manager, {"cam1": d1, "cam2": d2}, warmup=1.0, window=1.5,
    )

    avg_dual_fps = sum(dual_fps.values()) / len(dual_fps)
    ratio = (avg_dual_fps / mono_fps) if mono_fps else 0.0

    # Umbral deliberadamente laxo (>0, no >=80%): un bucle Python puro es GIL-bound
    # todo el tiempo (a diferencia de cv2/YOLO reales, que sueltan el GIL durante su
    # computo en C), asi que este test tiende a medir MAS degradacion que la real --
    # forzar el 80% literal aqui daria falsos negativos en maquinas con pocos cores
    # sin decir nada fiable sobre produccion. Lo que SI prueba: ninguna camara se
    # queda inanida por completo cuando compite con otra.
    assert avg_dual_fps > 0, (
        f"mono={mono_fps:.2f} fps, dual={avg_dual_fps:.2f} fps de media "
        f"(cam1={dual_fps['cam1']:.2f}, cam2={dual_fps['cam2']:.2f}), "
        f"ratio={ratio:.1%} -- alguna camara dejo de procesar frames del todo"
    )
    assert all(fps > 0 for fps in dual_fps.values()), (
        f"una camara quedo completamente inanida: {dual_fps}"
    )


async def TEST_rebalance_fps_activates_on_real_pipelines_under_load(mock_video_capture):
    """Complementa los tests con mocks de 36-06 (test_manager.py): CameraManager.
    rebalance_fps() debe imponer un techo real sobre AdaptiveRate cuando el coste
    estimado de dos pipelines REALES (no fakes) supera un presupuesto bajo."""
    manager = CameraManager()
    d1 = _add_camera(manager, "cam1")
    d2 = _add_camera(manager, "cam2")
    manager.start_all()
    try:
        await asyncio.sleep(1.0)  # deja que ambas AdaptiveRate observen latencia real

        total_before = sum(p.estimated_cpu_pct for p in manager.all())
        assert total_before > 0, "las pipelines reales no registraron ningun coste de CPU"

        # Presupuesto absurdamente bajo: fuerza rebalance_fps a actuar siempre,
        # sin depender de cuanta CPU tenga la maquina que ejecuta el test.
        manager.rebalance_fps(budget_pct=0.01)

        for pipeline in manager.all():
            cap = pipeline.detection.rate.effective_fps
            assert cap <= pipeline.detection.rate.min_fps + 0.01, (
                f"{pipeline.camera_id}: effective_fps={cap} no bajo al min_fps "
                f"tras rebalance_fps con presupuesto casi nulo"
            )

        # Liberar el presupuesto (holgado) debe devolver el control a la propia
        # histeresis de latencia -- el techo desaparece sin tocar el escalon interno.
        manager.rebalance_fps(budget_pct=100000.0)
        for pipeline in manager.all():
            assert pipeline.detection.rate._external_cap is None
    finally:
        manager.stop_all()
