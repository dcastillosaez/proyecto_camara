"""Puerta de movimiento para la detección (DET-09).

La mayor parte del tiempo de un sistema 24/7 la escena está vacía y YOLO se ejecuta
igual. Con la puerta activa, si no hay tracks vivos ni cambios en una miniatura de
160×90 respecto al último frame procesado, el DetectionWorker baja a `idle_fps`.
Nunca a cero: una persona inmóvil que no genera diferencia de píxeles debe seguir
detectándose, aunque sea a ese ritmo reducido.

Está DESACTIVADA por defecto (motion_gate_enabled=False): su riesgo, perder a alguien
quieto o ver tarde a quien entra, solo se puede medir con la cámara real.
"""

from __future__ import annotations

import cv2
import numpy as np

THUMB_SIZE = (160, 90)


class MotionGate:
    def __init__(
        self, idle_fps: float = 2.0, min_changed: float = 0.005, pixel_delta: int = 15,
    ) -> None:
        if idle_fps <= 0:
            raise ValueError("idle_fps debe ser > 0: la puerta nunca detiene la detección")
        self._idle_interval = 1.0 / idle_fps
        self._min_changed = min_changed
        self._pixel_delta = pixel_delta
        self._reference: np.ndarray | None = None
        self._last_allowed: float | None = None
        self.skipped = 0

    @staticmethod
    def _thumb(image: np.ndarray) -> np.ndarray:
        small = cv2.resize(image, THUMB_SIZE, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small

    def changed_fraction(self, thumb: np.ndarray) -> float:
        if self._reference is None or self._reference.shape != thumb.shape:
            return 1.0
        diff = cv2.absdiff(thumb, self._reference)
        return float(np.count_nonzero(diff > self._pixel_delta)) / diff.size

    def allow(self, image: np.ndarray, now: float, has_tracks: bool) -> bool:
        """True si este frame debe pasar a YOLO. La referencia es el último frame
        procesado, así que un movimiento lento se acumula hasta superar el umbral."""
        thumb = self._thumb(image)
        moving = self.changed_fraction(thumb) >= self._min_changed
        idle_due = self._last_allowed is None or now - self._last_allowed >= self._idle_interval
        if has_tracks or moving or idle_due:
            self._reference = thumb
            self._last_allowed = now
            return True
        self.skipped += 1
        return False
