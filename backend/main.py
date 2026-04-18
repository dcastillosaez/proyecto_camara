"""FastAPI application — MJPEG video feed, person detection, PTZ control."""

import asyncio
import datetime
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
import supervision as sv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.camera import router as camera_router, set_refs as camera_set_refs
from backend.config import get_settings
from backend.database import get_recent_events, get_stats_today, init_db, insert_event
from backend.detector import PersonDetector
from backend.ptz import router as ptz_router
from backend.recognizer import PersonRecognizer
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
            await insert_event(event["direction"], event["timestamp"])
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

    detector = PersonDetector(confidence=settings.yolo_confidence)
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
    camera_set_refs(rtsp_stream, tracker)
    # Apply initial processing resolution from config
    if settings.process_width > 0:
        rtsp_stream.set_process_size(settings.process_width, settings.process_height)

    rtsp_stream.start()
    logger.info("RTSP stream started: %s", settings.camera_url)
    yield
    rtsp_stream.stop()
    drain_task.cancel()
    logger.info("RTSP stream stopped")


app = FastAPI(lifespan=lifespan)
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
