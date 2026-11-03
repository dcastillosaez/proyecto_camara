"""Control adaptativo del FPS de inferencia con realimentacion de latencia."""

from __future__ import annotations

import logging
from collections import deque

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
    # DET-08: margen para aceptar un frame que llega un poco antes de su hora. Los
    # frames llegan con el periodo de la fuente: con 15 FPS de fuente y 12 pedidos,
    # exigir 83 ms exactos dejaba pasar uno de cada dos (7,5 FPS reales).
    _TOLERANCE = 0.25           # fraccion del intervalo
    _MEASURE_WINDOW = 20        # frames procesados para medir el FPS real

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
        self._next_due: float | None = None
        self._processed_at: deque[float] = deque(maxlen=self._MEASURE_WINDOW)
        self._avg_latency = 0.0
        self._over = 0
        self._under = 0
        self.steps_down = 0
        self.steps_up = 0
        self._external_cap: float | None = None

    @property
    def effective_fps(self) -> float:
        fps = self._steps[self._idx]
        if self._external_cap is not None:
            return min(fps, self._external_cap)
        return fps

    @property
    def min_fps(self) -> float:
        return self._min_fps

    def set_external_cap(self, cap: float | None) -> None:
        """Techo impuesto por un coordinador externo (Fase 36, SCALE-08:
        CameraManager.rebalance_fps() reparte CPU entre camaras), por encima de
        la propia histeresis de latencia. `None` lo libera — el escalon interno
        (`_idx`) nunca se toca, asi que retirar el techo restaura el ritmo que
        la propia latencia habria elegido sin necesidad de recalcular nada."""
        self._external_cap = cap

    @property
    def measured_fps(self) -> float:
        """FPS realmente procesado en los ultimos frames aceptados (DET-08). 0 sin datos.

        Puede quedar por debajo de effective_fps si la fuente no da para mas: el
        tracker debe sincronizarse con este valor, no con el pedido."""
        if len(self._processed_at) < 2:
            return 0.0
        span = self._processed_at[-1] - self._processed_at[0]
        return (len(self._processed_at) - 1) / span if span > 0 else 0.0

    def should_process(self, now: float) -> bool:
        """Acepta un frame si ha llegado su turno, con un margen de _TOLERANCE.

        DET-08: el turno avanza de intervalo en intervalo (no desde el ultimo frame
        aceptado), asi que los frames que llegan algo antes compensan a los que llegan
        tarde y la media se acerca al FPS pedido. Si se va mas de un intervalo por
        detras (escena vacia, fuente parada), el turno se reinicia: nunca rafagas."""
        interval = 1.0 / self.effective_fps
        if self._next_due is not None and now < self._next_due - interval * self._TOLERANCE:
            return False
        if self._next_due is None or now - self._next_due > interval:
            self._next_due = now + interval
        else:
            self._next_due += interval
        self._last_ts = now
        self._processed_at.append(now)
        return True

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
            "measured_fps": self.measured_fps,
            "avg_latency": self._avg_latency,
            "steps_down": float(self.steps_down),
            "steps_up": float(self.steps_up),
        }
