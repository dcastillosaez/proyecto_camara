---
phase: 30
slug: event-timeline-y-centro-de-alertas
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-20
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Compilado directamente por el orquestador a partir de `30-RESEARCH.md` § Validation Architecture (líneas 806-848) y de los 12 PLAN.md ya escritos y verificados por `gsd-plan-checker` (VERIFICATION PASSED), siguiendo el mismo criterio que `29-VALIDATION.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (backend). Sin framework de test JS — `tests/test_frontend_modules.py` valida los módulos nuevos por sintaxis (`node --check`) y convención (límite de líneas, `LOCKED_JS`), no por ejecución. |
| **Config file** | `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto` |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest <fichero(s) tocado(s) por la tarea> -q` (ver comando exacto por tarea en el mapa de abajo) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~90 s (línea base del proyecto, CLAUDE.md § Tests) |

---

## Sampling Rate

- **After every task commit:** el/los ficheros de test de esa tarea (ver columna `Automated Command`) — CLAUDE.md prohíbe la suite completa en cada paso.
- **After every plan wave:** `.venv/Scripts/python.exe -m pytest tests/test_event_bus.py tests/test_migrations.py tests/test_repositories.py tests/test_config.py tests/test_snapshots.py tests/test_events_api.py tests/test_alerts.py tests/test_security_regression.py tests/test_frontend_modules.py -q` (todos los ficheros que la fase toca)
- **Before `/gsd-verify-work`:** Full suite must be green + criterio 3 medido con 10.000 eventos reales (30-12 Task 1) + checkpoint visual manual (30-12 Task 2)
- **Max feedback latency:** ~90 s (duración de la suite completa)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------------|-----------|--------------------|-------------|--------|
| 30-01-01 | 01 | 1 | OPS-11 | `RuleEngine.evaluate()` partido en `match()` puro + `run_actions()`, comportamiento idéntico | unit | `pytest tests/test_rule_engine.py -q` | ✅ existe (9,6 KB), no se modifica — es la red del refactor | ⬜ pending |
| 30-01-02 | 01 | 1 | OPS-10, OPS-11 | `make_event_pipeline()`/`_broadcast_event()` sustituye los 4 suscriptores paralelos por uno solo ordenado; `payload.rules` poblado antes de persistir | integration | `pytest tests/test_stream.py tests/test_event_bus.py -q` | ❌ Wave 0 (test nuevo, cubierto en la misma tarea TDD) | ⬜ pending |
| 30-01-03 | 01 | 1 | OPS-10, OPS-11 | Carrera D-13/14/15 cerrada: evento con regla disparada se persiste **con** `payload.rules`, el WS lo emite después del insert | unit | `pytest tests/test_event_bus.py -q` | ❌ Wave 0 (mismo fichero que 30-01-02, tarea TDD) | ⬜ pending |
| 30-02-01 | 02 | 1 | OPS-09 | `idx_events_ts_id` creado por migración `SCHEMA_VERSION=3`, idempotente sobre una base v2 preexistente | unit | `pytest tests/test_migrations.py -q` | ⚠ existe, se amplía (ya prueba v1→v2) | ⬜ pending |
| 30-02-02 | 02 | 1 | OPS-09 | `EventRepo.query()` acepta `type` multi-valor y filtro por `rule` vía `json_each(payload.rules)`, cursor estable con 10k filas sembradas | unit + perf | `pytest tests/test_repositories.py -q` | ⚠ existe, se amplía | ⬜ pending |
| 30-03-01 | 03 | 2 | OPS-08 | `track_scope()` devuelve el bloque contiguo del track acotado por cámara y ventana temporal (no cruza track_id reciclados) | unit | `pytest tests/test_repositories.py -k track_scope -q` | ❌ Wave 0 | ⬜ pending |
| 30-03-02 | 03 | 2 | OPS-08 | `assign_person()` hace `UPDATE` retroactivo solo sobre la lista explícita de ids (no sobre todo el track_id, evita colisión con homónimos separados en el tiempo) | unit | `pytest tests/test_repositories.py -k assign_person -q` | ❌ Wave 0 | ⬜ pending |
| 30-03-03 | 03 | 2 | OPS-08 | `RecordingRepo.by_trigger_event_ids()` mapea evento→clip en una sola query por página (sin N+1) | unit | `pytest tests/test_repositories.py -k trigger_event -q` | ❌ Wave 0 | ⬜ pending |
| 30-04-01 | 04 | 2 | OPS-07 | Settings `snapshot_dir`/`snapshot_enabled` con validación de ruta (contención en `_PROJECT_ROOT`, mismo patrón que `reid_model_path`) | unit | `pytest tests/test_config.py -k snapshot -q` | ❌ Wave 0 | ⬜ pending |
| 30-04-02 | 04 | 2 | OPS-07 | `_capture_event_snapshot()` usa `asyncio.to_thread` para `cv2.imwrite` (nunca bloquea el event loop), throttle por track, `_purge_old_snapshots()` respeta retención diaria | unit | `pytest tests/test_snapshots.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-04-03 | 04 | 2 | OPS-07, OPS-08 | Hook cableado en el pipeline, `snapshot_path` público servido y montado, retención diaria activa | integration | `pytest tests/test_snapshots.py tests/test_event_bus.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-05-01 | 05 | 3 | OPS-07, OPS-08, OPS-09 | `GET /api/v2/events` — lista paginada por cursor, filtros combinables, envelope `media` siempre hermano de `event`, `total` | integration | `pytest tests/test_events_api.py tests/test_security_regression.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-05-02 | 05 | 3 | OPS-08 | Endpoints track-scope y assign-person expuestos, respetan rate limit v2 (`V2_RATE_LIMIT`) | integration + security | `pytest tests/test_events_api.py tests/test_security_regression.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-06-01 | 06 | 4 | OPS-11 | `GET /api/v2/alerts` agrupa por regla, ordenado por severidad y hora del último disparo, en servidor | integration | `pytest tests/test_alerts.py tests/test_security_regression.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-06-02 | 06 | 4 | OPS-11 | Silenciar/reactivar persiste en `app_config` vía `ConfigRepo`, con TTL; el silenciado es **solo de presentación** — la regla sigue evaluando y ejecutando acciones (Telegram/grabación no se tocan) | unit | `pytest tests/test_alerts.py -q` | ❌ Wave 0 | ⬜ pending |
| 30-07-01 | 07 | 5 | OPS-07, OPS-08, OPS-11 | Estilos nuevos en `components.css` (`.timeline-row`, `.timeline-sep`, `.sev-dot`, `.rule-chip`, `.row-action`, `.alert-group`, `#alert-drawer`) siguiendo exactamente `30-UI-SPEC.md` (spacing/tipografía/color) | mecánico | `pytest tests/test_frontend_modules.py -k line_limit -q` | ✅ (LOCKED_JS ya cubre el patrón, se amplía) | ⬜ pending |
| 30-07-02 | 07 | 5 | OPS-07, OPS-08, OPS-11 | Marcado: card de línea temporal sustituye a `#events-list` in situ, campana + cajón de alertas, `#mark-person-modal` propio (no reutiliza `#enroll-modal`, documentado como desviación) | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-07-03 | 07 | 5 | OPS-07 | JS huérfano que apuntaba al card de eventos eliminado, sin referencias rotas a ids retirados (`#filter-direction`, etc.) | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-08-01 | 08 | 6 | OPS-07 | `timeline-row.js` — fila con descripción en lenguaje llano, estado de descartados con deshacer de 5 s | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ (LOCKED_JS ampliado) | ⬜ pending |
| 30-08-02 | 08 | 6 | OPS-07, OPS-08, OPS-09 | `timeline.js` — filtros resueltos en servidor, cursor, scroll infinito con `IntersectionObserver`, ventana de DOM de 400 filas con compensación de `scrollTop` | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-08-03 | 08 | 6 | OPS-10 | Evento en vivo: inserción arriba si `scrollTop<8px`, píldora "N eventos nuevos" si no, barra de aviso "sin tiempo real" al caer el WS | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-09-01 | 09 | 7 | OPS-11 | `alertCenter.js` — badge de campana (rojo/ámbar/oculto sin alertas), cajón con agrupación por regla; `loadActiveAlerts` retirado de `dashboard.js` (deduplicación de responsabilidad) | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-09-02 | 09 | 7 | OPS-11 | Popover de silenciado con duración obligatoria (15min/1h/8h) como confirmación implícita, sin `confirm()` nativo; reactivación disponible | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-10-01 | 10 | 8 | OPS-10 | `websocket.js` — nuevo `case 'event'` en el dispatch, aviso de "sin tiempo real" en desconexión prolongada | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-10-02 | 10 | 8 | OPS-07, OPS-10, OPS-11 | `app.js` arranca `timeline.js` y `alertCenter.js` en el bootstrap; `LOCKED_JS` actualizado con los 4 módulos nuevos de la fase | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-11-01 | 11 | 9 | OPS-08 | `markPerson.js` — apertura del modal con el recorte del evento precargado (bbox sobre snapshot, 96×96), aviso explícito del alcance retroactivo antes de confirmar | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-11-02 | 11 | 9 | OPS-08 | Confirmación: enrola, llama a `assign-person`, repinta en sitio todas las filas visibles del mismo `track_id` sin recargar la lista ni perder el scroll | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 30-12-01 | 12 | 10 | OPS-09 | Criterio 3 (10.000 eventos navegables sin degradación) medido con datos reales (`scripts/seed_events.py`), suite completa en verde | perf | `pytest tests/ -q` | ✅ existe (`scripts/seed_events.py`) | ⬜ pending |
| 30-12-02 | 12 | 10 | Criterios 1/3/4/5/6 | Checkpoint visual bloqueante con navegador y, si hay acceso, cámara real: aspecto de fila, fluidez del scroll con 400 filas, evento nuevo <1s percibido, marcar como persona, agrupación/silenciado del centro de alertas | manual-only | — (`checkpoint:human-verify`, gate="blocking") | manual | ⬜ pending |
| 30-12-03 | 12 | 10 | OPS-07..OPS-11 | Fase cerrada en `REQUIREMENTS.md` (OPS-07..11 marcados `[x]`), `ROADMAP.md` y `STATE.md` actualizados, suite completa reejecutada verde | mecánico | `pytest tests/ -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_stream.py`/`tests/test_event_bus.py` — tests nuevos para el suscriptor único ordenado y la carrera de reglas cerrada (30-01-02/03, integrados en las tareas TDD, no un plan Wave 0 separado)
- [ ] `tests/test_repositories.py` — ampliar con `track_scope`/`assign_person`/`by_trigger_event_ids`/cursor multi-tipo/filtro por regla (30-02-02, 30-03-01..03)
- [ ] `tests/test_config.py` — settings `snapshot_dir`/`snapshot_enabled` (30-04-01)
- [ ] `tests/test_snapshots.py` (nuevo) — captura con `to_thread`, throttle, purga por retención (30-04-02/03)
- [ ] `tests/test_events_api.py` (nuevo) — router `/api/v2/events`, track-scope, assign-person (30-05-01/02)
- [ ] `tests/test_alerts.py` (nuevo) — agrupación, silenciado/reactivación, TTL, solo-presentación (30-06-01/02)
- [ ] `tests/test_migrations.py` — ampliar con `SCHEMA_VERSION=3`/`idx_events_ts_id` (30-02-01)
- [ ] `tests/test_frontend_modules.py` — ampliar `LOCKED_JS` con `views/timeline.js`, `components/{timelineRow,alertCenter,markPerson}.js` (30-07..30-11)
- [ ] Framework: **ninguna instalación** — todo el instrumental (pytest/pytest-asyncio, `scripts/seed_events.py`) ya existe en el repo.

Todos los ficheros de test "Wave 0" listados arriba se crean **dentro de la misma tarea TDD** que implementa el código correspondiente (patrón integrado del plan, no requieren un plan Wave 0 separado) — confirmado por `gsd-plan-checker` (Dimension 8: PASS readiness).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Fluidez del scroll infinito con 400 filas en pantalla, sin salto perceptible al recortar por arriba | OPS-09, criterio de éxito 3 | Sin runner de navegador en el repo (Fase 34 lo introduce); percepción de "salto" no es medible por assertion | Cargar 10.000 eventos sembrados (`scripts/seed_events.py`), hacer scroll continuo arriba/abajo, confirmar que no hay salto visible del contenido al recortar/reponer filas. Si es perceptible, aplicar el Plan B documentado en UI-SPEC (subir a 1000 filas sin recortar) |
| Evento nuevo visible en <1 s sin recargar | OPS-10, criterio de éxito 4 | Latencia percibida punta a punta (cámara→WS→DOM), no reproducible con un test unitario aislado | Con cámara real o `scripts/seed_events.py` inyectando un evento, cronometrar desde el disparo hasta que la fila aparece (inserción arriba o píldora "N eventos nuevos") |
| "Marcar como persona" precarga el crop correcto y actualiza retroactivamente todas las filas visibles del track | OPS-08, criterio de éxito 5 | Verificación visual del recorte (bbox sobre snapshot) y de la actualización en sitio sin recargar | Abrir el modal desde un evento con `track_id` conocido, confirmar recorte correcto, confirmar, verificar que todas las filas visibles de ese track cambian de "Desconocido" al nombre sin recargar la lista |
| Centro de alertas: agrupación, silenciado y "qué regla disparó" correctos de un vistazo | OPS-11, criterio de éxito 6 | Criterio de legibilidad/producto, no automatizable con assertion | Abrir el cajón con varias reglas activas, confirmar agrupación por regla ordenada por severidad, silenciar una, confirmar que se atenúa y deja de sumar al badge de la campana sin desaparecer de la lista |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (29/30 tareas automatizadas; la única manual es el checkpoint humano bloqueante de `30-12` Task 2, marcado explícitamente como tal en el plan)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (solo la tarea de checkpoint es manual, rodeada de tareas automatizadas)
- [x] Wave 0 covers all MISSING references (7 ficheros de test nuevos/ampliados, todos listados arriba, integrados en sus tareas TDD)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-20 (orquestador, tras leer `30-RESEARCH.md` § Validation Architecture, los 12 PLAN.md ya escritos y el `VERIFICATION PASSED` de `gsd-plan-checker`)
