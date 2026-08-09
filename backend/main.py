"""FastAPI application — MJPEG video feed, person detection, PTZ control."""

import asyncio
import datetime
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.auth import issue_ws_token, verify, verify_ws_token
from backend.config import build_rtsp_url, get_settings, mask_rtsp_url
from backend.database import (
    delete_events_range,
    delete_recordings_range,
    get_captures_for_person,
    get_events_filtered,
    get_recent_events,
    get_recent_recordings,
    get_session_factory,
    get_stats_today,
    get_zones,
    init_db,
    insert_capture,
    purge_old_events,
    purge_old_recordings,
    upsert_zone,
    delete_zone,
)
from backend.detector import PersonDetector
from backend.events import actions as event_actions
from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.rules import RuleEngine, load_rules
from backend.events.types import Event, EventType
from backend.gdrive import UploadQueue
from backend.notifier import Notifier
from backend.pipeline import CameraManager, CameraPipeline
from backend.recognizer import PersonRecognizer
from backend.storage.repositories import DetectionStatRepo, EventRepo, RecordingRepo
from backend.tracker import PersonTracker

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

logger = logging.getLogger(__name__)

# Fachada de la camara activa (CameraPipeline). Conserva el nombre historico
# porque es el que consumen todos los endpoints; RTSPStream ya no existe.
rtsp_stream: "CameraPipeline | None" = None
camera_manager: CameraManager | None = None
notifier: Notifier | None = None
event_bus: EventBus | None = None
event_engine: EventEngine | None = None
rule_engine: RuleEngine | None = None
_ws_clients: set[WebSocket] = set()
_ws_v2_clients: set[WebSocket] = set()
_start_time: float = time.time()


async def _broadcast(message: dict) -> None:
    """Send *message* to every connected v1 WebSocket client, dropping dead ones."""
    dead: set[WebSocket] = set()
    payload = json.dumps(message)
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


async def _broadcast_v2(event: Event) -> None:
    """Send the {"v": 2, "kind": "event", ...} envelope to every /api/v2/ws client."""
    dead: set[WebSocket] = set()
    payload = json.dumps({"v": 2, "kind": "event", "data": json.loads(event.model_dump_json())})
    for ws in _ws_v2_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_v2_clients.difference_update(dead)


async def _broadcast_v1_compat(event: Event) -> None:
    """Bridge typed LINE_CROSSED events to the v1 /ws "detection" message format.

    The v1 frontend depends on this shape; it's replaced wholesale in Fase 28.
    """
    if event.type != EventType.LINE_CROSSED:
        return
    stats = await get_stats_today()
    current_hour = event.ts.strftime("%H")
    await _broadcast({
        "type": "detection",
        "timestamp": event.ts.isoformat(),
        "direction": event.payload.get("direction", "?"),
        "total_today": stats["total_today"],
        "last_hour": stats["hourly"].get(current_hour, 0),
        "person_name": event.payload.get("person_name"),
        "is_intrusion": bool(event.payload.get("is_intrusion", False)),
    })


async def _camera_watchdog(check_interval: float = 10.0) -> None:
    """Periodically detect camera offline/online state and emit CAMERA_OFFLINE/RECOVERED."""
    was_offline = False
    while True:
        await asyncio.sleep(check_interval)
        if rtsp_stream is None or event_engine is None:
            continue
        health = rtsp_stream.health
        is_offline = not health.connected or health.last_frame_age_s > check_interval
        now = datetime.datetime.now()
        if is_offline and not was_offline:
            event_engine.camera_offline(now)
        elif not is_offline and was_offline:
            event_engine.camera_recovered(now)
        was_offline = is_offline


async def _detection_stats_flush_loop(interval: float = 30.0) -> None:
    """Periodically persist completed per-minute detection_stats buckets."""
    while True:
        await asyncio.sleep(interval)
        if event_engine is None:
            continue
        try:
            stat_repo = DetectionStatRepo(get_session_factory())
            await event_engine.flush_stats(stat_repo, datetime.datetime.now())
        except Exception:
            logger.exception("detection_stats flush failed")


async def _purge_loop() -> None:
    """Delete events and recordings older than the configured retention window. Runs daily."""
    while True:
        await asyncio.sleep(24 * 3600)
        settings = get_settings()
        try:
            if settings.events_retention_days > 0:
                n = await purge_old_events(settings.events_retention_days)
                if n:
                    logger.info("Purged %d events older than %d days", n, settings.events_retention_days)
            if settings.recordings_retention_days > 0:
                n = await purge_old_recordings(settings.recordings_retention_days)
                if n:
                    logger.info("Purged %d recordings older than %d days", n, settings.recordings_retention_days)
            if (
                settings.persons_retention_days > 0
                and rtsp_stream is not None
                and rtsp_stream.recognizer is not None
            ):
                n = await asyncio.to_thread(
                    rtsp_stream.recognizer.purge_unnamed,
                    settings.persons_retention_days,
                )
                if n:
                    logger.info(
                        "Purged %d unnamed persons older than %d days",
                        n, settings.persons_retention_days,
                    )
        except Exception as exc:
            logger.error("Purge loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rtsp_stream, camera_manager, notifier, event_bus, event_engine, rule_engine
    settings = get_settings()

    await init_db()  # idempotent: also runs the v1 -> v2 schema migration

    loop = asyncio.get_event_loop()
    event_bus = EventBus(loop=loop)
    event_engine = EventEngine(event_bus, camera_id="cam1")

    rules_path = Path("config/rules.yaml")
    if rules_path.exists():
        loaded_rules, rule_errors = load_rules(str(rules_path))
        for name, reason in rule_errors:
            logger.error("Regla invalida %r: %s", name, reason)
    else:
        loaded_rules, rule_errors = [], []
        logger.warning("%s no existe — arrancando sin reglas (ver scripts/generate_initial_rules.py)", rules_path)
    rule_engine = RuleEngine(loaded_rules, registry=event_actions.ACTIONS, invalid=rule_errors)

    event_repo = EventRepo(get_session_factory())

    async def _persist_event(event: Event) -> None:
        try:
            await event_repo.insert(event)
        except Exception:
            logger.exception("Failed to persist event %s", event.id)

    async def _apply_rules(event: Event) -> None:
        try:
            await rule_engine.evaluate(event)
        except Exception:
            logger.exception("RuleEngine evaluation failed for event %s", event.id)

    # Cada suscriptor recibe el mismo objeto Event por referencia (EVT-02) y corre
    # en su propia tarea — el orden de suscripcion no determina el de ejecucion,
    # pero no importa aqui: el id del evento ya viene fijado (uuid4 client-side)
    # antes de publicarse, no lo genera la persistencia.
    event_bus.subscribe("persistence", _persist_event)
    event_bus.subscribe("websocket_v1_compat", _broadcast_v1_compat)
    event_bus.subscribe("websocket_v2", _broadcast_v2)
    event_bus.subscribe("rules", _apply_rules)

    detector = PersonDetector(
        model_path=settings.yolo_model_path,
        confidence=settings.yolo_confidence,
        classes=settings.yolo_classes,
        label=settings.detection_label,
        imgsz=settings.yolo_imgsz,
    )
    tracker = PersonTracker(
        start=sv.Point(
            int(settings.line_start_x_frac * settings.process_width),
            int(settings.line_start_y_frac * settings.process_height),
        ),
        end=sv.Point(
            int(settings.line_end_x_frac * settings.process_width),
            int(settings.line_end_y_frac * settings.process_height),
        ),
        frame_rate=settings.tracker_frame_rate,
    )
    recognizer = PersonRecognizer(db_path=settings.db_path.replace("events.db", "persons.db"))

    # Ensure gallery directory exists
    import os as _os
    _os.makedirs(settings.gallery_dir, exist_ok=True)

    # Fase 20 — clip metadata persistence + Drive upload queue
    recording_repo = RecordingRepo(get_session_factory())

    def _on_clip_ready(result) -> None:
        """Called from the assembly thread when a clip is finalised (backend.pipeline.recording.ClipResult)."""
        async def _persist():
            rec_id = await recording_repo.create(
                camera_id="cam1", filename=result.path, started_at=result.started_at,
                reason=result.reason, trigger_event_id=result.trigger_event_id,
                person_id=result.person_id, zone_id=result.zone_id,
            )
            await recording_repo.finalize(
                rec_id, ended_at=result.ended_at, duration_s=result.duration_s,
                size_bytes=result.size_bytes, sha256=result.sha256,
                thumbnail_path=result.thumbnail_path, upload_state=result.upload_state,
            )
            await _broadcast({
                "type": "recording_started",
                "filename": Path(result.path).name,
                "id": rec_id,
            })

        asyncio.run_coroutine_threadsafe(_persist(), loop)

    async def _on_upload_failed(rec_id: int, message: str) -> None:
        await _broadcast({"type": "recording_failed", "id": rec_id, "error": message})
        if event_bus is not None:
            await event_bus.publish(Event(
                type=EventType.UPLOAD_FAILED, camera_id="cam1", ts=datetime.datetime.now(),
                payload={"reason": message, "recording_id": rec_id},
            ))

    upload_queue = UploadQueue(
        recording_repo,
        folder_id=settings.gdrive_folder_id,
        credentials_path=settings.gdrive_credentials_path,
        token_path=settings.gdrive_token_path,
        max_attempts=settings.max_upload_attempts,
        poll_secs=settings.upload_poll_secs,
        on_permanent_failure=_on_upload_failed,
    )
    upload_queue.start()

    def _on_recording_failure(message: str) -> None:
        logger.error("RecordingWorker failure: %s", message)
        if event_engine is not None:
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

    def _is_in_schedule() -> bool:
        """True si la hora actual cae dentro del horario de acceso configurado."""
        if not settings.schedule_enabled:
            return True
        now = datetime.datetime.now()
        if now.weekday() not in settings.schedule_days:
            return False
        sh, sm = map(int, settings.schedule_start.split(":"))
        eh, em = map(int, settings.schedule_end.split(":"))
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        return start <= now <= end

    _last_capture: dict[int, float] = {}

    def _save_gallery_capture(crop: np.ndarray, person_id: int) -> None:
        """Guarda un recorte en la galeria al identificar (throttled). Corre en el worker."""
        now = time.time()
        if now - _last_capture.get(person_id, 0) < settings.gallery_throttle_secs:
            return
        _last_capture[person_id] = now
        if len(_last_capture) > 256:
            expired = now - settings.gallery_throttle_secs
            for pid in [p for p, t in _last_capture.items() if t < expired]:
                del _last_capture[pid]
        if crop.size == 0:
            return
        gallery_dir = _os.path.join(settings.gallery_dir, str(person_id))
        _os.makedirs(gallery_dir, exist_ok=True)
        ts = datetime.datetime.now()
        image_path = _os.path.join(gallery_dir, f"{ts.strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(image_path, crop)
        asyncio.run_coroutine_threadsafe(insert_capture(person_id, ts, image_path), loop)

    process_size = (
        (settings.process_width, settings.process_height)
        if settings.process_width > 0 else None
    )
    camera_manager = CameraManager()
    pipeline = camera_manager.add(
        "cam1",
        build_rtsp_url(settings),
        process_size=process_size,
        detector=detector,
        tracker=tracker,
        recognizer=recognizer,
        event_engine=event_engine,
        is_intrusion=lambda: not _is_in_schedule(),
        recording_config=recording_config,
        on_identified=_save_gallery_capture,
        detection_fps=(
            settings.detection_target_fps,
            settings.detection_min_fps,
            settings.detection_max_fps,
        ),
        recognition_fps=settings.recognition_target_fps,
    )
    rtsp_stream = pipeline  # fachada consumida por los endpoints

    if settings.camera_driver == "tapo":
        from backend.camera import set_refs as camera_set_refs
        camera_set_refs(pipeline, tracker)

    pipeline.start()
    logger.info(
        "Pipeline v2 arrancado (%s) — deteccion %.0f FPS objetivo",
        mask_rtsp_url(build_rtsp_url(settings)), settings.detection_target_fps,
    )

    # Load persisted zones into the detection worker
    pipeline.set_zones(await get_zones())

    notifier = Notifier(
        webhook_url=settings.alert_webhook_url,
        telegram_token=settings.alert_telegram_token,
        telegram_chat_id=settings.alert_telegram_chat_id,
    )

    async def _recorder_hook(event: Event, action, rule_name: str) -> None:
        if pipeline.recording is not None:
            pipeline.recording.request_clip(
                reason=rule_name,
                trigger_ts=event.ts,
                trigger_event_id=event.id,
                person_id=event.person_id,
                zone_id=event.zone_id,
                severity=event.severity.value,
            )

    event_actions.configure(notifier=notifier, emit=event_bus.publish, recorder_hook=_recorder_hook)

    watchdog_task = asyncio.create_task(_camera_watchdog())
    purge_task = asyncio.create_task(_purge_loop())
    stats_flush_task = asyncio.create_task(_detection_stats_flush_loop())

    yield
    stats_flush_task.cancel()
    purge_task.cancel()
    watchdog_task.cancel()
    camera_manager.stop_all()   # para los workers, incluido el recorder
    upload_queue.stop()
    logger.info("Pipeline detenido")


_limiter = Limiter(key_func=get_remote_address)

app = FastAPI(lifespan=lifespan, dependencies=[Depends(verify)])
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_settings = get_settings()

if _settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' blob: data:; "
            "connect-src 'self' wss:;"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


app.add_middleware(SecurityHeadersMiddleware)

if _settings.camera_driver == "tapo":
    from backend.ptz import router as ptz_router
    from backend.camera import router as camera_router
    app.include_router(ptz_router)
    app.include_router(camera_router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Gallery images served as static files under /gallery/{person_id}/{filename}
_gallery_dir = Path(_settings.gallery_dir)
_gallery_dir.mkdir(parents=True, exist_ok=True)
app.mount("/gallery", StaticFiles(directory=str(_gallery_dir)), name="gallery")

_clips_dir = Path(_settings.clips_dir)
_clips_dir.mkdir(parents=True, exist_ok=True)
app.mount("/clips", StaticFiles(directory=str(_clips_dir)), name="clips")


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


async def mjpeg_generator():
    """Yield JPEG frames in MJPEG multipart format.

    El encode lo hace el StreamingWorker en su propio hilo; aqui solo se
    sirve el ultimo JPEG listo. Registrar la conexion y desconexion del
    cliente es lo que permite al worker no encodear cuando nadie mira.
    """
    if rtsp_stream is None:
        return
    rtsp_stream.client_connected()
    last: bytes | None = None
    try:
        while True:
            jpeg = rtsp_stream.get_jpeg()
            if jpeg is None or jpeg is last:
                await asyncio.sleep(0.02)
                continue
            last = jpeg
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
            await asyncio.sleep(0.02)
    except asyncio.CancelledError:
        pass
    finally:
        rtsp_stream.client_disconnected()


@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/detections")
async def detections():
    """Return live person count and bounding boxes from the most recent frame."""
    if rtsp_stream is None:
        return {"detections": [], "live_count": 0}
    return {
        "detections": rtsp_stream.get_detections(),
        "live_count": rtsp_stream.get_live_count(),
    }


@app.get("/counts")
async def counts():
    """Return cumulative line-crossing counts: total, in, and out."""
    if rtsp_stream is None:
        return {"in": 0, "out": 0, "total": 0}
    return rtsp_stream.get_counts()


@app.get("/api/stats")
async def api_stats():
    """Total crossings today and per-hour breakdown for the last 24 h."""
    return await get_stats_today()


@app.get("/api/health")
async def api_health():
    """System health metrics: CPU, RAM, FPS, uptime."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ram_pct = vm.percent
        ram_mb = vm.used // (1024 * 1024)
    except ImportError:
        cpu = ram_pct = ram_mb = -1
    fps = round(rtsp_stream.get_fps(), 1) if rtsp_stream else 0.0
    uptime = int(time.time() - _start_time)
    return {
        "cpu_percent": cpu,
        "ram_percent": ram_pct,
        "ram_used_mb": ram_mb,
        "fps": fps,
        "uptime_secs": uptime,
        "ws_clients": len(_ws_clients),
    }


@app.get("/api/events")
async def api_events(
    limit: int = Query(default=50, ge=1, le=500),
    direction: str | None = Query(default=None),
    person_name: str | None = Query(default=None),
    is_intrusion: bool | None = Query(default=None),
    from_dt: datetime.datetime | None = Query(default=None),
    to_dt: datetime.datetime | None = Query(default=None),
):
    """Most recent crossing events, with optional filters."""
    any_filter = any(v is not None for v in (direction, person_name, is_intrusion, from_dt, to_dt))
    if any_filter:
        events = await get_events_filtered(
            limit=limit,
            direction=direction,
            person_name=person_name,
            is_intrusion=is_intrusion,
            from_dt=from_dt,
            to_dt=to_dt,
        )
    else:
        events = await get_recent_events(limit)
    return {"events": events}


@app.get("/api/events/export")
async def api_events_export(
    direction: str | None = Query(default=None),
    person_name: str | None = Query(default=None),
    is_intrusion: bool | None = Query(default=None),
    from_dt: datetime.datetime | None = Query(default=None),
    to_dt: datetime.datetime | None = Query(default=None),
):
    """Export crossing events as a CSV file."""
    import csv, io
    events = await get_events_filtered(
        limit=10000,
        direction=direction,
        person_name=person_name,
        is_intrusion=is_intrusion,
        from_dt=from_dt,
        to_dt=to_dt,
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["id", "timestamp", "direction", "person_name", "is_intrusion"])
    writer.writeheader()
    writer.writerows(events)
    buf.seek(0)
    fname = f"eventos_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.delete("/api/events")
async def api_delete_events(from_dt: datetime.datetime, to_dt: datetime.datetime):
    """Delete crossing events in [from_dt, to_dt]. Returns deleted count."""
    if to_dt < from_dt:
        raise HTTPException(status_code=400, detail="to_dt must be >= from_dt")
    deleted = await delete_events_range(from_dt, to_dt)
    return {"deleted": deleted}


@app.get("/api/ws-token")
@_limiter.limit("10/minute")
async def ws_token(request: Request):
    """Issue a single-use WebSocket auth token (noop when auth disabled)."""
    return {"token": issue_ws_token()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str | None = Query(default=None)):
    if not verify_ws_token(token):
        await ws.close(code=1008)
        return
    await ws.accept()
    _ws_clients.add(ws)
    try:
        # Send current stats on connect so the dashboard populates immediately
        stats = await get_stats_today()
        await ws.send_text(json.dumps({"type": "init", **stats}))
        # Keep alive — client can send pings; we just wait for disconnect
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Fase 19 — API v2: eventos tipados y motor de reglas
# ---------------------------------------------------------------------------


@app.get("/api/v2/events")
async def api_v2_events(
    type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    person_id: int | None = Query(default=None),
    zone_id: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    from_dt: datetime.datetime | None = Query(default=None, alias="from"),
    to_dt: datetime.datetime | None = Query(default=None, alias="to"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Typed events with filters and cursor pagination (EventRepo.query)."""
    from backend.events.types import Severity

    try:
        event_type = EventType(type) if type else None
        event_severity = Severity(severity) if severity else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    repo = EventRepo(get_session_factory())
    items, next_cursor = await repo.query(
        type=event_type, severity=event_severity, person_id=person_id,
        zone_id=zone_id, camera_id=camera_id, ts_from=from_dt, ts_to=to_dt,
        cursor=cursor, limit=limit,
    )
    return {
        "events": [json.loads(e.model_dump_json()) for e in items],
        "cursor": next_cursor,
    }


@app.get("/api/v2/rules")
async def api_v2_rules():
    """Loaded rules plus any that failed validation, with their reason."""
    if rule_engine is None:
        raise HTTPException(status_code=503, detail="rule engine not initialised")
    return {
        "rules": [json.loads(r.model_dump_json()) for r in rule_engine.rules],
        "invalid": [{"name": name, "reason": reason} for name, reason in rule_engine.invalid_rules],
    }


@app.websocket("/api/v2/ws")
async def websocket_v2_endpoint(ws: WebSocket, token: str | None = Query(default=None)):
    """Unified v2 channel — currently emits {"kind": "event", ...}; metrics/tracks/system follow later phases."""
    if not verify_ws_token(token):
        await ws.close(code=1008)
        return
    await ws.accept()
    _ws_v2_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_v2_clients.discard(ws)


@app.get("/persons")
async def persons():
    """Return all known persons with visit history."""
    if rtsp_stream is None or rtsp_stream.recognizer is None:
        return {"persons": [], "recognition_enabled": False}
    return {
        "persons": rtsp_stream.recognizer.list_persons(),
        "recognition_enabled": rtsp_stream.recognizer.available,
    }


_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


@app.post("/api/enroll_face")
@_limiter.limit("5/minute")
async def enroll_face(
    request: Request,
    name: str = Form(..., max_length=100),
    image: UploadFile | None = File(default=None),
    use_current_frame: bool = Form(default=False),
):
    """Register a named person from an uploaded image or the current camera frame."""
    if rtsp_stream is None or rtsp_stream.recognizer is None:
        raise HTTPException(status_code=503, detail="Recognizer not available")
    if not rtsp_stream.recognizer.available:
        raise HTTPException(status_code=503, detail="face_recognition library not installed")

    if use_current_frame or image is None:
        frame = rtsp_stream.get_frame()
        if frame is None:
            raise HTTPException(status_code=503, detail="No frame available from camera")
        img_bgr = frame
    else:
        if image.content_type not in _ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported media type: {image.content_type}. Allowed: jpeg, png, webp")
        data = await image.read()
        if len(data) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
        arr = np.frombuffer(data, np.uint8)
        img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Could not decode image")

    pid = await asyncio.to_thread(rtsp_stream.recognizer.enroll_named_face, img_bgr, name.strip())
    if pid is None:
        raise HTTPException(status_code=422, detail="No face detected in the provided image")
    return {"person_id": pid, "name": name.strip()}


@app.get("/api/recordings")
async def api_recordings(limit: int = 20):
    """Most recent clip recordings with upload status."""
    return {"recordings": await get_recent_recordings(limit)}


@app.delete("/api/recordings")
async def api_delete_recordings(from_dt: datetime.datetime, to_dt: datetime.datetime):
    """Delete recordings created in [from_dt, to_dt]. Returns deleted count."""
    if to_dt < from_dt:
        raise HTTPException(status_code=400, detail="to_dt must be >= from_dt")
    deleted = await delete_recordings_range(from_dt, to_dt)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Phase 13: Zones
# ---------------------------------------------------------------------------

@app.get("/api/zones")
async def api_get_zones():
    """Return all configured interest zones."""
    return {"zones": await get_zones()}


class ZoneBody(dict):
    pass


@app.post("/api/zones")
async def api_upsert_zone(request: Request):
    """Create or update a zone. Body: {id, name, polygon_json, enabled?}."""
    body = await request.json()
    zone_id = str(body.get("id", "")).strip()
    name = str(body.get("name", "")).strip()
    polygon_json = body.get("polygon_json", "[]")
    enabled = bool(body.get("enabled", True))
    if not zone_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
    if len(zone_id) > 50 or len(name) > 100:
        raise HTTPException(status_code=400, detail="id/name too long")
    import json as _json
    try:
        pts = _json.loads(polygon_json) if isinstance(polygon_json, str) else polygon_json
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="polygon_json must be a JSON array with ≥3 points")
    await upsert_zone(zone_id, name, _json.dumps(pts), enabled)
    zones = await get_zones()
    if rtsp_stream is not None:
        rtsp_stream.set_zones(zones)
    return {"zones": zones}


@app.delete("/api/zones/{zone_id}")
async def api_delete_zone(zone_id: str):
    """Delete a zone by id."""
    deleted = await delete_zone(zone_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Zone not found")
    zones = await get_zones()
    if rtsp_stream is not None:
        rtsp_stream.set_zones(zones)
    return {"zones": zones}


@app.get("/api/zones/stats")
async def api_zone_stats():
    """Live per-zone presence: current occupants and cumulative entries."""
    if rtsp_stream is None:
        return {"zones": []}
    return {"zones": rtsp_stream.get_zone_stats()}


@app.get("/api/heatmap")
async def api_heatmap():
    """Accumulated activity heat map composed over the latest frame (JPEG)."""
    if rtsp_stream is None:
        raise HTTPException(status_code=503, detail="Stream not running")
    img = await asyncio.to_thread(rtsp_stream.get_heatmap)
    if img is None:
        raise HTTPException(status_code=404, detail="No activity recorded yet")
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="JPEG encoding failed")
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Phase 17: Pipeline v2 — FrameBroker + CaptureWorker health
# ---------------------------------------------------------------------------

@app.get("/api/v2/cameras")
async def api_v2_cameras():
    """List cameras managed by pipeline v2, with their capture health."""
    if camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    return {
        "cameras": [
            {**asdict(p.health), "workers": p.worker_status(), "degraded": p.degraded}
            for p in camera_manager.all()
        ]
    }


@app.get("/api/v2/cameras/{camera_id}/health")
async def api_v2_camera_health(camera_id: str):
    """CaptureWorker health for one camera, plus FrameBroker subscriber stats."""
    if camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    pipeline = camera_manager.get(camera_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {
        **asdict(pipeline.health),
        # capture_fps y detection_fps son deliberadamente distintos: esa
        # diferencia ES la prueba de que el pipeline esta desacoplado.
        "capture_fps": pipeline.get_fps(),
        "detection_fps": pipeline.get_detection_fps(),
        "broker_stats": pipeline.broker.stats(),
        **pipeline.stats(),
    }


# ---------------------------------------------------------------------------
# Phase 13: Gallery captures
# ---------------------------------------------------------------------------

@app.get("/api/alerts/config")
async def api_alerts_config():
    """Return current alert configuration (tokens masked)."""
    s = get_settings()
    return {
        "webhook_url": s.alert_webhook_url,
        "telegram_configured": bool(s.alert_telegram_token and s.alert_telegram_chat_id),
        "alert_on_intrusion": s.alert_on_intrusion,
        "alert_on_unknown": s.alert_on_unknown,
        "alert_on_detection": s.alert_on_detection,
        "cooldown_secs": s.alert_cooldown_secs,
        "count_threshold": s.alert_count_threshold,
        "active_channels": notifier.active_channels if notifier else [],
    }


@app.post("/api/alerts/test")
async def api_alerts_test():
    """Send a test alert to every configured channel."""
    if not notifier:
        raise HTTPException(status_code=503, detail="notifier not initialised")
    results = await notifier.test()
    return {"results": results}


@app.get("/api/alerts/status")
async def api_alerts_status():
    """Return notifier channels and loaded rules (decision logic now lives in rules.yaml)."""
    if not notifier:
        raise HTTPException(status_code=503, detail="notifier not initialised")
    return {
        "active_channels": notifier.active_channels,
        "rules": [r.name for r in rule_engine.rules] if rule_engine else [],
        "invalid_rules": rule_engine.invalid_rules if rule_engine else [],
    }


@app.get("/persons/{person_id}/captures")
async def person_captures(
    person_id: int,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return the most recent gallery captures for a person."""
    captures = await get_captures_for_person(person_id, limit)
    # Build relative URL paths usable from the frontend
    for c in captures:
        if c.get("image_path"):
            p = Path(c["image_path"])
            # Serve via /gallery/{person_id}/{filename}
            c["url"] = f"/gallery/{person_id}/{p.name}"
    return {"captures": captures}
