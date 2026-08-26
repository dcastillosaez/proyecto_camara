"""Tests for backend.pipeline.manager.CameraPipeline — métodos pull de solo lectura.

CameraPipeline se construye vía object.__new__() para evitar levantar
CaptureWorker/RTSP real en __init__(); solo se fijan los atributos que
get_person_boxes() necesita (registry, _process_size, capture.health).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.perception.face.identity import IdentityState
from backend.pipeline.manager import CameraManager, CameraPipeline
from backend.pipeline.tracking import TrackRegistry


class _FakeTracked:
    """Imita la forma de sv.Detections que consume update_from_detections (ver test_track_registry.py)."""

    def __init__(self, ids: list[int], boxes: list[tuple[int, int, int, int]] | None = None):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array(boxes if boxes else [[0, 0, 10, 10]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


def _bare_pipeline(process_size: tuple[int, int] | None = (100, 50)) -> CameraPipeline:
    p = object.__new__(CameraPipeline)
    p.registry = TrackRegistry()
    p._process_size = process_size
    p.capture = SimpleNamespace(health=SimpleNamespace(native_resolution=None))
    return p


def TEST_get_person_boxes_excludes_stale_tracks():
    """Solo los tracks visibles en frame_ids() aparecen en la salida (Pitfall 2)."""
    pipeline = _bare_pipeline()
    pipeline.registry.update_from_detections(
        _FakeTracked([1, 2], [(0, 0, 10, 10), (20, 20, 30, 30)]), now=1.0
    )
    pipeline.registry.set_frame_ids({1})

    boxes = pipeline.get_person_boxes()

    assert len(boxes) == 1
    assert boxes[0]["track_id"] == 1


def TEST_get_person_boxes_normalizes_bbox_0_to_1():
    """El bbox absoluto se normaliza dividiendo por (w, h) de process_size."""
    pipeline = _bare_pipeline(process_size=(100, 50))
    pipeline.registry.update_from_detections(
        _FakeTracked([1], [(10, 10, 20, 20)]), now=1.0
    )
    pipeline.registry.set_frame_ids({1})

    boxes = pipeline.get_person_boxes()

    assert len(boxes) == 1
    assert boxes[0]["bbox"] == pytest.approx([0.1, 0.2, 0.2, 0.4])


def TEST_get_person_boxes_returns_empty_without_process_size():
    """Sin process_size ni native_resolution validos, la salida es [] (no excepcion)."""
    pipeline = _bare_pipeline(process_size=None)
    pipeline.registry.update_from_detections(
        _FakeTracked([1], [(10, 10, 20, 20)]), now=1.0
    )
    pipeline.registry.set_frame_ids({1})

    boxes = pipeline.get_person_boxes()

    assert boxes == []


def TEST_get_person_boxes_includes_identity_fields():
    """identity_state e person_name se exponen como strings/valores planos."""
    pipeline = _bare_pipeline()
    pipeline.registry.update_from_detections(
        _FakeTracked([1], [(0, 0, 10, 10)]), now=1.0
    )
    pipeline.registry.set_frame_ids({1})
    pipeline.registry.set_identity_state(1, IdentityState.CONFIRMED)
    pipeline.registry.set_identity(1, 1, "Ana")

    boxes = pipeline.get_person_boxes()

    assert len(boxes) == 1
    assert boxes[0]["identity_state"] == "CONFIRMED"
    assert boxes[0]["person_name"] == "Ana"


# ─── Fase 36 (SCALE-05): CameraManager.remove() ───────────────────────────────
class _FakePipeline:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def TEST_manager_remove_stops_pipeline_and_forgets_it():
    manager = CameraManager()
    fake = _FakePipeline()
    manager._pipelines["cam1"] = fake

    assert manager.remove("cam1") is True
    assert fake.stopped is True
    assert manager.get("cam1") is None


def TEST_manager_remove_unknown_camera_returns_false_without_error():
    manager = CameraManager()

    assert manager.remove("does-not-exist") is False


def TEST_manager_remove_one_camera_does_not_touch_the_others():
    manager = CameraManager()
    cam1, cam2 = _FakePipeline(), _FakePipeline()
    manager._pipelines["cam1"] = cam1
    manager._pipelines["cam2"] = cam2

    manager.remove("cam1")

    assert cam1.stopped is True
    assert cam2.stopped is False
    assert manager.get("cam2") is cam2


# ─── Fase 36 (SCALE-08): CameraPipeline.estimated_cpu_pct ─────────────────────
def _pipeline_with_worker_stats(detection_stats=None, recognition_stats=None) -> CameraPipeline:
    p = object.__new__(CameraPipeline)
    p.detection = SimpleNamespace(stats=detection_stats) if detection_stats is not None else None
    p.recognition = SimpleNamespace(stats=recognition_stats) if recognition_stats is not None else None
    return p


def TEST_estimated_cpu_pct_is_fps_times_latency_as_percentage():
    """8 fps * 0.05s/frame = 40% de un core."""
    pipeline = _pipeline_with_worker_stats(
        detection_stats={"effective_fps": 8.0, "avg_latency": 0.05},
    )
    assert pipeline.estimated_cpu_pct == 40.0


def TEST_estimated_cpu_pct_sums_detection_and_recognition():
    pipeline = _pipeline_with_worker_stats(
        detection_stats={"effective_fps": 8.0, "avg_latency": 0.05},   # 40%
        recognition_stats={"effective_fps": 2.0, "avg_latency": 0.10},  # 20%
    )
    assert pipeline.estimated_cpu_pct == 60.0


def TEST_estimated_cpu_pct_is_zero_without_detection_or_recognition():
    pipeline = _pipeline_with_worker_stats()
    assert pipeline.estimated_cpu_pct == 0.0


# ─── Fase 36 (SCALE-08): CameraManager.rebalance_fps() ────────────────────────
class _FakeRate:
    def __init__(self, effective_fps: float, min_fps: float = 1.0) -> None:
        self.effective_fps = effective_fps
        self.min_fps = min_fps
        self.cap: float | None = "untouched"  # distinto de None para detectar "no se llamo"

    def set_external_cap(self, cap: float | None) -> None:
        self.cap = cap


def _fake_pipeline_for_rebalance(estimated_cpu_pct: float, effective_fps: float = 8.0, min_fps: float = 1.0):
    """`estimated_cpu_pct` es una @property de solo lectura calculada a partir de
    `detection.stats` — se fabrica una `avg_latency` que produzca el pct pedido
    (`effective_fps * avg_latency * 100`) en vez de asignarla directamente."""
    p = object.__new__(CameraPipeline)
    avg_latency = estimated_cpu_pct / (effective_fps * 100.0)
    p.detection = SimpleNamespace(
        rate=_FakeRate(effective_fps, min_fps),
        stats={"effective_fps": effective_fps, "avg_latency": avg_latency},
    )
    p.recognition = None
    return p


def TEST_rebalance_releases_cap_when_total_within_budget():
    manager = CameraManager()
    cam1 = _fake_pipeline_for_rebalance(estimated_cpu_pct=40.0)
    manager._pipelines["cam1"] = cam1

    manager.rebalance_fps(budget_pct=200.0)

    assert cam1.detection.rate.cap is None


def TEST_rebalance_caps_fps_proportionally_when_over_budget():
    manager = CameraManager()
    cam1 = _fake_pipeline_for_rebalance(estimated_cpu_pct=90.0, effective_fps=8.0)
    cam2 = _fake_pipeline_for_rebalance(estimated_cpu_pct=90.0, effective_fps=8.0)
    manager._pipelines["cam1"] = cam1
    manager._pipelines["cam2"] = cam2

    manager.rebalance_fps(budget_pct=90.0)  # total 180, presupuesto 90 -> ratio 0.5

    assert cam1.detection.rate.cap == 4.0
    assert cam2.detection.rate.cap == 4.0


def TEST_rebalance_never_caps_below_min_fps():
    manager = CameraManager()
    cam1 = _fake_pipeline_for_rebalance(estimated_cpu_pct=1000.0, effective_fps=8.0, min_fps=3.0)
    manager._pipelines["cam1"] = cam1

    manager.rebalance_fps(budget_pct=1.0)  # ratio minusculo, forzaria muy por debajo de 3.0

    assert cam1.detection.rate.cap == 3.0


def TEST_rebalance_does_not_touch_recognition_rate():
    manager = CameraManager()
    cam1 = _fake_pipeline_for_rebalance(estimated_cpu_pct=1000.0)
    cam1.recognition = SimpleNamespace(rate=_FakeRate(2.0, min_fps=2.0), stats={})
    manager._pipelines["cam1"] = cam1

    manager.rebalance_fps(budget_pct=1.0)

    assert cam1.recognition.rate.cap == "untouched"


def TEST_rebalance_skips_cameras_without_detection_worker():
    manager = CameraManager()
    p = object.__new__(CameraPipeline)
    p.detection = None
    manager._pipelines["cam1"] = p

    manager.rebalance_fps(budget_pct=1.0)  # no debe lanzar excepcion


def TEST_rebalance_with_zero_cameras_does_nothing():
    manager = CameraManager()
    manager.rebalance_fps(budget_pct=200.0)  # no debe lanzar excepcion
