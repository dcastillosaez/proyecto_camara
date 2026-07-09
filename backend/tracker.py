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

    def __init__(self, start: sv.Point, end: sv.Point, frame_rate: int = 15) -> None:
        # frame_rate debe ser el FPS real del pipeline (MEJORAS.md punto 14):
        # ByteTrack calcula max_time_lost = frame_rate/30 * lost_track_buffer,
        # así que con el default (30) y un stream real a ~15 FPS el buffer
        # efectivo en segundos era el doble del esperado.
        self._byte_tracker = sv.ByteTrack(lost_track_buffer=60, frame_rate=frame_rate)
        # Suaviza las bboxes entre frames (MEJORAS.md Bajas): menos jitter
        # visual y menos cruces falsos — complementa minimum_crossing_threshold.
        self._smoother = sv.DetectionsSmoother(length=5)
        # BOTTOM_CENTER (los pies) cruza la línea de forma más fiable que el
        # centro de la caja, que oscila con los brazos/postura (MEJORAS.md Bajas).
        self._line_zone = sv.LineZone(
            start=start,
            end=end,
            triggering_anchors=[sv.Position.BOTTOM_CENTER],
            minimum_crossing_threshold=self.CROSSING_THRESHOLD,
        )

        self._box_annotator = sv.BoxAnnotator(thickness=1)
        self._label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)
        # Estela del recorrido de cada track — depuración visual de la línea
        # de conteo (MEJORAS.md Bajas).
        self._trace_annotator = sv.TraceAnnotator(trace_length=30, thickness=1)

        self._in_count = 0
        self._out_count = 0
        self._crossed_ids: set[int] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, detections: sv.Detections) -> tuple[sv.Detections, list[dict[str, Any]]]:
        """
        Update ByteTrack with *detections*, trigger the line zone, and
        accumulate crossing counts.

        Returns ``(tracked_detections, crossings)`` where *crossings* is a
        list of ``{"direction": "in"|"out", "timestamp": datetime}`` dicts
        for each new crossing in this frame — ready to persist to the DB.

        LineZone already deduplicates per tracker_id (it keeps crossing state
        per track and only fires on real state changes), so every True in
        crossed_in/crossed_out is a genuine new crossing: a person entering
        and later leaving produces one "in" AND one "out" event.
        ``_crossed_ids`` only tracks distinct persons for the "total" count
        and must never gate the directional counters.
        """
        tracked = self._byte_tracker.update_with_detections(detections)
        if tracked.tracker_id is not None:
            tracked = self._smoother.update_with_detections(tracked)
        crossed_in, crossed_out = self._line_zone.trigger(tracked)
        ids = tracked.tracker_id if tracked.tracker_id is not None else []
        crossings: list[dict[str, Any]] = []
        now = datetime.datetime.now()
        with self._lock:
            for i, tid in enumerate(ids):
                if crossed_in[i]:
                    self._in_count += 1
                    self._crossed_ids.add(int(tid))
                    crossings.append({"direction": "in", "timestamp": now, "tracker_id": int(tid)})
                elif crossed_out[i]:
                    self._out_count += 1
                    self._crossed_ids.add(int(tid))
                    crossings.append({"direction": "out", "timestamp": now, "tracker_id": int(tid)})
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

    def get_counts(self) -> dict[str, int]:
        """Return cumulative ``{"in": N, "out": N, "total": N}`` counts."""
        with self._lock:
            return {
                "in": self._in_count,
                "out": self._out_count,
                "total": len(self._crossed_ids),
            }

    def reconfigure_line(self, start: sv.Point, end: sv.Point) -> None:
        """Replace the LineZone with new pixel coordinates. Thread-safe."""
        with self._lock:
            self._line_zone = sv.LineZone(
                start=start,
                end=end,
                triggering_anchors=[sv.Position.BOTTOM_CENTER],
                minimum_crossing_threshold=self.CROSSING_THRESHOLD,
            )
