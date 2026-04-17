"""FastAPI application — MJPEG video feed, person detection, and PTZ control."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

import cv2
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from backend.config import get_settings
from backend.detector import PersonDetector
from backend.ptz import router as ptz_router
from backend.stream import RTSPStream

logger = logging.getLogger(__name__)

rtsp_stream: RTSPStream | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rtsp_stream
    settings = get_settings()
    detector = PersonDetector(confidence=settings.yolo_confidence)
    rtsp_stream = RTSPStream(settings.camera_url, detector=detector)
    rtsp_stream.start()
    logger.info("RTSP stream started: %s", settings.camera_url)
    yield
    rtsp_stream.stop()
    logger.info("RTSP stream stopped")


app = FastAPI(lifespan=lifespan)
app.include_router(ptz_router)


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
    """Return the bounding boxes from the most recent detection pass."""
    if rtsp_stream is None:
        return {"detections": []}
    return {"detections": [asdict(d) for d in rtsp_stream.get_detections()]}
