---
phase: 31
slug: vista-de-anal-tica
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-22
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Compilado directamente por el orquestador a partir de `31-RESEARCH.md` § Validation Architecture (líneas 879-926) y de los 11 PLAN.md ya escritos, siguiendo la misma plantilla que `30-VALIDATION.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (`asyncio_mode = auto`). Sin framework de test JS — los módulos nuevos se validan por sintaxis (`node --check`) y convención (límite de 300 líneas, `LOCKED_JS`), no por ejecución. |
| **Config file** | `pytest.ini` — `python_functions = TEST_*` |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_analytics_api.py -q` (ajustar al fichero/patrón tocado por cada tarea, ver el mapa de abajo) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~90 s (línea base del proyecto, más los tests de presupuesto a 100k) |

---

## Sampling Rate

- **After every task commit:** el/los ficheros de test de esa tarea (ver columna `Automated Command`).
- **After every plan wave:** `.venv/Scripts/python.exe -m pytest tests/test_analytics_api.py tests/test_repositories.py tests/test_migrations.py tests/test_detection_worker.py tests/test_frontend_modules.py -q` (todos los ficheros que la fase toca).
- **Before `/gsd-verify-work`:** Full suite must be green + criterios 3 y 4 medidos con números reales (31-11 Task 2) + checkpoint visual manual (31-03 Task 4 y 31-11 Task 3).
- **Max feedback latency:** ~90 s.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------------|-----------|--------------------|-------------|--------|
| 31-01-01 | 01 | 1 | OPS-12, OPS-14 | `scripts/seed_events.py` puebla `person_id`/`zone_id` con `--persons`/`--zones` sin romper el determinismo (`seed=42`) ya usado por la Fase 30 | unit | `pytest tests/test_repositories.py -k seed_events -q` | ❌ Wave 0 | ⬜ pending |
| 31-01-02 | 01 | 1 | OPS-14 | `idx_events_analytics(camera_id, ts, person_id, zone_id, track_id)` creado por migración `SCHEMA_VERSION` v3→v4, idempotente | unit | `pytest tests/test_migrations.py -q` | ⚠ existe, se amplía (ya prueba v1→v2, v2→v3) | ⬜ pending |
| 31-01-03 | 01 | 1 | OPS-14 | Guarda del formato de almacenamiento de `DateTime` (ISO ancho fijo) — precondición de que `substr(ts,1,13)` sea correcto y 2,3× más rápido que `strftime` | unit | `pytest tests/test_repositories.py -k storage_format -q` | ❌ Wave 0 | ⬜ pending |
| 31-02-01 | 02 | 1 | OPS-12 | `cv2.COLORMAP_INFERNO` sustituye a `JET` en `compose_heatmap`; `DetectionWorker.heatmap_scale()` devuelve la leyenda relativa (0/50%/pico) | unit | `python -c "import cv2, backend.pipeline.detection as d; assert hasattr(cv2,'COLORMAP_INFERNO'); assert hasattr(d.DetectionWorker,'heatmap_scale')"` | ❌ Wave 0 | ⬜ pending |
| 31-02-02 | 02 | 1 | OPS-12 | Tests de `heatmap_scale()` y guarda de que el colormap sigue siendo INFERNO (regresión) | unit | `pytest tests/test_detection_worker.py -k heatmap -q` | ❌ Wave 0 | ⬜ pending |
| 31-03-01 | 03 | 1 | OPS-12, OPS-13, OPS-15 | La retícula de operaciones baja a su propia sección; se añade el `<nav role="tablist">` sin mover ni un píxel del vídeo/alertas/personas de la Fase 29 | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ (LOCKED_JS ampliado) | ⬜ pending |
| 31-03-02 | 03 | 1 | OPS-12, OPS-13, OPS-15 | Marcado completo de la vista de analítica (contenedores vacíos por panel) y clases CSS nuevas siguiendo `31-UI-SPEC.md` | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 31-03-03 | 03 | 1 | OPS-12, OPS-13, OPS-15 | `nav.js` conmuta pestañas con `hidden` + `history.replaceState`, enganchado desde `app.js` | mecánico | `node --check frontend/js/nav.js && node --check frontend/js/app.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 31-03-04 | 03 | 1 | Criterio 1 (zero-scroll Fase 29) | Checkpoint humano: la vista de operaciones no se ha movido ni un píxel tras añadir el tablist | manual-only | — (`checkpoint:human-verify`) | manual | ⬜ pending |
| 31-04-01 | 04 | 2 | OPS-12, OPS-13, OPS-14 | `AnalyticsRepo.bucket_for()`/`hourly()`/`summary()` con doble ventana SQL (actual vs. anterior) para la tendencia, sin aritmética en Python | unit | `pytest tests/test_repositories.py -k "analytics_hourly or analytics_summary or bucket_for" -q` | ❌ Wave 0 | ⬜ pending |
| 31-04-02 | 04 | 2 | OPS-12, OPS-13, OPS-14 | `occupancy()`/`persons_ranking()` (con `INDEXED BY` opcional) y `person_avatars()` — conteo/orden en SQL contra `events.db`, nunca JOIN contra la tabla `persons` sin poblar | unit | `pytest tests/test_repositories.py -k "analytics_occupancy or analytics_ranking or analytics_person_avatars" -q` | ❌ Wave 0 | ⬜ pending |
| 31-04-03 | 04 | 2 | OPS-14 | Criterio 4 medido a 100.000 eventos reales (presupuesto 0,5 s/consulta, 6-35× de margen sobre lo medido) + regresión de datos no vacíos (falla si `seed_events` volviera a dejar `person_id`/`zone_id` en NULL) | perf | `pytest tests/test_repositories.py -k analytics_budget -q` | ❌ Wave 0 | ⬜ pending |
| 31-05-01 | 05 | 3 | OPS-12, OPS-13, OPS-14 | Router `backend/api/v2/analytics.py` con `GET /hourly` y `/summary`, `configure()` desde el lifespan, rate limit heredado | integration | `python -c "from backend.main import app; rs=[...]; assert '/api/v2/analytics/hourly' in rs and '/api/v2/analytics/summary' in rs"` | ❌ Wave 0 | ⬜ pending |
| 31-05-02 | 05 | 3 | OPS-12, OPS-13, OPS-14 | `GET /occupancy` y `/persons`; el nombre de cada persona se resuelve con `asyncio.to_thread(recognizer.list_persons)`, fuera del event loop, nunca con `ATTACH DATABASE` | integration | `python -c "from backend.main import app; rs=[...]; assert '/api/v2/analytics/occupancy' in rs and '/api/v2/analytics/persons' in rs"` | ❌ Wave 0 | ⬜ pending |
| 31-05-03 | 05 | 3 | OPS-12, OPS-13, OPS-14 | `tests/test_analytics_api.py` — contrato de los 4 endpoints (422 con copy literal, `delta_pct: null` sin comparación, `recognizer.available=False` no rompe el ranking) y criterio 3 (payload de 30 días < 100 KB) | integration | `pytest tests/test_analytics_api.py -q` | ❌ Wave 0 | ⬜ pending |
| 31-06-01 | 06 | 4 | OPS-12 | `CameraPipeline.get_heatmap_scale()` + `GET /api/v2/analytics/heatmap` y `/heatmap/scale`; `/api/heatmap` v1 queda intacto | integration | `python -c "from backend.main import app; ...; assert hasattr(CameraPipeline,'get_heatmap_scale'); assert '/api/v2/analytics/heatmap' in rs and '/api/v2/analytics/heatmap/scale' in rs and '/api/heatmap' in rs"` | ❌ Wave 0 | ⬜ pending |
| 31-06-02 | 06 | 4 | OPS-12 | Tests de `/heatmap` (503 sin cámara, 404 sin actividad) y `/heatmap/scale` con un pipeline doble | integration | `pytest tests/test_analytics_api.py -k heatmap -q` | ❌ Wave 0 | ⬜ pending |
| 31-07-01 | 07 | 4 | OPS-12, OPS-14 | `views/analytics-charts.js::createCharts()`/`renderHourly()` — dos series (azul sólida / slate discontinua), 12px de eje, realce del pico, sin aritmética sobre datos del servidor | mecánico | `node --check frontend/js/views/analytics-charts.js` | ✅ | ⬜ pending |
| 31-07-02 | 07 | 4 | OPS-12, OPS-14 | `renderOccupancy()` y `resizeCharts()` (D-03: instancias creadas en la primera activación de la pestaña) | mecánico | `node --check frontend/js/views/analytics-charts.js` + `wc -l ≤ 300` | ✅ | ⬜ pending |
| 31-08-01 | 08 | 4 | OPS-13, OPS-14 | `views/analytics-range.js` — presets (hoy/7d/30d/personalizado), validación, `localStorage`, subtítulo; sin `.reduce`/`.sort`/`.filter`/`Math.max` sobre datos del servidor | mecánico | `node --check frontend/js/views/analytics-range.js` + `wc -l ≤ 300` | ✅ | ⬜ pending |
| 31-08-02 | 08 | 4 | OPS-13, OPS-14 | `views/analytics-ranking.js` — 4 tarjetas de tendencia y filas del ranking, anti-XSS (`textContent` para nombres de persona) | mecánico | `node --check frontend/js/views/analytics-ranking.js` + `wc -l ≤ 300` | ✅ | ⬜ pending |
| 31-09-01 | 09 | 5 | OPS-15 | Constructores de payload compartidos + `GET /api/v2/analytics/export` (CSV/JSON) — "lo que se descarga es lo que se ve" | integration | `python -c "...; assert '/api/v2/analytics/export' in rs"` + `pytest tests/test_analytics_api.py -q` | ❌ Wave 0 | ⬜ pending |
| 31-09-02 | 09 | 5 | OPS-15 | Tests del contrato de exportación: `Content-Disposition: attachment`, la sección `hourly` del JSON coincide con `GET /hourly` | integration | `pytest tests/test_analytics_api.py -k export -q` | ❌ Wave 0 | ⬜ pending |
| 31-10-01 | 10 | 6 | OPS-12, OPS-13, OPS-14, OPS-15 | `views/analytics.js` — arranque diferido, tanda de 4 peticiones en paralelo con `AbortController`, estado de error por panel (nunca `Promise.all` que aborte todo) | mecánico | `node --check frontend/js/views/analytics.js` | ✅ | ⬜ pending |
| 31-10-02 | 10 | 6 | OPS-12 | Panel del heatmap: distingue 404 de 503 preguntando primero a `/heatmap/scale`, cache-busting, recarga diferida y sin polling | mecánico | `node --check` de `analytics.js`/`analytics-charts.js` + `wc -l` | ✅ | ⬜ pending |
| 31-10-03 | 10 | 6 | OPS-15 | `views/analytics-export.js` y arranque desde `app.js` — `initAnalytics()` antes de `initNav()` para que abrir directo en `#analitica` no deje esqueletos para siempre | mecánico | `node --check` de `analytics-export.js`/`app.js` + `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 31-11-01 | 11 | 7 | OPS-12, OPS-13, OPS-14, OPS-15 | `LOCKED_JS` ampliado con los 6 módulos nuevos + `TEST_analytics_no_client_aggregation` (barre los 6 ficheros buscando `.reduce(`/`.sort(`/`.filter(`/`Math.max(`/`Math.min(`) | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 31-11-02 | 11 | 7 | OPS-14 | Criterios 3 y 4 medidos con números reales (no estimados) y suite completa en verde | perf | `pytest tests/ -q` | ✅ | ⬜ pending |
| 31-11-03 | 11 | 7 | Criterios 1/2/3/4/5 | Checkpoint visual bloqueante: la vista de analítica funciona con el servidor real (dos pestañas, gráficos, cambio de rango, exportación) | manual-only | — (`checkpoint:human-verify`) | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_analytics_api.py` (nuevo) — contrato de los 4 endpoints de lectura, `/heatmap`, `/heatmap/scale` y `/export`; cubre OPS-12, OPS-13, OPS-15 y el criterio 3 (31-05-03, 31-06-02, 31-09-02)
- [ ] `tests/test_repositories.py::TEST_analytics_*_budget_100k` — 4 tests de presupuesto con `seed_events(n=100_000, persons=N, zones=N)` (31-04-03)
- [ ] `tests/test_repositories.py::TEST_datetime_storage_format_is_fixed_width_iso` — guarda de `substr` (31-01-03)
- [ ] `tests/test_repositories.py -k seed_events` — cobertura de la extensión `--persons/--zones` (31-01-01)
- [ ] `tests/test_migrations.py::TEST_v3_to_v4_creates_analytics_index` — idempotencia del índice nuevo (31-01-02)
- [ ] `tests/test_detection_worker.py -k heatmap` — `heatmap_scale()` y guarda del colormap (31-02-02)
- [ ] `tests/test_frontend_modules.py` — `LOCKED_JS` con los 6 módulos + `TEST_analytics_no_client_aggregation` (31-11-01)
- [ ] Ampliar `scripts/seed_events.py` con `--persons N`/`--zones N` — sin esto los tests de ranking y ocupación medirían sobre datos vacíos y pasarían por accidente (31-01-01, ya cubierto arriba, remarcado por ser el hallazgo de más riesgo del research)
- [ ] Framework: **ninguna instalación** — pytest/pytest-asyncio ya instalados, sin runner JS que instalar.

Todos los ficheros de test "Wave 0" se crean/amplían **dentro de la misma tarea** que implementa el código correspondiente (patrón integrado, igual que la Fase 30) — confirmado por `gsd-plan-checker` (Dimension 8 readiness antes de este documento).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| El tablist no desplaza ni un píxel el vídeo/alertas/personas de la Fase 29 | Criterio 1 (zero-scroll heredado) | Constraint visual, no automatizable sin runner de navegador | Abrir el dashboard, confirmar que la zona de operaciones sigue idéntica a como quedó en la Fase 30 antes de añadir el tablist (31-03 Task 4) |
| La vista de analítica funciona de extremo a extremo con el servidor real | Criterios 1-5 del ROADMAP de la Fase 31 | Requiere navegador real +, para el heatmap con actividad genuina, cámara conectada | Con el servidor arrancado desde la raíz: cambiar de pestaña, confirmar que los dos gráficos se dibujan al activarse (no antes), cambiar el rango (hoy/7d/30d/personalizado) y confirmar que las 4 peticiones se resuelven en paralelo con estado de error independiente por panel, exportar CSV y JSON y confirmar que el contenido coincide con lo visible, y comprobar el panel del heatmap (503 sin cámara / 404 sin actividad / imagen con leyenda relativa) (31-11 Task 3) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (27/29 tareas automatizadas; las 2 manuales son los checkpoints humanos bloqueantes de 31-03 y 31-11, marcados explícitamente como tales en sus planes)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (los dos checkpoints manuales están rodeados de tareas automatizadas, nunca consecutivos entre sí)
- [x] Wave 0 covers all MISSING references (7 ficheros de test nuevos/ampliados, todos listados arriba, integrados en sus tareas)
- [x] No watch-mode flags
- [x] Feedback latency < 90s (con margen: el presupuesto de 100k events es 0,5s/consulta con 6-35× de margen sobre lo medido)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-22 (orquestador, tras leer `31-RESEARCH.md` § Validation Architecture, los 11 PLAN.md ya escritos y el `## ISSUES FOUND` de `gsd-plan-checker` — único bloqueante era la ausencia de este documento, ya resuelta)
