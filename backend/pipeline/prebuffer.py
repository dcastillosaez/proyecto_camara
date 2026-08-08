"""RingFrameBuffer: JPEG-encoded circular pre-recording buffer, bounded by time and RAM.

Raw BGR frames at 720p are ~2.7 MB each — 10s at 15 FPS would be ~400 MB.
JPEG q=85 brings that to ~120 KB/frame (~18 MB for the same window). The cost
is one imencode() per frame received, off the detection critical path, and
one imdecode() per frame when a clip actually assembles (ADR-07).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import cv2

from backend.pipeline.broker import Frame


@dataclass(slots=True)
class BufferedFrame:
    seq: int
    wall_clock: datetime
    jpeg: bytes


class RingFrameBuffer:
    """Filled continuously by RecordingWorker; drained (not cleared) when a clip starts."""

    def __init__(self, seconds: float, fps: float, max_bytes: int, quality: int = 85) -> None:
        self._max_frames = max(1, int(seconds * fps))
        self._max_bytes = max_bytes
        self._quality = quality
        self._lock = threading.Lock()
        self._items: deque[BufferedFrame] = deque()
        self._bytes = 0

    def push(self, frame: Frame) -> None:
        """Encode to JPEG and append, discarding the oldest frame(s) as needed."""
        ok, buf = cv2.imencode(".jpg", frame.image, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality])
        if not ok:
            return
        item = BufferedFrame(frame.seq, frame.wall_clock, buf.tobytes())
        with self._lock:
            self._items.append(item)
            self._bytes += len(item.jpeg)
            while self._items and (
                len(self._items) > self._max_frames or self._bytes > self._max_bytes
            ):
                old = self._items.popleft()
                self._bytes -= len(old.jpeg)

    def drain(self) -> list[BufferedFrame]:
        """Current contents in chronological order. Does NOT clear the buffer."""
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes

    @property
    def span_seconds(self) -> float:
        """Age of the oldest frame relative to the newest one currently buffered."""
        with self._lock:
            if len(self._items) < 2:
                return 0.0
            return (self._items[-1].wall_clock - self._items[0].wall_clock).total_seconds()
