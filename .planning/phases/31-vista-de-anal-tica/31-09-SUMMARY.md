---
phase: 31-vista-de-anal-tica
plan: 09
subsystem: api
tags: [fastapi, csv-export, json-export, streaming-response, rate-limiting]

# Dependency graph
requires:
  - phase: 31-05
    provides: "backend/api/v2/analytics.py con /hourly, /summary, /occupancy, /persons"
  - phase: 31-06
    provides: "backend/api/v2/analytics.py con /heatmap, /heatmap/scale (mismo router, sin tocar)"
provides:
  - "GET /api/v2/analytics/export — CSV por panel (hourly/occupancy/persons) y JSON del rango completo"
  - "_hourly_payload/_summary_payload/_occupancy_payload/_persons_payload: constructores async de modulo, fuente unica de verdad de paneles y export"
affects: [31-10, 31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Los cuatro GET de panel quedan como envoltorios de una linea sobre su constructor _*_payload — el export llama a los MISMOS constructores, nunca reimplementa relleno de eje ni agregacion"
    - "panel: Literal['hourly','occupancy','persons'] | None y format: Literal['csv','json'] en la firma del endpoint: el 422 de valor desconocido lo da Pydantic antes de ejecutar el cuerpo, no una `if`"
    - "Nombre de fichero compuesto solo con panel (Literal de tres valores) y stamp (fechas ya validadas por _resolve_range): ningun texto libre del cliente entra en el f-string del Content-Disposition"
    - "BOM UTF-8 (\\ufeff) al inicio del CSV: sin el, Excel en Windows corrompe los acentos de nombres de persona y zona; el export v1 de main.py no lo lleva porque sus datos eran ASCII"

key-files:
  created: []
  modified:
    - backend/api/v2/analytics.py
    - tests/test_analytics_api.py

key-decisions:
  - "La clave de cubo ('cubo') del CSV de hourly se recalcula con datetime.combine + _axis()/_key() dentro de export_analytics, sin volver a llamar a _resolve_range (ya validado dentro de _hourly_payload) — así el grep de aceptacion que exige cero _resolve_range dentro de export_analytics queda satisfecho sin reimplementar el relleno del eje, que sigue viniendo de los mismos _axis()/_key() del router"
  - "El JSON del export no reutiliza el 'range' de summary/hourly/occupancy: construye el suyo propio {from, to} a partir de las fechas ya normalizadas por FastAPI, porque cada seccion trae su propio 'range' con su bucket/dias y duplicarlo en la raiz habria sido redundante"

requirements-completed: [OPS-15]

# Metrics
duration: ~25min
completed: 2026-08-23
---

# Phase 31 Plan 09: Export CSV/JSON de la vista de analitica Summary

**`GET /api/v2/analytics/export` construido sobre los MISMOS constructores de payload que `/hourly`, `/summary`, `/occupancy` y `/persons` — la garantia real de "lo que se descarga es lo que se ve" es que ambos caminos comparten codigo, no que produzcan el mismo resultado por casualidad**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2
- **Files modified:** 2 (`backend/api/v2/analytics.py`, `tests/test_analytics_api.py`)

## Accomplishments

- Los cuerpos de `/hourly`, `/summary`, `/occupancy` y `/persons` se extrajeron a `_hourly_payload`, `_summary_payload`, `_occupancy_payload` y `_persons_payload` (funciones `async` de modulo); los cuatro `@router.get` quedan como envoltorios de una linea que llaman al constructor y devuelven su resultado — comportamiento identico, verificado sin tocar ni una linea de los tests de 31-05/31-06
- `GET /export` con `format: Literal["csv", "json"]` (default `csv`) y `panel: Literal["hourly", "occupancy", "persons"] | None`: valores desconocidos de cualquiera de los dos dan 422 de Pydantic, sin `if` de por medio
- CSV: BOM UTF-8 al inicio, cabecera en castellano por panel (`cubo,etiqueta,personas,personas_anterior` / `zona,entradas` / `posicion,person_id,nombre,visitas,variacion_pct`), `media_type="text/csv; charset=utf-8"` y `delta_pct=None` escrito como celda vacia, nunca la cadena `"None"`
- JSON: las cuatro secciones (`range`, `summary`, `hourly`, `occupancy`, `persons`) en un unico fichero, `ensure_ascii=False` para que los acentos salgan legibles
- Nombre de fichero compuesto por el servidor: `analitica-{panel}-{YYYYMMDD}_{YYYYMMDD}.csv` o `analitica-{YYYYMMDD}_{YYYYMMDD}.json`; `panel` es uno de tres valores fijos y `stamp` sale de fechas ya validadas por FastAPI — no hay ninguna via para que texto del cliente llegue al `Content-Disposition` (T-31-30)
- `panel` ausente en CSV -> 422 con `"Falta el panel para exportar en CSV."`, heredado del mismo patron de error literal que `_resolve_range`
- 10 tests nuevos en `tests/test_analytics_api.py` (`TEST_export_*`): cabecera exacta, BOM en bytes reales, filas del CSV de hourly igualando el numero de cubos de `/hourly`, celda vacia en `delta_pct` nulo, los tres 422 (sin panel, panel desconocido, formato desconocido) y la equivalencia literal entre la seccion `hourly` del JSON y el cuerpo de `GET /hourly` con los mismos parametros
- Peso real medido (no el del research, sino el de este export): JSON del rango completo con 30 dias sembrados (90 eventos: cruces + zonas + personas) = **1847 bytes**. Muy por debajo del limite de 100 KB del criterio 3.
- Suite completa del proyecto: **674 passed, 2 skipped** (664 previos de 31-06 + 10 nuevos), sin regresiones. `tests/test_analytics_api.py` completo: 37 passed.

## Task Commits

1. **Task 1: Extraer los constructores de payload y anadir GET /export** - `e360064` (feat)
2. **Task 2: Tests del contrato de exportacion** - `0d863b8` (test)

## Files Created/Modified

- `backend/api/v2/analytics.py` — refactor de los cuatro endpoints de panel a envoltorios sobre `_*_payload`, mas el endpoint `/export` nuevo (118 lineas netas anadidas)
- `tests/test_analytics_api.py` — bloque `# ─── /export (OPS-15) ───` con 10 tests nuevos (124 lineas anadidas)

## Decisions Made

Ver `key-decisions` en el frontmatter: la clave de cubo del CSV se recalcula localmente en `export_analytics` con los mismos `_axis()`/`_key()` del router (sin volver a llamar a `_resolve_range`, que ya valido el rango dentro de `_hourly_payload`), y el `range` del JSON del export es propio, distinto del `range` de cada seccion.

## Deviations from Plan

None - plan ejecutado tal como estaba escrito. La unica desviacion mecanica fue de herramienta, no de codigo: el `Edit` inicial escribio el caracter BOM literal (U+FEFF) en vez de la secuencia de escape `﻿` que pide el codigo fuente Python; se corrigio con un script Python que reescribe el fichero en bytes UTF-8 exactos antes del primer commit, asi que el commit final ya contiene la fuente correcta y ningun test se ejecuto sobre el estado intermedio erroneo.

## Issues Encountered

Ninguno de comportamiento. El unico contratiempo fue el de escritura de caracteres mencionado arriba, resuelto antes de verificar o comitear.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

El contrato de `<interfaces>` que consume `analytics-export.js` (31-10) esta completo y verificado: `GET /api/v2/analytics/export?camera_id=...&from=...&to=...&format=csv|json&panel=hourly|occupancy|persons`, con las cabeceras `Content-Disposition`/`Content-Type` exactas de la tabla del plan. 31-10 puede disparar la descarga con un simple `window.location = url` o un enlace `<a download>`, sin logica adicional en el cliente. El dato de peso del JSON (1847 bytes con datos moderados) queda anotado para que 31-11 lo compare contra el limite de 100 KB del criterio 3 al cerrar la fase.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
