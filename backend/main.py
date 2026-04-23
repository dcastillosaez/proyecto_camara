"""FastAPI application — MJPEG video feed, person detection, PTZ control."""

import asyncio
import datetime
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.database import (
    delete_events_range,
    delete_recordings_range,
    get_recent_events,
    get_recent_recordings,
    get_stats_today,
    init_db,
    insert_event,
    insert_recording,
    update_recording,
)
from backend.detector import PersonDetector
from backend.gdrive import DriveUploader
from backend.recognizer import PersonRecognizer
from backend.recorder import ClipRecorder
from backend.stream import RTSPStream
from backend.tracker import PersonTracker

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

logger = logging.getLogger(__name__)

rtsp_stream: RTSPStream | None = None
_ws_clients: set[WebSocket] = set()


async def _broadcast(message: dict) -> None:
    """Send *message* to every connected WebSocket client, dropping dead ones."""
    dead: set[WebSocket] = set()
    payload = json.dumps(message)
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


async def _drain_events(queue: asyncio.Queue) -> None:
    """Consume crossing events from the stream thread, persist, and broadcast."""
    while True:
        event = await queue.get()
        try:
            await insert_event(event["direction"], event["timestamp"], event.get("person_name"))
            stats = await get_stats_today()
            current_hour = datetime.datetime.now().strftime("%H")
            await _broadcast({
                "type": "detection",
                "timestamp": event["timestamp"].isoformat(),
                "direction": event["direction"],
                "total_today": stats["total_today"],
                "last_hour": stats["hourly"].get(current_hour, 0),
            })
        except Exception as exc:
            logger.error("DB insert / broadcast failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rtsp_stream
    settings = get_settings()

    await init_db()

    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    drain_task = asyncio.create_task(_drain_events(event_queue))

    detector = PersonDetector(
        model_path=settings.yolo_model_path,
        confidence=settings.yolo_confidence,
        classes=settings.yolo_classes,
        label=settings.detection_label,
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
    )
    recognizer = PersonRecognizer(db_path=settings.db_path.replace("events.db", "persons.db"))
    rtsp_stream = RTSPStream(
        settings.camera_url,
        detector=detector,
        tracker=tracker,
        recognizer=recognizer,
        event_loop=loop,
        event_queue=event_queue,
    )
    if settings.camera_driver == "tapo":
        from backend.camera import set_refs as camera_set_refs
        camera_set_refs(rtsp_stream, tracker)
    # Apply initial processing resolution from config
    if settings.process_width > 0:
        rtsp_stream.set_process_size(settings.process_width, settings.process_height)

    rtsp_stream.start()
    logger.info("RTSP stream started: %s", settings.camera_url)

    # Phase 10 — clip recorder + Drive uploader
    def _on_clip_ready(path: str) -> None:
        """Called from recorder thread when a clip is finalised."""
        import asyncio as _asyncio
        filename = Path(path).name
        coro = insert_recording(filename)
        future = _asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            rec_id = future.result(timeout=5)
        except Exception as exc:
            logger.error("insert_recording failed: %s", exc)
            rec_id = None
        uploader.enqueue(path)
        # Broadcast new recording event to dashboard
        if rec_id is not None:
            _asyncio.run_coroutine_threadsafe(
                _broadcast({"type": "recording_started", "filename": filename, "id": rec_id}),
                loop,
            )

    def _on_uploaded(path: str, gdrive_id: str) -> None:
        import asyncio as _asyncio
        filename = Path(path).name

        async def _update():
            recs = await get_recent_recordings(100)
            for r in recs:
                if r["filename"] == filename and r["upload_status"] == "pending":
                    await update_recording(r["id"], "uploaded", gdrive_id)
                    await _broadcast({
                        "type": "recording_uploaded",
                        "filename": filename,
                        "gdrive_id": gdrive_id,
                    })
                    break

        _asyncio.run_coroutine_threadsafe(_update(), loop)

    def _on_failed(path: str) -> None:
        import asyncio as _asyncio
        filename = Path(path).name

        async def _update():
            recs = await get_recent_recordings(100)
            for r in recs:
                if r["filename"] == filename and r["upload_status"] == "pending":
                    await update_recording(r["id"], "failed")
                    await _broadcast({"type": "recording_failed", "filename": filename})
                    break

        _asyncio.run_coroutine_threadsafe(_update(), loop)

    uploader = DriveUploader(
        folder_id=settings.gdrive_folder_id,
        credentials_path=settings.gdrive_credentials_path,
        token_path=settings.gdrive_token_path,
        on_uploaded=_on_uploaded,
        on_failed=_on_failed,
    )
    recorder = ClipRecorder(
        stream=rtsp_stream,
        clips_dir=settings.clips_dir,
        fps=settings.recording_fps,
        tail_secs=settings.recording_tail_secs,
        codec=settings.recording_codec,
        on_clip_ready=_on_clip_ready,
    )
    uploader.start()
    recorder.start()

    yield
    recorder.stop()
    uploader.stop()
    rtsp_stream.stop()
    drain_task.cancel()
    logger.info("RTSP stream stopped")


app = FastAPI(lifespan=lifespan)

_settings = get_settings()
if _settings.camera_driver == "tapo":
    from backend.ptz import router as ptz_router
    from backend.camera import router as camera_router
    app.include_router(ptz_router)
    app.include_router(camera_router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


async def mjpeg_generator():
    """Yield JPEG frames in MJPEG multipart format."""
    try:
        while True:
            frame = rtsp_stream.get_frame()
            if frame is None:
                await asyncio.sleep(0.1)
                continue
            _, jpeg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg.tobytes() + b"\r\n"
            )
            await asyncio.sleep(0.033)  # ~30 fps cap
    except asyncio.CancelledError:
        pass


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
        "detections": [asdict(d) for d in rtsp_stream.get_detections()],
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


@app.get("/api/events")
async def api_events(limit: int = 50):
    """Most recent crossing events."""
    return {"events": await get_recent_events(limit)}


@app.delete("/api/events")
async def api_delete_events(from_dt: datetime.datetime, to_dt: datetime.datetime):
    """Delete crossing events in [from_dt, to_dt]. Returns deleted count."""
    if to_dt < from_dt:
        raise HTTPException(status_code=400, detail="to_dt must be >= from_dt")
    deleted = await delete_events_range(from_dt, to_dt)
    return {"deleted": deleted}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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


@app.get("/persons")
async def persons():
    """Return all known persons with visit history."""
    if rtsp_stream is None or rtsp_stream._recognizer is None:
        return {"persons": [], "recognition_enabled": False}
    return {
        "persons": rtsp_stream._recognizer.list_persons(),
        "recognition_enabled": rtsp_stream._recognizer.available,
    }


@app.post("/api/enroll_face")
async def enroll_face(
    name: str = Form(...),
    image: UploadFile | None = File(default=None),
    use_current_frame: bool = Form(default=False),
):
    """Register a named person from an uploaded image or the current camera frame."""
    if rtsp_stream is None or rtsp_stream._recognizer is None:
        raise HTTPException(status_code=503, detail="Recognizer not available")
    if not rtsp_stream._recognizer.available:
        raise HTTPException(status_code=503, detail="face_recognition library not installed")

    if use_current_frame or image is None:
        frame = rtsp_stream.get_frame()
        if frame is None:
            raise HTTPException(status_code=503, detail="No frame available from camera")
        img_bgr = frame
    else:
        data = await image.read()
        arr = np.frombuffer(data, np.uint8)
        img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Could not decode image")

    pid = await asyncio.to_thread(rtsp_stream._recognizer.enroll_named_face, img_bgr, name.strip())
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
