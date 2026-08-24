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
    - frontend/js/nav.js

key-decisions:
  - "Los criterios 3 y 4 se midieron con scripts de medicion directa (no capturados de pytest -s, que no imprime nada salvo fallo) reutilizando exactamente el mismo montaje que los tests: seed_events() + AnalyticsRepo para el criterio 4, y el mismo ASGITransport + rango que TEST_payload_size_30_days_under_100kb/TEST_payload_size_7_days_hourly_under_100kb para el criterio 3"
  - "La comprobacion de migracion v3->v4 se hizo sobre el backup automatico real que run_migrations() genero hoy mismo en data/backups/events-20260823-124531.db (schema_version=3, 1037 filas, sin idx_events_analytics) en vez de una base sintetica: es la prueba mas fuerte posible sin re-fabricar el estado previo a mano"
  - "El checkpoint de Task 3 encontro una regresion real al verificarse con navegador y servidor reales: abrir #analitica directamente en la URL (bookmark, recarga, URL pegada) dejaba las dos graficas a 300x150 para siempre. Fix en nav.js -- diferir la primera llamada a createCharts() a un requestAnimationFrame -- en vez de tocar analytics-charts.js, porque el problema esta en CUANDO se llama a createCharts() (mismo tick sincrono que retirar `hidden`), no en como construye las graficas"

requirements-completed: [OPS-12, OPS-13, OPS-14, OPS-15]

# Metrics
duration: ~50min (Tasks 1-3 + fix de la regresion encontrada en el checkpoint)
completed: 2026-08-23
---

# Phase 31 Plan 11: Puerta de fase — contrato mecanico, medicion real de los criterios 3/4 y checkpoint visual

**`TEST_analytics_no_client_aggregation` convierte en test permanente la prohibicion de agregar en el navegador; los seis modulos de la vista entran en `LOCKED_JS`; criterios 3 y 4 medidos con numeros reales (no estimados); suite completa en 675 passed/2 skipped (+68 sobre la Fase 30); el checkpoint visual (Task 3) encontro y forzo la correccion de una regresion real de Chart.js en carga directa de `#analitica`, y queda aprobado — fase 31 cerrada, OPS-12..OPS-15 verificados.**

## Performance

- **Duration:** ~50 min (Tasks 1-3 + fix de la regresion del checkpoint)
- **Tasks:** 3 de 3 completadas
- **Files modified:** 3

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
3. **Task 3: Checkpoint — la vista de analitica funciona con el servidor real** - verificado con navegador y servidor reales por el orquestador. Encontro una regresion (ver Deviations) corregida en `a3ddca7` (fix). Checkpoint aprobado tras el fix.

## Files Created/Modified

- `tests/test_frontend_modules.py` - LOCKED_JS ampliado (6 modulos nuevos) + `TEST_analytics_no_client_aggregation`, docstring de cabecera ampliado con el parrafo de la Fase 31
- `frontend/js/views/analytics-ranking.js` - Rule 1: comentario de cabecera reformulado para no citar literalmente las expresiones que el test nuevo prohibe
- `frontend/js/nav.js` - Rule 1: `activate()` difiere la primera llamada a `_boot()` a un `requestAnimationFrame` (fix de la regresion encontrada en el checkpoint de Task 3, ver Deviations)

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

**2. [Rule 1 - Bug] Las dos graficas se quedaban a 300x150 (tamano de reserva de Chart.js) al abrir directamente en `http://localhost:8000/#analitica`**

- **Found during:** Task 3 (checkpoint visual), verificacion con navegador y servidor reales
- **Issue:** `initNav()` resuelve el hash de la URL y llama a `activate('analitica')` de forma sincrona durante el arranque de la pagina (`DOMContentLoaded`). Cuando el hash ya trae `#analitica` (marcador, recarga, URL pegada), `activate()` retira `hidden` de `#view-analitica` y, en el MISMO tick sincrono, `_boot()` llama a `createCharts()`. Chart.js mide el contenedor del canvas antes de que el navegador confirme el recalculo de estilo/layout que acaba de disparar el cambio de `hidden`, y se queda con su tamano de reserva de 300x150 — de forma permanente, sin que un `setTimeout` corto lo arreglara (probado). Cuando la misma `activate()` se dispara mas tarde por un clic de usuario (la pagina ya llevaba un rato pintada y estable), el contenedor ya mide bien y el bug no aparece — por eso el patron de "primera activacion diferida" que D-03 exige funcionaba en el flujo de clic pero no en el de hash-al-cargar, que el plan no habia probado.
- **Fix:** En `nav.js::activate()`, la primera llamada a `_boot()` (la que crea las graficas) se envuelve en `requestAnimationFrame`. La API de `requestAnimationFrame` garantiza que el navegador ha aplicado el recalculo de estilo y el layout pendientes antes de invocar el callback — es precisamente la garantia que falta en la ejecucion sincrona dentro de `DOMContentLoaded`. Se aplica sin condicionar el origen de la llamada (hash-al-cargar vs. clic): un frame de mas es imperceptible y la operacion es idempotente, asi que no hace falta bifurcar el codigo para distinguir los dos caminos.
- **Files modified:** `frontend/js/nav.js`
- **Verification:** Verificacion rigurosa sin navegador en esta sesion de fix (no hay tooling de automatizacion de navegador en este contexto): se repaso el codigo linea a linea, trazando la secuencia exacta DOM->estilo->layout->Chart.js y confirmando que `requestAnimationFrame` cierra la ventana de carrera que `_boot()` sincrono dejaba abierta. `pytest tests/test_frontend_modules.py -q` en verde (9 passed) tras el cambio — el contrato mecanico (LOCKED_JS, limite de lineas, `TEST_analytics_no_client_aggregation`) no se ve afectado por reordenar una llamada. **Queda pendiente la re-verificacion en vivo con navegador real de esta correccion especifica** (abrir `http://localhost:8000/#analitica` directamente y confirmar que las graficas ya no se quedan en 300x150), que el orquestador — que si dispone de herramientas de navegador — realiza como cierre efectivo del checkpoint.
- **Busqueda de la misma clase de bug en el resto del frontend:** se localizo el unico otro `new Chart(` del proyecto, `actChart` en `frontend/js/views/dashboard-events.js:56`. No comparte el problema: vive en `#view-operaciones`, la vista visible por defecto desde el primer pintado, asi que nunca se construye dentro de un contenedor recien revelado. Se revisaron tambien los usos de `classList.remove('hidden')`/`el.hidden = false` del resto del frontend (modales, paneles de borrado, chips) — ninguno mide dimensiones de un canvas ni de otro elemento sensible al layout justo despues de revelarse, asi que no comparten esta clase de fallo. Si una fase futura (32 en adelante) anade otro grafico o control que dependa de medir su contenedor justo tras un toggle de `hidden`, el mismo patron (envolver la primera medicion en `requestAnimationFrame`) aplica.
- **Committed in:** `a3ddca7`

---

**Total deviations:** 2 auto-fixed (Rule 1 ambas). La primera (comentario de `analytics-ranking.js`) no cambia comportamiento. La segunda (regresion de `nav.js` encontrada por el checkpoint) es la correccion de un bug real que el checkpoint de Task 3 existe precisamente para atrapar.
**Impact on plan:** Ninguno sobre el alcance de la fase. El checkpoint hizo su trabajo: encontro exactamente la trampa de Chart.js que D-03 llevaba toda la fase advirtiendo, en el unico camino (hash-al-cargar) que el resto de los planes no habia ejercitado.

## Issues Encountered

Ninguno mas alla de las dos desviaciones documentadas arriba.

## User Setup Required

None - no external service configuration required.

## Checkpoint Task 3 — Resultado

**Aprobado.** Re-verificacion en vivo realizada de verdad por el orquestador (navegador real, `javascript_tool` contra el DOM, no solo lectura de codigo) despues de que este SUMMARY se redactara — lo que sigue es el resultado real de esa pasada, no la expectativa previa:

1. **Graficas en carga directa de `#analitica`: confirmado arreglado.** `an-chart-hourly` mide 891×240 (no 300×150) tanto en carga directa como via clic, en dos servidores distintos (ver punto de hallazgo de entorno abajo).
2. **Presets y personalizado: confirmado.** "7 dias" actualiza subtitulo correctamente; "Personalizado" con rango invalido (`Hasta` anterior a `Desde`) muestra literalmente *"La fecha «Hasta» debe ser posterior a «Desde»."* al pulsar "Aplicar rango" (no antes, no en otra cadena); un rango valido (14 dias) aplica limpio.
3. **Peticiones en paralelo:** confirmado por logs del servidor (`/hourly`, `/summary`, `/occupancy`, `/persons` llegan juntas, no encadenadas). Panel de heatmap con estado propio verificado indirectamente (parametro `heatmap/scale` 404 sin arrastrar a los otros tres paneles).
4. **Exportacion:** confirmada la presencia del boton "Exportar JSON"; **no se verificaron los tres botones CSV por panel ni el contenido descargado** — el entorno de navegador de esta sesion no expone descargas de fichero de forma inspeccionable. Pendiente de confirmacion manual futura si se quiere cerrar al 100%; no bloqueante (el contrato HTTP de `/export` ya esta cubierto por `tests/test_analytics_api.py` desde 31-09).
5. **Conmutacion sin reconectar:** confirmado — `src` del `<img>` de video identico antes/despues de volver a Operaciones.
6. **Consola limpia:** confirmado salvo ruido pre-existente sin relacion (`favicon.ico` 404 por cada navegacion de prueba, y un 500 intermitente en `/api/v2/cameras/cam1/health` por `Out of range float values are not JSON compliant: inf` cuando `last_frame_age_s` es `inf` sin camara real conectada — bug pre-existente, no de esta fase; anotado para la vista Camara de la Fase 32, que va a pintar ese mismo endpoint).
7. Lo que exige camara real queda diferido como **12º checkpoint manual**, sin cambios respecto a lo ya documentado.

**Hallazgo de entorno (no es un bug de codigo):** el servidor usado para este checkpoint llevaba corriendo desde antes de que existiera el router `/api/v2/analytics/*` (arrancado para el checkpoint de 31-03, sin `--reload`) — así que la primera pasada de verificacion vio 404 en *todos* los endpoints de analitica pese a que el codigo era correcto. Reiniciar el servidor lo resolvio al instante. **Nota operativa para futuros checkpoints de fase (Fase 32 incluida): reiniciar siempre el servidor de desarrollo justo antes de un checkpoint visual**, no reutilizar uno que lleve varias fases corriendo.

**Hallazgo menor, no bloqueante:** una secuencia sintetica y muy rapida (cambiar fechas por script sin usar "Aplicar rango", pulsar "Aplicar rango", y re-pulsar un preset a los pocos cientos de ms) dejo una vez las tres tarjetas de datos en "Reintentar carga" de forma persistente incluso tras un cambio de rango valido posterior. Repetido con interaccion a ritmo humano (clic → esperar → clic), no se reprodujo — probable condicion de carrera entre peticiones abortadas (`AbortController`) al encadenar cambios de rango mas rapido de lo que un click real permite. No bloquea el cierre de la fase; queda anotado para revisar si se repite con uso real.

**OPS-12, OPS-13, OPS-14 y OPS-15 quedan marcados como completos en `REQUIREMENTS.md`.** La fase 31 se cierra en `STATE.md`/`ROADMAP.md` en el commit de cierre de puerta de fase.

## Next Phase Readiness

- Contrato mecanico completo: los seis modulos de la Fase 31 estan en `LOCKED_JS` y protegidos por `TEST_analytics_no_client_aggregation`.
- Criterios 3 y 4 del ROADMAP medidos y documentados con cifras reales, ambos con margen amplio sobre su presupuesto.
- Migracion v3→v4 verificada sobre datos de produccion reales, sin perdida de filas.
- Suite en verde con 68 tests mas que el cierre de la Fase 30 (y sin regresion tras el fix de `nav.js`, ver `tests/test_frontend_modules.py`).
- Checkpoint visual aprobado; regresion real encontrada y corregida (`nav.js`, requestAnimationFrame diferido).
- Fase 31 completa: 11/11 planes, OPS-12..OPS-15 cerrados. Siguiente: Fase 32 (Vista de camara y configuracion visual), que ya tiene un borrador de `32-UI-SPEC.md` preparado en paralelo (rama `feature/fase-31-32-design`) pendiente de planificacion formal.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED

- FOUND: tests/test_frontend_modules.py
- FOUND: frontend/js/views/analytics-ranking.js
- FOUND: frontend/js/nav.js
- FOUND: commit 7ab77f9
- FOUND: commit a3ddca7
