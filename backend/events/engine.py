"""EventEngine: converts raw pipeline state into typed, transition-only events.

One event per transition, never per frame — this is the point where v1 failed
conceptually. Keeps the previous state of every track (zones, presence) in
memory and only emits when that state actually changes. Also accumulates
detections per minute so ``detection_stats`` never gets one row per detection.

Every public method except ``flush_stats`` is synchronous and safe to call from
a worker thread (Phase 18 pipeline workers) — it publishes via
``EventBus.publish_threadsafe``.
"""

from __future__ import annotations

import datetime
from typing import Any

from backend.events.bus import EventBus
from backend.events.types import Event, EventType, Severity
from backend.storage.repositories import DetectionStatRepo


class EventEngine:
    def __init__(self, bus: EventBus, camera_id: str = "cam1") -> None:
        self._bus = bus
        self._camera_id = camera_id

        self._known_tracks: set[int] = set()
        self._zone_inside: dict[str, set[int]] = {}
        self._camera_offline = False

        self._minute_buckets: dict[datetime.datetime, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def _publish(self, event_type: EventType, ts: datetime.datetime, **fields: Any) -> None:
        event = Event(type=event_type, camera_id=self._camera_id, ts=ts, **fields)
        self._bus.publish_threadsafe(event)

    # ------------------------------------------------------------------
    # Line crossings (LineZone, Fase 17-18)
    # ------------------------------------------------------------------

    def emit_line_crossing(self, crossing: dict[str, Any]) -> None:
        self._publish(
            EventType.LINE_CROSSED,
            ts=crossing["timestamp"],
            track_id=crossing.get("tracker_id"),
            payload={
                "direction": crossing["direction"],
                "is_intrusion": bool(crossing.get("is_intrusion", False)),
            },
        )

    # ------------------------------------------------------------------
    # Track lifecycle
    # ------------------------------------------------------------------

    def process_tracks(self, active_track_ids: set[int], now: datetime.datetime) -> None:
        """Diff against the last known set of active tracks; emit only on transitions."""
        entered = active_track_ids - self._known_tracks
        exited = self._known_tracks - active_track_ids
        for track_id in entered:
            self._publish(EventType.PERSON_ENTERED, ts=now, track_id=track_id)
        for track_id in exited:
            self._publish(EventType.PERSON_EXITED, ts=now, track_id=track_id)
        self._known_tracks = set(active_track_ids)

    # ------------------------------------------------------------------
    # Zone membership
    # ------------------------------------------------------------------

    def process_zone(self, zone_id: str, inside_track_ids: set[int], now: datetime.datetime) -> None:
        previous = self._zone_inside.get(zone_id, set())
        entered = inside_track_ids - previous
        exited = previous - inside_track_ids
        for track_id in entered:
            self._publish(EventType.ZONE_ENTERED, ts=now, track_id=track_id, zone_id=zone_id)
        for track_id in exited:
            self._publish(EventType.ZONE_EXITED, ts=now, track_id=track_id, zone_id=zone_id)
        self._zone_inside[zone_id] = set(inside_track_ids)

    # ------------------------------------------------------------------
    # Camera health (CaptureWorker / WorkerSupervisor)
    # ------------------------------------------------------------------

    def camera_offline(self, now: datetime.datetime) -> None:
        if self._camera_offline:
            return
        self._camera_offline = True
        self._publish(EventType.CAMERA_OFFLINE, ts=now, severity=Severity.CRITICAL)

    def camera_recovered(self, now: datetime.datetime) -> None:
        if not self._camera_offline:
            return
        self._camera_offline = False
        self._publish(EventType.CAMERA_RECOVERED, ts=now)

    def degraded_mode(self, now: datetime.datetime, reason: str) -> None:
        self._publish(EventType.DEGRADED_MODE, ts=now, severity=Severity.WARNING, payload={"reason": reason})

    # ------------------------------------------------------------------
    # Detection aggregation — one row per minute, never per detection (ADR-06)
    # ------------------------------------------------------------------

    def accumulate_detections(
        self, ts: datetime.datetime, active_track_ids: set[int], confidences: list[float]
    ) -> None:
        minute = ts.replace(second=0, microsecond=0)
        bucket = self._minute_buckets.setdefault(minute, {
            "detections": 0, "unique_tracks": set(), "confidence_sum": 0.0,
            "confidence_n": 0, "max_concurrent": 0,
        })
        bucket["detections"] += len(active_track_ids)
        bucket["unique_tracks"] |= active_track_ids
        bucket["max_concurrent"] = max(bucket["max_concurrent"], len(active_track_ids))
        for confidence in confidences:
            bucket["confidence_sum"] += confidence
            bucket["confidence_n"] += 1

    async def flush_stats(self, stat_repo: DetectionStatRepo, now: datetime.datetime) -> int:
        """Persist every completed minute bucket (strictly before *now*'s minute). Returns count flushed."""
        current_minute = now.replace(second=0, microsecond=0)
        due = sorted(m for m in self._minute_buckets if m < current_minute)
        for minute in due:
            bucket = self._minute_buckets.pop(minute)
            avg_confidence = (
                bucket["confidence_sum"] / bucket["confidence_n"] if bucket["confidence_n"] else None
            )
            await stat_repo.upsert_minute(
                self._camera_id, minute, bucket["detections"], len(bucket["unique_tracks"]),
                avg_confidence, bucket["max_concurrent"],
            )
        return len(due)
