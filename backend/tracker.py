"""ByteTrack person tracking and LineZone crossing counter."""

import threading

import numpy as np
import supervision as sv


class PersonTracker:
    """
    Assigns persistent IDs to detected persons (ByteTrack) and counts how
    many cross a configurable virtual line in each direction (LineZone).

    Thread-safe: ``update`` and ``get_counts`` can be called from the RTSP
    capture thread while ``get_counts`` is read from an async endpoint.
    """

    def __init__(self, start: sv.Point, end: sv.Point) -> None:
        self._byte_tracker = sv.ByteTrack()
        self._line_zone = sv.LineZone(start=start, end=end)

        self._box_annotator = sv.BoxAnnotator(thickness=2)
        self._label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)
        self._line_annotator = sv.LineZoneAnnotator(
            thickness=2,
            text_scale=0.5,
            custom_in_text="IN",
            custom_out_text="OUT",
        )

        self._in_count = 0
        self._out_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, detections: sv.Detections) -> sv.Detections:
        """
        Update ByteTrack with *detections*, trigger the line zone, and
        accumulate crossing counts.  Returns detections enriched with
        ``tracker_id``.
        """
        tracked = self._byte_tracker.update_with_detections(detections)
        crossed_in, crossed_out = self._line_zone.trigger(tracked)
        with self._lock:
            self._in_count += int(crossed_in.sum())
            self._out_count += int(crossed_out.sum())
        return tracked

    def annotate(self, frame: np.ndarray, tracked: sv.Detections) -> np.ndarray:
        """
        Draw bounding boxes, tracker-ID / confidence labels, and the
        counting line (with live IN/OUT counters) onto a copy of *frame*.
        """
        labels = [
            f"#{tid} {conf:.2f}"
            for tid, conf in zip(
                tracked.tracker_id if tracked.tracker_id is not None else [],
                tracked.confidence if tracked.confidence is not None else [],
            )
        ]
        out = self._box_annotator.annotate(frame.copy(), tracked)
        out = self._label_annotator.annotate(out, tracked, labels=labels)
        out = self._line_annotator.annotate(out, self._line_zone)
        return out

    def get_counts(self) -> dict[str, int]:
        """Return cumulative ``{"in": N, "out": N, "total": N}`` counts."""
        with self._lock:
            return {
                "in": self._in_count,
                "out": self._out_count,
                "total": self._in_count + self._out_count,
            }
