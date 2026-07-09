---
name: supervision
description: Referencia de la librería supervision (Roboflow) para el pipeline de detección/tracking/conteo de este proyecto. Usar al trabajar en backend/detector.py, backend/tracker.py, backend/stream.py o backend/recognizer.py, o cuando se mencione ByteTrack, LineZone, PolygonZone, anotadores, conteo de cruces, zonas de interés o tracking de personas. El código fuente completo está clonado en third_party/supervision/.
---

# Supervision — referencia para el pipeline de reconocimiento

Versión instalada en `.venv`: **0.27.0** · Fuente clonada (0.30.0.dev, solo consulta): `third_party/supervision/`

## Regla principal

Antes de usar una API de supervision, verificar su firma real en el código fuente clonado — no fiarse de memoria. Rutas clave:

| Tema | Fichero fuente |
|---|---|
| `Detections` (estructura central) | `third_party/supervision/src/supervision/detection/core.py` |
| `LineZone` / `LineZoneAnnotator` | `third_party/supervision/src/supervision/detection/line_zone.py` |
| `PolygonZone` / `PolygonZoneAnnotator` | `third_party/supervision/src/supervision/detection/tools/polygon_zone.py` |
| `ByteTrack` | `third_party/supervision/src/supervision/tracker/byte_tracker/core.py` |
| `DetectionsSmoother` | `third_party/supervision/src/supervision/detection/tools/smoother.py` |
| Anotadores (Box, Label, Trace, HeatMap…) | `third_party/supervision/src/supervision/annotators/core.py` |
| `FPSMonitor` | `third_party/supervision/src/supervision/utils/video.py` |
| Ejemplos completos (conteo, tracking, speed) | `third_party/supervision/examples/` |

⚠️ El clon es 0.30.0.dev y el venv tiene 0.27.0: si una API del clon no existe en el venv, confirmar con
`.venv/Scripts/python.exe -c "import inspect, supervision as sv; print(inspect.signature(sv.X.__init__))"`.

## Firmas verificadas contra el venv (0.27.0)

```python
sv.LineZone(start: Point, end: Point,
            triggering_anchors=(TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT),
            minimum_crossing_threshold: int = 1)
# .trigger(detections) -> (crossed_in: np.bool_[N], crossed_out: np.bool_[N])
# .in_count / .out_count — contadores acumulados internos, ya deduplicados por tracker_id

sv.ByteTrack(track_activation_threshold=0.25, lost_track_buffer=30,
             minimum_matching_threshold=0.8, frame_rate=30,
             minimum_consecutive_frames=1)
# .update_with_detections(detections) -> Detections con .tracker_id
```

## Patrones de uso en este proyecto

Pipeline actual (`stream.py::_capture_loop`):
```
frame → PersonDetector.detect_sv() → sv.Detections
      → PersonTracker.update() (ByteTrack + LineZone)
      → PersonRecognizer.identify_or_register() (caras, por crop de bbox)
      → tracker.annotate() → MJPEG
```

- `sv.Detections.from_ultralytics(results[0])` — puente YOLO→supervision (ya usado en `detector.py:49`).
- Conteo de cruces: preferir `line_zone.in_count`/`out_count` internos a llevar contadores manuales — `LineZone` ya guarda estado por `tracker_id` y deduplica (ver MEJORAS.md punto 1).
- Anti-jitter en cruces: `minimum_crossing_threshold=2` y anchor `Position.BOTTOM_CENTER` para personas (los pies cruzan de forma más fiable que el centro).
- `frame_rate` de `ByteTrack` debe reflejar el FPS real del stream, no el default 30 — afecta a `lost_track_buffer` (que se mide en frames).
- Zonas de interés: `sv.PolygonZone(polygon: np.ndarray[int32])` + `.trigger(detections) -> np.bool_[N]` para presencia por zona; las zonas del proyecto se guardan normalizadas (0-1) en BD → multiplicar por (w, h) del frame antes de construir el polígono (ver `stream.py:263-266`).
- Suavizado de cajas: `sv.DetectionsSmoother` entre tracker y anotación — requiere `tracker_id` presente.

## Disponible en 0.27 (verificado)

`LineZone`, `PolygonZone`, `ByteTrack`, `DetectionsSmoother`, `BoxAnnotator`, `LabelAnnotator`, `TraceAnnotator`, `HeatMapAnnotator`, `FPSMonitor`, `InferenceSlicer`, `sv.Point`, `sv.Position`.

## Documentación offline

- `third_party/supervision/docs/` — mkdocs completo (how-to de tracking, conteo, anotadores).
- `third_party/supervision/examples/count_people_in_zone/` y `.../time_in_zone/` — ejemplos directamente aplicables a las zonas de interés del dashboard.
