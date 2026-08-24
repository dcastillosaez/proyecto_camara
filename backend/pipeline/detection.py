"""DetectionWorker — YOLO + ByteTrack + zonas + heatmap, con ritmo propio.

Porta la parte de deteccion/tracking/zonas/heatmap de
RTSPStream._process_frame (Fase 17) a un worker independiente que
consume del FrameBroker a su propio ritmo, gobernado por AdaptiveRate
en vez del contador fijo detect_every (SPEC_v2.md §5.3, 18-CONTEXT.md).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import supervision as sv

from backend.observability.metrics import metrics as _metrics
from backend.perception.objects import ObjectObservation, PersonObservation
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.observability.latency import LatencyTracker
    from backend.perception.behavior import BehaviorAnalyzer
    from backend.perception.objects import ObjectAnalyzer
    from backend.pipeline.broker import Subscription
    from backend.tracker import ObjectTracker, PersonTracker

logger = logging.getLogger(__name__)

PERSON_CLASS_IDS = (0,)   # la clase persona nunca entra en el tracker de objetos: es la
                          # dueña del LineZone (Fase 4), de la identidad (Fases 23/24),
                          # del ReID (Fase 25) y del analisis de comportamiento (Fase 26)


class DetectionWorker:
    """
    Consume frames del broker, ejecuta YOLO + ByteTrack a su FPS objetivo
    (ajustado por AdaptiveRate segun la latencia real) y publica el
    resultado en un TrackRegistry compartido.

    No conoce a los demas workers: escribe en el registry y en la cola de
    eventos existente; StreamingWorker y RecognitionWorker leen del
    registry por su cuenta (18-CONTEXT.md, "TrackRegistry es el punto de
    encuentro").
    """

    def __init__(
        self,
        sub: Subscription,
        detector: PersonDetector,
        tracker: PersonTracker,
        registry: TrackRegistry,
        rate: AdaptiveRate,
        event_engine: EventEngine | None = None,
        is_intrusion: Any = None,
        camera_id: str = "cam1",
        latency_tracker: LatencyTracker | None = None,
        behavior: "BehaviorAnalyzer | None" = None,
        object_tracker: "ObjectTracker | None" = None,
        object_class_ids: set[int] | None = None,
        objects: "ObjectAnalyzer | None" = None,
    ) -> None:
        self._sub = sub
        self._detector = detector
        self._tracker = tracker
        self._registry = registry
        self._rate = rate
        self._event_engine = event_engine
        self._camera_id = camera_id
        self._latency_tracker = latency_tracker
        self._behavior = behavior
        self._object_tracker = object_tracker
        self._objects = objects
        self._object_class_ids: frozenset[int] = frozenset(object_class_ids or ())
        # Callable[[], bool] opcional — decide si un cruce es intrusion
        # (RTSPStream._is_in_schedule). Sin ella, nunca se marca intrusion.
        self._is_intrusion = is_intrusion

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_effective_fps: float | None = None
        self._frames_processed = 0
        self._exceptions = 0

        self._lock = threading.Lock()
        self._zones: list[dict] = []
        self._zones_dirty = True
        self._zone_states: list[dict] = []
        self._zone_frame_size: tuple[int, int] = (0, 0)
        self._heat_mask: np.ndarray | None = None
        self._object_boxes: list[dict] = []      # ultima foto de objetos trackeados;
                                                 # writer: hilo de deteccion,
                                                 # readers: event loop (endpoint de
                                                 # contexto) y StreamingWorker (overlay)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="detection-worker"
        )
        self._thread.start()

    def is_alive(self) -> bool:
        """True si el hilo del worker sigue vivo (lo consulta WorkerSupervisor)."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("DetectionWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()

    @property
    def stats(self) -> dict:
        return {
            "frames_processed": self._frames_processed,
            "exceptions": self._exceptions,
            **self._rate.stats,
        }

    def set_zones(self, zones: list[dict]) -> None:
        """Replace the active interest zones list. Thread-safe."""
        with self._lock:
            self._zones = list(zones)
            self._zones_dirty = True

    def get_zone_stats(self) -> list[dict]:
        with self._lock:
            return [
                {"id": st["id"], "name": st["name"], "current": st["current"], "entries": st["entries"]}
                for st in self._zone_states
            ]

    def set_object_classes(self, class_ids: set[int]) -> None:
        """Ids que van al tracker de OBJETOS. Thread-safe."""
        with self._lock:
            self._object_class_ids = frozenset(class_ids)

    def get_object_stats(self) -> list[dict]:
        """Recuento por class_name de los objetos trackeados en el ultimo frame."""
        with self._lock:
            boxes = list(self._object_boxes)
        counts: dict[str, int] = {}
        for b in boxes:
            counts[b["class_name"]] = counts.get(b["class_name"], 0) + 1
        return [{"class_name": k, "count": v} for k, v in sorted(counts.items())]

    def get_object_boxes(self) -> list[dict]:
        """Cajas de objeto del ultimo frame, para el overlay del MJPEG. Thread-safe."""
        with self._lock:
            return [dict(b) for b in self._object_boxes]

    def compose_heatmap(self, frame: np.ndarray) -> np.ndarray | None:
        """Compose the accumulated activity heat map over *frame*. Heavy — call off the event loop."""
        with self._lock:
            mask = None if self._heat_mask is None else self._heat_mask.copy()
        if mask is None:
            return None
        peak = float(mask.max())
        if peak <= 0:
            return None
        if mask.shape != frame.shape[:2]:
            mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
        temp = np.clip(mask / peak * 255.0, 0, 255).astype(np.uint8)
        temp = cv2.blur(temp, (25, 25))
        # D-13: INFERNO es monotona en luminosidad, se ordena bien en escala de
        # grises y su extremo bajo se funde con el frame; JET es arcoiris, no
        # perceptualmente uniforme, y su extremo azul oscuro desaparece sobre
        # un frame nocturno.
        colored = cv2.applyColorMap(temp, cv2.COLORMAP_INFERNO)
        blended = cv2.addWeighted(frame, 0.5, colored, 0.5, 0)
        active = temp > 0
        out = frame.copy()
        out[active] = blended[active]
        return out

    def heatmap_scale(self) -> dict[str, float] | None:
        """Pico y media de la mascara acumulada, para la leyenda numerica del panel de analitica.

        La escala es SIEMPRE relativa (D-12/D-13): compose_heatmap normaliza dividiendo
        por el pico, asi que el extremo de la rampa es el 100 % de esta mascara, no una
        cifra de personas. La unidad de estos numeros es "frames de deteccion con
        presencia" (disco de 40 px por track y frame), no visitantes.

        Devuelve None cuando no hay mascara o su pico es 0 - mismo criterio que
        compose_heatmap, para que el endpoint pueda distinguir 404 (sin actividad)
        de 503 (sin frame).
        """
        with self._lock:
            mask = None if self._heat_mask is None else self._heat_mask.copy()
        if mask is None:
            return None
        peak = float(mask.max())
        if peak <= 0:
            return None
        return {"peak": peak, "mean": float(mask.mean())}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not self._rate.should_process(time.monotonic()):
                continue

            t0 = time.monotonic()
            try:
                sv_dets = self._detector.detect_sv(frame.image)
                # ─── Particion por clase ANTES del tracker (Fase 27, 27-RESEARCH Q4) ───
                # sv.ByteTrack es class-agnostic: el class_id no llega al matcher
                # (core.py:104-110) y el id puede transferirse entre clases cuando las
                # cajas se solapan (reproducido). Mandar sv_dets completo a
                # PersonTracker haria que un coche cruzando la linea sumara al conteo de
                # personas de la Fase 4, que esta en produccion.
                person_dets, object_dets = self._split_by_class(sv_dets)
                tracked, crossings = self._tracker.update(person_dets)
                obj_tracked = (
                    self._object_tracker.update(object_dets)
                    if self._object_tracker is not None
                    else None
                )
            except Exception:
                self._exceptions += 1
                logger.exception("DetectionWorker: fallo de inferencia, se salta el frame")
                continue

            inference_latency = time.monotonic() - t0
            self._rate.observe(inference_latency)
            _metrics.inference_latency_seconds.labels(stage="yolo").observe(inference_latency)
            self._frames_processed += 1
            self._sync_tracker_frame_rate()

            if self._latency_tracker is not None:
                self._latency_tracker.mark_processed(frame)

            now = time.monotonic()  # "processed_at" for OBS-03 — right after inference, before event emission
            _metrics.active_tracks.labels(camera=self._camera_id).set(len(tracked))
            self._registry.update_from_detections(tracked, now)
            self._update_zones_and_heat(tracked, frame.image.shape, frame.captured_at, now)
            self._analyze_behavior(tracked, frame.captured_at, now)      # NUEVO (Fase 26)
            self._analyze_objects(obj_tracked, tracked, frame.captured_at, now)  # NUEVO (Fase 27)
            self._update_object_boxes(obj_tracked)
            self._emit_crossings(crossings, frame.captured_at, now)
            self._emit_track_lifecycle(tracked, frame.captured_at, now)
            self._registry.prune(now)

    def _split_by_class(self, dets: sv.Detections) -> tuple[sv.Detections, sv.Detections]:
        """Separa personas y objetos. El slicing preserva data["class_name"] (verificado
        en 27-RESEARCH.md, medicion 2 de H-1), asi que el nombre de clase para el payload
        del evento sale del modelo y no de un mapa COCO escrito a mano."""
        cls = dets.class_id
        with self._lock:
            object_ids = self._object_class_ids
        if cls is None or len(dets) == 0:
            return dets, dets[:0]
        person_dets = dets[np.isin(cls, PERSON_CLASS_IDS)]
        object_dets = dets[np.isin(cls, list(object_ids))] if object_ids else dets[:0]
        return person_dets, object_dets

    def _update_object_boxes(self, obj_tracked: sv.Detections | None) -> None:
        """Refresca la foto de objetos trackeados bajo self._lock. Sin foto anterior
        si no hay objetos en este frame: conservarla mentiria al overlay."""
        boxes: list[dict] = []
        if obj_tracked is not None and len(obj_tracked) and obj_tracked.tracker_id is not None:
            names = obj_tracked.data.get("class_name") if obj_tracked.data else None
            for i, tid in enumerate(obj_tracked.tracker_id):
                class_id = int(obj_tracked.class_id[i]) if obj_tracked.class_id is not None else -1
                class_name = str(names[i]) if names is not None else str(class_id)
                x1, y1, x2, y2 = obj_tracked.xyxy[i]
                boxes.append({
                    "track_id": int(tid),
                    "class_id": class_id,
                    "class_name": class_name,
                    "bbox": (float(x1), float(y1), float(x2), float(y2)),
                })
        with self._lock:
            self._object_boxes = boxes

    def _analyze_behavior(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        """Analisis de comportamiento del frame (Fase 26, BEH-01..BEH-05).

        Patron de aislamiento de fallos de RecognitionWorker._sync_identity
        (recognition.py:366-374): un fallo del analizador nunca mata el hilo de
        deteccion, solo incrementa el contador de excepciones que ya expone
        /api/v2/cameras/{id}/health.
        """
        if self._behavior is None or self._event_engine is None:
            return
        ids = tracked.tracker_id
        if ids is None:
            return
        try:
            centroids: dict[int, tuple[float, float]] = {}
            histories: dict[int, Any] = {}
            for i, tid in enumerate(ids):
                tid = int(tid)
                x1, y1, x2, y2 = map(int, tracked.xyxy[i])
                centroids[tid] = ((x1 + x2) / 2, (y1 + y2) / 2)   # igual que tracking.py:66
                st = self._registry.get(tid)
                if st is not None:
                    histories[tid] = st.centroid_history          # por referencia, sin copiar
            findings = self._behavior.analyze(
                centroids=centroids,
                zone_membership=self._zone_membership_snapshot(),
                histories=histories,
                now=processed_at,                                 # monotonico del frame
            )
            self._behavior.prune(processed_at, set(centroids))
        except Exception:
            self._exceptions += 1
            logger.exception("DetectionWorker: analisis de comportamiento fallo")
            return
        wall_now = datetime.datetime.now()
        for f in findings:
            self._event_engine.emit_behavior(f, wall_now, captured_at, processed_at)

    def _analyze_objects(self, obj_tracked: Any, tracked: Any, captured_at: float, processed_at: float) -> None:
        """Analisis de objetos abandonados/retirados del frame (Fase 27, BEH-07).

        Mismo patron de aislamiento de fallos que _analyze_behavior (que a su vez viene de
        RecognitionWorker._sync_identity, recognition.py:366-374): un fallo del analizador
        nunca mata el hilo de deteccion, solo incrementa el contador de excepciones que ya
        expone /api/v2/cameras/{id}/health.

        Las distancias se miden entre anclas BOTTOM_CENTER, no entre centroides: una
        mochila en el suelo junto a una persona de pie tiene el centroide desplazado media
        altura de persona aunque se esten tocando (27-RESEARCH.md Q1). Es la misma
        convencion que ya usan el LineZone (tracker.py:41) y el heatmap (linea 312).
        """
        if self._objects is None or self._event_engine is None or obj_tracked is None:
            return
        obj_ids = obj_tracked.tracker_id
        if obj_ids is None:
            return
        try:
            excluded = self._excluded_object_ids(obj_tracked)
            zone_of = self._object_zone_ids(obj_tracked)
            names = obj_tracked.data.get("class_name") if obj_tracked.data else None
            anchors = obj_tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)
            observations: list[ObjectObservation] = []
            for i, raw_tid in enumerate(obj_ids):
                tid = int(raw_tid)
                x, y = anchors[i]
                class_id = int(obj_tracked.class_id[i]) if obj_tracked.class_id is not None else -1
                class_name = str(names[i]) if names is not None else str(class_id)
                x1, y1, x2, y2 = obj_tracked.xyxy[i]
                observations.append(ObjectObservation(
                    track_id=tid, x=float(x), y=float(y),
                    class_id=class_id, class_name=class_name,
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    zone_id=zone_of.get(tid),
                    excluded=tid in excluded,
                ))
            persons: list[PersonObservation] = []
            person_ids = tracked.tracker_id
            if person_ids is not None and len(tracked):
                person_anchors = tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)
                for i, raw_tid in enumerate(person_ids):
                    px, py = person_anchors[i]
                    y1, y2 = tracked.xyxy[i][1], tracked.xyxy[i][3]
                    persons.append(PersonObservation(
                        track_id=int(raw_tid), x=float(px), y=float(py),
                        height_px=float(y2 - y1),
                    ))
            findings = self._objects.analyze(observations, persons, processed_at)
            findings += self._objects.prune(processed_at, {int(t) for t in obj_ids})
        except Exception:
            self._exceptions += 1
            logger.exception("DetectionWorker: analisis de objetos fallo")
            return
        wall_now = datetime.datetime.now()
        for f in findings:
            self._event_engine.emit_object(f, wall_now, captured_at, processed_at)

    def _excluded_object_ids(self, obj_tracked: Any) -> set[int]:
        """Ids de objeto que caen dentro de una zona kind == "exclude_objects".

        Se usa sv.PolygonZone.trigger() sobre los mismos _zone_states que ya existen en
        vez de escribir un test punto-en-poligono propio: recalcularlo duplicaria la
        inferencia geometrica y podria divergir del conteo de get_zone_stats()
        (mismo motivo que _zone_membership_snapshot, linea 229).
        """
        ids = obj_tracked.tracker_id
        excluded: set[int] = set()
        if ids is None or len(obj_tracked) == 0:
            return excluded
        with self._lock:
            states = list(self._zone_states)
        for st in states:
            if st.get("kind") != "exclude_objects":
                continue
            mask = st["zone"].trigger(obj_tracked)
            if len(mask):
                excluded |= {int(ids[i]) for i in np.flatnonzero(mask)}
        return excluded

    def _object_zone_ids(self, obj_tracked: Any) -> dict[int, str | None]:
        """Zona en la que cae cada objeto, para el zone_id del evento. None = escena."""
        ids = obj_tracked.tracker_id
        if ids is None or len(obj_tracked) == 0:
            return {}
        zone_of: dict[int, str | None] = {int(t): None for t in ids}
        with self._lock:
            states = list(self._zone_states)
        for st in states:
            mask = st["zone"].trigger(obj_tracked)
            if len(mask):
                for i in np.flatnonzero(mask):
                    zone_of[int(ids[i])] = st["id"]
        return zone_of

    def _zone_membership_snapshot(self) -> dict[str, set[int]]:
        """Track ids por zona de ESTE frame, reutilizando `st["inside"]` (T-26-*).

        `st["inside"]` ya lo calculo `_update_zones_and_heat` con
        `sv.PolygonZone.trigger()` en este mismo frame. Recalcularlo aqui
        duplicaria la inferencia geometrica y podria divergir del conteo de
        `get_zone_stats()`.
        """
        with self._lock:
            return {st["id"]: set(st["inside"]) for st in self._zone_states}

    def _emit_track_lifecycle(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        """Publica el estado de tracks del frame actual y, si hay event_engine,
        los eventos de ciclo de vida. Son dos cosas distintas (Fase 24, D-05):
        la publicacion en el registry siempre ocurre; la emision de eventos,
        solo si hay event_engine configurado (CameraPipeline lo tiene a None por
        defecto en la mayoria de tests de este fichero). Si set_frame_ids
        quedara detras de la guarda de event_engine, RecognitionWorker.
        _sync_identity veria frame_ids() vacio en cada ciclo y reportaria todo
        track CONFIRMED como perdido de inmediato.
        """
        ids = tracked.tracker_id
        active_ids = {int(tid) for tid in ids} if ids is not None else set()
        self._registry.set_frame_ids(active_ids)
        if self._event_engine is None:
            return
        wall_now = datetime.datetime.now()
        self._event_engine.process_tracks(active_ids, wall_now, captured_at, processed_at)
        confidences = list(tracked.confidence) if tracked.confidence is not None else []
        self._event_engine.accumulate_detections(wall_now, active_ids, confidences)

    def _sync_tracker_frame_rate(self) -> None:
        """Si AdaptiveRate cambio de escalon, sincroniza ByteTrack (riesgo #1 de la fase)."""
        fps = self._rate.effective_fps
        if fps != self._last_effective_fps:
            self._last_effective_fps = fps
            self._tracker.set_frame_rate(fps)
            if self._object_tracker is not None:
                self._object_tracker.set_frame_rate(fps)   # si no, el tracker de objetos
                                                           # queda desincronizado del FPS real

    def _emit_crossings(self, crossings: list[dict], captured_at: float, processed_at: float) -> None:
        if not crossings or self._event_engine is None:
            return
        is_intrusion = bool(self._is_intrusion()) if self._is_intrusion else False
        for c in crossings:
            self._event_engine.emit_line_crossing(
                {**c, "is_intrusion": is_intrusion}, captured_at, processed_at
            )

    def _update_zones_and_heat(
        self, tracked: Any, shape: tuple, captured_at: float = 0.0, processed_at: float = 0.0
    ) -> None:
        """Trigger the PolygonZones and accumulate the activity heat mask (MEJORAS.md Bajas)."""
        fh, fw = shape[:2]
        with self._lock:
            dirty = self._zones_dirty
            self._zones_dirty = False
            zones_snap = list(self._zones)
        if dirty or self._zone_frame_size != (fw, fh):
            self._zone_frame_size = (fw, fh)
            self._rebuild_zone_states(zones_snap, fw, fh)

        ids = tracked.tracker_id
        for st in self._zone_states:
            mask = st["zone"].trigger(tracked)
            inside = (
                {int(ids[i]) for i in np.flatnonzero(mask)}
                if ids is not None and len(mask)
                else set()
            )
            with self._lock:
                st["entries"] += len(inside - st["inside"])
                st["inside"] = inside
                st["current"] = len(inside)
            if self._event_engine is not None:
                self._event_engine.process_zone(
                    st["id"], inside, datetime.datetime.now(), captured_at, processed_at,
                    now_monotonic=processed_at,
                )

        if len(tracked) == 0:
            return
        if self._heat_mask is None or self._heat_mask.shape != (fh, fw):
            self._heat_mask = np.zeros((fh, fw), dtype=np.float32)
        pts_mask = np.zeros((fh, fw), dtype=np.float32)
        for xy in tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER):
            cv2.circle(pts_mask, (int(xy[0]), int(xy[1])), 40, 1, -1)
        self._heat_mask += pts_mask

    def _rebuild_zone_states(self, zones: list[dict], fw: int, fh: int) -> None:
        states: list[dict] = []
        for z in zones:
            if not z.get("enabled", True):
                continue
            try:
                pts = np.array(
                    [[int(p[0] * fw), int(p[1] * fh)] for p in json.loads(z["polygon_json"])],
                    dtype=np.int64,
                )
                if len(pts) < 3:
                    continue
                states.append({
                    "id": z["id"],
                    "name": z["name"],
                    "kind": z.get("kind"),
                    "polygon": pts,
                    "zone": sv.PolygonZone(polygon=pts),
                    "inside": set(),
                    "entries": 0,
                    "current": 0,
                })
            except Exception:
                logger.warning("DetectionWorker: zone %s invalid polygon_json, skipped", z.get("id"))
        with self._lock:
            self._zone_states = states
