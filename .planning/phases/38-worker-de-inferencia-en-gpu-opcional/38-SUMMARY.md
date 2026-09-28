---
phase: 38-worker-de-inferencia-en-gpu-opcional
plans: [38-01, 38-02, 38-03, 38-04, 38-05]
status: complete
completed: 2026-09-28
requirements: [SCALE-11, SCALE-12]
---

# Fase 38 — Resumen de ejecución

Los cinco planes se ejecutaron a mano en una sola sesión, sin `gsd-sdk` (no está
instalado en esta máquina), con el mismo formato de resumen único que usaron las Fases
34-37. Hay un commit por plan y otro para el bug que salió en el checkpoint.

## Qué se hizo, plan a plan

**38-01.** Nuevo paquete `backend/inference/` con `device.py`: `DeviceChoice`,
`ONNX_PROVIDERS` y `resolve_device()`, cacheado por proceso. Las sondas de torch y de
onnxruntime importan en diferido y nunca lanzan. La disponibilidad se evalúa por familia de
motor. `Settings.inference_device` (`auto|cpu|cuda`, validado por `Literal`) queda
registrado en `config_schema` con `applies="restart_server"`. 11 tests en
`tests/test_inference_device.py`.

**38-02.** `PersonDetector` acepta `device`. Con `None`, la ruta CPU no cambia ni una
línea de comportamiento: no hay `.to()`, no hay warm-up y `CUDA_VISIBLE_DEVICES` no se
toca. Con CUDA mueve el modelo, lee el dispositivo efectivo, calienta una vez y, si algo
falla, se queda en CPU con `fallback_reason`. Se añadieron 6 tests.

**38-03.** `ReIDEngine` y `FaceEngine` aceptan `providers` y detectan el fallback
silencioso de onnxruntime comparando `get_providers()` con lo pedido. En `FaceEngine`,
`ctx_id` se deriva de los providers, así que no se puede pedir CUDA y deshacerlo con
`ctx_id=-1`. `PersonRecognizer` gana `face_providers`, `face_device` y
`face_fallback_reason`. Se añadieron 7 tests.

**38-04.** `factory.py` resuelve el dispositivo una vez, lo pasa a YOLO y a ReID, y emite
`DEGRADED_MODE` como mucho una vez por motor y proceso. `main.py` hace lo mismo con el
motor facial. `CameraPipeline.device_stats()` publica `devices` dentro de `stats()`, y de
ahí sale en `GET /api/v2/cameras/{id}/health` sin tocar la capa web. Se añadieron 5 tests.

**38-05.** Arnés `tests/test_inference_benchmark.py` (p50 intercalado CPU frente a CUDA,
se salta sin GPU) y `38-GPU-NOTES.md` con DirectML fuera de alcance, el ≥3× pendiente y el
batching descartado con su condición de reapertura. La nota de trazabilidad va en
`REQUIREMENTS.md`.

## Desviaciones respecto a los planes

1. **El motor facial se reporta solo en `main.py`.** El plan 38-04 lo incluía también en
   `factory._report_device_fallbacks`. Como `PersonRecognizer` es de proceso, se habría
   emitido un `DEGRADED_MODE` duplicado para `face` (uno desde `main.py` y otro desde el
   factory de la primera cámara), así que `_report_device_fallbacks` cubre solo YOLO y
   ReID.
2. **`TEST_benchmark_harness_skips_without_cuda` usa `pytest.raises(pytest.skip.Exception)`**
   en vez de `BaseException` más una comprobación de `typename`. Es equivalente y más
   directo.
3. **Bug previo arreglado en el checkpoint.** Al arrancar el servidor real,
   `GET /api/v2/cameras` y `GET /api/v2/cameras/{id}/health` respondían 500 mientras la
   cámara no había entregado ningún frame. `CaptureWorker.health` publica
   `last_frame_age_s=inf` y JSON no admite infinitos. El fallo venía de la Fase 18, no de
   esta. Se corrigió en la capa API (`_health_dict` en `backend/api/v2/cameras.py`
   serializa `inf` como `null`); el `inf` interno se mantiene porque el sampler de
   Prometheus y el vigilante de `main.py` dependen de él. `frontend/js/views/camera.js`
   pinta `—` y el estado `reconnecting` cuando llega `null`. Test de regresión:
   `TEST_health_serializes_infinite_frame_age_as_null`.

## Checkpoint (Task 3 de 38-05), verificado con el servidor real

- `GET /api/v2/cameras/cam1/health` devuelve 200 con
  `devices = {requested: "auto", yolo/reid/face: {effective: "cpu", fallback_reason: null}}`
  y conserva `capture_fps`, `detection_fps`, `broker_stats` y `workers`.
- Con `INFERENCE_DEVICE=cuda` el arranque aborta con un mensaje que nombra las dos sondas
  y sugiere `auto`.
- **Hallazgo pendiente de decisión:** las líneas `Motor yolo en cpu` y
  `Dispositivo de inferencia: ...` son `logger.info` y no aparecen en la consola. El
  proyecto no configura logging en ningún sitio, así que el root logger se queda en
  WARNING y ningún `logger.info` de `backend.*` se ve, tampoco los de fases anteriores.
  El dispositivo elegido sí es observable a través de `/health`. Hacer visible el log
  exige decidir la configuración global de logging, que se sale del alcance de esta fase.

## Criterios de éxito del ROADMAP

| # | Criterio | Estado | Evidencia |
|---|----------|--------|-----------|
| 1 | GPU detectada con log claro | ✓ CUDA (DirectML fuera de alcance) | `test_inference_device.py`; `devices` en `/health`; log INFO (ver hallazgo) |
| 2 | Proveedor adecuado por motor, seleccionable | ✓ | `-k "cuda_path or device"` en detector/face/reid; `inference_device` en config |
| 3 | ≥3× FPS con GPU, medido | ⧗ Pendiente | Arnés listo; requiere stack GPU instalado (`38-GPU-NOTES.md`) |
| 4 | Sin GPU, idéntico a la Fase 37 | ✓ | `TEST_cpu_path_*`, `TEST_*_defaults_to_cpu_providers`, suite completa verde |
| 5 | Fallo de GPU → CPU + DEGRADED_MODE | ✓ con dobles | `TEST_cuda_path_falls_back_*`, `*_silent_cpu_fallback`, `_report_device_fallbacks` |
| 6 | Batching opcional y desactivable | ✓ por decisión | Descartado y justificado en `38-GPU-NOTES.md` |

Suite completa: 883 passed y 16 skipped (882 antes del fix de `inf`, más su test de
regresión).
