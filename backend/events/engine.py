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
import time
from typing import TYPE_CHECKING, Any

from backend.events.bus import EventBus
from backend.events.types import Event, EventType, Severity
from backend.perception.behavior import BehaviorFinding, BehaviorKind
from backend.perception.face.identity import IdentityState, IdentityTransition
from backend.storage.repositories import DetectionStatRepo

if TYPE_CHECKING:
    from backend.observability.latency import LatencyTracker


_BEHAVIOR_EVENT_TYPE: dict[BehaviorKind, EventType] = {
    BehaviorKind.LOITERING: EventType.LOITERING,
    BehaviorKind.RUNNING: EventType.RUNNING,
    BehaviorKind.IMMOBILE: EventType.IMMOBILE,
    BehaviorKind.CROWD: EventType.CROWD_DETECTED,
}


class EventEngine:
    def __init__(
        self, bus: EventBus, camera_id: str = "cam1", latency_tracker: LatencyTracker | None = None
    ) -> None:
        self._bus = bus
        self._camera_id = camera_id
        self._latency_tracker = latency_tracker

        self._known_tracks: set[int] = set()
        self._zone_inside: dict[str, set[int]] = {}
        self._zone_entry_at: dict[str, dict[int, float]] = {}
        self._camera_offline = False

        self._minute_buckets: dict[datetime.datetime, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def _publish(
        self,
        event_type: EventType,
        ts: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
        **fields: Any,
    ) -> None:
        """captured_at/processed_at are monotonic timestamps for OBS-03 latency tracking —
        stashed under private payload keys, never part of the public Event contract
        (21-CONTEXT.md). _emitted_at is set unconditionally so downstream (the WebSocket
        broadcast handler) can always measure the EVENT_TO_WS stage."""
        payload = dict(fields.pop("payload", None) or {})
        emitted_at = time.monotonic()
        payload["_emitted_at"] = emitted_at
        if captured_at is not None:
            payload["_captured_at"] = captured_at
        event = Event(type=event_type, camera_id=self._camera_id, ts=ts, payload=payload, **fields)
        self._bus.publish_threadsafe(event)
        if self._latency_tracker is not None and processed_at is not None:
            self._latency_tracker.mark_event(captured_at or 0.0, processed_at)

    # ------------------------------------------------------------------
    # Line crossings (LineZone, Fase 17-18)
    # ------------------------------------------------------------------

    def emit_line_crossing(
        self, crossing: dict[str, Any], captured_at: float | None = None, processed_at: float | None = None
    ) -> None:
        self._publish(
            EventType.LINE_CROSSED,
            ts=crossing["timestamp"],
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=crossing.get("tracker_id"),
            payload={
                "direction": crossing["direction"],
                "is_intrusion": bool(crossing.get("is_intrusion", False)),
            },
        )

    # ------------------------------------------------------------------
    # Track lifecycle
    # ------------------------------------------------------------------

    def process_tracks(
        self,
        active_track_ids: set[int],
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Diff against the last known set of active tracks; emit only on transitions."""
        entered = active_track_ids - self._known_tracks
        exited = self._known_tracks - active_track_ids
        for track_id in entered:
            self._publish(
                EventType.PERSON_ENTERED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id,
            )
        for track_id in exited:
            self._publish(
                EventType.PERSON_EXITED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id,
            )
        self._known_tracks = set(active_track_ids)

    # ------------------------------------------------------------------
    # Zone membership
    # ------------------------------------------------------------------

    def process_zone(
        self,
        zone_id: str,
        inside_track_ids: set[int],
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
        now_monotonic: float | None = None,
    ) -> None:
        previous = self._zone_inside.get(zone_id, set())
        entered = inside_track_ids - previous
        exited = previous - inside_track_ids
        entry_at = self._zone_entry_at.setdefault(zone_id, {})
        for track_id in entered:
            if now_monotonic is not None:
                entry_at[track_id] = now_monotonic
            self._publish(
                EventType.ZONE_ENTERED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id, zone_id=zone_id,
            )
        for track_id in exited:
            t0 = entry_at.pop(track_id, None)  # el pop ES la politica de limpieza (T-26-08)
            payload: dict[str, Any] = {}
            if t0 is not None and now_monotonic is not None:
                payload["duration_s"] = round(now_monotonic - t0, 3)  # BEH-04
            self._publish(
                EventType.ZONE_EXITED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id, zone_id=zone_id,
                payload=payload,
            )
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
    # Identidad (Fase 24)
    # ------------------------------------------------------------------

    @staticmethod
    def _identity_event_type(transition: IdentityTransition) -> EventType | None:
        """Traduce una transicion de la FSM al catalogo de SPEC_v2.md §6.1.

        No hay tipo de evento para CANDIDATE ni para TEMPORARILY_LOST: son estados
        intermedios que la UI leera del TrackRegistry (bloque C), no eventos.
        """
        if transition.to_state is IdentityState.CONFIRMED:
            return EventType.PERSON_RECOGNIZED
        if transition.to_state is IdentityState.UNKNOWN:
            if transition.from_state is IdentityState.CANDIDATE:
                return EventType.UNKNOWN_PERSON
            if transition.from_state in (IdentityState.CONFIRMED,
                                         IdentityState.TEMPORARILY_LOST):
                return EventType.IDENTITY_LOST
        return None

    def emit_identity(
        self,
        transition: IdentityTransition,
        now: datetime.datetime,
        person_name: str | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Publica el evento de identidad correspondiente a *transition*, si lo hay.

        FACE-09: una visita genera un unico evento de reconocimiento. La guarda de
        idempotencia vive en la FSM, que marca `emits=False` cuando el cambio de estado
        es continuacion de la misma visita (recuperacion de un track dentro de
        lost_ttl) o cuando el evento ya se emitio para ese track.
        """
        if not transition.emits:
            return
        event_type = self._identity_event_type(transition)
        if event_type is None:
            return
        self._publish(
            event_type,
            ts=now,
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=transition.track_id,
            person_id=transition.person_id,
            person_name=person_name,
            confidence=transition.confidence or None,
            bbox=bbox,
            payload={
                "state": transition.to_state.value,
                "previous_state": transition.from_state.value,
                "votes": transition.votes,
                "window": transition.window,
            },
        )

    # ------------------------------------------------------------------
    # Comportamiento (Fase 26)
    # ------------------------------------------------------------------

    def emit_behavior(
        self,
        finding: BehaviorFinding,
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Publica el evento de comportamiento correspondiente a *finding*, si lo hay.

        La guarda de idempotencia NO esta aqui: vive en el latch por episodio de
        BehaviorAnalyzer, igual que `emits` vive en la FSM para emit_identity. Sin ese
        latch, una persona parada 10 min generaria ~4.800 IMMOBILE a 8 FPS — "the point
        where v1 failed conceptually" (docstring de esta clase).
        """
        event_type = _BEHAVIOR_EVENT_TYPE.get(finding.kind)
        if event_type is None:
            return
        self._publish(
            event_type,
            ts=now,
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=finding.track_id,
            zone_id=finding.zone_id,
            payload=finding.magnitudes(),
        )

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
