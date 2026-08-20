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
from backend.pipeline.manager import CameraPipeline
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
