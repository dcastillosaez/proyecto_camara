---
phase: 31-vista-de-anal-tica
plan: 11
subsystem: testing
tags: [pytest, frontend-contract, performance-budget, migrations, phase-gate]

# Dependency graph
requires:
  - phase: 31-01
    provides: "idx_events_analytics, seed_events --persons/--zones, guarda de formato de DateTime"
  - phase: 31-04
    provides: "AnalyticsRepo (hourly/summary/occupancy/persons_ranking) y los tests de presupuesto @100k"
  - phase: 31-05
    provides: "Router /api/v2/analytics con /hourly, /summary, /occupancy, /persons y el test de payload de 30 dias"
  - phase: 31-09
    provides: "GET /api/v2/analytics/export (CSV/JSON)"
  - phase: 31-10
    provides: "Los seis modulos de la vista cableados de punta a punta (nav.js + views/analytics*.js)"
provides:
  - "LOCKED_JS ampliado con los seis modulos de la Fase 31 (contrato mecanico de 300 lineas)"
  - "TEST_analytics_no_client_aggregation: barrera permanente contra .reduce()/.sort()/.filter()/Math.max()/Math.min() en los modulos de analitica (OPS-14/D-07)"
  - "Criterios 3 y 4 del ROADMAP medidos con numeros reales sobre datos sembrados"
  - "Migracion v3->v4 verificada sobre una copia de la base de datos real de produccion (no una base temporal de test)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Test de politica por grep literal (no ejecucion): TEST_analytics_no_client_aggregation barre el codigo fuente de los seis modulos de analitica buscando llamadas que resolverian en el navegador un dato que el servidor ya entrega calculado; el mensaje del assert dice donde esta el dato ya resuelto (peak_index, chart, has_previous, truncated), no solo que la linea esta prohibida"
    - "Formato de listas Python una entrada por linea en LOCKED_JS/ANALYTICS_JS: necesario porque los criterios de aceptacion de este tipo de test cuentan LINEAS que coinciden (grep -c cuenta lineas, no ocurrencias), no coincidencias totales"

key-files:
  created: []
  modified:
    - tests/test_frontend_modules.py
    - frontend/js/views/analytics-ranking.js

key-decisions:
  - "Los criterios 3 y 4 se midieron con scripts de medicion directa (no capturados de pytest -s, que no imprime nada salvo fallo) reutilizando exactamente el mismo montaje que los tests: seed_events() + AnalyticsRepo para el criterio 4, y el mismo ASGITransport + rango que TEST_payload_size_30_days_under_100kb/TEST_payload_size_7_days_hourly_under_100kb para el criterio 3"
  - "La comprobacion de migracion v3->v4 se hizo sobre el backup automatico real que run_migrations() genero hoy mismo en data/backups/events-20260823-124531.db (schema_version=3, 1037 filas, sin idx_events_analytics) en vez de una base sintetica: es la prueba mas fuerte posible sin re-fabricar el estado previo a mano"

requirements-completed: []  # OPS-12..OPS-15 quedan pendientes de la aprobacion del checkpoint (Task 3), no se marcan hasta entonces

# Metrics
duration: ~35min (Tasks 1-2; Task 3 pendiente)
completed: 2026-08-23
---

# Phase 31 Plan 11: Puerta de fase — contrato mecanico, medicion real de los criterios 3/4 y checkpoint visual (PARCIAL)

**`TEST_analytics_no_client_aggregation` convierte en test permanente la prohibicion de agregar en el navegador; los seis modulos de la vista entran en `LOCKED_JS`; criterios 3 y 4 medidos con numeros reales (no estimados); suite completa en 675 passed/2 skipped (+68 sobre la Fase 30); Task 3 (checkpoint visual bloqueante) queda pendiente de verificacion humana con servidor real.**

## Performance

- **Duration:** ~35 min (Tasks 1 y 2)
- **Tasks:** 2 de 3 completadas automaticamente; Task 3 es un checkpoint bloqueante que requiere verificacion humana
- **Files modified:** 2

## Accomplishments

- `LOCKED_JS` ampliado con `nav.js` y los cinco `views/analytics*.js`: los seis modulos de la Fase 31 quedan bajo el mismo contrato mecanico (existencia en disco + limite de 300 lineas) que ya vigilaba las Fases 28/30.
- `TEST_analytics_no_client_aggregation` nuevo: barre `nav.js` + los cinco modulos de analitica buscando `.reduce(`/`.sort(`/`.filter(`/`Math.max(`/`Math.min(`. Encontro y forzo la correccion de un incumplimiento real (ver Deviations): el comentario de cabecera de `analytics-ranking.js` citaba literalmente esas expresiones al explicar por que el modulo NO las usa, disparando su propio test.
- Criterio 4 (agregaciones @100k, presupuesto 500 ms) medido con datos reales:

  | Agregacion | Tiempo medido |
  |---|---|
  | `hourly()` | ~228-241 ms |
  | `summary()` | ~346 ms |
  | `occupancy()` | ~13-15 ms |
  | `persons_ranking()` | ~13-14 ms |

  Las cuatro quedan por debajo del presupuesto de 500 ms, con margen mas ajustado en `hourly`/`summary` que el estimado en `31-RESEARCH.md` (14-78 ms) — la maquina de esta medicion tenia el servidor de desarrollo corriendo en paralelo para el checkpoint de Task 3, lo que consume CPU compartida; aun asi el margen sobre el presupuesto (500 ms) es de 1,4x-2,2x en el peor caso, suficiente para no ser flaky. El propio test automatizado (`pytest tests/test_repositories.py -k analytics_budget`) que corre sin ese proceso adicional en CI pasa en verde sobradamente.
- Criterio 3 (payload, presupuesto 100 KB) medido con datos reales, mismo montaje de test (`ASGITransport` + rango de la Fase 31):

  | Payload | Tamano medido |
  |---|---|
  | `/hourly` 30 dias (cubo diario, 30 eventos) | 565 bytes |
  | `/hourly` 7 dias (cubo horario, 56 eventos) | 3210 bytes |
  | `/export?format=json` (30 dias, 4 secciones) | 1147 bytes |

  Los tres muy por debajo del limite de 100 KB — 2-3 ordenes de magnitud de margen.
- Migracion v3→v4 verificada sobre la base de datos **real** de este entorno, no una base temporal de test: se tomo el backup automatico que `run_migrations()` habia generado hoy mismo antes de aplicar la migracion (`data/backups/events-20260823-124531.db`, `schema_version=3`, 1037 filas, sin `idx_events_analytics`), se copio y se le aplico `run_migrations()` de nuevo. Resultado: `schema_version` pasa a `4`, `idx_events_analytics` aparece en `sqlite_master`, y el recuento de filas de `events` no cambia (1037 antes y despues).
- Suite completa: **675 passed, 2 skipped** (+68 sobre los 607 con los que cerro la Fase 30). Sin `failed` ni `error`. Barrido de merge de ola (`test_analytics_api.py` + `test_repositories.py` + `test_migrations.py` + `test_frontend_modules.py`): 120 passed. `test_migrations.py` + `test_architecture.py` + `test_security_regression.py`: 41 passed.
- Nota heredada de `31-01-SUMMARY.md` para el acta de la fase: el `COUNT(*)` filtrado de la linea temporal de la Fase 30 cuesta **563 ms @100k**. **No es una regresion de esta fase** — el criterio de la Fase 30 se midio a 10.000 eventos, no 100.000 — y `idx_events_analytics` **no lo arregla** porque el indice no contiene `severity`. Queda anotado para una revision futura del rendimiento de la linea temporal, fuera del alcance de la Fase 31.

## Task Commits

1. **Task 1: LOCKED_JS + TEST_analytics_no_client_aggregation** - `7ab77f9` (test)
2. **Task 2: Medir los criterios 3 y 4 con numeros reales y pasar la suite completa** - sin commit (tarea de medicion y acta, ningun fichero de produccion modificado, tal como especifica el plan)

**Task 3 (checkpoint:human-verify, gate="blocking") queda pendiente** — ver `## Checkpoint Pendiente` abajo. Este SUMMARY es parcial hasta que se apruebe.

## Files Created/Modified

- `tests/test_frontend_modules.py` - LOCKED_JS ampliado (6 modulos nuevos) + `TEST_analytics_no_client_aggregation`, docstring de cabecera ampliado con el parrafo de la Fase 31
- `frontend/js/views/analytics-ranking.js` - Rule 1: comentario de cabecera reformulado para no citar literalmente las expresiones que el test nuevo prohibe

## Decisions Made

Ver `key-decisions` en el frontmatter: medicion directa con scripts efimeros (fuera del repo, en scratchpad) que reutilizan exactamente el mismo montaje que los tests automatizados, en vez de confiar en que `pytest -s` imprimiera algo (los tests solo imprimen en caso de fallo); y verificacion de la migracion sobre el backup automatico real generado hoy por `run_migrations()`, no sobre una base sintetica.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] El comentario de cabecera de `analytics-ranking.js` citaba literalmente `.reduce()`/`.sort()`/`.filter()`/`Math.max()`, disparando el test nuevo que el propio plan pedia escribir**

- **Found during:** Task 1, primera ejecucion de `pytest tests/test_frontend_modules.py -q`
- **Issue:** El comentario de cabecera explicaba que el modulo NO usa esas expresiones citandolas literalmente ("cero `.reduce()/.sort()/.filter()/Math.max()` (OPS-14)"), y la expresion regular del test nuevo (`_FORBIDDEN`) no distingue comentarios de codigo — mismo patron de hallazgo ya documentado en `31-07-SUMMARY.md`, `31-08-SUMMARY.md` y `31-10-SUMMARY.md` para otros criterios de conteo/prohibicion literal.
- **Fix:** Reformulado el comentario sin citar los nombres de metodo exactos ("sin agregacion ni reordenacion en el navegador (OPS-14)"). Sin cambio de comportamiento.
- **Files modified:** `frontend/js/views/analytics-ranking.js`
- **Verification:** `pytest tests/test_frontend_modules.py -q` en verde (9 passed)
- **Committed in:** `7ab77f9` (parte del commit de Task 1)

---

**Total deviations:** 1 auto-fixed (Rule 1, correccion de comentario para que el test de politica nuevo no se dispare a si mismo — ningun cambio de comportamiento).
**Impact on plan:** Ninguno sobre el alcance. El hallazgo confirma que el test nuevo funciona correctamente incluso contra codigo ya escrito en planes anteriores.

## Issues Encountered

Ninguno mas alla de la desviacion documentada arriba.

## User Setup Required

None - no external service configuration required.

## Checkpoint Pendiente

**Task 3 (`checkpoint:human-verify`, `gate="blocking"`) no se ha ejecutado.** Requiere verificacion visual con navegador real contra el servidor en marcha (`http://localhost:8000/#analitica`), que esta fuera del alcance de este agente de ejecucion. El servidor ya estaba en marcha en este entorno al empezar este plan (arrancado previamente para el checkpoint de `31-03`).

Pendiente de verificar (ver `31-11-PLAN.md` Task 3 para el detalle completo):
1. Las dos graficas se pintan al abrir directamente en `#analitica`, con tamano correcto (trampa de Chart.js con contenedor oculto, D-03).
2. Los cuatro presets de rango y el personalizado funcionan, con las dos cadenas de error exactas.
3. Las cuatro peticiones salen en paralelo (Red del navegador) y un panel caido (heatmap sin senal) no arrastra a los demas.
4. Los cuatro ficheros exportados se descargan con nombre y acentos correctos.
5. Conmutar de pestana no reconecta el MJPEG ni el WebSocket.
6. Consola limpia y foco navegable con `Tab`.
7. Lo que exija camara real (heatmap con actividad genuina, ranking con personas reconocidas de verdad) puede diferirse como 12º checkpoint manual, mismo criterio no bloqueante que los 11 anteriores en `STATE.md`.

**OPS-12, OPS-13, OPS-14 y OPS-15 no se marcan como completos en `REQUIREMENTS.md` hasta que este checkpoint se resuelva.** La fase 31 no se cierra en `STATE.md`/`ROADMAP.md` hasta entonces.

## Next Phase Readiness

- Contrato mecanico completo: los seis modulos de la Fase 31 estan en `LOCKED_JS` y protegidos por `TEST_analytics_no_client_aggregation`.
- Criterios 3 y 4 del ROADMAP medidos y documentados con cifras reales, ambos con margen amplio sobre su presupuesto.
- Migracion v3→v4 verificada sobre datos de produccion reales, sin perdida de filas.
- Suite en verde con 68 tests mas que el cierre de la Fase 30.
- Bloqueante para cerrar la fase: la aprobacion del checkpoint visual de Task 3. El siguiente agente debe reanudar directamente en Task 3 con el servidor ya en marcha, verificar los siete puntos de arriba, y solo entonces completar este SUMMARY, actualizar `REQUIREMENTS.md`/`STATE.md`/`ROADMAP.md` y hacer el commit final de la fase.

---
*Phase: 31-vista-de-anal-tica*
*Completed: PARCIAL — pendiente checkpoint Task 3*

## Self-Check: PASSED

- FOUND: tests/test_frontend_modules.py
- FOUND: frontend/js/views/analytics-ranking.js
- FOUND: commit 7ab77f9

(Nota: "PASSED" cubre unicamente la existencia de los ficheros y el commit de las Tasks 1-2. La Task 3 —checkpoint bloqueante— sigue pendiente de verificacion humana, ver seccion `## Checkpoint Pendiente` arriba.)
