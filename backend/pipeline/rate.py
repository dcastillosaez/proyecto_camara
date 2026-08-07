"""Control adaptativo del FPS de inferencia con realimentacion de latencia."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AdaptiveRate:
    """
    Decide a que ritmo procesar frames y ajusta ese ritmo segun la latencia
    real observada, en vez de un contador fijo de frames (MEJORAS.md /
    SPEC_v2.md §5.3).

    should_process(now) decide por tiempo transcurrido desde el ultimo
    procesado — determinista y facil de testear con reloj simulado.

    observe(latency) alimenta una media movil exponencial. Si la latencia
    media supera el presupuesto (1/fps * BUDGET_RATIO) durante DOWN_STREAK
    observaciones seguidas, baja un escalon; si queda muy por debajo del
    presupuesto durante UP_STREAK observaciones seguidas, sube un escalon.
    La histeresis (rachas, no un solo dato) evita oscilar en cada frame.
    """

    STEPS: tuple[float, ...] = (12.0, 8.0, 5.0, 3.0)

    _ALPHA = 0.2                # suavizado de la media movil
    _BUDGET_RATIO = 0.8         # presupuesto = (1 / fps) * 0.8
    _DOWN_STREAK = 3            # observaciones seguidas por encima para bajar
    _UP_STREAK = 10             # observaciones seguidas holgadas para subir
    _UP_RATIO = 0.5             # "holgado" = latencia < presupuesto * 0.5

    def __init__(
        self, target_fps: float = 8.0, min_fps: float = 3.0, max_fps: float = 12.0
    ) -> None:
        self._steps = [f for f in self.STEPS if min_fps <= f <= max_fps] or [target_fps]
        self._idx = min(
            range(len(self._steps)),
            key=lambda i: abs(self._steps[i] - target_fps),
        )
        self._min_fps = min_fps
        self._max_fps = max_fps
        self._last_ts: float | None = None
        self._avg_latency = 0.0
        self._over = 0
        self._under = 0
        self.steps_down = 0
        self.steps_up = 0

    @property
    def effective_fps(self) -> float:
        return self._steps[self._idx]

    def should_process(self, now: float) -> bool:
        if self._last_ts is None:
            self._last_ts = now
            return True
        if now - self._last_ts >= 1.0 / self.effective_fps:
            self._last_ts = now
            return True
        return False

    def observe(self, latency: float) -> None:
        self._avg_latency = (
            latency if self._avg_latency == 0.0
            else self._ALPHA * latency + (1 - self._ALPHA) * self._avg_latency
        )
        budget = (1.0 / self.effective_fps) * self._BUDGET_RATIO

        if self._avg_latency > budget:
            self._over += 1
            self._under = 0
            if self._over >= self._DOWN_STREAK and self._idx < len(self._steps) - 1:
                self._idx += 1
                self.steps_down += 1
                self._over = 0
                logger.info(
                    "AdaptiveRate: bajando a %.1f FPS (latencia %.3fs)",
                    self.effective_fps, self._avg_latency,
                )
        elif self._avg_latency < budget * self._UP_RATIO:
            self._under += 1
            self._over = 0
            if self._under >= self._UP_STREAK and self._idx > 0:
                self._idx -= 1
                self.steps_up += 1
                self._under = 0
                logger.info(
                    "AdaptiveRate: subiendo a %.1f FPS (latencia %.3fs)",
                    self.effective_fps, self._avg_latency,
                )
        else:
            self._over = 0
            self._under = 0

    @property
    def stats(self) -> dict[str, float]:
        return {
            "effective_fps": self.effective_fps,
            "avg_latency": self._avg_latency,
            "steps_down": float(self.steps_down),
            "steps_up": float(self.steps_up),
        }
