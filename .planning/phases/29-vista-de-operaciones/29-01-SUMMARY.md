---
phase: 29
plan: 01
subsystem: backend/pipeline + backend/main (WebSocket)
tags: [tracking, websocket, ops-05]
dependency-graph:
  requires: []
  provides:
    - "CameraPipeline.get_person_boxes()"
    - "_tracks_broadcast_loop() (asyncio, registrada en lifespan())"
    - "mensaje WS {\"type\": \"tracks\", \"camera_id\": ..., \"tracks\": [...]}"
  affects:
    - "29-02-PLAN.md (consume literalmente el mismo payload en el frontend)"
tech-stack:
  added: []
  patterns:
    - "Método pull de solo lectura en CameraPipeline (precedente: get_object_boxes(), Fase 27)"
    - "Corrutina asyncio periódica registrada/cancelada en lifespan() (precedente: _housekeeping_loop)"
key-files:
  created:
    - tests/test_manager.py
  modified:
    - backend/pipeline/manager.py
    - backend/main.py
    - tests/test_stream.py
decisions:
  - "bbox normalizado 0-1 (no píxeles absolutos) — el frontend solo conoce naturalWidth/naturalHeight, no process_size"
  - "Filtrado por frame_ids(), nunca snapshot()/active_ids() sin filtrar — evita bboxes fantasma de tracks con hasta 30s sin verse (TTL de prune())"
  - "Canal /ws legacy reutilizado (decisión ya fijada en 29-RESEARCH.md, no re-evaluada aquí)"
metrics:
  duration: "~35 min"
  completed: 2026-08-20
---

# Phase 29 Plan 01: Publicador de tracks a 2Hz (backend) Summary

Backend expone `CameraPipeline.get_person_boxes()` (bboxes de personas normalizados 0-1, filtrados por `frame_ids()`) y una corrutina asyncio nueva `_tracks_broadcast_loop()` que los publica por `/ws` cada 500ms exactos, sin tocar ningún worker del pipeline.

## Lo construido

**Task 1 — `CameraPipeline.get_person_boxes()`** (`backend/pipeline/manager.py`): método de solo lectura, mismo patrón que `get_object_boxes()` (Fase 27). Normaliza el bbox absoluto de cada `TrackState` dividiendo por `get_process_size()` (con fallback a `get_native_resolution()`), filtra por `registry.frame_ids()` (nunca `snapshot()` sin filtrar, para no arrastrar tracks con hasta 30s sin verse), y expone `identity_state` como string (`ts.identity_state.value`) y `person_name`. Devuelve `[]` sin excepción si no hay resolución válida. 4 tests nuevos en `tests/test_manager.py` (fichero nuevo, no existía) — construyen `CameraPipeline` vía `object.__new__()` para evitar levantar `CaptureWorker`/RTSP real.

**Task 2 — `_tracks_broadcast_loop()`** (`backend/main.py`): corrutina asyncio nueva, mismo molde que `_housekeeping_loop` — `while True: await asyncio.sleep(interval); if camera_manager is None: continue; ...`. Cada 500ms, para cada pipeline llama a `get_person_boxes()` y hace `await _broadcast({"type": "tracks", "camera_id": ..., "tracks": ...})` sobre el `_ws_clients` ya existente (canal `/ws` legacy, sin endpoint nuevo). Registrada como `tracks_task` en `lifespan()` junto a `housekeeping_task`, cancelada en el shutdown. 1 test de integración nuevo en `tests/test_stream.py` (`TEST_tracks_broadcast_loop_sends_normalized_payload`), primer precedente de test WS-loop en el repo — sigue el patrón de mocks de `TEST_077_lifespan_starts_and_stops_camera_pipeline`, fuerza una sola iteración parcheando `asyncio.sleep` con `side_effect=[None, CancelledError()]`.

## Contrato del mensaje (fuente para 29-02-PLAN.md)

```json
{
  "type": "tracks",
  "camera_id": "cam1",
  "tracks": [
    {"track_id": 7, "bbox": [0.12, 0.30, 0.28, 0.81], "identity_state": "CONFIRMED", "person_name": "Ana"}
  ]
}
```

## Deviations from Plan

None - plan executed exactly as written.

## Verificación

- `pytest tests/test_manager.py -q` → 4 passed
- `pytest tests/test_stream.py -k tracks -q` → 2 passed (1 nuevo + 1 preexistente que matchea el patrón)
- `pytest tests/ -q` → 530 passed, 2 skipped (525 previos + 5 nuevos)
- Ningún hilo del pipeline ni ninguna corrutina del bucle ejecuta inferencia — el bucle solo lee (`get_person_boxes()`) y hace `await asyncio.sleep`/`await _broadcast` (CLAUDE.md invariantes 1, 5, 6)

## Self-Check: PASSED

- FOUND: backend/pipeline/manager.py contiene `def get_person_boxes`
- FOUND: backend/main.py contiene `_tracks_broadcast_loop` (definición, creación de task, cancelación)
- FOUND: tests/test_manager.py (4 funciones TEST_*)
- FOUND: tests/test_stream.py contiene TEST_tracks_broadcast_loop_sends_normalized_payload
- FOUND commit 38e7f80: feat(29-01): get_person_boxes() en CameraPipeline, filtrado por frame_ids
- FOUND commit b12e2fc: feat(29-01): _tracks_broadcast_loop publica bboxes por /ws a 2Hz
