"""Tests for PersonTracker — counts, annotation, and line reconfiguration."""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import supervision as sv

from backend.tracker import PersonTracker


@pytest.fixture
def tracker():
    return PersonTracker(lines=[{"id": "l1", "name": "Linea 1", "start": sv.Point(0, 360), "end": sv.Point(1280, 360)}])


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
def TEST_078_initial_counts_all_zero(tracker):
    """Fresh tracker reports zero crossings in all directions for its one line."""
    assert tracker.get_counts() == {"l1": {"name": "Linea 1", "in": 0, "out": 0, "total": 0}}


# ─── Estructura del dict devuelto por get_counts ─────────────────────────────
# get_counts() es consumido por el endpoint /counts y el WebSocket.
# Ambos esperan, por línea, exactamente las claves 'name', 'in', 'out' y 'total'.
# Un cambio de nombre rompería el frontend sin error en Python.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_079_get_counts_has_all_keys(tracker):
    """get_counts always returns a dict keyed by line_id with 'name'/'in'/'out'/'total'."""
    counts = tracker.get_counts()
    assert set(counts.keys()) == {"l1"}
    assert {"name", "in", "out", "total"} == set(counts["l1"].keys())


# ─── PersonTracker sin líneas configuradas ────────────────────────────────────
# Un tracker instanciado sin lines= (frame_rate solo) no debe lanzar excepción
# al actualizar ni al leer contadores: simplemente no hay líneas que cruzar.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_094_no_lines_configured_update_and_counts_do_not_raise():
    """PersonTracker(frame_rate=15) without lines: update() and get_counts() are safe."""
    empty_tracker = PersonTracker(frame_rate=15)
    det = _make_tracked(1, [1])
    with patch.object(empty_tracker._byte_tracker, "update_with_detections", return_value=det):
        tracked, crossings = empty_tracker.update(sv.Detections.empty())
    assert isinstance(tracked, sv.Detections)
    assert crossings == []
    assert empty_tracker.get_counts() == {}


# ─── Cruce en dirección IN: solo incrementa in y total de su línea ───────────
# Simula que LineZone.trigger devuelve crossed_in=True para el tracker_id=7.
# Verifica que in sube a 1, total sube a 1 y out permanece en 0 dentro de 'l1'.
# Confirma que los contadores son independientes entre sí.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_080_counts_after_in_crossing(tracker):
    """One IN crossing increments 'in' and 'total', leaves 'out' at zero."""
    det = _make_tracked(1, [7])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        tracker.update(sv.Detections.empty())

    counts = tracker.get_counts()["l1"]
    assert counts["in"] == 1
    assert counts["out"] == 0
    assert counts["total"] == 1


# ─── Cruces IN y OUT de IDs distintos son independientes ─────────────────────
# Dos personas distintas (tracker_id 1 y 2) cruzan en direcciones opuestas.
# Verifica que in=1, out=1, total=2 — los contadores no se mezclan entre sí
# ni se anulan mutuamente.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_081_counts_in_plus_out_independent(tracker):
    """IN and OUT crossings from different tracker IDs are counted independently."""
    for tid, crossed_in, crossed_out in [(1, True, False), (2, False, True)]:
        det = _make_tracked(1, [tid])
        with (
            patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
            # passthrough: el smoother real conserva tracks de frames previos
            # en su ventana y desalinearía el trigger mockeado de tamaño fijo
            patch.object(tracker._smoother, "update_with_detections", side_effect=lambda d: d),
            patch.object(tracker._lines[0]["zone"], "trigger",
                         return_value=(np.array([crossed_in]), np.array([crossed_out]))),
        ):
            tracker.update(sv.Detections.empty())

    counts = tracker.get_counts()["l1"]
    assert counts["in"] == 1
    assert counts["out"] == 1
    assert counts["total"] == 2


# ─── total cuenta IDs únicos, no suma de eventos ─────────────────────────────
# ByteTrack puede volver a ver el mismo tracker_id en frames sucesivos.
# El tracker usa crossed_ids (set) por línea para deduplicar: el mismo ID que
# cruza 3 veces debe contar como total=1, no total=3.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_082_total_counts_unique_ids_not_events(tracker):
    """'total' equals the number of unique IDs that crossed, not the sum of in+out."""
    det = _make_tracked(1, [99])
    for _ in range(3):
        with (
            patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
            patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
        ):
            tracker.update(sv.Detections.empty())
    assert tracker.get_counts()["l1"]["total"] == 1


# ─── Ida y vuelta del mismo ID: ambas direcciones cuentan ────────────────────
# Regresión del punto 1 de MEJORAS.md: el mismo tracker_id que entra (in) y
# después sale (out) debe registrar AMBOS cruces. LineZone ya deduplica por
# track internamente; crossed_ids no debe bloquear los contadores
# direccionales, solo alimentar el total de personas distintas.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_091_same_id_in_then_out_counts_both(tracker):
    """Same tracker_id crossing in then out increments both counters."""
    det = _make_tracked(1, [7])
    for crossed_in, crossed_out in [(True, False), (False, True)]:
        with (
            patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
            patch.object(tracker._lines[0]["zone"], "trigger",
                         return_value=(np.array([crossed_in]), np.array([crossed_out]))),
        ):
            _, crossings = tracker.update(sv.Detections.empty())
        assert len(crossings) == 1

    counts = tracker.get_counts()["l1"]
    assert counts["in"] == 1
    assert counts["out"] == 1
    assert counts["total"] == 1  # una sola persona distinta


# ─── Jitter sobre la línea no genera cruces ──────────────────────────────────
# Regresión del punto 2 de MEJORAS.md: minimum_crossing_threshold=2 exige que
# el objeto permanezca 2 frames al otro lado antes de confirmar el cruce.
# Una bbox cuyo centro oscila alrededor de la línea (355↔365 con línea en 360)
# nunca cumple esa condición y no debe producir ningún evento.
# Se usa el LineZone REAL; solo se mockea ByteTrack para fijar el tracker_id.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_092_line_jitter_does_not_count(tracker):
    """Bbox jitter around the line never confirms a crossing."""
    def det_at(y: int) -> sv.Detections:
        det = sv.Detections(
            xyxy=np.array([[600, y - 100, 700, y + 100]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([0]),
        )
        det.tracker_id = np.array([3])
        return det

    events = []
    for y in [340, 355, 365, 355, 365, 355, 365, 355]:
        with patch.object(tracker._byte_tracker, "update_with_detections", return_value=det_at(y)):
            _, crossings = tracker.update(sv.Detections.empty())
        events += crossings

    assert events == []
    assert tracker.get_counts() == {"l1": {"name": "Linea 1", "in": 0, "out": 0, "total": 0}}


# ---------------------------------------------------------------------------
# update() — return value
# ---------------------------------------------------------------------------

# ─── Tipo de retorno de update() ─────────────────────────────────────────────
# update() es llamado desde el hilo de captura RTSP.
# Debe devolver siempre (sv.Detections, list) para que el pipeline de anotación
# y la cola de eventos funcionen sin comprobaciones de tipo adicionales.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_083_update_returns_tuple_of_detections_and_crossings(tracker):
    """update() returns (sv.Detections, list)."""
    empty = sv.Detections.empty()
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=empty),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([]), np.array([]))),
    ):
        tracked, crossings = tracker.update(sv.Detections.empty())
    assert isinstance(tracked, sv.Detections)
    assert isinstance(crossings, list)


# ─── Claves obligatorias en cada evento de cruce ─────────────────────────────
# Cada dict de cruce es persistido en BD por _drain_events en main.py.
# Las claves 'direction', 'timestamp', 'tracker_id', 'line_id' y 'line_name'
# son requeridas:
#   - direction → columna events.direction
#   - timestamp → columna events.timestamp
#   - tracker_id → para enriquecer con nombre de persona (person_cache)
#   - line_id/line_name → identifican de qué línea proviene el cruce (OPS-22)
# Un campo faltante causaría KeyError silencioso en producción.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_084_update_crossing_event_has_required_keys(tracker):
    """Each crossing dict must contain direction/timestamp/tracker_id/line_id/line_name."""
    det = _make_tracked(1, [5])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())
    assert len(crossings) == 1
    c = crossings[0]
    assert "direction" in c and "timestamp" in c and "tracker_id" in c
    assert c["line_id"] == "l1"
    assert c["line_name"] == "Linea 1"


# ---------------------------------------------------------------------------
# N líneas independientes
# ---------------------------------------------------------------------------

# ─── Dos líneas configuradas, cruce de una sola ──────────────────────────────
# Con dos líneas independientes, un cruce en 'l1' no debe afectar los
# contadores de 'l2'. Confirma que cada línea lleva su propio estado.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_095_two_lines_crossing_one_leaves_other_untouched():
    """Crossing line l1 does not affect l2's counters."""
    two_lines = PersonTracker(lines=[
        {"id": "l1", "name": "Entrada", "start": sv.Point(0, 300), "end": sv.Point(640, 300)},
        {"id": "l2", "name": "Salida", "start": sv.Point(0, 500), "end": sv.Point(640, 500)},
    ])
    det = _make_tracked(1, [7])
    with (
        patch.object(two_lines._byte_tracker, "update_with_detections", return_value=det),
        patch.object(two_lines._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
        patch.object(two_lines._lines[1]["zone"], "trigger", return_value=(np.array([False]), np.array([False]))),
    ):
        _, crossings = two_lines.update(sv.Detections.empty())

    assert len(crossings) == 1
    assert crossings[0]["line_id"] == "l1"
    assert crossings[0]["line_name"] == "Entrada"
    counts = two_lines.get_counts()
    assert counts["l2"] == {"name": "Salida", "in": 0, "out": 0, "total": 0}


# ─── Una persona cruza dos líneas en el mismo frame ──────────────────────────
# El mismo tracker_id puede cruzar dos líneas distintas en el mismo frame
# (p. ej. dos umbrales de un pasillo). update() debe devolver dos entradas en
# crossings, ambas con el mismo tracker_id — la identidad de ByteTrack es
# compartida, no se duplica por línea.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_096_same_frame_crosses_two_lines_shares_tracker_id():
    """One person crossing two lines in the same frame yields two crossings, same tracker_id."""
    two_lines = PersonTracker(lines=[
        {"id": "l1", "name": "Linea 1", "start": sv.Point(0, 300), "end": sv.Point(640, 300)},
        {"id": "l2", "name": "Linea 2", "start": sv.Point(0, 500), "end": sv.Point(640, 500)},
    ])
    det = _make_tracked(1, [7])
    with (
        patch.object(two_lines._byte_tracker, "update_with_detections", return_value=det),
        patch.object(two_lines._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
        patch.object(two_lines._lines[1]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, crossings = two_lines.update(sv.Detections.empty())

    assert len(crossings) == 2
    line_ids = {c["line_id"] for c in crossings}
    assert line_ids == {"l1", "l2"}
    assert all(c["tracker_id"] == 7 for c in crossings)


# ---------------------------------------------------------------------------
# annotate()
# ---------------------------------------------------------------------------

# ─── Tipo de retorno: siempre ndarray ────────────────────────────────────────
# annotate() alimenta al encoder MJPEG y al VideoWriter del grabador.
# Ambos requieren un ndarray de numpy; devolver None o un tipo distinto
# causaría una excepción en cv2.imencode o writer.write().
# ─────────────────────────────────────────────────────────────────────────────
def TEST_085_annotate_returns_ndarray(tracker, blank_frame):
    """annotate() always returns a numpy ndarray."""
    assert isinstance(tracker.annotate(blank_frame, _make_tracked(1, [1])), np.ndarray)


# ─── Preservación de dimensiones del frame ───────────────────────────────────
# Los anotadores de supervision (BoxAnnotator, LabelAnnotator) no deben
# alterar el shape del frame. Un cambio de dimensiones rompería el MJPEG
# stream y la grabación de clips.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_086_annotate_preserves_frame_shape(tracker, blank_frame):
    """annotate() does not change the frame dimensions."""
    result = tracker.annotate(blank_frame, _make_tracked(1, [1]))
    assert result.shape == blank_frame.shape


# ─── Inmutabilidad del frame de entrada ──────────────────────────────────────
# annotate() llama internamente a frame.copy() antes de anotar.
# Si modificara el frame original en-place, los datos almacenados en
# RTSPStream._frame se corromperían para todos los consumidores concurrentes
# (endpoint MJPEG, grabador, reconocedor).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_087_annotate_does_not_mutate_original(tracker, blank_frame):
    """annotate() must not modify the input frame in-place."""
    original = blank_frame.copy()
    tracker.annotate(blank_frame, _make_tracked(1, [1]))
    np.testing.assert_array_equal(blank_frame, original)


# ─── Detecciones vacías: sin excepción ───────────────────────────────────────
# Cuando no hay personas en escena, update() devuelve sv.Detections.empty().
# annotate() debe manejar correctamente ese caso sin iterar sobre arrays nulos
# ni lanzar IndexError/AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_088_annotate_empty_detections_no_crash(tracker, blank_frame):
    """annotate() with empty Detections does not raise."""
    result = tracker.annotate(blank_frame, sv.Detections.empty())
    assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# reconfigure_line() / reconfigure_lines()
# ---------------------------------------------------------------------------

# ─── Reconfiguración en caliente sin excepción ───────────────────────────────
# reconfigure_line() permite al usuario mover la línea de conteo desde el
# dashboard sin reiniciar el servidor. Debe aceptar nuevas coordenadas
# y reemplazar el LineZone interno sin lanzar ninguna excepción. Wrapper de
# compatibilidad sobre reconfigure_lines() hasta que el Plan 33-05 lo retire.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_089_reconfigure_line_does_not_raise(tracker):
    """reconfigure_line() can be called without crashing."""
    tracker.reconfigure_line(sv.Point(0, 100), sv.Point(1280, 100))


# ─── El tracker sigue operativo tras reconfigurar ────────────────────────────
# Tras reemplazar el LineZone, el pipeline completo update() debe seguir
# funcionando. Si reconfigure_line dejara el tracker en estado inconsistente,
# la siguiente llamada a update() lanzaría AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_090_reconfigure_line_tracker_still_works_after(tracker):
    """update() succeeds after reconfigure_line()."""
    tracker.reconfigure_line(sv.Point(0, 100), sv.Point(1280, 100))
    det = _make_tracked(1, [42])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([False]), np.array([False]))),
    ):
        tracked, crossings = tracker.update(sv.Detections.empty())
    assert crossings == []


# ─── reconfigure_lines sustituye la lista completa ───────────────────────────
# Llamar a reconfigure_lines con líneas de id distinto reemplaza la lista
# entera: la línea anterior desaparece de get_counts().
# ─────────────────────────────────────────────────────────────────────────────
def TEST_097_reconfigure_lines_replaces_full_list(tracker):
    """reconfigure_lines() with a different id set drops the old lines entirely."""
    tracker.reconfigure_lines([
        {"id": "l2", "name": "Nueva", "start": sv.Point(0, 200), "end": sv.Point(1280, 200)},
    ])
    assert set(tracker.get_counts().keys()) == {"l2"}


# ─── reconfigure_lines conserva el conteo de líneas con el mismo id ──────────
# Mover un vértice de una línea existente (mismo id) no debe resetear su
# conteo acumulado — solo las líneas realmente nuevas arrancan en cero.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_098_reconfigure_lines_preserves_counts_for_same_id():
    """reconfigure_lines() keeps in/out/total for a line whose id is reused."""
    t = PersonTracker(lines=[{"id": "l1", "name": "Linea 1", "start": sv.Point(0, 300), "end": sv.Point(640, 300)}])
    det = _make_tracked(1, [7])
    with (
        patch.object(t._byte_tracker, "update_with_detections", return_value=det),
        patch.object(t._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        t.update(sv.Detections.empty())
    assert t.get_counts()["l1"]["in"] == 1

    # Mueve el vértice de l1 y añade l2 nueva
    t.reconfigure_lines([
        {"id": "l1", "name": "Linea 1", "start": sv.Point(0, 320), "end": sv.Point(640, 320)},
        {"id": "l2", "name": "Linea 2", "start": sv.Point(0, 500), "end": sv.Point(640, 500)},
    ])
    counts = t.get_counts()
    assert counts["l1"]["in"] == 1  # conservado
    assert counts["l2"] == {"name": "Linea 2", "in": 0, "out": 0, "total": 0}  # nueva, en cero


# ─── reconfigure_lines NO recrea ByteTrack: tracks activos sobreviven ────────
# El track_id asignado por ByteTrack antes de reconfigure_lines() debe seguir
# siendo el mismo tras la llamada — recrear el ByteTrack perdería la
# identidad de los tracks activos.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_099_reconfigure_lines_does_not_recreate_bytetrack(tracker):
    """reconfigure_lines() mutates the line list, never self._byte_tracker."""
    bt_before = tracker._byte_tracker
    tracker.reconfigure_lines([
        {"id": "l2", "name": "Otra", "start": sv.Point(0, 200), "end": sv.Point(1280, 200)},
    ])
    assert tracker._byte_tracker is bt_before


# ─── set_frame_rate sincroniza max_time_lost sin recrear el tracker ─────────
# Fase 18: AdaptiveRate cambia el ritmo de deteccion en caliente. Recrear el
# ByteTrack perderia todos los tracks activos; set_frame_rate debe mutar
# max_time_lost in-place, preservando la identidad del objeto ByteTrack
# (y por tanto sus tracks activos).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_093_set_frame_rate_updates_max_time_lost_in_place(tracker):
    """set_frame_rate mutates max_time_lost without replacing the ByteTrack instance."""
    bt_before = tracker._byte_tracker
    tracker.set_frame_rate(30)
    assert tracker._byte_tracker is bt_before  # mismo objeto, tracks preservados
    assert tracker._byte_tracker.max_time_lost == int(30 / 30.0 * tracker.LOST_TRACK_BUFFER)

    tracker.set_frame_rate(8)
    assert tracker._byte_tracker.max_time_lost == int(8 / 30.0 * tracker.LOST_TRACK_BUFFER)
