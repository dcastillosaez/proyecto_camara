"""ClipWriter — writes frames to an MP4 file. No decision logic (Fase 20).

When/why to record lives in RecordingWorker (pre/post-buffer state machine)
and, upstream of that, in config/rules.yaml's "record" action.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ClipWriter:
    def __init__(self, path: str, fps: float, frame_size: tuple[int, int], codec: str = "mp4v") -> None:
        self.path = path
        fourcc = cv2.VideoWriter_fourcc(*codec)
        self._writer = cv2.VideoWriter(path, fourcc, fps, frame_size)

    @property
    def is_opened(self) -> bool:
        return self._writer.isOpened()

    def write_image(self, image: np.ndarray) -> None:
        self._writer.write(image)

    def write_jpeg(self, jpeg: bytes) -> None:
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is not None:
            self._writer.write(image)

    def release(self) -> None:
        self._writer.release()
