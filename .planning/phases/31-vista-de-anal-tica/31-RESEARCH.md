# Phase 31: Vista de analítica — Research

**Researched:** 2026-08-22
**Domain:** Agregación SQL sobre SQLite + segunda vista frontend con Chart.js, sin dependencias nuevas
**Confidence:** HIGH — todo lo determinante está medido en esta sesión contra una base real de 100.000 eventos sembrada con `scripts/seed_events.py`, con `EXPLAIN QUERY PLAN` y tiempos p50 de 7 repeticiones. Las decisiones de arquitectura se han verificado leyendo el código del repo, no de memoria.

## Summary

Los dos criterios con filo de esta fase se comportan de forma **opuesta** a lo que la intuición sugería, y eso cambia el plan.

**El criterio 3 (payload de 30 días < 100 KB) no es un problema: sobra un orden de magnitud.** Treinta días de cubos horarios son 721 puntos; serializados como arrays paralelos con las dos series (actual y periodo anterior) pesan **11,3 KB**, y como lista de objetos `{label,value,prev}` pesan **28,9 KB**. Incluso el rango máximo de 90 días en cubo horario —2.161 puntos, el peor caso concebible— se queda en **57,0 KB** con arrays paralelos. No hace falta ningún umbral de degradación a cubo diario *por tamaño*. El umbral hora→día que fija el UI-SPEC (hora hasta 7 días, día por encima) sigue siendo correcto, pero por **legibilidad de la gráfica**, no por peso: son motivos distintos y el plan debe decirlo así.

**El criterio 4 (<500 ms sobre 100.000 eventos) sí falla con el esquema actual, y falla en tres consultas.** Medido tal cual está hoy la base: ocupación por zona **551 ms**, conocidas/desconocidas **535 ms**, personas distintas por hora **618 ms** — las tres por encima del presupuesto. La causa es la misma en las tres: `zone_id`, `person_id` y `track_id` no están en ningún índice que también cubra `(camera_id, ts)`, así que SQLite recorre el rango por `idx_events_cam_ts` y luego baja a la tabla fila por fila. Un único índice compuesto nuevo —`idx_events_analytics (camera_id, ts, person_id, zone_id, track_id)`— convierte las tres en *covering index scans* y las deja en **28 ms, 14 ms y 78 ms** respectivamente (mejoras de ×20, ×36 y ×8). Requiere migración `SCHEMA_VERSION` 3→4 siguiendo el patrón que ya dejó la Fase 30. Con ese índice, **las nueve consultas de la fase caben en 78 ms** y un cambio de rango completo (las cuatro agregaciones encadenadas) cuesta **196 ms**.

Y hay un bloqueo real que había que resolver antes de planificar: **`persons.db` es un fichero SQLite distinto de `events.db`** (verificado en `backend/recognizer.py:80,110` frente a `backend/config.py:74`), así que un `JOIN` SQL entre `events.person_id` y el nombre de la persona **no existe**. La salida no es aflojar D-07: el conteo y el **orden** del ranking se resuelven íntegramente en SQL sobre `events.db`, y solo el **nombre** —que no es agregación— se enriquece en el servidor con `recognizer.list_persons()` bajo `asyncio.to_thread`. El avatar sí se puede resolver en SQL: la tabla `captures` vive en `events.db`.

**Recomendación principal:** añadir `idx_events_analytics` vía migración a v4, resolver las cuatro agregaciones con `substr()` (no `strftime()`, 2,3× más rápido) sobre `events` —nunca sobre `detection_stats`—, enriquecer el ranking con nombres desde el proceso (no desde el navegador) y usar `INDEXED BY` solo en la consulta del ranking, con test que lo proteja.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Diseño visual e interacción (ya fijado por 31-UI-SPEC.md — aprobado 6/6, no volver a preguntar)**

- **D-01:** Sin dependencias nuevas de ningún tipo. Se reutilizan Tailwind CDN, `components.css` y Chart.js 4.5.1 (ya cargado con SRI en `frontend/index.html`). El sistema de diseño se hereda literalmente de `29-UI-SPEC.md`/`30-UI-SPEC.md`: spacing 4/8/16/24/32/48/64, exactamente 4 tamaños tipográficos (12/16/14/30px) y 2 pesos (600/700), superficies slate-950/900 y un único acento azul con lista cerrada de usos.
- **D-02 (decisión estructural de la fase):** La analítica vive en una **segunda vista conmutada por pestañas**, no en un router ni como sección apilada de la página actual. Mecanismo mínimo y explícito: `<nav role="tablist">` con dos botones, `hidden` para conmutar, hash sincronizado con `history.replaceState` (nunca asignando `location.hash`), cabecera común siempre visible. **El MJPEG y el WebSocket nunca se desmontan al cambiar de pestaña.**
- **D-03:** Las instancias de Chart.js se crean **en la primera activación de la pestaña**, no al cargar la página: un `<canvas>` dentro de un contenedor `display:none` mide 0×0 y Chart.js calcularía mal el tamaño. Es la trampa concreta que documenta el UI-SPEC.
- **D-04:** El texto que Chart.js dibuja dentro del lienzo **también cumple el contrato tipográfico** (12px). La densidad se resuelve con `maxTicksLimit`, jamás bajando el tamaño de letra. Los 9-11px del histograma heredado de la Fase 5 son legado no replicable.
- **D-05:** Dos subsistemas de color nuevos que el sistema heredado no tenía, ambos acotados: **paleta de series** (azul sólido vs. slate discontinuo, máximo 4 series, legítima porque dentro de un `<canvas>` no hay afordancias que confundir con el acento) y **rampa secuencial del heatmap** (JET → INFERNO). Las tendencias van **deliberadamente sin verde/rojo**: más gente no es "bueno" ni "malo", depende del negocio.
- **D-06:** Ancla visual de la vista = panel "Personas por hora" (8 de 12 columnas, único con área rellena). Los demás paneles son lectura secundaria.

**Agregación en servidor (OPS-14 — el requisito con más filo de la fase)**

- **D-07:** **Prohibición explícita y auditable:** en los módulos de analítica del navegador no puede aparecer ni un `.reduce()`, ni un `.sort()`, ni un `.filter()`, ni un `Math.max()` sobre datos del servidor. La única aritmética permitida en cliente es de **formato** (separador de millares, símbolo de porcentaje, `padStart` de horas). El porcentaje de variación, la hora pico, el orden del ranking y el orden de las zonas llegan ya resueltos desde SQL. Es el mismo criterio que se aplicó a `alertCenter.js` en la Fase 30 y es verificable con `grep`.
- **D-08:** Un cambio de rango dispara las cuatro peticiones **en paralelo** (`summary`, `hourly`, `occupancy`, `persons`) más la recarga del `<img>` del heatmap, y **cada panel resuelve su estado por separado**: un endpoint que falle pinta su error dentro de su panel sin dejar la vista en blanco. Nada de `Promise.all` que aborte todo al primer rechazo.
- **D-09:** Cada tanda de peticiones usa un `AbortController`; al cambiar de rango con peticiones en vuelo se abortan y se ignoran las respuestas rezagadas. Los `input[type=date]` no disparan nada al teclear: solo el botón "Aplicar rango".
- **D-10:** El CSV/JSON los genera el **servidor**, siguiendo el patrón ya existente de `bindEventExport()` en `dashboard-events.js` — el navegador no serializa un dataset que ya tiene el backend.

**Alcance honesto del mapa de calor**

- **D-11:** El heatmap es un **`<img>` contra `/api/v2/analytics/heatmap`**, no un lienzo de Chart.js: lo compone OpenCV en servidor sobre el último frame (`compose_heatmap`, ya existente en `backend/pipeline/detection.py`) y se versiona tal cual, como fija `SPEC_v2.md` §8.1.
- **D-12:** El heatmap **acumula desde el arranque de la cámara y no sigue el rango seleccionado**, y el panel lo dice con un chip visible ("acumulado desde el arranque") en lugar de fingir que responde al selector. Esto es deliberado: reconstruirlo en SQL desde `events.bbox` produciría un mapa de la línea de conteo (los eventos se disparan en cruces y transiciones de zona, no de forma continua), es decir, un heatmap sesgado con apariencia de autoridad. Un dato honesto con su alcance escrito al lado es mejor que uno falsamente preciso.
- **D-13:** Al versionar el heatmap a v2, cambiar `cv2.COLORMAP_JET` por `cv2.COLORMAP_INFERNO` en `compose_heatmap` (cambio de una línea) por la razón perceptual documentada en el UI-SPEC. El heatmap no lleva botón de exportar: es una imagen, no una tabla.

**Reparto en módulos**

- **D-14:** Seis módulos nuevos bajo `frontend/js/`, todos por debajo del tope duro de 300 líneas que impone `tests/test_frontend_modules.py::TEST_line_limit` (la Fase 30 ya tuvo que partir la línea temporal en cuatro por esto): `nav.js` (~70), `views/analytics.js` (~220), `views/analytics-charts.js` (~200), `views/analytics-range.js` (~130), `views/analytics-ranking.js` (~150), `views/analytics-export.js` (~90). Los seis se añaden a `LOCKED_JS`.
- **D-15:** Convención anti-XSS heredada e innegociable: las plantillas `innerHTML` llevan solo nodos vacíos y constantes del módulo; todo dato del backend entra por `textContent`/`dataset`/propiedades del DOM. Aplica en particular a los **nombres de persona** del ranking y a los **nombres de zona**.

### Claude's Discretion

- Forma exacta de la respuesta de cada endpoint de analítica (nombres de campo, envelope) — debe ser coherente con las convenciones que ya fijaron `backend/api/v2/events.py` y `alerts.py` en la Fase 30 (router con `configure()`, rate limit desde `deps.py`).
- Estrategia SQL concreta de cada agregación y qué índices hacen falta para cumplir el criterio 4 (<500 ms sobre 100.000 eventos). `DetectionStatRepo` ya agrega por minuto y tiene `hourly_baseline()` de la Fase 27 — decidir en RESEARCH si las agregaciones se apoyan en `detection_stats` (barato, ya agregado) o en `events` (más preciso, más caro), o en una combinación por panel.
- Si el criterio 3 (payload de 30 días < 100 KB) obliga a agrupar por día en vez de por hora cuando el rango supera cierto umbral, y dónde está ese umbral.
- Formato exacto del cursor/parámetros de rango (`from`/`to` ISO vs. presets nombrados) y cómo se validan los rangos inválidos o excesivos.
- Mecanismo concreto de la descarga CSV/JSON (`Content-Disposition` + enlace directo vs. `blob`), respetando D-10.

> **Todas las áreas de discreción quedan resueltas con recomendación única en la sección "Resolución de las preguntas abiertas".** No se devuelve un menú al planner.

### Deferred Ideas (OUT OF SCOPE)

- Vista de cámara y árbol de configuración visual — Fase 32.
- Editores visuales de zonas, líneas y reglas — Fase 33.
- Tests E2E — Fase 34.
- `js/store.js` y un router declarativo — siguen diferidos: la conmutación por pestañas de D-02 es el mecanismo mínimo suficiente y no justifica introducir una capa de estado global.
- Heatmap que respete el rango temporal seleccionado — requeriría una fuente de datos continua (muestreo periódico de posiciones), que no existe hoy; ver D-12 para por qué no se resuelve con `events.bbox`.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Descripción (REQUIREMENTS.md) | Soporte de este research |
|----|-------------------------------|--------------------------|
| **OPS-12** | Existe una vista de analítica con personas por hora, ocupación por zona y heatmap | Consulta de `hourly` medida a 27 ms (`type='LINE_CROSSED'`) y de `occupancy` a 28 ms con el índice nuevo; heatmap versionado a v2 reutilizando `compose_heatmap` (ya existe) + endpoint de escala para la leyenda numérica que exige el UI-SPEC (§"Panel 3") |
| **OPS-13** | La analítica muestra ranking de personas por visitas y tendencia frente al periodo anterior | Ranking + variación resueltos en **una sola consulta** con `SUM(CASE …)`, 27 ms con `INDEXED BY`. Nombres desde `persons.db` en el servidor (bloqueo del split de bases resuelto en Q5). Tendencia global reutiliza el mismo patrón de doble ventana, **no** `hourly_baseline()` (ver Q4) |
| **OPS-14** | Las agregaciones se calculan en base de datos, no en el navegador | Todas las cifras del contrato (total, variación, hora pico, orden del ranking, orden de zonas) salen de SQL. Ninguna requiere `.reduce()`/`.sort()` en cliente. La verificación mecánica de D-07 se propone como test de frontend (ver "Validation Architecture") |
| **OPS-15** | La analítica es exportable a CSV y JSON en el rango visible | `StreamingResponse` + `Content-Disposition`, mismo molde que `/api/events/export` (`main.py:910-937`), consumido con `window.location.href` como ya hace `bindEventExport()` (`dashboard-events.js:113`). Export JSON de 30 días medido en **2,1 KB** (cubo diario) / **18,3 KB** (cubo horario) |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Agregación temporal (personas por hora/día) | Database (SQLite) | API (formato de etiquetas) | OPS-14 lo exige literalmente; medido: SQLite agrega 100.000 filas en 27-67 ms, el navegador tendría que descargarse 100.000 eventos primero |
| Cálculo del % de variación frente al periodo anterior | Database (SQLite) | — | Una sola consulta con doble ventana `SUM(CASE …)` cuesta 26 ms; hacerlo en cliente exigiría dos datasets completos y viola D-07 |
| Hora pico y su valor | Database (SQLite) | — | `ORDER BY n DESC LIMIT 1` sobre los cubos ya materializados; `Math.max()` en cliente está explícitamente prohibido por D-07 |
| Orden del ranking de personas y de zonas | Database (SQLite) | — | `ORDER BY … DESC LIMIT 10` en SQL; `.sort()` en cliente prohibido por D-07 |
| Resolución de **nombre** de persona | API (proceso Python) | — | Los nombres viven en `persons.db`, un fichero SQLite distinto: no hay JOIN posible. No es agregación, es una búsqueda en un diccionario de ≤10 entradas |
| Resolución de **avatar** de persona | Database (SQLite) | — | `captures.image_path` vive en `events.db`; subconsulta correlacionada del capture más reciente por persona |
| Resolución de **nombre** de zona | Database (SQLite) | — | `zones.name` vive en `events.db` (`backend/database.py:37-51`); `LEFT JOIN zones ON events.zone_id = zones.id` |
| Composición del mapa de calor | Pipeline (hilo de detección) + API | — | `DetectionWorker._heat_mask` es estado en memoria del worker; `compose_heatmap` es CPU pesada y va por `asyncio.to_thread` (ya lo hace el endpoint v1) |
| Serialización CSV/JSON del export | API (proceso Python) | — | D-10 lo fija; construir el CSV en JS sería agregar en el navegador |
| Conmutación de pestaña y estado del hash | Browser / Client | — | Es navegación pura, sin datos: es exactamente el sitio donde tiene que vivir |
| Dibujo de las gráficas y `aria-label` resumen | Browser / Client | — | Chart.js renderiza; el resumen textual se compone con valores que **ya manda el servidor** (total, máximo, mínimo y sus horas) |
| Validación del rango (orden y longitud) | API (autoridad) | Browser (cortesía) | El UI-SPEC lo dice literalmente: "el servidor valida igual y devuelve 422; la validación de cliente es cortesía, no seguridad" |

**Comprobación de tier que el plan-checker debe verificar:** ninguna tarea puede asignar al navegador el cálculo de un total, un máximo, un orden o un porcentaje. Si una tarea de `views/analytics-*.js` contiene aritmética que no sea de formato, está mal asignada.

---

## Standard Stack

### Core — todo ya instalado, cero dependencias nuevas

| Componente | Versión verificada | Propósito en esta fase | Por qué es el estándar aquí |
|-----------|--------------------|------------------------|------------------------------|
| SQLite | **3.49.1** `[VERIFIED: .venv/Scripts/python.exe -c "import sqlite3; sqlite3.sqlite_version"]` | Motor de todas las agregaciones | Es la única base del proyecto (CLAUDE.md prohíbe PostgreSQL antes del bloque D). Soporta `substr`, `strftime`, CTEs, `INDEXED BY` y `EXPLAIN QUERY PLAN` |
| SQLAlchemy 2 async + aiosqlite | ya en `requirements.txt` | Repos de agregación | `EventRepo`/`DetectionStatRepo` ya existen y son el sitio natural |
| FastAPI + slowapi | ya en uso | Routers `/api/v2/analytics/*` | `backend/api/v2/context.py` ya publica bajo ese mismo prefijo; dos routers con el mismo prefix conviven sin problema en FastAPI |
| OpenCV (`cv2`) | ya en uso | `COLORMAP_INFERNO`, `imencode` del heatmap | `COLORMAP_INFERNO` está en OpenCV 4.x, no añade nada `[VERIFIED: cv2.COLORMAP_INFERNO existe en el árbol de constantes de OpenCV 4, ya usado COLORMAP_JET en detection.py:180]` |
| **Chart.js 4.5.1** | **es la última publicada** `[VERIFIED: npm view chart.js dist-tags → { next: '4.0.0-release', latest: '4.5.1' }, 2026-08-22]` | Gráfica horaria y de ocupación | Ya cargado con SRI en `index.html:8`. **No hay versión más nueva a la que subir**: el pin actual está al día, así que "no tocar el `<script>`" (UI-SPEC) no cuesta nada |
| Tailwind CDN | ya en uso | Retícula de 12 columnas de la vista | — |

### Alternatives Considered

| En lugar de | Se podría usar | Trade-off medido |
|-------------|----------------|------------------|
| `substr(ts,1,13)` | `strftime('%Y-%m-%dT%H:00', ts)` | `strftime` cuesta **120,8 ms** frente a **51,8 ms** de `substr` sobre 100.000 filas (×2,3). `strftime` es robusto ante cualquier formato de almacenamiento; `substr` depende del formato TEXT exacto. Recomendado `substr` **con test de guarda** (ver Pitfall 1) |
| `events` como fuente | `detection_stats` (ya preagregado) | `detection_stats` es **más caro**, no más barato: 30 días de minutos son 43.200 filas y la agregación horaria cuesta **60,7 ms**, frente a **27,0 ms** de `events` filtrado por `LINE_CROSSED`. Y además es semánticamente incorrecto aquí (ver Q1) |
| Índice compuesto único | Tres índices estrechos por columna | SQLite usa **un** índice por referencia de tabla: tres índices no se combinarían. El compuesto de 5 columnas sirve a las tres consultas como covering |
| `INDEXED BY` en el ranking | Reescrituras del predicado (`+person_id`, `ifnull`, `HAVING`, subconsulta) | **Ninguna de las cuatro reescrituras funciona**: SQLite se queda en el skip-scan de `idx_events_person` en las cuatro (191-209 ms). `INDEXED BY` es la única palanca (17-27 ms) |
| `<img src>` simple para el heatmap | `fetch` → `blob:` para leer cabeceras de escala | El CSP ya permite `img-src blob:` (`main.py:741`), pero `isSafeMediaUrl()` rechaza `blob:` y habría que relajarla. Un endpoint JSON de escala aparte es más simple y no toca seguridad |

**Instalación:** ninguna. `pip install` no se ejecuta en esta fase.

---

## Mediciones — criterios 3 y 4

> Metodología idéntica a la de la Fase 30 (`30-RESEARCH.md` § "Planes de consulta medidos"): base SQLite real creada con `models.Base.metadata.create_all()` + `run_migrations()` (así que incluye `idx_events_ts_id` de la Fase 30), sembrada con `scripts/seed_events.py -n 100000 --days 30`, `ANALYZE` ejecutado, `EXPLAIN QUERY PLAN` sobre cada candidata y p50 de 7 ejecuciones. Máquina: la del proyecto (Windows 11, Python 3.12.10, SQLite 3.49.1). Base resultante: **70,1 MB** (76,8 MB con el índice nuevo).
>
> `seed_events.py` deja `person_id` y `zone_id` a `NULL`, así que el banco los rellenó con un `UPDATE` posterior: 35 % de eventos con identidad (60 personas distintas) y 60 % con zona (14 zonas, por encima del tope de 10 del UI-SPEC). También se sembraron 129.600 filas de `detection_stats` (90 días de minutos) para poder comparar las dos fuentes.

### Criterio 4 — antes y después del índice

| Consulta (rango 30 días, 100.000 eventos) | Sin índice nuevo | Con `idx_events_analytics` | Factor |
|---|---:|---:|---:|
| `hourly` cubo horario, todos los tipos | 51,9 ms | 51,0 ms | — |
| `hourly` cubo horario, `type='LINE_CROSSED'` | 27,7 ms | **27,0 ms** | — |
| `hourly` cubo diario | 60,6 ms | 60,6 ms | — |
| `hourly` actual + anterior en una consulta (60 d, `CASE`) | 60,8 ms | **50,6 ms** | 1,2× |
| `summary` total + hora pico (CTE) | 60,4 ms | 62,1 ms | — |
| `summary` total actual + anterior (60 d) | 25,8 ms | **25,8 ms** | — |
| **`summary` conocidas / desconocidas** | **535,4 ms** ❌ | **13,6 ms** ✅ | **36,0×** |
| **`occupancy` top 10 por zona** | **551,3 ms** ❌ | **27,9 ms** ✅ | **19,7×** |
| `occupancy` filtrado a `type='ZONE_ENTERED'` | 25,2 ms | 23,8 ms | — |
| **`hourly` con `COUNT(DISTINCT track_id)`** | **617,9 ms** ❌ | **77,7 ms** ✅ | **8,0×** |
| `persons` ranking top 10 (sin hint) | 201,5 ms | 190,2-228,2 ms | — |
| **`persons` ranking con `INDEXED BY`** | n/a | **16,8-21,5 ms** ✅ | **11,7×** |
| **`persons` ranking + variación, `INDEXED BY`, 60 d** | 212,6 ms | **26,7 ms** ✅ | **8,0×** |

**Coste total de un cambio de rango** (las cinco consultas del contrato encadenadas sobre la misma conexión, con el índice): **196,0 ms p50** (mín. 179,5 / máx. 200,5). Con margen de 2,5× sobre el presupuesto de 500 ms para una sola consulta, y por debajo de él incluso sumadas.

### Planes de consulta relevantes (`EXPLAIN QUERY PLAN`)

```
-- occupancy, SIN el índice nuevo: 551 ms
SEARCH events USING INDEX idx_events_cam_ts (camera_id=? AND ts>? AND ts<?)
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
    -> el índice sólo resuelve el rango; zone_id obliga a bajar a la tabla 100.000 veces

-- occupancy, CON idx_events_analytics: 28 ms
SEARCH events USING COVERING INDEX idx_events_analytics (camera_id=? AND ts>? AND ts<?)
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
    -> "COVERING": nunca toca la tabla. Los dos TEMP B-TREE sobre 14 grupos son irrelevantes

-- persons ranking, SIN hint: 191-228 ms
SEARCH events USING INDEX idx_events_person (ANY(person_id) AND ts>? AND ts<?)
USE TEMP B-TREE FOR ORDER BY
    -> skip-scan: SQLite recorre el índice una vez por cada person_id distinto

-- persons ranking, CON INDEXED BY idx_events_analytics: 17-27 ms
SEARCH events USING COVERING INDEX idx_events_analytics (camera_id=? AND ts>? AND ts<?)
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
```

### Anchura del índice — por qué 5 columnas y no 4 ni 6

Medido con tres composiciones distintas:

| Composición | `known_unknown` | `occupancy` | `ranking` (hint) | `hourly DISTINCT track` |
|---|---:|---:|---:|---:|
| *(sin índice)* | 535 ms ❌ | 551 ms ❌ | 201 ms | 618 ms ❌ |
| `(camera_id, ts, person_id, zone_id)` | 12,6 ms | 26,2 ms | 205 ms | **590 ms** ❌ |
| `(camera_id, ts, person_id, zone_id, track_id)` ← **recomendado** | 13,6 ms | 28,5 ms | **21,5 ms** | **77,7 ms** ✅ |
| `(camera_id, ts, type, person_id, zone_id, track_id)` | 14,9 ms | 27,9 ms | 190 ms | 77,7 ms |

`track_id` es imprescindible si alguna métrica usa `COUNT(DISTINCT track_id)` (590 → 78 ms). `type` **no aporta nada**: cuando hay filtro por tipo SQLite prefiere `idx_events_type_ts` de todos modos, y cuando no lo hay la columna solo engorda el índice. Se queda fuera.

**Coste de escritura del índice extra:** 0,0618 ms/insert con 6 índices frente a 0,0684 ms/insert con 5 `[VERIFIED: medido con `executemany` de 2.000 filas]`. La diferencia está dentro del ruido (sale invertida), lo que es esperable a este tamaño: el proyecto inserta unos pocos eventos por segundo, no miles. **Crear el índice sobre 102.000 filas cuesta 196 ms**, así que la migración no es perceptible al arrancar.

**Sin regresión sobre la Fase 30.** Con `idx_events_analytics` presente, las consultas de la línea temporal siguen eligiendo `idx_events_ts_id`: primera página 0,04 ms, cursor profundo 0,04 ms, `severity` sola 1,62 ms, `type IN (3) + severity` con `+events.type` 6,37 ms. Ninguna cambió de plan.

### Criterio 3 — tamaños de payload reales

Serializados con `json.dumps(separators=(",",":"), ensure_ascii=False)`, medidos en bytes UTF-8:

| Payload | Cubos | Objetos `{label,value}` | Objetos + serie anterior | **Arrays paralelos** |
|---|---:|---:|---:|---:|
| 30 días, cubo horario | 721 | 21,1 KB | 28,9 KB | **11,3 KB** |
| 7 días, cubo horario | 169 | — | 6,8 KB | ~2,7 KB |
| 30 días, cubo diario | 31 | — | 1,5 KB | ~0,6 KB |
| **90 días (rango máximo), cubo horario** | 2.161 | — | 109,8 KB ⚠️ | **57,0 KB** ✅ |
| Export JSON completo 30 días, cubo diario | — | — | — | **2,1 KB** |
| Export JSON completo 30 días, cubo horario | — | — | — | **18,3 KB** |

**Conclusión:** el criterio 3 se cumple con **3,5× de margen** en el peor caso realista y con **8,8×** en el caso que el criterio menciona (30 días). El único escenario que roza los 100 KB es 90 días en cubo horario con formato de objetos —109,8 KB—, y ese escenario **no ocurre** porque el UI-SPEC ya manda cubo diario por encima de 7 días. Usar arrays paralelos lo hace además imposible por construcción (57,0 KB).

---

## Resolución de las preguntas abiertas

### Q1 — Fuente de datos por panel: `events`, no `detection_stats`

**Recomendación: `events` en los cuatro paneles. `detection_stats` no se toca en esta fase.**

Tres razones, en orden de peso:

1. **Coherencia con lo que el operador ya está viendo.** El histograma "Actividad hoy" del dashboard actual se alimenta de `EventRepo.hourly_counts(since_24h, type=EventType.LINE_CROSSED)` `[VERIFIED: backend/database.py:222]`. Si la vista de analítica contara otra cosa para la misma hora, el operador vería dos cifras distintas del mismo día en la misma aplicación. Eso es un bug de producto aunque las dos consultas sean correctas.
2. **Invariante 9 de `CLAUDE.md`:** *"Conteo = tracking/cruce, no suma de detecciones por frame."* `detection_stats.detections` acumula `len(active_track_ids)` una vez por frame procesado, así que depende del FPS que `AdaptiveRate` haya elegido — lo dice literalmente el docstring de `hourly_baseline()` (`repositories.py:411-440`). Y `unique_tracks` sumado por hora cuenta dos veces a quien cruza el límite de un minuto. Ninguna de las dos es "personas por hora".
3. **Y encima es más caro.** Medido: `detection_stats` en cubo horario a 30 días son **60,7 ms** (43.200 filas de minuto) frente a **27,0 ms** de `events` filtrado por `LINE_CROSSED`. La intuición de "ya está preagregado, será más barato" es falsa aquí porque el preagregado es por minuto, no por hora.

**Reparto final por panel:**

| Panel | Fuente | Consulta | Coste medido |
|---|---|---|---:|
| Personas por hora/día | `events` | `COUNT(*) … WHERE type='LINE_CROSSED'` agrupado por `substr(ts,1,13\|10)` | 27,0 ms |
| Tarjetas de tendencia | `events` | Una consulta de doble ventana `SUM(CASE …)` + una de conocidas/desconocidas | 25,8 + 13,6 ms |
| Ocupación por zona | `events` | `COUNT(*) … WHERE type IN ('ZONE_ENTERED')` agrupado por `zone_id`, `LEFT JOIN zones` | 23,8-27,9 ms |
| Personas más vistas | `events` (+ `captures`) | `GROUP BY person_id` con `INDEXED BY`, nombres enriquecidos en Python | 26,7 ms |
| Mapa de calor | `DetectionWorker._heat_mask` (memoria) | No es SQL | — |

`detection_stats` sigue siendo la fuente de `/api/v2/analytics/context` (Fase 27) y ahí se queda. Son dos preguntas distintas: "nivel de actividad relativo a lo normal" (contexto) frente a "cuánta gente pasó" (analítica).

### Q2 — Payload y granularidad: el umbral es de legibilidad, no de peso

**Recomendación: `bucket = "hour"` si el rango abarca ≤ 7 días; `bucket = "day"` por encima. El servidor lo decide, lo devuelve en el campo `bucket` y manda las etiquetas ya formateadas.**

Medido, el criterio 3 **no fuerza ningún umbral**: 30 días horarios pesan 11,3 KB con arrays paralelos y hasta el rango máximo de 90 días horarios cabe en 57,0 KB. El umbral de 7 días viene del UI-SPEC ("Hoy" → 24 cubos, "7 días" → 168 cubos horarios, "30 días" → 30 cubos diarios) y de la regla de tipo de gráfica (≤48 cubos → barras, >48 → línea). El plan debe documentarlo **como decisión de legibilidad**, para que nadie la "optimice" más adelante creyendo que existe por tamaño.

Cómo se comunica al cliente, con lo que el UI-SPEC ya exige:

```json
{
  "range":    { "from": "2026-07-23", "to": "2026-08-22", "bucket": "day" },
  "labels":   ["23 jul", "24 jul", "…"],
  "values":   [312, 289, "…"],
  "previous": [270, 301, "…"]
}
```

El título del panel se deriva de `bucket` ("Personas por hora" / "Personas por día"), exactamente como manda la tabla de copy. **Formato de arrays paralelos**, no lista de objetos: pesa 2,6× menos (11,3 KB frente a 28,9 KB en 30 días horarios) y es el formato que Chart.js consume directamente (`data.labels` + `data.datasets[].data`), sin que el navegador tenga que hacer un `.map()` — que, aunque no sea agregación, es exactamente el tipo de código que D-07 quiere fuera.

**Umbral duro de seguridad:** 90 días es el máximo que acepta el servidor (422 por encima), coherente con la cadena de copy "El rango máximo es de 90 días." y con el `le=90` que ya usa `/api/v2/analytics/context` (`context.py:113`).

### Q3 — Índices: uno nuevo, migración a `SCHEMA_VERSION = 4`

**Recomendación:**

```sql
CREATE INDEX IF NOT EXISTS idx_events_analytics
  ON events (camera_id, ts, person_id, zone_id, track_id);
```

**Qué índices existentes sirven, y a qué:**

| Índice | Existe desde | Qué agregación de la Fase 31 resuelve |
|---|---|---|
| `idx_events_cam_ts (camera_id, ts DESC)` | Fase 19 | `hourly` sin filtro de tipo — **covering** por sí solo (51 ms). No hace falta tocar nada para este panel |
| `idx_events_type_ts (type, ts DESC)` | Fase 19 | `hourly` con `type='LINE_CROSSED'` (27 ms) y `occupancy` con `type='ZONE_ENTERED'` (24 ms) |
| `idx_events_person (person_id, ts DESC)` | Fase 19 | Lo elige SQLite para el ranking, pero por skip-scan: 191-228 ms. Es exactamente el índice del que hay que escapar (ver Q5) |
| `idx_events_ts (ts DESC)` | Fase 19 | Nada de esta fase |
| `idx_events_ts_id (ts DESC, id DESC)` | **Fase 30** | Nada de esta fase; se verifica que no se degrada (comprobado, sin cambio de plan) |
| **`idx_events_analytics`** | **Fase 31 (nuevo)** | Las tres consultas que hoy **fallan** el criterio 4, más el ranking bajo hint |

**Sí requiere migración.** `models.Base.metadata.create_all()` **no crea índices sobre tablas que ya existen** — es la misma lección que la Fase 30 dejó escrita en `migrations.py:170-175`. El patrón está establecido y hay que seguirlo literalmente:

1. Declarar el índice en `models.Event.__table_args__` (para bases nuevas).
2. `SCHEMA_VERSION = 3` → `4` en `backend/storage/migrations.py:25`.
3. Añadir `_migrate_v3_to_v4(conn)` con `CREATE INDEX IF NOT EXISTS …` + `_record_version(conn, 4)`.
4. Registrar `(4, "indice compuesto de analitica", _migrate_v3_to_v4)` en la lista `MIGRATIONS`.

`_record_version` graba **su propia** versión objetivo, nunca `SCHEMA_VERSION` — el comentario de `migrations.py:92-95` lo advierte explícitamente y es el error más fácil de cometer aquí. `tests/test_migrations.py` ya existe y debe crecer con un caso de v3→v4.

**No añadir más índices.** En particular, nada de un índice por `severity` ni por combinación de filtros: la Fase 30 ya midió que SQLite usa **un** índice por referencia de tabla y que multiplicarlos no los combina.

### Q4 — Tendencia: consulta propia de doble ventana, **no** `hourly_baseline()`

**Recomendación: consulta propia. `hourly_baseline()` y `/api/v2/analytics/context` responden a otra pregunta y reutilizarlos sería acoplar dos semánticas distintas.**

Leído el código (`repositories.py:411-480` y `context.py:99-136`), `hourly_baseline()` calcula la **media móvil de N días para una franja horaria concreta**, sobre `detection_stats.unique_tracks`, y `context.py` la usa para clasificar la hora en curso como `low`/`normal`/`high`/`unknown` normalizando a tasa por minuto. Lo que pide OPS-13 es otra cosa: **el total del rango elegido frente al total del periodo inmediatamente anterior de igual longitud**. Cuatro diferencias que lo hacen no reutilizable:

| | `hourly_baseline()` (Fase 27) | Tendencia de la Fase 31 |
|---|---|---|
| Fuente | `detection_stats.unique_tracks` | `events` (`LINE_CROSSED`) |
| Ventana | Franja horaria fija, N días | Rango arbitrario del usuario, 1-90 días |
| Comparación | Media entre días | Total del periodo anterior contiguo |
| Salida | Nivel cualitativo (`low`/`high`) | Porcentaje con signo |

La forma correcta —y ya medida a 25,8 ms— es **una sola consulta que barre `[inicio_anterior, fin_actual]` y separa las dos ventanas con `CASE`**, en vez de dos consultas:

```sql
SELECT SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS current,
       SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS previous
FROM events
WHERE camera_id = :cam AND ts >= :prev_from AND ts < :cur_to
  AND type = 'LINE_CROSSED';
```

**Lo que sí se reutiliza de la Fase 27 es el criterio, no el código:** cuando `previous` es 0 o el periodo anterior no tiene datos, el servidor devuelve `delta_pct: null` y el cliente pinta "sin comparación" — el mismo principio del `level: "unknown"` de `context.py`, citado literalmente en la tabla de copy del UI-SPEC. Nunca un `+∞ %` ni un `0 %` inventado.

El mismo patrón de doble ventana sirve para la superposición del periodo anterior en la gráfica (agrupando además por cubo, 50,6 ms) y para la variación por persona del ranking (26,7 ms). **Tres usos, un solo patrón SQL** — merece una función auxiliar compartida en el repo, no tres consultas parecidas.

### Q5 — Ranking de personas y el split `persons.db` — **bloqueo real, resuelto**

**Confirmado: son dos ficheros SQLite distintos.**

- `backend/config.py:74` → `db_path: str = "data/events.db"`
- `backend/main.py:472` → `PersonRecognizer(db_path=settings.db_path.replace("events.db", "persons.db"))`
- `backend/recognizer.py:110` → `sqlite3.connect(str(self._db_path), check_same_thread=False)`, con su propio `_init_db()` (`recognizer.py:484-501`) creando `persons(id, name, encoding, first_seen, last_seen, visit_count)` y `face_encodings`.

Y hay una trampa adicional: **`events.db` también tiene una tabla `persons`** (`backend/storage/models.py:41-53`, del esquema v2 de la Fase 19), pero **nadie escribe nunca en ella** `[VERIFIED: grep de `models.Person` en todo `backend/` no devuelve ni una escritura]`. Está vacía. `events.person_id` es una FK declarada contra esa tabla vacía cuyos valores reales vienen de `persons.db`. Quien intente el `JOIN` obvio obtendrá cero filas y creerá que no hay datos.

**Resolución que respeta D-07 sin fisuras** — tres capas, y ninguna de ellas es el navegador:

| Dato | Dónde se resuelve | Cómo |
|---|---|---|
| **Conteo de visitas y ORDEN del ranking** | SQL en `events.db` | `GROUP BY person_id ORDER BY … DESC LIMIT 10` — el orden llega resuelto, D-07 intacto |
| **Variación frente al periodo anterior, por persona** | SQL en `events.db` | Doble ventana `SUM(CASE …)` en la misma consulta |
| **Avatar** | SQL en `events.db` | `captures.image_path` **vive en `events.db`** (`backend/database.py:54-62`, `get_captures_for_person`) — subconsulta del capture más reciente por persona, transformada a `/gallery/{id}/{fichero}` con el mismo formato que `main.py:1244` |
| **Nombre** | Proceso Python, no SQL | `pipeline.recognizer.list_persons()` devuelve `[{id, name, …}]` completo desde `persons.db`; se convierte en `dict` y se hace lookup sobre ≤10 filas |

Detalles que el plan no puede saltarse:

- `list_persons()` es **sqlite3 síncrono bajo un `threading.Lock`** (`recognizer.py:337-359`). Llamarlo desde una corrutina bloquearía el event loop, contra `CLAUDE.md` ("No ejecutar CPU pesado en el event loop"). **Va envuelto en `asyncio.to_thread`**, igual que `main.py:1146` hace con `get_heatmap`.
- Si el reconocimiento facial no está disponible (`recognizer.available is False`), `list_persons()` devuelve `[]` y **no existe `self._conn`** — el ranking debe degradar a "Persona {id}" y seguir funcionando, no romperse. Es el caso normal en una instalación sin modelos de cara.
- El acceso al recognizer se obtiene con el patrón ya establecido: `configure(camera_manager)` en el `lifespan` (`main.py:587`) y luego `camera_manager.get(camera_id).recognizer` (`manager.py:100`), exactamente como hace `context.py`.
- **No usar `ATTACH DATABASE`** para juntar los dos ficheros. Añadiría acoplamiento entre el pool de conexiones async de SQLAlchemy y un fichero que gestiona otro subsistema en WAL con su propio lock, para ahorrar un lookup en un diccionario de 60 entradas. Es el clásico caso de complejidad que `CLAUDE.md` prohíbe ("cambio mínimo").
- **XSS:** `personGallery.js:26-36` mete `${p.name}` dentro de `innerHTML` — es un agujero preexistente, fuera del alcance de esta fase, pero **el ranking nuevo no puede copiar ese patrón**. D-15 es explícito: nombre por `textContent`.

**Sobre el `INDEXED BY`:** la consulta del ranking es la única de la fase donde el planificador de SQLite elige mal. Se probaron cuatro reescrituras para desviarlo de `idx_events_person` sin hint —`+person_id IS NOT NULL` (208 ms), `ifnull(person_id,0) > 0` (209 ms), `person_id+0 > 0` (192 ms), `HAVING person_id IS NOT NULL` (198 ms), subconsulta `FROM (SELECT …)` (201 ms)— y **ninguna cambia el plan**. El truco del `+` que funcionó en la Fase 30 con `type` aquí no sirve, porque `camera_id` y `ts` siguen siendo términos indexables de `idx_events_person`.

Como **197 ms ya cumple el criterio 4**, el `INDEXED BY` es una optimización, no un requisito. Recomendado aplicarlo (11,7×) con dos salvaguardas: (a) `INDEXED BY` **falla la consulta** si el índice no existe, así que la migración a v4 es su precondición dura; (b) un test que ejecute la consulta del ranking contra una base migrada, para que la desaparición del índice se detecte en CI y no en producción. En SQLAlchemy se expresa con `select(...).with_hint(models.Event, "INDEXED BY idx_events_analytics")`.

### Q6 — Exportación CSV/JSON: `StreamingResponse` + `Content-Disposition`, consumido con `window.location.href`

**Recomendación: copiar literalmente el molde que ya funciona, no inventar uno.**

El patrón existente son dos piezas:

- Servidor: `/api/events/export` (`main.py:910-937`) monta un `csv.DictWriter` sobre un `io.StringIO` y devuelve `StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})`.
- Cliente: `bindEventExport()` (`dashboard-events.js:113-116`) hace `window.location.href = '/api/events/export'`. Sin `blob`, sin `URL.createObjectURL`, sin `<a download>` sintético.

La Fase 30 dejó ese export **intacto a propósito** y anotado para OPS-15 — el comentario en `dashboard-events.js:108-111` lo dice con todas las letras: *"El export CSV sigue apuntando al endpoint v1 (/api/events/export, tabla crossing_events) … anotado para OPS-15"*. Esta fase es esa fase.

**Contrato recomendado:**

| | CSV por panel | JSON del rango |
|---|---|---|
| Ruta | `GET /api/v2/analytics/export` | misma |
| Parámetros | `from`, `to`, `format=csv`, `panel=hourly\|occupancy\|persons` | `from`, `to`, `format=json` |
| `media_type` | `text/csv; charset=utf-8` | `application/json` |
| Nombre (`Content-Disposition`) | `analitica-{panel}-{YYYYMMDD}_{YYYYMMDD}.csv` | `analitica-{YYYYMMDD}_{YYYYMMDD}.json` |
| Peso medido (30 días) | < 30 KB | 2,1 KB (día) / 18,3 KB (hora) |

Un solo endpoint, no cinco: la superficie a proteger con rate limit y validación es menor y `TEST_all_v2_endpoints_rate_limited` tiene menos que comprobar. El `panel` va como enum de FastAPI (`Literal["hourly","occupancy","persons"]`), no como cadena libre — así el 422 lo da Pydantic, no una `if` en el cuerpo.

**Dos detalles no obvios:**

- **BOM UTF-8 en el CSV.** Los nombres de persona y de zona llevan acentos y Excel en Windows los rompe sin BOM. `buf.write('\ufeff')` antes del `writeheader()`. El export v1 no lo hace porque sus datos eran ASCII; los de esta fase no lo son. `[ASSUMED]` — el comportamiento de Excel es conocido pero no se ha verificado en esta sesión con un fichero real.
- **`isSafeMediaUrl()` aplica.** La URL de descarga la construye el módulo `analytics-export.js` a partir del rango, no llega del backend, así que técnicamente no está bajo la regla; pero antes de asignarla a `window.location.href` conviene pasarla igualmente por `isSafeMediaUrl()` (`timeline-row.js:16-18`, añadida al cerrar la Fase 30 tras 3 alertas de CodeQL). Es una línea y evita reabrir esa clase de alerta.

### Q7 — Versionar el heatmap a v2: qué implica exactamente

Menos de lo que parece en el pipeline, y más de lo que parece en la leyenda.

**Lo que ya existe y no cambia:** `CameraPipeline.get_heatmap()` (`manager.py:374-378`) toma el último frame y llama a `DetectionWorker.compose_heatmap()` (`detection.py:167-185`), que normaliza la máscara acumulada a 0-255, la difumina, aplica el colormap y la mezcla al 50/50 **solo donde hay actividad** (`out[active] = blended[active]`). El endpoint v1 (`main.py:1141-1153`) ya hace lo correcto: `await asyncio.to_thread(rtsp_stream.get_heatmap)` y `cv2.imencode(".jpg", …, quality 85)`. `rtsp_stream` **es** un `CameraPipeline` (`main.py:67,652`), no un objeto legado distinto.

**Los cinco cambios reales:**

1. **`COLORMAP_JET` → `COLORMAP_INFERNO`** en `detection.py:180`. Una línea (D-13).
2. **Router nuevo** `GET /api/v2/analytics/heatmap?camera_id=cam1` que use `camera_manager.get(camera_id)` en vez de la global `rtsp_stream`, con `@limiter.limit(V2_RATE_LIMIT)` — obligatorio, `TEST_all_v2_endpoints_rate_limited` recorre todas las rutas `/api/v2` y falla si falta.
3. **Códigos de estado con significado distinto**, que el UI-SPEC ya diferencia con dos textos de estado vacío: **503** cámara sin señal (no hay frame) y **404** sin actividad acumulada (`_heat_mask is None` o su máximo es 0). Hoy v1 devuelve 404 para ambos, así que la lógica de `compose_heatmap` (que retorna `None` en los dos casos) no basta: el endpoint debe comprobar el frame **antes** de componer.
4. **La leyenda numérica necesita un dato que hoy no sale a ningún sitio.** El UI-SPEC exige tres marcas `0` / medio / pico "tomados del propio servidor", y `compose_heatmap` solo devuelve píxeles. Hace falta exponer `float(mask.max())` y `float(mask.mean())` desde el `DetectionWorker` bajo el mismo `self._lock`. **Cómo entregarlo:** un endpoint JSON hermano (`GET /api/v2/analytics/heatmap/scale`), no cabeceras HTTP — un `<img src>` simple no puede leer cabeceras, y pasar a `fetch`+`blob:` obligaría a relajar `isSafeMediaUrl()` para aceptar `blob:` (el CSP sí lo permite ya, `main.py:741`, pero la función no).
5. **La unidad del pico hay que decirla con honestidad.** La máscara acumula, por cada frame procesado, un disco de radio 40 px alrededor del ancla `BOTTOM_CENTER` de cada track (`detection.py:486-493`). Su unidad es "frames de detección con presencia", no personas, y `compose_heatmap` la normaliza dividiendo por el máximo — es decir, **el color es relativo, siempre**. La leyenda honesta es relativa (`0` → `50 %` → `pico`) con el valor absoluto disponible en el `title`. Etiquetar el extremo como "18.432 personas" sería inventar una unidad. Es el mismo principio de D-12 aplicado a la escala.

Y una consecuencia menor pero incómoda: el v1 `/api/heatmap` sigue existiendo y sigue devolviendo JET. O se deja como está (ningún consumidor lo usa desde el frontend nuevo) o se convierte en un alias del v2. Recomendado **dejarlo intacto**: mismo criterio con el que la Fase 30 dejó el export v1 en su sitio, y borrar superficie pública no es "el cambio mínimo".

### Q8 (adicional) — Conmutación de pestañas: qué hay que tocar de verdad

Verificado contra los ficheros reales, no supuesto:

- **`<main>` es hoy la propia retícula**: `<main class="flex-1 p-4 grid grid-cols-1 lg:grid-cols-5 gap-4 max-w-[1600px] mx-auto w-full" role="main">` (`index.html:56`), con dos `<section>` dentro (`lg:col-span-3` y `lg:col-span-2`) y cierre en la línea 678. Para tener dos `role="tabpanel"` hermanos, **el grid tiene que bajar un nivel**: `<main>` pasa a ser contenedor neutro y las clases de grid se mudan al `<section id="view-operaciones" role="tabpanel">`. Es una edición estructural de `index.html`, no un añadido al final del fichero, y conviene que sea su propia tarea.
- **La cabecera tiene sitio para el `tablist`.** `index.html:18-53`: bloque izquierdo con logo y título, bloque derecho con badge del modelo, `#cam-status`, `#btn-alert-center` y `#clock`. El `<nav role="tablist">` va entre ambos, y no hay que reordenar nada de lo existente.
- **La trampa de Chart.js con contenedor oculto es real y está documentada.** El remedio oficial es `chart.resize()` cuando el contenedor recupera tamaño `[CITED: chartjs.org/docs/latest/developers/api.html — ".resize(width?, height?) — Resizes the canvas element … Resizes & redraws to fill its container element"]`, y la propia documentación de responsividad usa ese mismo patrón para el caso análogo de impresión `[CITED: chartjs.org/docs/latest/configuration/responsive.html]`. El síntoma en contenedor `display:none` —canvas a su tamaño intrínseco de 300×150 y gráfica borrosa o desalineada— está reportado repetidamente contra Chart.js `[CITED: github.com/chartjs/Chart.js/issues/1311, /issues/2114, /issues/2267]`. D-03 es correcto y no hay que replantearlo.
- **`bindEventExport()` es el único enganche de `app.js` que esta fase sustituye.** Todo lo demás de `app.js:16-57` (el MJPEG, `initTracksOverlay`, `initTimeline`, `connectWS`, los `setInterval` de galería/salud/observabilidad) sigue arrancando en `DOMContentLoaded` con la vista de operaciones oculta o no — es exactamente lo que D-02 pide.
- **El rate limit no es un problema.** Verificado en el código de slowapi: `limit_scope = lim.scope or endpoint` `[VERIFIED: inspect.getsource(slowapi.extension.Limiter.__evaluate_limits)]`, es decir, los 60/minuto son **por endpoint y por IP**, no un cupo global compartido. Cinco peticiones por cambio de rango dan margen para 60 cambios de rango por minuto. La preocupación de que la observabilidad (`setInterval` de 5 s) consumiera el cupo de la analítica es infundada.

---

## Architecture Patterns

### Diagrama de flujo de datos

```
                    ┌──────────────────────────────────────────┐
   click en un      │  frontend/js/views/analytics-range.js    │
   .filter-chip ───►│  · valida to>=from y to-from<=90d        │
   o "Aplicar"      │  · persiste en localStorage              │
                    │  · resuelve preset -> {from,to} ISO      │
                    └────────────────┬─────────────────────────┘
                                     │ emite rango efectivo
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │  frontend/js/views/analytics.js          │
                    │  · 1 AbortController por tanda           │
                    │  · 4 fetch en PARALELO, sin Promise.all  │
                    │  · cada panel resuelve su estado solo    │
                    └───┬──────┬──────┬──────┬──────┬──────────┘
                        │      │      │      │      │
        ┌───────────────┘      │      │      │      └──────────────┐
        ▼                      ▼      ▼      ▼                     ▼
  /analytics/summary    /hourly  /occupancy  /persons      /heatmap (+/scale)
        │                  │        │           │                  │
        └──────┬───────────┴────────┴───────────┘                  │
               ▼                                                   ▼
   ┌───────────────────────────────┐              ┌────────────────────────────┐
   │ backend/api/v2/analytics.py   │              │ camera_manager.get(cam)    │
   │ · @limiter.limit(V2_RATE_...) │              │  .get_heatmap()            │
   │ · valida rango -> 422         │              │  -> compose_heatmap()      │
   │ · decide bucket hour|day      │              │     (INFERNO, to_thread)   │
   │ · formatea etiquetas          │              └──────────┬─────────────────┘
   └───────────┬───────────────────┘                         │
               │                                             │ JPEG
               ▼                                             ▼
   ┌───────────────────────────────┐              ┌────────────────────────────┐
   │ AnalyticsRepo (repositories)  │              │  <img loading="lazy">      │
   │ · substr(ts,1,13|10)          │              │  + leyenda INFERNO 0/½/pico│
   │ · SUM(CASE ...) doble ventana │              └────────────────────────────┘
   │ · INDEXED BY (solo ranking)   │
   └───────────┬───────────────────┘
               │
        ┌──────┴───────────────────────────┐
        ▼                                  ▼
  ┌──────────────────────┐      ┌───────────────────────────┐
  │ events.db            │      │ persons.db  (FICHERO      │
  │ · events             │      │             SEPARADO)     │
  │ · zones  (JOIN OK)   │      │ · persons(id, name)       │
  │ · captures (JOIN OK) │      │  -> list_persons() en     │
  │ · idx_events_analytics│     │     asyncio.to_thread     │
  └──────────────────────┘      └───────────────────────────┘
        │                                  │
        └──────────► enriquecido en el SERVIDOR ◄────────┘
                     (nunca en el navegador — D-07)
```

### Estructura de ficheros

```
backend/
├── api/v2/
│   └── analytics.py          # NUEVO: summary, hourly, occupancy, persons,
│                             #        heatmap, heatmap/scale, export
├── storage/
│   ├── repositories.py       # MODIFICADO: + AnalyticsRepo
│   ├── models.py             # MODIFICADO: + idx_events_analytics en __table_args__
│   └── migrations.py         # MODIFICADO: SCHEMA_VERSION 3->4 + _migrate_v3_to_v4
├── pipeline/detection.py     # MODIFICADO: JET->INFERNO + heatmap_scale()
└── main.py                   # MODIFICADO: include_router + configure(camera_manager)

frontend/
├── index.html                # MODIFICADO: tablist en cabecera; el grid baja de
│                             #   <main> a <section role="tabpanel"> + vista nueva
├── css/components.css        # MODIFICADO: .nav-tab .analytics-panel .rank-row
│                             #   .range-seg .chart-skeleton
└── js/
    ├── app.js                # MODIFICADO: initNav() + activación diferida
    ├── nav.js                # NUEVO ~70
    └── views/
        ├── analytics.js          # NUEVO ~220  orquestador
        ├── analytics-charts.js   # NUEVO ~200  Chart.js + aria-label
        ├── analytics-range.js    # NUEVO ~130  selector y validación
        ├── analytics-ranking.js  # NUEVO ~150  filas + tarjetas
        └── analytics-export.js   # NUEVO ~90   URLs de descarga

tests/
├── test_analytics_api.py     # NUEVO  contrato de los endpoints
├── test_repositories.py      # MODIFICADO: + 4 tests de presupuesto @100k
├── test_migrations.py        # MODIFICADO: + caso v3->v4
└── test_frontend_modules.py  # MODIFICADO: + 6 módulos a LOCKED_JS
                              #             + TEST_analytics_no_client_aggregation
```

### Pattern 1 — Doble ventana en una sola consulta

**Qué:** en vez de dos consultas (periodo actual y periodo anterior), una sola que barre el rango extendido y separa las ventanas con `CASE`.
**Cuándo:** las tres comparaciones de la fase (tendencia global, serie superpuesta, variación por persona).
**Por qué:** una sola apertura de cursor, un solo recorrido del índice, y el resultado llega ya emparejado — el navegador no tiene que casar dos arrays por etiqueta, que es justo el tipo de trabajo que D-07 prohíbe.

```python
# Fuente: medido en esta sesión — 25,8 ms @100k
stmt = text("""
    SELECT SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS current,
           SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS previous
      FROM events
     WHERE camera_id = :cam
       AND ts >= :prev_from AND ts < :cur_to
       AND type = :etype
""").bindparams(cam=camera_id, cur_from=cur_from, prev_from=prev_from,
                cur_to=cur_to, etype=EventType.LINE_CROSSED.value)
```

`bindparams`, nunca f-strings — misma regla que la Fase 30 dejó escrita para el filtro por regla.

### Pattern 2 — `substr()` en lugar de `strftime()` para el cubo temporal

**Qué:** `substr(ts, 1, 13)` para el cubo horario y `substr(ts, 1, 10)` para el diario.
**Cuándo:** todas las agregaciones por cubo de esta fase.
**Por qué:** 2,3× más rápido, y la ordenación lexicográfica coincide con la cronológica porque el formato es ISO de ancho fijo.

Formato de almacenamiento **verificado en esta sesión** insertando con el ORM real:

```
('x', 'text', '2026-08-22 09:05:03.123456', '2026-08-22 09', '2026-08-22')
('y', 'text', '2026-08-22 09:05:03.000000', '2026-08-22 09', '2026-08-22')
```

Ancho fijo incluso con microsegundos a cero. Ver Pitfall 1 para la guarda obligatoria.

### Pattern 3 — Router v2 con `configure()` inyectado desde el `lifespan`

**Qué:** el molde exacto de `backend/api/v2/context.py`, que además ya vive bajo `/api/v2/analytics`.
**Cuándo:** el router nuevo de esta fase.

```python
# Fuente: backend/api/v2/context.py:29-38 (Fase 27), verbatim
router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])

_camera_manager: Any = None

def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager
```

Y en `main.py`, junto a los seis `include_router` que ya hay (`main.py:757-772`) y al `configure` de `context.py` (`main.py:587`). Cada endpoint lleva su `@limiter.limit(V2_RATE_LIMIT)`: no es opcional, `TEST_all_v2_endpoints_rate_limited` lo comprueba route por route.

### Pattern 4 — Formato de arrays paralelos para las series

```json
{
  "range":  { "from": "2026-08-15", "to": "2026-08-22", "bucket": "hour" },
  "labels": ["00:00", "01:00", "…"],
  "values": [3, 0, "…"],
  "previous": [5, 1, "…"],
  "peak":   { "label": "18:00", "value": 34 },
  "total":  312,
  "min":    { "label": "04:00", "value": 0 }
}
```

`peak`, `total` y `min` van en el payload aunque sean derivables de `values`: los necesita el `aria-label` que el UI-SPEC exige regenerar tras cada carga ("Personas por hora, del 15 al 21 de agosto: 312 personas en total, máximo 34 a las 18:00, mínimo 0 a las 04:00") y calcularlos en el navegador sería un `Math.max()`, prohibido por D-07. Cuestan 0 ms extra: salen de la misma CTE que ya materializa los cubos.

### Anti-patterns a evitar

- **`JOIN persons` dentro de `events.db`.** Devuelve cero filas siempre. La tabla existe y está vacía.
- **`ATTACH DATABASE 'persons.db'`.** Complejidad desproporcionada para un lookup de 60 entradas.
- **`Promise.all` para las cuatro peticiones.** D-08 lo prohíbe explícitamente.
- **Crear los `Chart` en `DOMContentLoaded`.** D-03; canvas de 0×0.
- **Copiar la tipografía de `dashboard-events.js` (9-11px).** D-04; es legado.
- **`.reduce()`/`.sort()`/`Math.max()` sobre datos del servidor** en `views/analytics-*.js`. D-07, auditable con `grep`.
- **`innerHTML` con interpolación de nombres** (el patrón de `personGallery.js:26-36`). D-15.
- **Añadir un índice por combinación de filtros.** SQLite usa uno por referencia de tabla; multiplicarlos no los combina (medido en la Fase 30).

---

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|---|---|---|---|
| Agregar por hora/día | Bucle Python sobre filas | `GROUP BY substr(ts,…)` en SQL | 27 ms frente a traer 100.000 filas al proceso; y OPS-14 lo exige |
| Comparar contra el periodo anterior | Dos consultas + emparejado en Python | Una consulta de doble ventana `SUM(CASE …)` | Un recorrido en vez de dos, resultado ya emparejado |
| Ordenar el ranking | `sorted()` en Python o `.sort()` en JS | `ORDER BY … LIMIT 10` | D-07; y el `LIMIT` evita materializar 60 grupos |
| Serializar CSV | Concatenar cadenas con comas | `csv.DictWriter` de la stdlib | Comillas, comas en los nombres, saltos de línea, `\r\n`. Ya está resuelto en `main.py:929` |
| Descargar un fichero desde JS | `Blob` + `URL.createObjectURL` + `<a download>` sintético | `window.location.href = url` con `Content-Disposition` en el servidor | El molde ya existe (`dashboard-events.js:113`) y evita tocar `isSafeMediaUrl()`/CSP |
| Rampa de color perceptual | Interpolar hues a mano | `cv2.applyColorMap(…, cv2.COLORMAP_INFERNO)` | Está en OpenCV, es una línea, y es perceptualmente uniforme por construcción |
| Elegir el índice correcto | Adivinar por intuición | `EXPLAIN QUERY PLAN` + medición | Tres de las nueve consultas fallaban el criterio 4 y ninguna lo parecía a simple vista |
| Redimensionar el canvas al mostrarlo | Recrear el `Chart` en cada activación | `chart.resize()` | API documentada; recrear pierde animaciones y filtra memoria |
| Rate limiting del router nuevo | Un decorador propio | `@limiter.limit(V2_RATE_LIMIT)` de `deps.py` | El test de seguridad lo exige y el valor es constante compartida |

**La idea de fondo:** en esta fase, casi todo lo que parece "un poco de lógica en el navegador" es en realidad una violación de OPS-14 disfrazada. La pregunta de control ante cualquier línea de JS nueva es: *¿esto seguiría siendo correcto si el dataset tuviera 100.000 filas?* Si la respuesta es "no, porque no las tengo todas", el cálculo va en SQL.

---

## Common Pitfalls

### Pitfall 1 — `substr()` sobre un formato de fecha que cambia bajo los pies

**Qué falla:** `substr(ts,1,13)` da `'2026-08-22 09'` **solo** porque SQLAlchemy almacena `DateTime` como TEXT ISO de ancho fijo. Si algún día una fila entra por otra vía con formato distinto (`'2026-08-22T09:05:03Z'`, o un entero Unix), el `GROUP BY` agrupa mal **sin lanzar ningún error**: la gráfica sale con cubos raros y nadie sabe por qué.
**Por qué ocurre:** es una optimización que cambia una función semántica (`strftime`) por una sintáctica (`substr`).
**Cómo evitarlo:** un test de guarda que inserte un evento **por el ORM real** y compruebe el formato almacenado. Verificado hoy:

```python
# TEST_datetime_storage_format_is_fixed_width_iso
# ('x', 'text', '2026-08-22 09:05:03.123456', '2026-08-22 09', '2026-08-22')
assert typeof_ts == "text"
assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}", raw_ts)
```

**Señal temprana:** el test cae en cuanto alguien cambie el dialecto o el tipo de columna.
**Plan B si no se quiere el acoplamiento:** `strftime` cuesta 120 ms, sigue dentro de los 500 ms. Es una decisión legítima, pero hay que tomarla explícitamente, no por descuido.

### Pitfall 2 — `create_all()` no crea índices sobre tablas existentes

**Qué falla:** se declara `idx_events_analytics` en `models.py`, los tests pasan (bases nuevas), y en la instalación real del usuario el índice **nunca aparece**: la ocupación por zona sigue tardando 551 ms y el `INDEXED BY` del ranking **rompe la consulta con un error**.
**Por qué ocurre:** `metadata.create_all()` solo crea objetos que faltan por completo; no altera tablas ya creadas. La Fase 30 chocó con exactamente esto y lo dejó escrito en `migrations.py:170-175`.
**Cómo evitarlo:** declarar **y** migrar. `SCHEMA_VERSION = 4` + `_migrate_v3_to_v4` con `CREATE INDEX IF NOT EXISTS`, registrado en `MIGRATIONS`. Test en `test_migrations.py` que parta de una base marcada como v3 y verifique que tras `run_migrations()` el índice está en `sqlite_master`.
**Señal temprana:** `run_migrations()` sale por el `return` temprano (`migrations.py:194-196`) sin hacer nada porque `current >= SCHEMA_VERSION`.

### Pitfall 3 — `_record_version(conn, SCHEMA_VERSION)` en vez de la versión propia

**Qué falla:** si `_migrate_v3_to_v4` graba `SCHEMA_VERSION` en vez del literal `4`, una migración v5 futura escrita después dejará bases marcadas como v5 sin haberse ejecutado.
**Por qué ocurre:** parece más "mantenible" usar la constante.
**Cómo evitarlo:** `_record_version(conn, 4)`. El docstring de `_record_version` (`migrations.py:92-95`) ya avisa de esto con nombre y apellidos.

### Pitfall 4 — El `JOIN` de personas que devuelve cero filas

**Qué falla:** `SELECT p.name FROM events e JOIN persons p ON p.id = e.person_id` compila, se ejecuta y devuelve **vacío**. Parece "no hay personas identificadas" y se pinta el estado vacío del ranking.
**Por qué ocurre:** `events.db` tiene una tabla `persons` del esquema v2 que nadie ha poblado nunca; los datos reales están en `persons.db`.
**Cómo evitarlo:** ver Q5. El nombre se resuelve en Python.
**Señal temprana:** el ranking pinta "Sin personas identificadas" mientras la galería de personas del dashboard sí muestra gente.

### Pitfall 5 — `list_persons()` bloqueando el event loop

**Qué falla:** llamar `recognizer.list_persons()` directamente desde una corrutina hace I/O de sqlite3 síncrono **bajo un `threading.Lock` que también usa el hilo de reconocimiento**. Bajo carga, el event loop se para y el MJPEG y el WebSocket se resienten.
**Por qué ocurre:** el método parece barato y devuelve 60 filas.
**Cómo evitarlo:** `await asyncio.to_thread(recognizer.list_persons)`. Precedente exacto: `main.py:1146` hace lo mismo con `get_heatmap`.
**Señal temprana:** `tests/test_architecture.py` protege la regla "ninguna corrutina ejecuta trabajo pesado" — conviene extenderla a este caso.

### Pitfall 6 — El heatmap con `<img>` en un panel oculto y `loading="lazy"`

**Qué falla:** el UI-SPEC pide `loading="lazy"`. Un `<img loading="lazy">` dentro de un contenedor `display:none` **no dispara la petición** hasta que el contenedor es visible. Eso es lo deseado la primera vez, pero si el módulo cambia `img.src` para forzar recarga mientras la pestaña está oculta, la recarga no ocurre y el operador ve la imagen antigua al volver.
**Por qué ocurre:** `loading="lazy"` y "recargar al cambiar de rango" son dos comportamientos que se pisan.
**Cómo evitarlo:** recargar el heatmap **solo cuando la pestaña está activa**; al volver a la pestaña, aplicar el `src` pendiente. Es la misma lógica de "diferir hasta la activación" de D-03, y encaja bien porque el UI-SPEC ya dice "se recarga … al volver a la pestaña".
**Señal temprana:** cambiar de rango en Analítica, ir a Operaciones, volver, y ver el heatmap con la marca de tiempo vieja.

### Pitfall 7 — Cache-busting del heatmap

**Qué falla:** `img.src` con la misma URL no vuelve a pedir nada; el navegador sirve de caché y el mapa parece congelado.
**Cómo evitarlo:** añadir `?t=${Date.now()}` al recargar. Un parámetro que el servidor ignora. **Ojo:** la URL sigue empezando por `/`, así que `isSafeMediaUrl()` la acepta sin cambios.

### Pitfall 8 — El `<main>` que es a la vez la retícula

**Qué falla:** se añade la vista de analítica como tercer hijo de `<main>` y aparece como una **columna más** del `lg:grid-cols-5` en vez de como una vista aparte. El `hidden` la oculta, pero al mostrarla la retícula de operaciones y la de analítica se pelean.
**Por qué ocurre:** `<main>` lleva `grid grid-cols-1 lg:grid-cols-5` directamente (`index.html:56`).
**Cómo evitarlo:** mover las clases de grid de `<main>` al `<section role="tabpanel">` de operaciones. Tarea propia, con verificación visual.

### Pitfall 9 — Truncar el eje Y de una gráfica de conteos

**Qué falla:** dejar que Chart.js elija el mínimo del eje Y exagera visualmente las variaciones.
**Cómo evitarlo:** `y: { min: 0 }`. El UI-SPEC lo llama "la deshonestidad visual más común en dashboards" y ya está en el contrato; se repite aquí porque es fácil que se pierda entre las opciones de Chart.js.

### Pitfall 10 — Los 6 módulos nuevos y el tope de 300 líneas

**Qué falla:** `views/analytics.js` crece por encima de 300 líneas y `TEST_line_limit` rompe la suite. La Fase 30 ya tuvo que partir la línea temporal en cuatro por esto.
**Cómo evitarlo:** respetar el reparto de D-14 desde el principio y añadir los seis a `LOCKED_JS` en la misma tarea en que se crean, no al final.

---

## Code Examples

### Repo de agregación — el molde de las cuatro consultas

```python
# backend/storage/repositories.py — AnalyticsRepo (nuevo)
# Fuente: patrón de DetectionStatRepo.hourly_baseline (repositories.py:411),
# tiempos medidos en esta sesión @100k.

BUCKET_HOUR_DAYS = 7   # <=7 dias -> cubo horario; por encima, cubo diario (Q2)

def _bucket_expr(bucket: str):
    """substr sobre el TEXT ISO de ancho fijo — 2,3x mas rapido que strftime.
    El formato esta protegido por TEST_datetime_storage_format_is_fixed_width_iso."""
    return "substr(ts,1,13)" if bucket == "hour" else "substr(ts,1,10)"

async def hourly(self, camera_id, cur_from, cur_to, bucket):
    """Serie actual + periodo anterior en UNA consulta (50,6 ms @100k, 60 dias)."""
    span = cur_to - cur_from
    prev_from = cur_from - span
    sql = text(f"""
        SELECT {_bucket_expr(bucket)} AS b,
               SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS cur,
               SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS prev
          FROM events
         WHERE camera_id = :cam AND ts >= :prev_from AND ts < :cur_to
           AND type = :etype
         GROUP BY b ORDER BY b
    """)
    async with self._sf() as session:
        rows = (await session.execute(sql, {
            "cam": camera_id, "cur_from": cur_from, "prev_from": prev_from,
            "cur_to": cur_to, "etype": EventType.LINE_CROSSED.value,
        })).all()
    return rows
```

### Ranking con `INDEXED BY` — la única consulta que necesita hint

```python
# 26,7 ms con hint frente a 212,6 ms sin el (medido).
# INDEXED BY FALLA si el indice no existe: la migracion a v4 es precondicion dura.
sql = text("""
    SELECT person_id,
           SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS cur,
           SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS prev
      FROM events INDEXED BY idx_events_analytics
     WHERE camera_id = :cam AND ts >= :prev_from AND ts < :cur_to
       AND person_id IS NOT NULL
     GROUP BY person_id
    HAVING cur > 0
     ORDER BY cur DESC
     LIMIT 10
""")
```

### Enriquecimiento de nombres — en el servidor, fuera del event loop

```python
# backend/api/v2/analytics.py
pipeline = _camera_manager.get(camera_id) if _camera_manager else None
recognizer = getattr(pipeline, "recognizer", None)
if recognizer is not None and getattr(recognizer, "available", False):
    # sqlite3 sincrono bajo threading.Lock -> nunca en el event loop
    names = {p["id"]: p["name"] for p in await asyncio.to_thread(recognizer.list_persons)}
else:
    names = {}   # instalacion sin reconocimiento: el ranking sigue funcionando

items = [
    {"person_id": r.person_id,
     "name": names.get(r.person_id) or f"Persona {r.person_id}",
     "avatar_url": avatars.get(r.person_id),      # de captures, en events.db
     "visits": r.cur,
     "delta_pct": None if not r.prev else round((r.cur - r.prev) * 100 / r.prev)}
    for r in rows          # el ORDEN ya viene de SQL — nada de sorted() aqui
]
```

### Migración v3 → v4

```python
# backend/storage/migrations.py
SCHEMA_VERSION = 4          # era 3 (Fase 30)

def _migrate_v3_to_v4(conn: Connection) -> None:
    """Indice compuesto de analitica (Fase 31, OPS-12/OPS-14).

    Medido @100k: ocupacion por zona 551 -> 28 ms, conocidas/desconocidas
    535 -> 14 ms, personas distintas por hora 618 -> 78 ms. Las tres estaban
    por encima del presupuesto de 500 ms del criterio 4. create_all() no crea
    indices sobre tablas que ya existen, por eso va explicito. CREATE INDEX
    sobre 102.000 filas tarda 196 ms. No toca filas ni columnas.
    """
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_events_analytics "
        "ON events (camera_id, ts, person_id, zone_id, track_id)"))
    _record_version(conn, 4)      # el literal 4, NUNCA SCHEMA_VERSION

MIGRATIONS = [
    (2, "esquema v2 completo", _migrate_v1_to_v2),
    (3, "indice compuesto de la linea temporal", _migrate_v2_to_v3),
    (4, "indice compuesto de analitica", _migrate_v3_to_v4),
]
```

### Activación diferida de las gráficas

```javascript
// frontend/js/nav.js — patron minimo de D-02/D-03
let analyticsBooted = false;

function activate(view) {
  document.getElementById('view-operaciones').hidden = (view !== 'operaciones');
  document.getElementById('view-analitica').hidden   = (view !== 'analitica');
  // history.replaceState, NUNCA location.hash: las pestañas no son paginas
  history.replaceState(null, '', `#${view}`);
  if (view !== 'analitica') return;
  if (!analyticsBooted) { analyticsBooted = true; bootAnalytics(); }  // crea los Chart
  else { resizeAnalyticsCharts(); }                                   // chart.resize()
}
```

Nunca `img.src = ''` sobre el MJPEG ni desconexión del WebSocket al conmutar: D-02 lo prohíbe y `videoCanvas.js` dispararía su lógica de reconexión.

---

## State of the Art

| Enfoque antiguo | Enfoque actual en este repo | Cuándo cambió | Impacto en esta fase |
|---|---|---|---|
| CSV exportado desde `crossing_events` (v1) | Eventos tipados en `events` con esquema v2 | Fase 19 | El export de OPS-15 debe leer de `events`, no de `crossing_events`. La Fase 30 dejó el export v1 intacto y anotado para esta fase |
| Paginación por `OFFSET` | Cursor por valor de fila `(ts, id)` + `idx_events_ts_id` | Fase 30 | No aplica a agregaciones (no paginan), pero fija la metodología: medir con `EXPLAIN QUERY PLAN`, no estimar |
| Lógica en `index.html` inline | ES modules bajo `frontend/js/` con tope de 300 líneas | Fase 28 | Los seis módulos de D-14 y `LOCKED_JS` |
| `Chart.js` instanciado en el arranque | (esta fase) instanciación diferida a la activación de pestaña | Fase 31 | D-03 |
| `cv2.COLORMAP_JET` | `cv2.COLORMAP_INFERNO` | Fase 31 | D-13, una línea |
| Un único `<main>` que es la retícula | Dos `role="tabpanel"` hermanos dentro de `<main>` | Fase 31 | Edición estructural de `index.html`, ver Pitfall 8 |

**Obsoleto / no replicar:**

- Tipografía de 9-11px de `dashboard-events.js` (legado de la Fase 5). D-04.
- `innerHTML` con interpolación de datos del backend (`personGallery.js:26-36`). D-15.
- Tarjetas de estadística con color de fondo verde/azul/ámbar (legado de la Fase 5). El UI-SPEC las declara no replicables.

---

## Assumptions Log

| # | Claim | Sección | Riesgo si es falso |
|---|---|---|---|
| A1 | Excel en Windows necesita BOM UTF-8 para no romper acentos en un CSV | Q6 | Bajo. Si es innecesario, el BOM sobra pero no rompe nada; si falta y hacía falta, los nombres con tilde salen mal en Excel |
| A2 | En una instalación real, la proporción de eventos con `person_id` y `zone_id` no es radicalmente distinta del 35 % / 60 % sembrado | Mediciones | Medio-bajo. Con menos cardinalidad las consultas son **más** rápidas; con más zonas o personas el `TEMP B-TREE FOR GROUP BY` crece, pero sobre grupos, no sobre filas |
| A3 | `type='LINE_CROSSED'` es la métrica de "personas" que el operador espera | Q1 | Bajo-medio. Está respaldado por `backend/database.py:222` (el histograma actual usa exactamente eso) y por el invariante 9 de `CLAUDE.md`, pero es una decisión de producto que conviene confirmar en `/gsd:plan-phase` |
| A4 | `cv2.COLORMAP_INFERNO` existe en la versión de OpenCV instalada | Stack | Bajo. Está en OpenCV 4.x desde hace años; verificable con una línea antes de implementar |
| A5 | `zones.name` está poblado para las zonas que aparecen en `events.zone_id` | Q1 / occupancy | Medio. Si una zona se borró, el `LEFT JOIN` da `NULL` y el panel debe caer al propio `zone_id` como etiqueta en vez de mostrar "null" |
| A6 | Las tarjetas de tendencia "conocidas / desconocidas" cuentan **eventos**, no personas distintas | Tarjetas | Medio. `COUNT(DISTINCT person_id)` es otra cifra (y otra consulta, ~78 ms). El UI-SPEC dice "{N} conocidas / {M} desconocidas" sin desambiguar. **Conviene fijarlo en el plan** |

Las mediciones de rendimiento y de payload, el split de bases de datos, el formato de almacenamiento de `DateTime`, el alcance del rate limit de slowapi y la versión de Chart.js **no** son suposiciones: están verificadas en esta sesión y marcadas `[VERIFIED]` en el texto.

---

## Open Questions

1. **(RESOLVED — 31-04-PLAN.md) ¿"Conocidas / desconocidas" cuenta eventos o personas distintas?** (A6)
   - Lo que se sabe: la tarjeta muestra `{N} conocidas` con apoyo `{M} desconocidas`. Contar eventos cuesta 13,6 ms; contar personas distintas cuesta ~78 ms. Ambas caben.
   - Lo que no está claro: cuál espera leer el operador. "342 conocidas" leído como eventos es una cifra enorme y poco intuitiva; leído como personas es 12.
   - Recomendación: **personas distintas** (`COUNT(DISTINCT person_id)` frente a `COUNT(DISTINCT track_id) WHERE person_id IS NULL`), que es lo que la etiqueta sugiere en castellano. Confirmarlo en la planificación; el coste no decide.

2. **(RESOLVED — 31-04-PLAN.md) Ocupación por zona: ¿`ZONE_ENTERED` a secas o `ZONE_ENTERED` + `INTRUSION`?**
   - Lo que se sabe: `ZONE_ENTERED` es el evento que lleva `zone_id` de forma sistemática (`engine.py:150-160`), pero `INTRUSION` también lo lleva (`engine.py:271,310`). Filtrar por tipo baja la consulta a 24 ms; no filtrar la deja en 28 ms con el índice nuevo.
   - Recomendación: **filtrar a `ZONE_ENTERED`**. "Ocupación" es cuánta gente entró en la zona; una intrusión ya está contada como entrada.

3. **(RESOLVED — 31-02-PLAN.md) La unidad del pico del heatmap.**
   - Lo que se sabe: la máscara acumula frames-con-presencia en un disco de 40 px, y `compose_heatmap` normaliza dividiendo por el máximo, así que la escala **siempre es relativa**.
   - Recomendación: leyenda relativa (`0` / `50 %` / `pico`) con el valor absoluto en el `title`. Etiquetar el extremo con un número de personas sería inventar una unidad, contra el espíritu de D-12.

4. **(RESOLVED — no se toca en esta fase, registrado para una futura) `COUNT(*)` filtrado de la Fase 30 a escala de 100k** — *fuera de alcance, para el registro.*
   - Medido en esta sesión: `COUNT(*) WHERE severity=? AND ts BETWEEN ?` cuesta **563 ms @100k** usando `idx_events_ts` sin covering. La línea temporal solo lo pide en la primera página y con filtros activos, y el criterio de la Fase 30 se midió a 10.000 eventos, así que no es una regresión ni un incumplimiento. Pero a 100.000 eventos ese contador es lento.
   - Recomendación: **no tocarlo en esta fase**. Anotarlo para cuando alguien revise el rendimiento de la línea temporal a escala real. `idx_events_analytics` no lo arregla (no contiene `severity`).

---

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|---|---|---|---|---|
| Python | Todo el backend | ✓ | 3.12.10 | — |
| SQLite | Agregaciones, `EXPLAIN QUERY PLAN` | ✓ | 3.49.1 | — |
| SQLAlchemy 2 + aiosqlite | Repos | ✓ | ya en `requirements.txt` | — |
| OpenCV (`cv2`) | Heatmap INFERNO | ✓ | ya en uso (`detection.py`) | — |
| `scripts/seed_events.py` | Medir criterios 3 y 4 | ✓ | ya existe (usado por `30-12`) | — |
| Chart.js CDN 4.5.1 | Dos gráficas | ✓ | ya con SRI en `index.html:8`; **es la última publicada** | — |
| Cámara Tapo C212 real | Checkpoint visual del heatmap | ⚠️ no verificable aquí | — | El heatmap necesita frame en vivo; los estados 404/503 sí son testeables sin cámara |
| `dbstat` de SQLite | Medir el tamaño exacto del índice | ✗ | no compilado en este build | Se midió el crecimiento del fichero: 70,1 → 76,8 MB (≈ 6,7 MB de índice sobre 100k filas) |

**Sin dependencias bloqueantes.** Lo único no verificable en esta sesión es el checkpoint visual que requiere cámara — el mismo 11º checkpoint manual que la Fase 30 dejó diferido.

---

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|---|---|
| Framework | pytest + pytest-asyncio (`asyncio_mode = auto`) |
| Fichero de configuración | `pytest.ini` — `python_functions = TEST_*` (**el prefijo no es el estándar, es `TEST_`**) |
| Comando rápido | `.venv/Scripts/python.exe -m pytest tests/test_analytics_api.py -q` |
| Suite completa | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s) |

### Mapa requisito → test

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|---|---|---|---|---|
| OPS-12 | `/hourly` devuelve `bucket`, `labels`, `values`, `previous` coherentes | integración | `pytest tests/test_analytics_api.py -k hourly -q` | ❌ Wave 0 |
| OPS-12 | `/occupancy` viene ordenado desc y truncado a 10 | integración | `pytest tests/test_analytics_api.py -k occupancy -q` | ❌ Wave 0 |
| OPS-12 | `/heatmap` devuelve 503 sin cámara y 404 sin actividad | integración | `pytest tests/test_analytics_api.py -k heatmap -q` | ❌ Wave 0 |
| OPS-13 | `/persons` viene ordenado desc, con `delta_pct: null` sin comparación | integración | `pytest tests/test_analytics_api.py -k persons -q` | ❌ Wave 0 |
| OPS-13 | El ranking sobrevive a `recognizer.available is False` | unit | `pytest tests/test_analytics_api.py -k no_recognizer -q` | ❌ Wave 0 |
| **OPS-14** | **Criterio 4: las 4 agregaciones < 500 ms @100k** | perf | `pytest tests/test_repositories.py -k analytics_budget -q` | ❌ Wave 0 |
| **OPS-14** | **Criterio 3: el payload de 30 días < 100 KB** | integración | `pytest tests/test_analytics_api.py -k payload_size -q` | ❌ Wave 0 |
| OPS-14 | Ningún `.reduce()`/`.sort()`/`.filter()`/`Math.max()` en `views/analytics-*.js` | estático | `pytest tests/test_frontend_modules.py -k no_client_aggregation -q` | ❌ Wave 0 |
| OPS-15 | El export devuelve `Content-Disposition: attachment` con el nombre del contrato | integración | `pytest tests/test_analytics_api.py -k export -q` | ❌ Wave 0 |
| — | La migración v3→v4 crea el índice de forma idempotente | unit | `pytest tests/test_migrations.py -k v3_to_v4 -q` | ❌ Wave 0 |
| — | El formato de almacenamiento de `DateTime` es ISO de ancho fijo (guarda de `substr`) | unit | `pytest tests/test_repositories.py -k storage_format -q` | ❌ Wave 0 |
| — | Todo endpoint `/api/v2/analytics/*` tiene rate limit | seguridad | `pytest tests/test_security_regression.py -k rate_limited -q` | ✅ **ya existe** y cubre automáticamente los endpoints nuevos |
| — | Los 6 módulos nuevos existen y caben en 300 líneas | estático | `pytest tests/test_frontend_modules.py -q` | ✅ existe, hay que ampliar `LOCKED_JS` |

**Sobre los presupuestos de los tests de rendimiento:** la Fase 30 usó `_BUDGET_10K_SECS = 0.1` con dos órdenes de magnitud de margen para no ser flaky. El equivalente aquí, con el criterio expresado a 100.000 eventos, es un presupuesto de **0,5 s por consulta** (el criterio literal) sabiendo que lo medido es 14-78 ms: entre 6× y 35× de margen, suficiente para una máquina cargada y aun así capaz de detectar la desaparición del índice (que devuelve las consultas a 535-618 ms).

### Sampling Rate

- **Por commit de tarea:** el fichero de test tocado (`pytest tests/test_analytics_api.py -q`).
- **Por merge de ola:** `pytest tests/test_analytics_api.py tests/test_repositories.py tests/test_migrations.py tests/test_frontend_modules.py -q`.
- **Puerta de fase:** suite completa en verde antes de `/gsd:verify-work`. Obligatorio porque esta fase toca migraciones, API y frontend a la vez — los tres disparadores del punto 2 de la sección "Tests" de `CLAUDE.md`.

### Wave 0 Gaps

- [ ] `tests/test_analytics_api.py` — no existe; cubre OPS-12, OPS-13, OPS-15 y los dos criterios numéricos
- [ ] `tests/test_repositories.py::TEST_analytics_*_budget_100k` — cuatro tests de presupuesto con `seed_events(n=100_000)`
- [ ] `tests/test_repositories.py::TEST_datetime_storage_format_is_fixed_width_iso` — guarda de `substr` (Pitfall 1)
- [ ] `tests/test_migrations.py::TEST_v3_to_v4_creates_analytics_index` — idempotencia + `sqlite_master`
- [ ] `tests/test_frontend_modules.py` — ampliar `LOCKED_JS` con los seis módulos + `TEST_analytics_no_client_aggregation`
- [ ] Ampliar `scripts/seed_events.py` con `--persons N` y `--zones N`: hoy deja `person_id` y `zone_id` a `NULL` (líneas 46-47), así que **los tests de ranking y ocupación medirían sobre datos vacíos y pasarían por accidente**. Es un requisito, no una mejora.

No hace falta instalar framework: pytest ya está y la suite es de 607 tests.

---

## Security Domain

### Categorías ASVS aplicables

| Categoría ASVS | Aplica | Control estándar en este repo |
|---|---|---|
| V2 Authentication | sí (heredado) | Auth global de la app: `FastAPI(dependencies=[Depends(verify)])`. Los routers incluidos con `include_router` la heredan; **no** añadir `Depends(verify)` por ruta |
| V3 Session Management | no | Sin sesión propia; el estado de la vista vive en `localStorage` y en el hash |
| V4 Access Control | sí | LAN, sin roles. La analítica es de solo lectura y no añade ninguna acción destructiva |
| V5 Input Validation | **sí, es la categoría central** | `from`/`to` como `datetime` de FastAPI (no cadenas), `days`/rango acotado con `le=90` → 422, `panel` y `format` como `Literal[...]`, `limit` con `pagination_limit()` si algún endpoint lista |
| V6 Cryptography | no | Sin secretos nuevos |
| V7 Error Handling | sí | `HTTPException` con `detail` en castellano; nunca volcar el SQL ni la traza al cliente |
| V12 Files & Resources | sí | El JPEG del heatmap y el CSV/JSON del export son las únicas respuestas no-JSON. Nombre de fichero **construido por el servidor**, jamás con datos del usuario |
| V14 Configuration | sí | CSP ya vigente (`main.py:736-743`): `img-src 'self' blob: data:` cubre el `<img>` del heatmap sin tocar nada |

### Patrones de amenaza para este stack

| Patrón | STRIDE | Mitigación estándar |
|---|---|---|
| Inyección SQL vía parámetros de rango o `panel` | Tampering | `bindparams` / parámetros de SQLAlchemy, **nunca** f-strings. Los nombres de índice del `INDEXED BY` son literales del código, no entrada |
| XSS por nombre de persona o de zona en el ranking | Tampering | D-15: `textContent`. `personGallery.js:26-36` es el contraejemplo que **no** se copia |
| DoS por rango absurdo (`from=1970`) | DoS | Validación `to - from <= 90 días` → 422, en el servidor. La del cliente es cortesía |
| DoS por martilleo de agregaciones | DoS | `@limiter.limit(V2_RATE_LIMIT)` por endpoint (60/min/IP, verificado como scope por endpoint) |
| Path traversal en el nombre del fichero exportado | Tampering | El nombre lo compone el servidor con fechas normalizadas; no se acepta ningún fragmento del cliente |
| `img.src` / `window.location.href` con URL controlada | Tampering | `isSafeMediaUrl()` (`timeline-row.js:16-18`), añadida tras 3 alertas de CodeQL al cerrar la Fase 30. Aplica al `<img>` del heatmap, al avatar del ranking y a la URL de descarga |
| Fuga de identidad por un endpoint de conteos | Info disclosure | Precedente de la Fase 27: `/context` es de solo recuentos, nunca devuelve identificadores. **Aquí sí se devuelven `person_id` y nombre**, y es correcto porque OPS-13 lo pide explícitamente — pero es una diferencia deliberada que conviene dejar escrita en el docstring del router |

---

## Project Constraints (from CLAUDE.md)

Directivas accionables que el planner debe verificar en cada tarea:

1. **Windows 11 + Python 3.12**, venv en `.venv/`. Comandos con `.venv/Scripts/python.exe`.
2. **Trabajar desde la raíz del repositorio** (`F:\Documentos\IA\Proyecto_Camara`), nunca desde `.claude/worktrees/*`. No crear worktrees.
3. **No añadir dependencias** ni frameworks ni infraestructura sin necesidad. Esta fase no añade ninguna (coincide con D-01).
4. **Prohibido explícitamente:** WebRTC, Docker, PostgreSQL, React/Vue, bundlers.
5. **Nunca exponer credenciales RTSP** en código, logs, commits ni respuestas.
6. **Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.** Consecuencia directa aquí: `list_persons()` y `compose_heatmap()` van por `asyncio.to_thread`. `tests/test_architecture.py` es la barrera.
7. **No ejecutar CPU pesado en el event loop.** Ídem.
8. **No crear estado global oculto.** Los routers v2 usan `configure()` inyectado desde el `lifespan`, no imports cruzados.
9. **Conteo = tracking/cruce, no suma de detecciones por frame** (invariante 9). Sustenta Q1.
10. **Frontend HTML + JS vanilla, sin build step.** Chart.js por CDN.
11. **Tests durante la iteración: solo el fichero afectado.** Suite completa al terminar (obligatoria aquí: se tocan pipeline, API, configuración y frontend).
12. **Regla final:** *"Implementa el cambio mínimo que resuelva el problema sin aumentar innecesariamente latencia, complejidad o acoplamiento."* Es el argumento por el que se descarta `ATTACH DATABASE`, por el que se deja el heatmap v1 intacto y por el que no se añaden más índices de los necesarios.

**Skill local del proyecto:** `.claude/skills/supervision/SKILL.md` — referencia de la librería supervision con el código clonado en `third_party/supervision/`. **No aplica a esta fase**: no se toca detección, tracking ni zonas del pipeline, solo el colormap del heatmap.

---

## Sources

### Primarias (confianza ALTA — verificadas en esta sesión)

- **Mediciones propias** contra una base SQLite real de 100.000 eventos + 129.600 filas de `detection_stats`, con `EXPLAIN QUERY PLAN` y p50 de 7 repeticiones. Cuatro rondas de banco: baseline, índice candidato, anchuras de índice y coste de escritura, alternativas al hint y regresión de la Fase 30.
- **Código del repositorio, leído directamente:** `backend/storage/models.py`, `repositories.py` (`EventRepo.hourly_counts`, `DetectionStatRepo.hourly_baseline`, `assign_person`, `track_scope`), `migrations.py`, `backend/database.py`, `backend/recognizer.py`, `backend/config.py`, `backend/main.py`, `backend/api/v2/{context,events,alerts,deps}.py`, `backend/pipeline/{detection,manager}.py`, `backend/events/{types,engine}.py`, `frontend/index.html`, `frontend/js/{app,api}.js`, `frontend/js/views/{dashboard-events,timeline,timeline-row}.js`, `frontend/js/components/personGallery.js`, `frontend/css/components.css`, `tests/{test_frontend_modules,test_security_regression,test_repositories}.py`, `pytest.ini`, `scripts/seed_events.py`.
- **npm registry** — `npm view chart.js dist-tags` → `latest: 4.5.1` (2026-08-22). Confirma que el pin del proyecto está al día.
- **slowapi** — `inspect.getsource(Limiter.__evaluate_limits)`: `limit_scope = lim.scope or endpoint`. Confirma que el rate limit es por endpoint, no global.
- **SQLAlchemy/SQLite** — inserción real con el ORM del proyecto y lectura del valor crudo: `typeof(ts) = 'text'`, formato `'YYYY-MM-DD HH:MM:SS.ffffff'` de ancho fijo.
- `.planning/phases/30-event-timeline-y-centro-de-alertas/30-RESEARCH.md` — metodología de medición y planes de consulta de la fase anterior.
- `.planning/phases/31-vista-de-anal-tica/31-UI-SPEC.md` y `31-CONTEXT.md` — contrato visual y decisiones bloqueadas.
- `propuesta_mejora/SPEC_v2.md` §8.1-8.2 — contrato de endpoints y estructura de frontend.
- `.planning/ROADMAP.md` § Phase 31 y `.planning/REQUIREMENTS.md` líneas 254-257.

### Secundarias (confianza MEDIA — documentación oficial vía Context7)

- Chart.js — *Responsive Charts* (`chartjs.org/docs/latest/configuration/responsive.html`): `responsive`, `maintainAspectRatio`, `resizeDelay`, y el patrón `resize()` para el caso análogo de impresión.
- Chart.js — *Developers / API* (`chartjs.org/docs/latest/developers/api.html`): `.resize(width?, height?)`.

### Terciarias (confianza BAJA — corroboran el síntoma, no lo definen)

- Incidencias de Chart.js sobre canvas en contenedores `display:none`: `github.com/chartjs/Chart.js/issues/1311`, `/issues/2114`, `/issues/2267`. Coinciden en el síntoma (300×150) y en el remedio (`resize()` al hacerse visible), lo que respalda D-03 — pero D-03 ya estaba bloqueado por el UI-SPEC y no depende de estas fuentes.

---

## Metadata

**Desglose de confianza:**

| Área | Nivel | Motivo |
|---|---|---|
| Criterio 4 (<500 ms) | **HIGH** | Nueve consultas medidas antes y después del índice, con planes de consulta, sobre 100.000 filas reales |
| Criterio 3 (<100 KB) | **HIGH** | Seis formatos de payload serializados y medidos en bytes |
| Elección de índice | **HIGH** | Tres composiciones comparadas + coste de escritura + regresión de la Fase 30 verificada |
| Split `persons.db` | **HIGH** | Verificado leyendo `recognizer.py`, `config.py`, `main.py` y comprobando que nadie escribe `models.Person` |
| Fuente de datos por panel | **HIGH** | Medido y respaldado por el código existente (`database.py:222`) y por el invariante 9 |
| Trampa de Chart.js | **MEDIUM-HIGH** | El remedio está en la documentación oficial; el síntoma exacto solo en incidencias de la comunidad |
| Semántica de las tarjetas (A6) | **MEDIUM** | El coste está medido; la elección de producto queda como pregunta abierta |
| BOM UTF-8 en el CSV (A1) | **LOW** | Conocimiento general, no verificado con un fichero real en esta sesión |

**Fecha de research:** 2026-08-22
**Válido hasta:** ~2026-09-21 (30 días). Todo lo medido es local y estable: solo lo invalidaría un cambio de esquema en `events`, un cambio de versión de SQLite o la aparición de Chart.js 5.
