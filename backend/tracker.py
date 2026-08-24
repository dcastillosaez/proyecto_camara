"""ByteTrack person tracking and LineZone crossing counter."""

import datetime
import threading
from typing import Any

import numpy as np
import supervision as sv


class PersonTracker:
    """
    Assigns persistent IDs to detected persons (ByteTrack) and counts how
    many cross a configurable virtual line in each direction (LineZone).

    Thread-safe: ``update`` and ``get_counts`` can be called from the RTSP
    capture thread while ``get_counts`` is read from an async endpoint.
    """

    # Frames que el objeto debe permanecer al otro lado de la línea antes de
    # confirmar el cruce — filtra cruces falsos por jitter de la bbox.
    CROSSING_THRESHOLD = 2
    LOST_TRACK_BUFFER = 60

    def __init__(self, lines: list[dict[str, Any]] | None = None, frame_rate: int = 15) -> None:
        # frame_rate debe ser el FPS real del pipeline (MEJORAS.md punto 14):
        # ByteTrack calcula max_time_lost = frame_rate/30 * lost_track_buffer,
        # así que con el default (30) y un stream real a ~15 FPS el buffer
        # efectivo en segundos era el doble del esperado.
        self._byte_tracker = sv.ByteTrack(
            lost_track_buffer=self.LOST_TRACK_BUFFER, frame_rate=frame_rate
        )
        # Suaviza las bboxes entre frames (MEJORAS.md Bajas): menos jitter
        # visual y menos cruces falsos — complementa minimum_crossing_threshold.
        self._smoother = sv.DetectionsSmoother(length=5)

        self._box_annotator = sv.BoxAnnotator(thickness=1)
        self._label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)
        # Estela del recorrido de cada track — depuración visual de la línea
        # de conteo (MEJORAS.md Bajas).
        self._trace_annotator = sv.TraceAnnotator(trace_length=30, thickness=1)

        self._lock = threading.Lock()
        # Lista de líneas independientes (D-01, OPS-22): cada entrada lleva su
        # propio LineZone + contadores. ByteTrack/smoother arriba se COMPARTEN
        # entre todas las líneas — una misma persona conserva su identidad al
        # cruzar varias líneas, solo el conteo es por-línea.
        self._lines: list[dict[str, Any]] = [self._build_line(line) for line in (lines or [])]

    def _build_line(
        self,
        line: dict[str, Any],
        in_count: int = 0,
        out_count: int = 0,
        crossed_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        # BOTTOM_CENTER (los pies) cruza la línea de forma más fiable que el
        # centro de la caja, que oscila con los brazos/postura (MEJORAS.md Bajas).
        return {
            "id": line["id"],
            "name": line["name"],
            "zone": sv.LineZone(
                start=line["start"],
                end=line["end"],
                triggering_anchors=[sv.Position.BOTTOM_CENTER],
                minimum_crossing_threshold=self.CROSSING_THRESHOLD,
            ),
            "in_count": in_count,
            "out_count": out_count,
            "crossed_ids": set(crossed_ids) if crossed_ids else set(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, detections: sv.Detections) -> tuple[sv.Detections, list[dict[str, Any]]]:
        """
        Update ByteTrack with *detections*, trigger every configured line
        zone, and accumulate crossing counts per line.

        Returns ``(tracked_detections, crossings)`` where *crossings* is a
        list of ``{"direction": "in"|"out", "timestamp": datetime,
        "tracker_id": int, "line_id": str, "line_name": str}`` dicts for each
        new crossing in this frame — ready to persist to the DB. A person
        crossing two lines in the same frame produces two entries, one per
        line, sharing the same ``tracker_id``.

        LineZone already deduplicates per tracker_id (it keeps crossing state
        per track and only fires on real state changes), so every True in
        crossed_in/crossed_out is a genuine new crossing: a person entering
        and later leaving produces one "in" AND one "out" event.
        ``crossed_ids`` only tracks distinct persons for the "total" count
        and must never gate the directional counters.
        """
        tracked = self._byte_tracker.update_with_detections(detections)
        if tracked.tracker_id is not None:
            tracked = self._smoother.update_with_detections(tracked)
        ids = tracked.tracker_id if tracked.tracker_id is not None else []
        crossings: list[dict[str, Any]] = []
        now = datetime.datetime.now()
        with self._lock:
            for line in self._lines:
                crossed_in, crossed_out = line["zone"].trigger(tracked)
                for i, tid in enumerate(ids):
                    if crossed_in[i]:
                        line["in_count"] += 1
                        line["crossed_ids"].add(int(tid))
                        crossings.append({
                            "direction": "in", "timestamp": now, "tracker_id": int(tid),
                            "line_id": line["id"], "line_name": line["name"],
                        })
                    elif crossed_out[i]:
                        line["out_count"] += 1
                        line["crossed_ids"].add(int(tid))
                        crossings.append({
                            "direction": "out", "timestamp": now, "tracker_id": int(tid),
                            "line_id": line["id"], "line_name": line["name"],
                        })
        return tracked, crossings

    def annotate(
        self,
        frame: np.ndarray,
        tracked: sv.Detections,
        labels: list[str] | None = None,
    ) -> np.ndarray:
        """
        Draw bounding boxes, labels, and the counting line onto a copy of *frame*.
        Pass *labels* to override the default '#id conf' format.
        """
        if labels is None:
            labels = [
                f"#{tid} {conf:.2f}"
                for tid, conf in zip(
                    tracked.tracker_id if tracked.tracker_id is not None else [],
                    tracked.confidence if tracked.confidence is not None else [],
                )
            ]
        out = self._box_annotator.annotate(frame.copy(), tracked)
        # TraceAnnotator exige tracker_id — con detecciones vacías es None
        if tracked.tracker_id is not None:
            out = self._trace_annotator.annotate(out, tracked)
        out = self._label_annotator.annotate(out, tracked, labels=labels)
        return out

    def get_counts(self) -> dict[str, dict[str, Any]]:
        """Return cumulative counts per line: ``{line_id: {"name", "in", "out", "total"}}``."""
        with self._lock:
            return {
                line["id"]: {
                    "name": line["name"],
                    "in": line["in_count"],
                    "out": line["out_count"],
                    "total": len(line["crossed_ids"]),
                }
                for line in self._lines
            }

    def set_frame_rate(self, frame_rate: float) -> None:
        """
        Sync ByteTrack's lost-track window to a new effective frame rate
        (Fase 18: AdaptiveRate cambia el ritmo de detección en caliente).

        Muta ``max_time_lost`` directamente en vez de recrear el
        ``ByteTrack`` — recrearlo perdería todos los tracks activos y sus
        IDs. Es el mismo cálculo que hace ``ByteTrack.__init__``
        internamente (``max_time_lost = frame_rate/30 * lost_track_buffer``).
        """
        with self._lock:
            self._byte_tracker.max_time_lost = int(
                frame_rate / 30.0 * self.LOST_TRACK_BUFFER
            )

    def reconfigure_lines(self, lines: list[dict[str, Any]]) -> None:
        """Replace the full line list with new pixel coordinates. Thread-safe.

        Conserva in_count/out_count/crossed_ids de cada línea cuyo ``id`` ya
        existiera (mover un vértice o reordenar la lista no debe perder el
        conteo acumulado) — solo las líneas realmente nuevas arrancan en cero.
        ``self._byte_tracker``/``self._smoother`` NUNCA se recrean aquí:
        recrearlos perdería todos los tracks activos y sus IDs (mismo motivo
        que ``set_frame_rate``, más arriba).
        """
        with self._lock:
            existing = {line["id"]: line for line in self._lines}
            new_lines = []
            for line in lines:
                prev = existing.get(line["id"])
                if prev is not None:
                    new_lines.append(self._build_line(
                        line, prev["in_count"], prev["out_count"], prev["crossed_ids"]
                    ))
                else:
                    new_lines.append(self._build_line(line))
            self._lines = new_lines

    def reconfigure_line(self, start: sv.Point, end: sv.Point) -> None:
        """Wrapper de compatibilidad — la única llamada real sigue siendo
        posicional (backend/camera.py:194, endpoint /resolution). El Plan
        33-05 migra ese caller a reconfigure_lines/LineRepo y retira este
        wrapper; hasta entonces sustituye la lista completa por una única
        línea "_legacy"."""
        self.reconfigure_lines([{"id": "_legacy", "name": "Linea", "start": start, "end": end}])


class ObjectTracker:
    """ByteTrack dedicado a las clases de objeto (Fase 27, BEH-06/BEH-07).

    Existe porque sv.ByteTrack es class-agnostic: el tensor que entra al matcher se
    construye solo con xyxy y confidence (supervision/tracker/byte_tracker/core.py:104-110)
    y el reensamblado del tracker_id es una asignacion humgara por IoU con umbral 0,5.
    Reproducido en 27-RESEARCH.md Q4: un track de mochila le TRANSFIERE su id a una
    persona colocada casi en la misma caja. Un tracker por grupo de clases es la unica
    forma de que la identidad no migre entre clases.

    Diferencias deliberadas con PersonTracker:
    - SIN suavizado de detecciones entre frames: ese suavizado hace deepcopy del
      elemento MAS VIEJO del deque y solo promedia xyxy/confidence, asi que congelaria
      class_id hasta 5 frames (0,6 s a 8 FPS, medido) y retrasaria la desaparicion otro
      tanto. Justo las dos señales que BEH-07 necesita frescas.
    - SIN contador de cruce de linea (la Fase 4 en produccion): el conteo es de
      personas y solo debe ver personas.
    - SIN anotadores: el overlay de objetos se dibuja aparte, con color propio.
    """

    LOST_TRACK_BUFFER = 60

    def __init__(self, frame_rate: int = 15) -> None:
        # Mismo motivo que en PersonTracker (MEJORAS.md punto 14): ByteTrack calcula
        # max_time_lost = frame_rate/30 * lost_track_buffer, asi que con el default (30)
        # y un stream real a ~15 FPS el buffer efectivo en segundos era el doble.
        self._byte_tracker = sv.ByteTrack(
            lost_track_buffer=self.LOST_TRACK_BUFFER, frame_rate=frame_rate
        )
        self._lock = threading.Lock()

    def update(self, detections: sv.Detections) -> sv.Detections:
        """Trackea las detecciones de objeto. Devuelve solo sv.Detections: sin
        cruces de linea, sin suavizado, sin anotar."""
        return self._byte_tracker.update_with_detections(detections)

    def set_frame_rate(self, frame_rate: float) -> None:
        """
        Sync ByteTrack's lost-track window to a new effective frame rate
        (Fase 18: AdaptiveRate cambia el ritmo de detección en caliente).

        Muta ``max_time_lost`` directamente en vez de recrear el
        ``ByteTrack`` — recrearlo perdería todos los tracks activos y sus
        IDs. Es el mismo cálculo que hace ``ByteTrack.__init__``
        internamente (``max_time_lost = frame_rate/30 * lost_track_buffer``).
        """
        with self._lock:
            self._byte_tracker.max_time_lost = int(
                frame_rate / 30.0 * self.LOST_TRACK_BUFFER
            )
