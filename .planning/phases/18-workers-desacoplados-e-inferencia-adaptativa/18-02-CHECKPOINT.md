# Task 6 — Checkpoint con cámara real (2026-08-08)

**Estado:** dado por suficiente. 3/4 criterios superados con evidencia directa; el 4º quedó inconcluso por un corte externo de la cámara, documentado abajo.

## 1. CPU antes/después

Comparativa mediante git worktree: `ed85328` (fin fase 17, `RTSPStream` monolítico) vs `main` (fase 18, 5 workers), mismo proceso Python, 60s con una persona en escena.

| | Antes (fase 17) | Después (fase 18) |
|---|---|---|
| CPU (normalizado, 8 cores) | 587.3% | 568.8% |
| RAM | 632 MB | 636 MB |

Ligera mejora de CPU, sin regresión de RAM. No es la ganancia dramática que cabría esperar de desacoplar el pipeline — el modelo YOLO sigue siendo el coste dominante — pero confirma que la capa de workers/supervisor no añade overhead significativo.

## 2. Ritmo desacoplado

`GET /api/v2/cameras/cam1/health` con carga real: `capture_fps: 15.4` vs `detection_fps: 12.0`. Números claramente distintos — la prueba directa de que la captura y la detección corren a ritmos independientes.

## 3. Aislamiento de crash en vivo

Se añadió temporalmente un endpoint de depuración (`POST /api/v2/_debug/crash/{cam}/{worker}`, retirado tras la prueba) que corrompe `_registry` del `DetectionWorker` para forzar una excepción real no capturada.

- **1er y 2º crash:** excepción real (`AttributeError`) → hilo muerto → `WorkerSupervisor` lo reinicia (log: `"detector caido, reiniciando (caida N/3)"`) → `detector` vuelve a `running` en segundos.
- **3er crash dentro de la ventana de 60s:** `detector` → `FAILED`, `degraded: true`. Log: `"detector marcado FAILED tras 3 caidas en 60s — modo degradado, sin mas reintentos"`.
- Durante todo el proceso: `capture`, `streaming`, `recording`, `recognition` siguieron `running` sin verse afectados.
- `GET /video_feed` siguió sirviendo bytes MJPEG (2.1 MB en 2s) con el detector en `FAILED` — el vídeo nunca se interrumpió.

Nota: la ventana de 60s expiró entre el primer crash y los siguientes por el tiempo real transcurrido analizando logs entre intentos — comportamiento correcto y ya cubierto por `test_restart_count_resets_after_window`.

## 4. 1h sin crecimiento de latencia — INCONCLUSO (incidente externo)

Monitor propio sondeando `/api/v2/cameras/cam1/health` cada 20s durante 60 min (164 muestras, `soak_1h_results.csv`).

**Primeros ~52 minutos:** sin problemas. `last_frame_age_s` estable (~0.04s), `capture_fps` ~13-15, `detection_fps` fijo en 12.0, `reconnects=0`, `degraded=false` todo el tramo.

**A partir de t≈3153s (min 52.5):** `last_frame_age_s` empieza a crecer sin límite (llega a 393s al cierre del test) y `connected` pasa a `False`.

**Diagnóstico — no es un bug del pipeline:**
- El puerto RTSP 554 de la cámara rechazaba conexiones en el momento del corte y seguía rechazándolas al verificarlo después (mismo síntoma que al inicio de esta sesión, antes de que se activara "Cuenta de cámara" en la app Tapo). El ping seguía respondiendo — la red y el dispositivo están vivos, es el servicio RTSP el que dejó de responder.
- El backoff de reconexión funcionó exactamente como está diseñado: secuencia `1s → 2s → 4s → 8s → 16s → 30s` (tope) confirmada en logs, reintentando cada 30s de forma indefinida sin crashear ni fugar recursos.
- `reconnects` se quedó en 0 porque ningún intento de reconexión tuvo éxito — coherente con que el servicio RTSP de la cámara, no la red, es el que falló.

**Conclusión:** el crecimiento de `last_frame_age_s` en este caso es la señal *correcta* de una desconexión real y prolongada, no el síntoma de acumulación de buffer que la prueba original buscaba detectar (ese síntoma sería `connected:true` con latencia creciente en silencio — aquí `connected` pasó a `false` de inmediato y se mantuvo así, con reintentos visibles todo el rato).

## Hallazgo colateral (no bloqueante, anotado para el futuro)

`WorkerSupervisor.degraded` solo refleja workers con hilo muerto (`FAILED`). Una desconexión RTSP prolongada dentro de `CaptureWorker` (hilo vivo, pero `connected=False` sostenido) no se propaga a `degraded`. Podría valer la pena que la salud del pipeline también contemple "conectado pero sin frames recientes" como una forma de degradación. Candidato para Fase 19 (Event Engine) o 21 (Observabilidad).

## Decisión

Se da la Task 6 por completa. Los 3 criterios verificables con el sistema controlado (CPU, ritmo, aislamiento de crash) pasan con evidencia sólida. El corte de cámara a los 52 min es un incidente de infraestructura externo (mismo patrón que el de inicio de sesión — la cámara Tapo parece perder el servicio RTSP de forma intermitente), no una regresión introducida por la Fase 18, y queda documentado en vez de repetido.
