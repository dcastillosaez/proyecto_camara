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
