# 17-01 Summary — FrameBroker

**Plan:** 17-01-PLAN.md · **Wave:** 1 · **Estado:** completo

## Qué se construyó

`backend/pipeline/broker.py`: `Frame` (dataclass con `camera_id`, `seq`, `captured_at`, `wall_clock`, `image`, propiedad `age`), `Subscription` (slot de un frame por consumidor, espera bloqueante con `threading.Condition`) y `FrameBroker` (fan-out latest-frame: `subscribe`, `publish`, `stats`, `close`).

`backend/pipeline/__init__.py` reexporta `Frame`, `FrameBroker`, `Subscription`.

## Decisiones seguidas del CONTEXT

- Slot por suscriptor con `Condition`, no `queue.Queue` ni cola compartida (17-CONTEXT.md, "FrameBroker: slot por suscriptor").
- Sin copia defensiva en `publish()`/`get()` — el contrato de no-mutación se documenta en el docstring de `Frame.image`.
- `publish()` copia la lista de suscriptores bajo `self._lock` y notifica fuera de él: un suscriptor lento nunca bloquea al productor ni a los demás.

## Verificación

- 10/10 tests de `tests/test_broker.py` (no-bloqueo con 1000 publish, aislamiento entre suscriptor lento/rápido, dropped/delivered por suscriptor, timeout de `get()`, desbloqueo en `close()`, rechazo de nombre duplicado).
- Suite completa: 122/122 sin regresión.

## Desviaciones del plan

Ninguna. La implementación sigue el código de referencia del plan sin cambios de comportamiento.

## Habilita

17-02 (CaptureWorker) consume `FrameBroker.subscribe()`/`publish()` tal cual.
