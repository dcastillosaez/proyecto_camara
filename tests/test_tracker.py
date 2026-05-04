"""Tests for PersonTracker — counts, annotation, and line reconfiguration."""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import supervision as sv

from backend.tracker import PersonTracker


@pytest.fixture
def tracker():
    return PersonTracker(start=sv.Point(0, 360), end=sv.Point(1280, 360))


@pytest.fixture
def blank_frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def _make_tracked(n: int, tracker_ids=None) -> sv.Detections:
    """Build a synthetic sv.Detections with n tracked persons."""
    xyxy = np.array([[i * 100, 100, i * 100 + 50, 300] for i in range(n)], dtype=np.float32)
    det = sv.Detections(
        xyxy=xyxy,
        confidence=np.ones(n, dtype=np.float32) * 0.9,
        class_id=np.zeros(n, dtype=int),
    )
    det.tracker_id = np.array(tracker_ids if tracker_ids is not None else list(range(1, n + 1)))
    return det


# ---------------------------------------------------------------------------
# get_counts
# ---------------------------------------------------------------------------

# ─── Estado inicial: todos los contadores en cero ────────────────────────────
# Un tracker recién instanciado no ha procesado ningún frame; todos sus
# contadores deben partir de cero. Este test actúa como línea base para
# los tests de conteo que vienen después.
# ─────────────────────────────────────────────────────────────────────────────
def test_initial_counts_all_zero(tracker):
    """Fresh tracker reports zero crossings in all directions."""
    assert tracker.get_counts() == {"in": 0, "out": 0, "total": 0}


# ─── Estructura del dict devuelto por get_counts ─────────────────────────────
# get_counts() es consumido por el endpoint /counts y el WebSocket.
# Ambos esperan exactamente las claves 'in', 'out' y 'total'.
# Un cambio de nombre rompería el frontend sin error en Python.
# ─────────────────────────────────────────────────────────────────────────────
def test_get_counts_has_all_keys(tracker):
    """get_counts always returns a dict with 'in', 'out', and 'total' keys."""
    counts = tracker.get_counts()
    assert {"in", "out", "total"} == set(counts.keys())


# ─── Cruce en dirección IN: solo incrementa in y total ───────────────────────
# Simula que LineZone.trigger devuelve crossed_in=True para el tracker_id=7.
# Verifica que in sube a 1, total sube a 1 y out permanece en 0.
# Confirma que los contadores son independientes entre sí.
# ─────────────────────────────────────────────────────────────────────────────
def test_counts_after_in_crossing(tracker):
    """One IN crossing increments 'in' and 'total', leaves 'out' at zero."""
    det = _make_tracked(1, [7])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        tracker.update(sv.Detections.empty())

    counts = tracker.get_counts()
    assert counts["in"] == 1
    assert counts["out"] == 0
    assert counts["total"] == 1


# ─── Cruces IN y OUT de IDs distintos son independientes ─────────────────────
# Dos personas distintas (tracker_id 1 y 2) cruzan en direcciones opuestas.
# Verifica que in=1, out=1, total=2 — los contadores no se mezclan entre sí
# ni se anulan mutuamente.
# ─────────────────────────────────────────────────────────────────────────────
def test_counts_in_plus_out_independent(tracker):
    """IN and OUT crossings from different tracker IDs are counted independently."""
    for tid, crossed_in, crossed_out in [(1, True, False), (2, False, True)]:
        det = _make_tracked(1, [tid])
        with (
            patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
            patch.object(tracker._line_zone, "trigger",
                         return_value=(np.array([crossed_in]), np.array([crossed_out]))),
        ):
            tracker.update(sv.Detections.empty())

    counts = tracker.get_counts()
    assert counts["in"] == 1
    assert counts["out"] == 1
    assert counts["total"] == 2


# ─── total cuenta IDs únicos, no suma de eventos ─────────────────────────────
# ByteTrack puede volver a ver el mismo tracker_id en frames sucesivos.
# El tracker usa _crossed_ids (set) para deduplicar: el mismo ID que cruza
# 3 veces debe contar como total=1, no total=3.
# ─────────────────────────────────────────────────────────────────────────────
def test_total_counts_unique_ids_not_events(tracker):
    """'total' equals the number of unique IDs that crossed, not the sum of in+out."""
    det = _make_tracked(1, [99])
    for _ in range(3):
        with (
            patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
            patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
        ):
            tracker.update(sv.Detections.empty())
    assert tracker.get_counts()["total"] == 1


# ---------------------------------------------------------------------------
# update() — return value
# ---------------------------------------------------------------------------

# ─── Tipo de retorno de update() ─────────────────────────────────────────────
# update() es llamado desde el hilo de captura RTSP.
# Debe devolver siempre (sv.Detections, list) para que el pipeline de anotación
# y la cola de eventos funcionen sin comprobaciones de tipo adicionales.
# ─────────────────────────────────────────────────────────────────────────────
def test_update_returns_tuple_of_detections_and_crossings(tracker):
    """update() returns (sv.Detections, list)."""
    empty = sv.Detections.empty()
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=empty),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([]), np.array([]))),
    ):
        tracked, crossings = tracker.update(sv.Detections.empty())
    assert isinstance(tracked, sv.Detections)
    assert isinstance(crossings, list)


# ─── Claves obligatorias en cada evento de cruce ─────────────────────────────
# Cada dict de cruce es persistido en BD por _drain_events en main.py.
# Las claves 'direction', 'timestamp' y 'tracker_id' son requeridas:
#   - direction → columna events.direction
#   - timestamp → columna events.timestamp
#   - tracker_id → para enriquecer con nombre de persona (person_cache)
# Un campo faltante causaría KeyError silencioso en producción.
# ─────────────────────────────────────────────────────────────────────────────
def test_update_crossing_event_has_required_keys(tracker):
    """Each crossing dict must contain 'direction', 'timestamp', and 'tracker_id'."""
    det = _make_tracked(1, [5])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())
    assert len(crossings) == 1
    c = crossings[0]
    assert "direction" in c and "timestamp" in c and "tracker_id" in c


# ---------------------------------------------------------------------------
# annotate()
# ---------------------------------------------------------------------------

# ─── Tipo de retorno: siempre ndarray ────────────────────────────────────────
# annotate() alimenta al encoder MJPEG y al VideoWriter del grabador.
# Ambos requieren un ndarray de numpy; devolver None o un tipo distinto
# causaría una excepción en cv2.imencode o writer.write().
# ─────────────────────────────────────────────────────────────────────────────
def test_annotate_returns_ndarray(tracker, blank_frame):
    """annotate() always returns a numpy ndarray."""
    assert isinstance(tracker.annotate(blank_frame, _make_tracked(1, [1])), np.ndarray)


# ─── Preservación de dimensiones del frame ───────────────────────────────────
# Los anotadores de supervision (BoxAnnotator, LabelAnnotator) no deben
# alterar el shape del frame. Un cambio de dimensiones rompería el MJPEG
# stream y la grabación de clips.
# ─────────────────────────────────────────────────────────────────────────────
def test_annotate_preserves_frame_shape(tracker, blank_frame):
    """annotate() does not change the frame dimensions."""
    result = tracker.annotate(blank_frame, _make_tracked(1, [1]))
    assert result.shape == blank_frame.shape


# ─── Inmutabilidad del frame de entrada ──────────────────────────────────────
# annotate() llama internamente a frame.copy() antes de anotar.
# Si modificara el frame original en-place, los datos almacenados en
# RTSPStream._frame se corromperían para todos los consumidores concurrentes
# (endpoint MJPEG, grabador, reconocedor).
# ─────────────────────────────────────────────────────────────────────────────
def test_annotate_does_not_mutate_original(tracker, blank_frame):
    """annotate() must not modify the input frame in-place."""
    original = blank_frame.copy()
    tracker.annotate(blank_frame, _make_tracked(1, [1]))
    np.testing.assert_array_equal(blank_frame, original)


# ─── Detecciones vacías: sin excepción ───────────────────────────────────────
# Cuando no hay personas en escena, update() devuelve sv.Detections.empty().
# annotate() debe manejar correctamente ese caso sin iterar sobre arrays nulos
# ni lanzar IndexError/AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def test_annotate_empty_detections_no_crash(tracker, blank_frame):
    """annotate() with empty Detections does not raise."""
    result = tracker.annotate(blank_frame, sv.Detections.empty())
    assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# reconfigure_line()
# ---------------------------------------------------------------------------

# ─── Reconfiguración en caliente sin excepción ───────────────────────────────
# reconfigure_line() permite al usuario mover la línea de conteo desde el
# dashboard sin reiniciar el servidor. Debe aceptar nuevas coordenadas
# y reemplazar el LineZone interno sin lanzar ninguna excepción.
# ─────────────────────────────────────────────────────────────────────────────
def test_reconfigure_line_does_not_raise(tracker):
    """reconfigure_line() can be called without crashing."""
    tracker.reconfigure_line(sv.Point(0, 100), sv.Point(1280, 100))


# ─── El tracker sigue operativo tras reconfigurar ────────────────────────────
# Tras reemplazar el LineZone, el pipeline completo update() debe seguir
# funcionando. Si reconfigure_line dejara el tracker en estado inconsistente,
# la siguiente llamada a update() lanzaría AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def test_reconfigure_line_tracker_still_works_after(tracker):
    """update() succeeds after reconfigure_line()."""
    tracker.reconfigure_line(sv.Point(0, 100), sv.Point(1280, 100))
    det = _make_tracked(1, [42])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False]), np.array([False]))),
    ):
        tracked, crossings = tracker.update(sv.Detections.empty())
    assert crossings == []
