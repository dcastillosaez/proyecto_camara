"""Clip recorder — starts .mp4 recording when persons detected, stops 5 s after last detection."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

import cv2

logger = logging.getLogger(__name__)

_FOURCC = cv2.VideoWriter_fourcc(*"mp4v")


class ClipRecorder:
    """
    Monitors RTSPStream.get_live_count(). While persons visible:
      - Opens a new .mp4 clip in *clips_dir*.
      - Writes frames at *fps*.
    When live_count drops to 0, continues recording for *tail_secs* then
    finalises the clip and calls *on_clip_ready(path)*.
    """

    def __init__(
        self,
        stream,
        clips_dir: str = "data/clips",
        fps: float = 15.0,
        tail_secs: float = 5.0,
        on_clip_ready: Callable[[str], None] | None = None,
    ) -> None:
        self._stream = stream
        self._clips_dir = Path(clips_dir)
        self._fps = fps
        self._tail_secs = tail_secs
        self._on_clip_ready = on_clip_ready

        self._running = False
        self._writer: cv2.VideoWriter | None = None
        self._current_path: str | None = None
        self._last_live_ts: float = 0.0
        self._frame_size: tuple[int, int] = (1280, 720)

    def start(self) -> None:
        self._running = True
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="clip-recorder")
        self._thread.start()
        logger.info("ClipRecorder started — clips dir: %s", self._clips_dir)

    def stop(self) -> None:
        self._running = False
        if self._writer is not None:
            self._finalise()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        interval = 1.0 / self._fps
        while self._running:
            t0 = time.monotonic()
            frame = self._stream.get_frame()
            live = self._stream.get_live_count()

            if frame is not None:
                h, w = frame.shape[:2]
                if (w, h) != self._frame_size:
                    self._frame_size = (w, h)

                if live > 0:
                    if self._writer is None:
                        self._start_clip()
                    if self._writer is not None:
                        self._writer.write(frame)
                    self._last_live_ts = time.monotonic()

                elif self._writer is not None:
                    tail_elapsed = time.monotonic() - self._last_live_ts
                    if tail_elapsed < self._tail_secs:
                        self._writer.write(frame)
                    else:
                        self._finalise()

            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _start_clip(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = str(self._clips_dir / f"clip_{ts}.mp4")
        writer = cv2.VideoWriter(path, _FOURCC, self._fps, self._frame_size)
        if not writer.isOpened():
            logger.error("ClipRecorder: VideoWriter failed to open %s", path)
            return
        self._writer = writer
        self._current_path = path
        logger.info("ClipRecorder: recording started → %s", path)

    def _finalise(self) -> None:
        if self._writer is None:
            return
        self._writer.release()
        self._writer = None
        path = self._current_path
        self._current_path = None

        if not path or not os.path.exists(path):
            logger.warning("ClipRecorder: clip path missing after finalise")
            return
        size = os.path.getsize(path)
        if size < 4096:
            logger.warning("ClipRecorder: discarding near-empty clip %s (%d bytes)", path, size)
            os.remove(path)
            return

        logger.info("ClipRecorder: clip ready %s (%d KB)", path, size // 1024)
        if self._on_clip_ready:
            try:
                self._on_clip_ready(path)
            except Exception as exc:
                logger.error("ClipRecorder: on_clip_ready raised: %s", exc)
