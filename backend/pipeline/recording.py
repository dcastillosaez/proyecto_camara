"""RecordingWorker — feeds a RingFrameBuffer continuously and assembles clips
with pre/post-buffer context around triggering events (Fase 20, ADR-07).

Two threads:
  _feed_loop      broker -> RingFrameBuffer (always) + live queue (while a clip is active)
  _assembly_loop  drains the pre-buffer, writes the clip, extends its deadline on
                  new requests instead of opening a second overlapping clip, and
                  keeps writing live frames until post_buffer_secs after the last
                  request — all off the capture critical path.
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import cv2
import numpy as np

from backend.pipeline.prebuffer import BufferedFrame, RingFrameBuffer
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry
from backend.recorder import ClipWriter

if TYPE_CHECKING:
    from backend.pipeline.broker import Frame, Subscription

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class ClipRequest:
    reason: str
    trigger_ts: datetime
    trigger_event_id: str | None = None
    person_id: int | None = None
    zone_id: str | None = None
    severity: str = "info"


@dataclass
class ClipResult:
    path: str
    started_at: datetime
    ended_at: datetime
    reason: str
    trigger_event_id: str | None
    person_id: int | None
    zone_id: str | None
    duration_s: float
    size_bytes: int
    sha256: str
    thumbnail_path: str | None
    upload_state: str


@dataclass
class _ActiveClip:
    writer: ClipWriter
    started_at: datetime
    deadline: datetime
    request: ClipRequest
    trigger_jpeg: bytes | None = None


class RecordingWorker:
    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        clips_dir: str = "data/clips",
        thumbnails_dir: str = "data/thumbnails",
        fps: float = 15.0,
        pre_buffer_secs: float = 10.0,
        post_buffer_secs: float = 10.0,
        pre_buffer_max_mb: int = 48,
        pre_buffer_jpeg_quality: int = 85,
        codec: str = "mp4v",
        thumbnail_width: int = 320,
        upload_min_severity: str = "warning",
        on_clip_ready: Callable[[ClipResult], None] | None = None,
        on_failure: Callable[[str], None] | None = None,
        live_queue_max: int = 0,
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._clips_dir = Path(clips_dir)
        self._thumbnails_dir = Path(thumbnails_dir)
        self._fps = fps
        self._post_buffer_secs = post_buffer_secs
        self._codec = codec
        self._thumbnail_width = thumbnail_width
        self._upload_min_severity = upload_min_severity
        self._on_clip_ready = on_clip_ready
        self._on_failure = on_failure

        self._prebuffer = RingFrameBuffer(
            seconds=pre_buffer_secs, fps=fps,
            max_bytes=pre_buffer_max_mb * 1024 * 1024,
            quality=pre_buffer_jpeg_quality,
        )
        self._rate = AdaptiveRate(target_fps=fps, min_fps=fps, max_fps=fps)

        self._requests: queue.Queue[ClipRequest] = queue.Queue()
        max_live = live_queue_max or max(1, int(fps * (post_buffer_secs + 30)))
        self._live_queue: queue.Queue = queue.Queue(maxsize=max_live)
        self._live_dropped = 0

        self._frame_size: tuple[int, int] = (1280, 720)
        self._running = False
        self._feed_thread: threading.Thread | None = None
        self._assembly_thread: threading.Thread | None = None
        self._active: _ActiveClip | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._feed_thread = threading.Thread(target=self._feed_loop, daemon=True, name="recording-feed")
        self._assembly_thread = threading.Thread(target=self._assembly_loop, daemon=True, name="recording-assembly")
        self._feed_thread.start()
        self._assembly_thread.start()

    def is_alive(self) -> bool:
        """True if both worker threads are still running (queried by WorkerSupervisor)."""
        return bool(
            self._feed_thread is not None and self._feed_thread.is_alive()
            and self._assembly_thread is not None and self._assembly_thread.is_alive()
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        for t in (self._feed_thread, self._assembly_thread):
            if t is not None:
                t.join(timeout)
                if t.is_alive():
                    logger.warning("RecordingWorker: %s did not stop within %.1fs", t.name, timeout)
        self._sub.close()

    def request_clip(
        self,
        reason: str,
        trigger_ts: datetime,
        trigger_event_id: str | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        severity: str = "info",
    ) -> None:
        """Start or extend the active clip. Thread-safe — callable from the asyncio loop."""
        self._requests.put_nowait(
            ClipRequest(reason, trigger_ts, trigger_event_id, person_id, zone_id, severity)
        )

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "prebuffer_bytes": self._prebuffer.bytes_used,
            "prebuffer_span_seconds": self._prebuffer.span_seconds,
            "live_dropped": self._live_dropped,
            "clip_active": self._active is not None,
            **self._rate.stats,
        }

    # ------------------------------------------------------------------
    # Feed thread: broker -> prebuffer (+ live queue while a clip is active)
    # ------------------------------------------------------------------

    def _feed_loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not self._rate.should_process(time.monotonic()):
                continue
            t0 = time.monotonic()

            h, w = frame.image.shape[:2]
            self._frame_size = (w, h)
            self._prebuffer.push(frame)
            if self._active is not None:
                self._offer_live(frame)

            self._rate.observe(time.monotonic() - t0)

    def _offer_live(self, frame: Frame) -> None:
        try:
            self._live_queue.put_nowait(frame)
            return
        except queue.Full:
            pass
        try:
            self._live_queue.get_nowait()
            self._live_dropped += 1
        except queue.Empty:
            pass
        try:
            self._live_queue.put_nowait(frame)
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Assembly thread: state machine (idle <-> recording)
    # ------------------------------------------------------------------

    def _assembly_loop(self) -> None:
        while self._running:
            if self._active is None:
                try:
                    req = self._requests.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._begin_clip(req)
            else:
                try:
                    req = self._requests.get(timeout=0.1)
                    self._extend_clip(req)
                except queue.Empty:
                    pass
                self._drain_live_frames()
                if self._active is not None and datetime.now() >= self._active.deadline:
                    self._finalize_clip()

        if self._active is not None:
            self._finalize_clip()

    def _begin_clip(self, req: ClipRequest) -> None:
        ts = req.trigger_ts.strftime("%Y%m%d_%H%M%S")
        path = str(self._clips_dir / f"clip_{ts}.mp4")
        writer = ClipWriter(path, self._fps, self._frame_size, self._codec)
        if not writer.is_opened:
            logger.error("RecordingWorker: VideoWriter failed to open %s", path)
            if self._on_failure:
                try:
                    self._on_failure(f"VideoWriter failed to open {path}")
                except Exception:
                    logger.exception("RecordingWorker: on_failure raised")
            return

        pre_frames = self._prebuffer.drain()
        for item in pre_frames:
            writer.write_jpeg(item.jpeg)

        # Drop any live frames left over from a previous clip before starting this one.
        while True:
            try:
                self._live_queue.get_nowait()
            except queue.Empty:
                break

        self._active = _ActiveClip(
            writer=writer,
            started_at=pre_frames[0].wall_clock if pre_frames else req.trigger_ts,
            deadline=req.trigger_ts + timedelta(seconds=self._post_buffer_secs),
            request=req,
            trigger_jpeg=self._closest_jpeg(pre_frames, req.trigger_ts),
        )

    @staticmethod
    def _closest_jpeg(pre_frames: list[BufferedFrame], ts: datetime) -> bytes | None:
        """The pre-buffer frame closest to the trigger timestamp — the thumbnail source
        (the event frame has the relevant content, not necessarily the first buffered one)."""
        if not pre_frames:
            return None
        closest = min(pre_frames, key=lambda item: abs((item.wall_clock - ts).total_seconds()))
        return closest.jpeg

    def _extend_clip(self, req: ClipRequest) -> None:
        if self._active is None:
            return
        new_deadline = req.trigger_ts + timedelta(seconds=self._post_buffer_secs)
        if new_deadline > self._active.deadline:
            self._active.deadline = new_deadline

    def _drain_live_frames(self) -> None:
        if self._active is None:
            return
        while True:
            try:
                frame = self._live_queue.get_nowait()
            except queue.Empty:
                return
            self._active.writer.write_image(frame.image)

    def _finalize_clip(self) -> None:
        active = self._active
        self._active = None
        if active is None:
            return
        active.writer.release()
        path = active.writer.path
        ended_at = datetime.now()

        rank = _SEVERITY_RANK.get(active.request.severity, 0)
        min_rank = _SEVERITY_RANK.get(self._upload_min_severity, 1)
        upload_state = "pending" if rank >= min_rank else "skipped"

        result = ClipResult(
            path=path,
            started_at=active.started_at,
            ended_at=ended_at,
            reason=active.request.reason,
            trigger_event_id=active.request.trigger_event_id,
            person_id=active.request.person_id,
            zone_id=active.request.zone_id,
            duration_s=(ended_at - active.started_at).total_seconds(),
            size_bytes=os.path.getsize(path) if os.path.exists(path) else 0,
            sha256=self._sha256_file(path) if os.path.exists(path) else "",
            thumbnail_path=self._save_thumbnail(active),
            upload_state=upload_state,
        )
        logger.info("RecordingWorker: clip ready %s", result.path)
        if self._on_clip_ready:
            try:
                self._on_clip_ready(result)
            except Exception:
                logger.exception("RecordingWorker: on_clip_ready raised")

    @staticmethod
    def _sha256_file(path: str, block_size: int = 65536) -> str:
        """Streamed — never loads the file into memory whole (clips can be tens of MB)."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                h.update(chunk)
        return h.hexdigest()

    def _save_thumbnail(self, active: _ActiveClip) -> str | None:
        """Thumbnail from the trigger frame (the relevant content), not the clip's first frame."""
        if active.trigger_jpeg is None:
            return None
        image = cv2.imdecode(np.frombuffer(active.trigger_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        h, w = image.shape[:2]
        if w > self._thumbnail_width:
            scale = self._thumbnail_width / w
            image = cv2.resize(image, (self._thumbnail_width, max(1, int(h * scale))))
        stem = Path(active.writer.path).stem
        thumb_path = str(self._thumbnails_dir / f"{stem}.jpg")
        if not cv2.imwrite(thumb_path, image):
            return None
        return thumb_path
