"""Tests for DetectionWorker.set_lines() (hot-reload de lineas) y gating de
horario de zona en DetectionWorker._update_zones_and_heat (Plan 33-05)."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import numpy as np
import supervision as sv

from backend.pipeline.broker import FrameBroker
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry
from backend.tracker import PersonTracker


def _worker_with_real_tracker() -> DetectionWorker:
    """Igual que _worker_for_zones() de test_detection_worker.py, pero con un
    PersonTracker real (no MagicMock) para poder inspeccionar el LineZone
    reconfigurado con las coordenadas en pixeles que produce set_lines()."""
    broker = FrameBroker()
    return DetectionWorker(
        broker.subscribe("detector"), MagicMock(), PersonTracker(),
        TrackRegistry(), AdaptiveRate(),
    )


def _tracked_at(boxes, tids) -> sv.Detections:
    det = sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.ones(len(tids)),
        class_id=np.zeros(len(tids), dtype=int),
    )
    det.tracker_id = np.array(tids)
    return det


# ─── set_lines() convierte fraccion -> pixel y alimenta PersonTracker ───────
def test_set_lines_hot_reload_converts_fraction_to_pixel():
    worker = _worker_with_real_tracker()
    worker.set_lines([{
        "id": "l1", "name": "Entrada", "enabled": True,
        "start_x_frac": 0.0, "start_y_frac": 0.5,
        "end_x_frac": 1.0, "end_y_frac": 0.5,
    }])

    shape = (720, 1280, 3)
    worker._update_lines(shape)

    counts = worker._tracker.get_counts()
    assert "l1" in counts
    assert counts["l1"] == {"name": "Entrada", "in": 0, "out": 0, "total": 0}

    line = worker._tracker._lines[0]
    assert line["zone"].vector.start == sv.Point(0, 360)
    assert line["zone"].vector.end == sv.Point(1280, 360)


# ─── Cambiar la resolucion entre frames recalcula la linea sin llamar set_lines de nuevo ─
def test_line_recalculated_on_resolution_change_without_new_set_lines():
    worker = _worker_with_real_tracker()
    worker.set_lines([{
        "id": "l1", "name": "Entrada", "enabled": True,
        "start_x_frac": 0.0, "start_y_frac": 0.5,
        "end_x_frac": 1.0, "end_y_frac": 0.5,
    }])

    worker._update_lines((720, 1280, 3))
    line = worker._tracker._lines[0]
    assert line["zone"].vector.start == sv.Point(0, 360)
    assert line["zone"].vector.end == sv.Point(1280, 360)

    # 720p -> 1080p sin volver a llamar set_lines: se recalcula igualmente
    # (mismo gate _line_frame_size != (fw, fh) que usan las zonas).
    worker._update_lines((1080, 1920, 3))
    line = worker._tracker._lines[0]
    assert line["zone"].vector.start == sv.Point(0, 540)
    assert line["zone"].vector.end == sv.Point(1920, 540)


# ---------------------------------------------------------------------------
# Horario propio de zona (OPS-23) — gating en _update_zones_and_heat
# ---------------------------------------------------------------------------

def _worker_for_zones() -> DetectionWorker:
    broker = FrameBroker()
    return DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
    )


# ─── Una zona fuera de su ventana horaria no cuenta entradas ────────────────
def test_zone_schedule_blocks_trigger_outside_window():
    worker = _worker_for_zones()
    today = datetime.datetime.now().weekday()
    other_day = (today + 1) % 7  # dia garantizado distinto de hoy
    worker.set_zones([{
        "id": "z1", "name": "Z1", "enabled": True,
        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "schedule": {"days": [other_day]},
    }])

    shape = (720, 1280, 3)
    worker._update_zones_and_heat(_tracked_at([[300, 100, 340, 400]], [1]), shape)

    assert worker.get_zone_stats() == [
        {"id": "z1", "name": "Z1", "current": 0, "entries": 0}
    ]


# ─── Una zona sin horario se comporta exactamente igual que antes (sin regresion) ─
def test_zone_without_schedule_counts_normally():
    worker = _worker_for_zones()
    worker.set_zones([{
        "id": "z1", "name": "Z1", "enabled": True,
        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "schedule": None,
    }])

    shape = (720, 1280, 3)
    worker._update_zones_and_heat(_tracked_at([[300, 100, 340, 400]], [1]), shape)

    assert worker.get_zone_stats() == [
        {"id": "z1", "name": "Z1", "current": 1, "entries": 1}
    ]
