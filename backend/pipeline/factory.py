"""Factoria de CameraPipeline — construye el stack completo (detector, tracker,
event_engine y recording_config) de UNA camara a partir de su catalogo y de
los servicios compartidos del proceso.

Usada tanto en el arranque (`main.py`, una llamada por fila de `CameraRepo`)
como en el alta en caliente (`POST /api/v2/cameras`, Fase 36) — es el unico
sitio que sabe construir una `CameraPipeline` de produccion, para que ambos
caminos no diverjan.

Cada camara nueva recibe su PROPIO `detector`/`tracker` (nunca se comparte un
modelo YOLO entre pipelines, ver riesgo de CPU en SPEC_v2.md Fase 36) y su
PROPIO `EventEngine` (bug corregido en la Fase 36: antes todas las camaras
compartian un unico EventEngine con `camera_id="cam1"` fijo, asi que un evento
de una segunda camara se habria persistido con el camera_id equivocado). El
`recognizer` (galeria facial) SI se comparte: identificar a la misma persona
da igual por que camara entre.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np

from backend.config import Settings
from backend.detector import PersonDetector
from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.observability.latency import LatencyTracker
from backend.pipeline.manager import CameraManager, CameraPipeline
from backend.recognizer import PersonRecognizer
from backend.storage.repositories import RecordingRepo
from backend.tracker import PersonTracker

logger = logging.getLogger(__name__)


@dataclass
class SharedPipelineServices:
    """Servicios compartidos por TODAS las camaras — construidos una unica vez."""

    settings: Settings
    event_bus: EventBus
    latency_tracker: LatencyTracker
    recognizer: PersonRecognizer | None
    recording_repo: RecordingRepo
    active_classes: list[int]
    is_intrusion: Callable[[], bool]
    on_identified: Callable[[np.ndarray, int], None]
    broadcast: Callable[[dict], Awaitable[None]]
    loop: asyncio.AbstractEventLoop


def build_camera_pipeline(
    camera_manager: CameraManager,
    camera_id: str,
    rtsp_url: str,
    services: SharedPipelineServices,
    *,
    process_size: tuple[int, int] | None = None,
) -> CameraPipeline:
    """Construye, registra en `camera_manager` y devuelve una CameraPipeline lista
    para `.start()`. No arranca la pipeline ni carga zonas/lineas — eso lo decide
    quien llama (el arranque y el alta en caliente lo hacen en momentos distintos)."""
    settings = services.settings

    detector = PersonDetector(
        model_path=settings.yolo_model_path,
        confidence=settings.yolo_confidence,
        classes=services.active_classes,
        label=settings.detection_label,
        imgsz=settings.yolo_imgsz,
    )
    tracker = PersonTracker(frame_rate=settings.tracker_frame_rate)
    event_engine = EventEngine(services.event_bus, camera_id=camera_id, latency_tracker=services.latency_tracker)

    def _on_clip_ready(result) -> None:
        """Corre en el hilo de ensamblado del clip (backend.pipeline.recording.ClipResult)."""
        async def _persist():
            rec_id = await services.recording_repo.create(
                camera_id=camera_id, filename=result.path, started_at=result.started_at,
                reason=result.reason, trigger_event_id=result.trigger_event_id,
                person_id=result.person_id, zone_id=result.zone_id,
            )
            await services.recording_repo.finalize(
                rec_id, ended_at=result.ended_at, duration_s=result.duration_s,
                size_bytes=result.size_bytes, sha256=result.sha256,
                thumbnail_path=result.thumbnail_path, upload_state=result.upload_state,
            )
            await services.broadcast({
                "type": "recording_started",
                "filename": Path(result.path).name,
                "id": rec_id,
            })

        asyncio.run_coroutine_threadsafe(_persist(), services.loop)

    def _on_recording_failure(message: str) -> None:
        logger.error("RecordingWorker failure (%s): %s", camera_id, message)
        event_engine.degraded_mode(datetime.datetime.now(), reason=message)

    recording_config = {
        "clips_dir": settings.clips_dir,
        "thumbnails_dir": "data/thumbnails",
        "fps": settings.recording_fps,
        "pre_buffer_secs": settings.pre_buffer_secs,
        "post_buffer_secs": settings.post_buffer_secs,
        "pre_buffer_max_mb": settings.pre_buffer_max_mb,
        "pre_buffer_jpeg_quality": settings.pre_buffer_jpeg_quality,
        "codec": settings.recording_codec,
        "upload_min_severity": settings.upload_min_severity,
        "on_clip_ready": _on_clip_ready,
        "on_failure": _on_recording_failure,
    }

    pipeline = camera_manager.add(
        camera_id,
        rtsp_url,
        process_size=process_size,
        detector=detector,
        tracker=tracker,
        recognizer=services.recognizer,
        event_engine=event_engine,
        latency_tracker=services.latency_tracker,
        is_intrusion=services.is_intrusion,
        recording_config=recording_config,
        on_identified=services.on_identified,
        detection_fps=(
            settings.detection_target_fps,
            settings.detection_min_fps,
            settings.detection_max_fps,
        ),
        recognition_fps=settings.recognition_target_fps,
        identity_vote_window=settings.identity_vote_window,
        identity_min_votes=settings.identity_min_votes,
        identity_min_ratio=settings.identity_min_ratio,
        identity_lost_ttl=settings.identity_lost_ttl_secs,
        identity_revalidate_after=settings.identity_revalidate_after_secs,
        identity_low_confidence=settings.face_confirm_threshold,
        reid_enabled=settings.reid_enabled,
        reid_model_path=settings.reid_model_path,
        reid_inherit_window=settings.reid_inherit_window_secs,
        reid_similarity_threshold=settings.reid_similarity_threshold,
        reid_interval=settings.reid_interval_secs,
        reid_inherit=settings.reid_inherit_identity,
        reid_max_gallery_entries=settings.reid_max_gallery_entries,
        behavior_enabled=settings.behavior_enabled,
        loiter_secs=settings.loiter_secs,
        loiter_radius_px=settings.loiter_radius_px,
        loiter_require_zone=settings.loiter_require_zone,
        run_speed_px_s=settings.run_speed_px_s,
        run_window_secs=settings.run_window_secs,
        immobile_secs=settings.immobile_secs,
        immobile_radius_px=settings.immobile_radius_px,
        crowd_threshold=settings.crowd_threshold,
        behavior_max_tracks=settings.behavior_max_tracks,
        objects_enabled=settings.objects_enabled,
        object_class_ids=settings.object_class_ids,
        object_left_secs=settings.object_left_secs,
        object_still_radius_px=settings.object_still_radius_px,
        object_person_radius_px=settings.object_person_radius_px,
        object_person_radius_ratio=settings.object_person_radius_ratio,
        object_warmup_secs=settings.object_warmup_secs,
        object_gone_secs=settings.object_gone_secs,
        object_person_window_secs=settings.object_person_window_secs,
        object_max_tracks=settings.object_max_tracks,
    )
    pipeline.set_detection_classes(services.active_classes)
    return pipeline
