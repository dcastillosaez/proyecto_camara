---
phase: 33
slug: editores-visuales-de-zonas-l-neas-y-reglas
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-24
---

# Phase 33 — Validation Strategy

> Per-phase validation contract para el sampling de feedback durante la ejecución.
> Compilado directamente a partir de `33-RESEARCH.md` § Validation Architecture (líneas
> 319-352) y de los 14 `PLAN.md` ya escritos (33-01..33-14), siguiendo la misma plantilla
> que `32-VALIDATION.md` — este documento fue uno de los bloqueantes que dejó
> `gsd-plan-checker` en la primera pasada de revisión, ya resuelto aquí.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest.ini`: `python_functions = TEST_*`, `asyncio_mode = auto`). Sin framework de test JS — los módulos nuevos (`zoneEditor.js`, `lineEditor.js`, `rules-form.js`, `rules-editor.js`, extensiones de `videoCanvas.js`/`camera.js`/`app.js`) se validan por sintaxis (`node --check`) y por `tests/test_frontend_modules.py` (`LOCKED_JS`, tope de 300 líneas, convención anti-XSS), no por ejecución. |
| **Config file** | `pytest.ini` (raíz del proyecto) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_zones_api.py tests/test_lines_api.py tests/test_rules_api.py -q` (ficheros nuevos, Wave 0 — ajustar al fichero tocado por cada tarea, ver el mapa de abajo) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~90 s (línea base del proyecto) |

---

## Sampling Rate

- **After every task commit:** el/los ficheros de test de esa tarea (ver columna `Automated Command`).
- **After every plan wave:** suite acumulada de los ficheros que la fase toca hasta ese punto — por ejemplo, tras la Wave 2: `.venv/Scripts/python.exe -m pytest tests/test_repositories.py tests/test_rule_engine.py tests/test_migrations.py tests/test_zones_api.py tests/test_pipeline_lines.py tests/test_detection_worker.py tests/ -k "camera and not test_camera_module" -q`.
- **Before `/gsd-verify-work`:** Full suite must be green + los 7 criterios de éxito del ROADMAP trazados a un `pytest -k` concreto (33-14 Task 1) + checkpoint visual manual bloqueante (33-14 Task 2).
- **Max feedback latency:** ~90 s.

---

## Per-Task Verification Map

> Cada `Automated Command` es copia literal del `<verify><automated>` del `PLAN.md`
> correspondiente — no una versión re-derivada (lección de la segunda pasada de checker
> en la Fase 32: los comandos re-derivados divergen del `<verify>` real y dan una falsa
> señal de cobertura).

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------------|-----------|--------------------|-------------|--------|
| 33-01-01 | 01 | 1 | OPS-22 (base) | `LineRepo` + `RuleRepo.get(rule_id)` — mismo molde que `ZoneRepo`, tabla `lines` del esquema v2 pasa a tener consumidor real | unit | `.venv/Scripts/python.exe -m pytest tests/test_repositories.py -k "Line or rule_get" -q` | ⚠ existe, casos nuevos | ⬜ pending |
| 33-01-02 | 01 | 1 | RULE-05, OPS-23 | `RuleEngine.would_match()` público (sin mutar debounce) + `is_schedule_active()` para el gating de horario de zonas | unit | `.venv/Scripts/python.exe -m pytest tests/test_rule_engine.py -k "would_match or schedule_active" -q` | ⚠ existe, casos nuevos | ⬜ pending |
| 33-02-01 | 02 | 1 | OPS-21, OPS-22, OPS-23 | Migración v4→v5: backfill `zones.polygon_json`→`polygon`, seed de línea por defecto en la tabla `lines` desde la línea única `.env` existente | integration | `.venv/Scripts/python.exe -m pytest tests/test_migrations.py -q` | ✅ (fichero existe, caso nuevo) | ⬜ pending |
| 33-03-01 | 03 | 1 | OPS-21, OPS-23 | Router `/api/v2/zones` — CRUD, validación de polígono (≥3 puntos, fracciones `[0,1]`), hot-reload sin reiniciar (criterio 6) | integration | `.venv/Scripts/python.exe -m pytest tests/test_zones_api.py -q` | ❌ Wave 0 | ⬜ pending |
| 33-04-01 | 04 | 1 | OPS-22 | `PersonTracker` refactor de una línea a N líneas independientes con conteo propio, ByteTrack compartido (D-01) | unit | `.venv/Scripts/python.exe -m pytest tests/test_tracker.py tests/test_phase9.py -q` | ⚠ existen, migrados + casos nuevos | ⬜ pending |
| 33-04-02 | 04 | 1 | OPS-22 | `emit_line_crossing` propaga `line_id`/`line_name` al payload; migración de las 4 construcciones `PersonTracker(...)` posicionales en `tests/test_detection_worker.py` a la forma `lines=[...]` (bloqueante corregido en revisión — ver `33-04-PLAN.md` Task 2) | unit | `.venv/Scripts/python.exe -m pytest tests/test_event_engine.py tests/test_detection_worker.py -q` | ⚠ existen, migrados | ⬜ pending |
| 33-05-01 | 05 | 2 | OPS-21, OPS-22, OPS-23 | `DetectionWorker.set_lines()` (hot-reload de líneas <1s) + zonas leen `polygon` como lista (no `polygon_json`) + gating de horario de zona vía `is_schedule_active()` | integration | `.venv/Scripts/python.exe -m pytest tests/test_pipeline_lines.py tests/test_detection_worker.py -q` | ❌ Wave 0 (`test_pipeline_lines.py`) | ⬜ pending |
| 33-05-02 | 05 | 2 | OPS-22 | `CameraPipeline.set_lines()` + retirada del recálculo manual de línea en `camera.py` (ya no hay línea única `.env`) | integration | `.venv/Scripts/python.exe -m pytest tests/ -k "camera and not test_camera_module" -q` | ✅ | ⬜ pending |
| 33-06-01 | 06 | 2 | OPS-24, RULE-05 | Router `/api/v2/rules` — CRUD validado contra `Rule`/`When`/`Action` reales, 422 con shape CUSTOM `{"detail":{"errors":[...]}}` (bloqueante corregido en revisión — nunca el shape nativo de FastAPI), `POST /{id}/test` puro sobre los últimos 500 eventos | integration | `.venv/Scripts/python.exe -m pytest tests/test_rules_api.py -q` | ❌ Wave 0 | ⬜ pending |
| 33-07-01 | 07 | 3 | OPS-22 | Router `/api/v2/lines` — CRUD, validación (línea no degenerada), hot-reload | integration | `.venv/Scripts/python.exe -m pytest tests/test_lines_api.py -q` | ❌ Wave 0 | ⬜ pending |
| 33-08-01 | 08 | 4 | OPS-21, OPS-22, OPS-24 | Wiring de los 3 routers v2 (zonas/líneas/reglas) + arranque de `CameraPipeline`/`rule_engine` desde repositorios v2, no desde YAML/`.env` de línea única | integration | `.venv/Scripts/python.exe -m pytest tests/test_zones_api.py tests/test_lines_api.py tests/test_rules_api.py -q` | ✅ | ⬜ pending |
| 33-08-02 | 08 | 4 | OPS-22 | `config_schema.py` — retirar los campos `line_*_frac` de línea única, apuntar `external_source` de zonas/líneas/reglas a los routers v2 | unit | `.venv/Scripts/python.exe -m pytest tests/test_config_schema.py tests/test_config_api.py -q` | ✅ | ⬜ pending |
| 33-08-03 | 08 | 4 | OPS-21, OPS-22, OPS-24 | Suite completa + verificación de arranque real (`import backend.main` no falla tras retirar la línea única) | perf/integration | `.venv/Scripts/python.exe -m pytest tests/ -q` | ✅ | ⬜ pending |
| 33-09-01 | 09 | 1 | OPS-21, OPS-22 | `canvasClickToFrac` exportada + `syncCanvasToImage` reutilizable + cursor de edición — base matemática compartida por `zoneEditor.js`/`lineEditor.js` | mechanical | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-10-01 | 10 | 2 | OPS-21 | Motor de canvas de `zoneEditor.js` — dibujo/arrastre de vértices/hit-testing, sin `innerHTML` (corrige la única desviación anti-XSS del fichero legacy) | mechanical | `node --check frontend/js/components/zoneEditor.js && .venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-10-02 | 10 | 2 | OPS-21, OPS-23 | CRUD de zona (kind/schedule) contra `/api/v2/zones`; 422 nativo de FastAPI (lista) renderizado con `d.detail.map(e => e.msg).join(', ')` (warning de checker corregido en revisión, no `d.detail` directo) | mechanical | `node --check frontend/js/components/zoneEditor.js && .venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-11-01 | 11 | 2 | OPS-22 | Motor de canvas de `lineEditor.js` — trazado de dos clicks + indicador visual de dirección | mechanical | `node --check frontend/js/components/lineEditor.js && .venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-11-02 | 11 | 2 | OPS-22 | CRUD de línea contra `/api/v2/lines`; mismo fix de renderizado 422 nativo que 33-10-02 (warning de checker corregido en revisión) | mechanical | `node --check frontend/js/components/lineEditor.js && .venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-12-01 | 12 | 1 | OPS-24 | `rules-form.js` — renderers de campo para `When`/`Action`, `data-when-field` para mapeo de errores 422, sin `innerHTML` | mechanical | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-12-02 | 12 | 1 | OPS-24, RULE-05 | `rules-editor.js` — CRUD + "Probar regla" contra `/api/v2/rules`; consume el shape CUSTOM `{"detail":{"errors":[...]}}` que 33-06 ahora garantiza (contradicción de checker resuelta en revisión) | mechanical | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-13-01 | 13 | 5 | OPS-21, OPS-22, OPS-24 | Armazón HTML de los tres editores en `#view-camara` + retirada de la tarjeta legacy "Zonas de interés" (Fase 13) | mechanical | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -k "no_inline_logic" -q` | ✅ | ⬜ pending |
| 33-13-02 | 13 | 5 | OPS-21, OPS-22, OPS-24 | Wiring en `camera.js`/`app.js` (`initZoneEditor`/`initLineEditor`/`initRulesEditor`) + enlaces de las subsecciones de solo lectura de Ajustes actualizados a los editores reales | mechanical | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 33-13-03 | 13 | 5 | OPS-21..24, RULE-05 | `LOCKED_JS`/`LOCKED_CSS` ampliado con los módulos nuevos de la fase + checkpoint de arranque con servidor real | perf/integration | `.venv/Scripts/python.exe -m pytest tests/ -q` | ✅ | ⬜ pending |
| 33-14-01 | 14 | 6 | OPS-21..24, RULE-05 | Trazabilidad de los 7 criterios de éxito del ROADMAP (líneas 641-648) a un test concreto por nombre de fichero::función + suite completa en verde | perf/integration | `.venv/Scripts/python.exe -m pytest tests/ -q` | ✅ | ⬜ pending |
| 33-14-02 | 14 | 6 | Criterios 1-7 del ROADMAP | Checkpoint visual bloqueante: dibujar/mover/borrar zona con tipo+horario, trazar 2 líneas con dirección visible, componer y probar una regla, hot-reload <1s sin parón visible | manual-only | — (`checkpoint:human-verify`, gate="blocking") | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_zones_api.py` (nuevo) — contrato de `GET/POST /api/v2/zones` + `DELETE /{id}`: validación de polígono (≥3 puntos, fracciones `[0,1]`), `kind`/`schedule`, hot-reload sin reinicio (criterio 6), molde: `tests/test_detection_config_api.py` (33-03-01)
- [ ] `tests/test_lines_api.py` (nuevo) — contrato de `GET/POST /api/v2/lines` + `DELETE /{id}`: validación de línea no degenerada, hot-reload (33-07-01)
- [ ] `tests/test_rules_api.py` (nuevo) — CRUD de reglas validado contra `Rule`/`When`/`Action`, shape custom de error 422 (`{"detail":{"errors":[...]}}`), `POST /{id}/test` contra eventos mockeados (33-06-01)
- [ ] `tests/test_pipeline_lines.py` (nuevo) — `DetectionWorker.set_lines()`/`CameraPipeline.set_lines()`: hot-reload <1s sin reiniciar el pipeline (criterio 6), molde: patrón ya usado por `set_zones()` en `backend/pipeline/detection.py` (33-05-01)
- [ ] Fixture/seed de eventos sintéticos: NO se crea un fichero nuevo — 33-06 mockea `EventRepo.query` directamente en `tests/test_rules_api.py` (decisión documentada en el propio plan); `scripts/seed_events.py` (ya existe) cubre el volumen real solo para el checkpoint manual de 33-14
- [ ] El frontend (canvas, drag de vértices, trazado de línea) no tiene cobertura automatizada en esta fase (Playwright llega en Fase 34) — verificación manual/checkpoint visual (33-14 Task 2), mismo patrón que toda fase de frontend anterior (32-08)
- [ ] Framework: **ninguna instalación** — pytest ya instalado, sin runner JS que instalar

Todos los ficheros de test "Wave 0" se crean/amplían **dentro de la misma tarea** que implementa el código correspondiente (patrón integrado, igual que las Fases 30, 31 y 32).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Dibujar/mover/editar vértices/borrar un polígono sobre el vídeo en vivo | Criterio 1 del ROADMAP | Interacción de ratón sobre `<canvas>`, sin framework de test JS en esta fase (Playwright llega en la Fase 34) | 33-14 Task 2, paso 1-2 |
| Trazar dos líneas de conteo con indicador de dirección visible | Criterio 2 del ROADMAP | Igual que arriba — dibujo interactivo | 33-14 Task 2, paso 3 |
| Zona con tipo+horario visibles y editables desde el formulario | Criterio 3 del ROADMAP | Requiere DOM real renderizado, no solo el módulo importado | 33-14 Task 2, paso 1 |
| Componer una regla completa y validarla en servidor desde el formulario | Criterio 4 del ROADMAP | Interacción de formulario + servidor real | 33-14 Task 2, paso 4 |
| `POST /rules/{id}/test` con volumen de eventos real (no mockeado) | Criterio 5 del ROADMAP | El test automatizado de 33-06 mockea `EventRepo.query`; el volumen real depende de los eventos ya sembrados en `data/events.db` o de `scripts/seed_events.py` | 33-14 Task 2, paso 4 (con seed si hace falta) |
| Hot-reload de zona/línea en <1s sin parón visible del stream MJPEG | Criterio 6 del ROADMAP | Latencia real observable solo con el pipeline vivo sirviendo vídeo, no en pytest — `tests/test_pipeline_lines.py`/`tests/test_zones_api.py` cubren la ausencia de reinicio a nivel unitario, pero no la percepción visual de continuidad | 33-14 Task 2, paso 5 |
| Zona dibujada a 720p sigue siendo correcta al cambiar a 1080p | Criterio 7 del ROADMAP | Mayormente AUTOMATIZADO: 33-05-01 cubre el recálculo de línea/zona al cambiar `shape` de frame (`tests/test_pipeline_lines.py`, bullet "720p → 1080p" del `<behavior>`), y `_rebuild_zone_states` reutiliza la misma matemática fracción→píxel para zonas. Solo la negociación real de resolución con la cámara Tapo queda fuera de pytest | Cubierto por `pytest tests/test_pipeline_lines.py -q` (unit, 33-05-01) + observación manual si la cámara cambia de resolución durante 33-14 Task 2 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (23/24 tareas automatizadas; la única manual es el checkpoint humano bloqueante de 33-14 Task 2, precedido siempre por 33-14 Task 1 con suite en verde — nunca dos tareas manuales consecutivas)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (4 ficheros de test nuevos, todos listados arriba, integrados en sus tareas correspondientes)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-24 (revisión dirigida tras `gsd-plan-checker` — VERIFICATION: ISSUES FOUND, 4 blockers + 2 warnings). Este documento cierra el Blocker 1 (ausencia de `33-VALIDATION.md`); los otros 3 blockers (contradicción de shape 422 en 33-06/33-12, migración incompleta de `PersonTracker(...)` en `tests/test_detection_worker.py` dentro de 33-04, y Open Questions de `33-RESEARCH.md` sin marcador `(RESOLVED)`) y los 2 warnings (renderizado de 422 nativo en 33-10/33-11) se corrigieron directamente en los `PLAN.md`/`RESEARCH.md` afectados, no en este documento — las filas de la tabla de arriba ya reflejan esas correcciones.
