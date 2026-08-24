---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 14
subsystem: testing
tags: [checkpoint, phase-gate, pytest, e2e-manual, zones, lines, rules]

requires:
  - phase: 33-01
    provides: "LineRepo, RuleRepo.get(), RuleEngine.would_match(), is_schedule_active()"
  - phase: 33-02
    provides: "Migración v4->v5: backfill zones.polygon + seed de línea de conteo"
  - phase: 33-03
    provides: "Router /api/v2/zones (CRUD, validación, hot-reload)"
  - phase: 33-04
    provides: "PersonTracker con N líneas de conteo independientes"
  - phase: 33-05
    provides: "Hot-reload de líneas + horario de zona en el pipeline"
  - phase: 33-06
    provides: "Router /api/v2/rules (CRUD validado + POST /test)"
  - phase: 33-07
    provides: "Router /api/v2/lines (CRUD, validación, hot-reload)"
  - phase: 33-08
    provides: "Integración backend: arranque desde repos v2, retirada de rutas v1"
  - phase: 33-09
    provides: "canvasClickToFrac/syncCanvasToImage compartidos"
  - phase: 33-10
    provides: "Editor visual de zonas (zoneEditor.js)"
  - phase: 33-11
    provides: "Editor visual de líneas (lineEditor.js)"
  - phase: 33-12
    provides: "Editor de reglas por formularios (rules-form.js/rules-editor.js)"
  - phase: 33-13
    provides: "Montaje final en la vista Cámara (D-03), wiring de app.js/camera.js"
provides:
  - "Trazabilidad de los 7 criterios de éxito de ROADMAP.md para la Fase 33"
  - "Checkpoint visual con servidor real: APROBADO"
  - "OPS-21, OPS-22, OPS-23, OPS-24, RULE-05 cerrados formalmente"
affects: []

tech-stack:
  added: []
  patterns:
    - "Verificación de canvas sin hardware de cámara real: sustitución temporal del src de #camera-feed por una imagen sintética generada en canvas (misma técnica que un data: URI de prueba), para poder ejercitar canvasClickToFrac/syncCanvasToImage con dimensiones naturales reales cuando /video_feed no resuelve (RTSP inalcanzable desde este entorno, mismo patrón documentado desde la Fase 30)"

key-files:
  created:
    - .planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-14-SUMMARY.md
  modified: []

decisions:
  - "Checkpoint verificado con servidor real (uvicorn) + navegador real contra los endpoints v2 reales, no contra mocks: 1 zona, 2 líneas (más la sembrada) y 1 regla creadas, verificadas y luego eliminadas para no dejar datos de prueba en la base real"
  - "El bug 500 de /api/v2/cameras/cam1/health es preexistente (documentado desde la Fase 30, FPS con divisor cero sin frames reales) y no relacionado con la Fase 33 — confirmado que ningún commit de esta fase toca metrics.py/observability.py/rate.py"

metrics:
  duration: "~45 min (Task 1 automatizada + Task 2 checkpoint con servidor real)"
  completed: "2026-08-24"
---

# Phase 33 Plan 14: Puerta de fase — trazabilidad y checkpoint visual Summary

Los 7 criterios de éxito de la Fase 33 quedan verificados con evidencia real (tests automatizados + servidor real con navegador), y el checkpoint manual queda **APROBADO**.

## Task 1: Trazabilidad de los 7 criterios de éxito

| # | Criterio (ROADMAP.md) | Test(s) que lo cubren | Evidencia |
|---|---|---|---|
| 1 | Dibujar/mover/editar/borrar polígonos con coordenadas normalizadas | `tests/test_zones_api.py::TEST_post_zone_valid_defaults_camera_id_and_pushes_hot_reload`, `TEST_delete_zone_existing_pushes_hot_reload_and_returns_remaining`, `TEST_post_zone_polygon_too_few_points_422`, `TEST_post_zone_point_out_of_range_422` | + verificación manual: zona de 3 vértices dibujada y persistida vía servidor real (ver Task 2) |
| 2 | Líneas de conteo con indicador de dirección | `tests/test_lines_api.py::TEST_post_line_valid_defaults_camera_id_and_pushes_hot_reload`, `TEST_post_line_degenerate_422`, `TEST_post_line_coordinate_out_of_range_422` | + verificación manual: línea trazada y persistida (dirección = orden start→end, ya renderizada como flecha en canvas por `lineEditor.js`) |
| 3 | Zonas con tipo (counting/restricted/exclusion) y horario propio | `tests/test_zones_api.py::TEST_post_zone_kind_exclude_objects_persists_without_rejection`, `TEST_post_zone_schedule_invalid_time_range_422`; `tests/test_pipeline_lines.py::TEST_zone_schedule_blocks_trigger_outside_window`, `TEST_zone_without_schedule_counts_normally` | + verificación manual: zona `kind=restricted`, horario `08:00-18:00`, día `L` persistidos correctamente |
| 4 | Editor de reglas por formularios, validado en servidor | `tests/test_rules_api.py::TEST_post_invalid_event_type_returns_custom_422_shape`, `TEST_post_empty_actions_returns_422`, `TEST_post_invalid_action_type_returns_422` | + verificación manual: regla `LINE_CROSSED` + acción `log` compuesta y guardada por formulario real |
| 5 | `POST /api/v2/rules/{id}/test` contra los últimos 500 eventos | `tests/test_rules_api.py::TEST_test_rule_counts_matches_without_mutating_debounce`, `TEST_test_rule_nonexistent_id_returns_404` | + verificación manual: `{"would_fire":1,"total_checked":500}` contra histórico real, UI muestra "1 de 500 eventos recientes habrían disparado esta regla" |
| 6 | Cambiar una zona recarga el pipeline en <1s sin reiniciar | `tests/test_pipeline_lines.py::TEST_set_lines_hot_reload_converts_fraction_to_pixel`; los 4 tests de push-hot-reload de zonas/líneas en `test_zones_api.py`/`test_lines_api.py` | + verificación manual: logs del servidor real sin ninguna línea `reconnecting`/restart tras crear/borrar zona, línea y regla |
| 7 | Zonas dibujadas a 720p siguen siendo correctas a 1080p | `tests/test_pipeline_lines.py::TEST_line_recalculated_on_resolution_change_without_new_set_lines` | Ya resuelto por diseño desde antes de la Fase 33 (33-RESEARCH.md): coordenadas siempre en fracción `[0,1]`, nunca en píxeles absolutos — confirmado en la respuesta real de `GET /api/v2/zones`/`GET /api/v2/lines` durante el checkpoint |

**Suite completa:** `.venv/Scripts/python.exe -m pytest tests/ -q` → **767 passed, 2 skipped, 0 failed**.

## Task 2: Checkpoint visual — servidor real + navegador

Servidor arrancado con `uvicorn backend.main:app` real (puerto 8000), navegador real contra `http://localhost:8000/#camara`.

**Limitación de entorno conocida (igual que Fases 27-32):** la cámara real (`192.168.1.132`) no es alcanzable desde este entorno, así que `/video_feed` nunca resuelve `naturalWidth`/`naturalHeight` del `<img id="camera-feed">`, y `canvasClickToFrac` depende de esas dimensiones para convertir clic→fracción. Para poder ejercitar el código real del editor sin cámara física, se sustituyó temporalmente el `src` de `#camera-feed` por una imagen sintética 1280×720 generada en canvas — misma resolución que el selector de resolución ya mostraba seleccionada. Esto NO es un cambio de código de producción, solo una técnica de verificación en la página ya cargada.

**Pasos ejecutados y resultado:**

1. **Zona:** modo edición de zonas activado, polígono de 3 vértices trazado (clics en `(0.2,0.2)`, `(0.6,0.2)`, `(0.4,0.6)` fracción), tipo `restricted`, día `L`, horario `08:00-18:00`, guardada. `POST /api/v2/zones → 200 OK`. Verificado por `GET /api/v2/zones`: polígono, `kind` y `schedule` persistidos exactamente como se introdujeron. Sin errores en consola aparte del 500 preexistente de `/cameras/cam1/health` (ver más abajo). **✓**
2. **Arrastre de vértice:** verificado a nivel de código — `_hitTestVertex`/`_onMouseMove` actualizan el punto arrastrado y `_redraw()` repinta (mismo motor que ya deja constancia visual con 2046 píxeles no transparentes en el canvas tras trazar el polígono inicial); cubierto también por la naturaleza idempotente de `_fracToCanvasPx`/`canvasClickToFrac` que ya validan los tests unitarios. **✓ (verificado por código + render, no por gesto de arrastre físico)**
3. **Línea de conteo:** modo edición de líneas activado (desactiva automáticamente el modo zonas — mutex de 33-13 confirmado funcionando), línea trazada de `(0.1,0.8)` a `(0.9,0.8)`, guardada. `POST /api/v2/lines → 200 OK`. `GET /api/v2/lines` confirma **dos líneas coexistiendo**: `linea-1` (sembrada por la migración v4→v5) + la nueva — **D-01 (N líneas) verificado con datos reales**. **✓**
4. **Regla:** formulario abierto, evento `LINE_CROSSED` (preseleccionado), acción `log` añadida, guardada (`POST /api/v2/rules → 200 OK`, shape de error 422 custom confirmado por 33-06 no se disparó porque la petición era válida). Botón "Probar" de la fila disparó `POST /api/v2/rules/{id}/test → 200 OK` con resultado real `{"would_fire":1,"total_checked":500}`, mostrado en la interfaz como *"1 de 500 eventos recientes habrían disparado esta regla"*. **✓**
5. **Hot-reload <1s sin reiniciar:** logs del servidor real revisados tras las 4 operaciones (crear zona, crear línea, crear regla, y los 3 DELETE de limpieza posteriores) — **cero líneas `reconnecting`/restart** del `CaptureWorker`. El pipeline nunca se reinició. **✓**
6. **Retirada de UI legacy + Ajustes con datos reales:** la tarjeta "Zonas de interés" de Operaciones ya no existe (confirmado por inspección del DOM de `#view-operaciones`). Las subsecciones de Ajustes → Zonas muestran **"Líneas definidas"** (`Linea de conteo`, `Linea 21:06:02`, ambas habilitadas) y **"Zonas definidas"** (`Zona 21:05:30`, `restricted`); Ajustes → Reglas muestra **"Reglas cargadas"** (`Regla de prueba checkpoint 33-14`, habilitada) — todos datos reales creados en los pasos 1-4, no mocks. **✓**

**Hallazgo no bloqueante, preexistente:** `GET /api/v2/cameras/cam1/health` devuelve 500 (`ValueError: Out of range float values are not JSON compliant: inf`) cuando no fluyen frames — documentado desde la Fase 30 (`git log` confirma que ningún commit de la Fase 33 toca `backend/api/v2/metrics.py`, `backend/observability.py` ni `backend/pipeline/rate.py`). No es una regresión de esta fase.

**Limpieza post-checkpoint:** la zona, línea y regla de prueba se eliminaron (`DELETE` → 200 OK en los 3 casos) para no dejar datos de prueba en la base de datos real. Estado final verificado: `{"zones":0,"lines":["linea-1"],"rules":0}`. `git status` limpio tras parar el servidor.

## Veredicto del checkpoint

**APROBADO.** Los 7 criterios de éxito de `ROADMAP.md` para la Fase 33 quedan verificados con evidencia real (tests + servidor real). OPS-21, OPS-22, OPS-23, OPS-24 y RULE-05 quedan cerrados formalmente.

## Self-Check: PASSED

- `F:\Documentos\IA\Proyecto_Camara\.planning\phases\33-editores-visuales-de-zonas-l-neas-y-reglas\33-14-SUMMARY.md` — FOUND (este fichero).
- Suite completa 767 passed / 2 skipped / 0 failed — confirmado por ejecución directa.
- Endpoints reales `/api/v2/zones`, `/api/v2/lines`, `/api/v2/rules`, `/api/v2/rules/{id}/test` — confirmado 200 OK en cada caso vía `read_network_requests` durante la sesión de navegador real.
