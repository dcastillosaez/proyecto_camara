---
phase: 31-vista-de-anal-tica
plan: 05
subsystem: api
tags: [fastapi, sql-aggregation, analytics, rate-limiting, asyncio-to-thread]

# Dependency graph
requires:
  - phase: 31-04
    provides: "AnalyticsRepo (hourly, summary, occupancy, persons_ranking, person_avatars) resuelto en SQL"
provides:
  - "Router backend/api/v2/analytics.py con GET /hourly, /summary, /occupancy y /persons"
  - "_resolve_range(), _label(), _axis(), _key(), _parse_bucket_key(): helpers de formateo compartidos por los cuatro endpoints"
  - "Contrato HTTP cerrado que consumen 31-07 (graficas), 31-08 (rango y ranking), 31-09 (export) y 31-10 (orquestador)"
affects: [31-06, 31-07, 31-08, 31-09, 31-10, 31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "El router formatea y rellena el eje a cero; nunca vuelve a agregar (sum/sorted/max) sobre filas que ya trajo el repo (OPS-14, D-07)"
    - "peak_index/min_index/chart/has_previous/truncated calculados en el servidor para que el cliente nunca necesite Math.max()/.reduce()"
    - "asyncio.to_thread(recognizer.list_persons) para cruzar persons.db (sqlite3 sincrono bajo threading.Lock) sin parar el event loop"
    - "_key()/_parse_bucket_key() como juntura exacta con substr(ts,1,13|10) del repo — si divergen, los cubos salen a 0 sin error visible"

key-files:
  created:
    - backend/api/v2/analytics.py
    - tests/test_analytics_api.py
  modified:
    - backend/main.py

key-decisions:
  - "min_index se calcula con min(range(len(values)), key=values.__getitem__), simetrico a peak_index: en empate gana el indice mas bajo en ambos casos, coincidiendo con ORDER BY n DESC/ASC, bucket ASC del repo"
  - "Los tres commits de Task 1 y Task 2 se separaron manualmente pese a haberse escrito el fichero completo de una vez, para que cada commit corresponda exactamente a los endpoints que el plan asigna a esa tarea (hourly+summary vs occupancy+persons)"

requirements-completed: [OPS-12, OPS-13, OPS-14]

# Metrics
duration: ~30min
completed: 2026-08-23
---

# Phase 31 Plan 05: Router de analitica — /hourly, /summary, /occupancy, /persons Summary

**Cuatro endpoints HTTP (`/api/v2/analytics/{hourly,summary,occupancy,persons}`) que exponen las agregaciones SQL de 31-04 con el eje temporal completo, porcentajes de variacion y ranking de personas ya resueltos en servidor, sin ningun `.reduce()`/`Math.max()` pendiente para el cliente**

## Performance

- **Duration:** ~30 min
- **Tasks:** 3
- **Files modified:** 3 (1 nuevo router, 1 fichero de tests nuevo, main.py con 2 inserciones)

## Accomplishments

- `GET /hourly`: serie temporal con el eje **completo** (cubos vacios a 0), comparacion con el periodo anterior emparejada por posicion, `peak_index`/`min_index` (empate -> indice mas bajo) y `chart` (`"bar"` hasta 48 cubos, `"line"` por encima)
- `GET /summary`: `delta_pct` firmado (`null` si no hay periodo anterior, nunca infinito), `peak`/`min` con la misma funcion de etiqueta que el eje de `/hourly`, y `known`/`unknown` como personas distintas
- `GET /occupancy`: ranking de zonas ya ordenado por SQL, truncado a 10 con `truncated` explicito para que el cliente no compare `total_zones` contra `len(labels)`
- `GET /persons`: ranking de personas con nombre real resuelto contra `persons.db` via `asyncio.to_thread(recognizer.list_persons)` — nunca `JOIN persons` (tabla vacia en `events.db`) ni `ATTACH DATABASE` — con degradacion a `"Persona {id}"` y `recognition_available: false` sin reconocimiento facial
- `_resolve_range()` centraliza la validacion de rango: `to < from` y rango > 90 dias devuelven 422 con las dos cadenas literales de la tabla de copy del UI-SPEC, nunca tocan la base
- `backend/main.py` cablea `analytics_v2_module.configure(camera_manager)` en el lifespan y registra el router — el heatmap v1 (`cv2.COLORMAP`) queda intacto, sin tocar
- 21 tests nuevos en `tests/test_analytics_api.py`: validacion de rango, contrato de los cuatro endpoints y los dos tests del criterio 3 con el peso real de la respuesta

## Task Commits

1. **Task 1: Router nuevo con /hourly y /summary, y su cableado desde main.py** - `b41c33a` (feat)
2. **Task 2: /occupancy y /persons, con los nombres de persons.db fuera del event loop** - `4db5444` (feat)
3. **Task 3: tests/test_analytics_api.py — contrato de los cuatro endpoints y criterio 3** - `701eb7f` (test)

## Files Created/Modified

- `backend/api/v2/analytics.py` (nuevo, 249 lineas) — router completo con los cuatro endpoints y sus helpers de formateo
- `backend/main.py` — `analytics_v2_module.configure(camera_manager)` en el lifespan (junto a `context_v2_module`) e `include_router(analytics_v2_router)` al final del modulo
- `tests/test_analytics_api.py` (nuevo, 21 tests) — contrato HTTP completo

## Decisions Made

- **`min_index` simetrico a `peak_index`**: el plan solo detallaba la formula de `peak_index`; se aplico el mismo criterio de desempate (`min()` sobre `range(len(values))`) para que ambos coincidan con el `ORDER BY` del repo en cualquier direccion.
- **Separacion manual de los commits de Task 1 y Task 2**: el fichero se escribio completo en un unico `Write`, pero para mantener la trazabilidad de "un commit por tarea" que exige el protocolo de ejecucion, se retiraron temporalmente `/occupancy` y `/persons` (y el import de `asyncio`), se comitio el estado de Task 1, y se restauraron para el commit de Task 2 — sin que ningun test se ejecutara sobre el estado intermedio incompleto de forma que quedara sin verificar.
- **`captures` creada a mano en el fixture `sf` de los tests**: igual que en `tests/test_repositories.py`, la tabla vive en `events.db` pero fuera de `backend.storage.models` (Base distinta de `backend/database.py`); sin ella `person_avatars()` fallaba con `no such table: captures` incluso en el caso vacio.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring de test citaba literalmente `datetime.now()`, disparando el criterio de aceptacion que prohibe esa cadena**
- **Found during:** Task 3, verificacion de criterios de aceptacion
- **Issue:** El comentario "Fechas siempre fijas (nunca `datetime.now()`)" hacia que `grep -c "datetime.now()"` devolviera `1` en vez de `0`, el valor que exige el criterio de aceptacion literal del plan.
- **Fix:** Reescrito el comentario sin citar la llamada literal ("nunca la hora actual del sistema").
- **Files modified:** `tests/test_analytics_api.py`
- **Commit:** `701eb7f` (parte del commit de Task 3)

---

**Total deviations:** 1 auto-fixed (Rule 1, cosmético — no afecta a codigo de produccion).
**Impact on plan:** Ninguno sobre el comportamiento; solo ajuste de redaccion de un comentario de test para cumplir el criterio de aceptacion literal.

## Issues Encountered

`person_avatars()` fallaba en los tests de `/persons` con `sqlite3.OperationalError: no such table: captures` porque el fixture solo ejecutaba `models.Base.metadata.create_all()`, que no conoce la tabla `captures` (vive bajo otra `Base` de SQLAlchemy). Resuelto creando la tabla a mano con `sqlite3` directo en el fixture `sf`, mismo patron que `tests/test_repositories.py::TEST_analytics_person_avatars_returns_latest_capture`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- El contrato HTTP de los cuatro paneles de datos de la Vista de analitica esta completo y verificado: `range`, `labels`/`values`/`previous`, `peak_index`/`min_index`, `has_previous`, `chart` en `/hourly`; `delta_pct`/`peak`/`min`/`known`/`unknown` en `/summary`; `truncated` en `/occupancy`; `person_id`/`name`/`avatar_url`/`delta_pct`/`recognition_available` en `/persons`.
- Peso real medido para el criterio 3 (anotado para 31-11): payload de `/hourly` con 30 dias en cubo diario (30 eventos sembrados) = **565 bytes**; payload de `/hourly` con 7 dias en cubo horario (56 eventos sembrados) = **3210 bytes**. Ambos muy por debajo del limite de 100 KB — el margen medido en 31-04 (57 KB en el rango maximo de 90 dias horarios) ya anticipaba que el criterio no seria ajustado.
- 31-06 puede anadir `/heatmap` y `/heatmap/scale` sobre este mismo fichero sin tocar los cuatro endpoints existentes.
- 31-09 (export) y 31-10 (orquestador del frontend) tienen ya el contrato JSON cerrado que consumir.
- Suite completa del proyecto: **658 passed, 2 skipped** (637 previos + 21 nuevos), sin regresiones. `tests/test_architecture.py` (5 passed) y `tests/test_security_regression.py -k rate_limited` (2 passed) verdes con las rutas nuevas ya incluidas.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
