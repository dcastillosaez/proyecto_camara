# Phase 31: Vista de analítica - Pattern Map

**Mapped:** 2026-08-22
**Files analyzed:** 21 (13 new, 8 modified)
**Analogs found:** 21 / 21

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/api/v2/analytics.py` (NUEVO) | router (controller) | request-response (agregación SQL) | `backend/api/v2/context.py` | exact — mismo prefijo `/api/v2/analytics`, mismo `configure()` |
| `backend/storage/repositories.py::AnalyticsRepo` (nuevo, en fichero existente) | service (repo) | CRUD/agregación | `DetectionStatRepo.hourly_baseline()` + `EventRepo.query()`/`_filter_conditions()` | exact — mismo fichero, mismo patrón de doble ventana |
| `backend/storage/models.py` (MODIFICADO — `Event.__table_args__`) | model | — | `Event.__table_args__` ya existente (Fase 30 añadió `idx_events_ts_id`) | exact |
| `backend/storage/migrations.py` (MODIFICADO — v3→v4) | migration | batch | `_migrate_v2_to_v3` (Fase 30) | exact — mismo molde línea a línea |
| `backend/pipeline/detection.py` (MODIFICADO — `compose_heatmap`) | service (pipeline) | transform (imagen) | el propio método, ya existente | exact — cambio de una línea + exponer `heatmap_scale()` |
| `backend/main.py` (MODIFICADO — routers + lifespan) | config/bootstrap | — | bloque `include_router`/`configure()` de Fase 27/30 | exact |
| `frontend/index.html` (MODIFICADO — tablist + grid) | markup | — | estructura de cabecera/`<main>` existente | role-match — edición estructural, no un componente nuevo a copiar |
| `frontend/css/components.css` (MODIFICADO — clases nuevas) | config (estilos) | — | reglas existentes (`.ptz-btn`, `.filter-chip`, `.event-item`) | role-match |
| `frontend/js/app.js` (MODIFICADO — `initNav()`) | provider (bootstrap) | event-driven | bloque `DOMContentLoaded` existente | exact |
| `frontend/js/nav.js` (NUEVO) | provider (router mínimo) | event-driven | no hay analog directo (no existía router); patrón más cercano: activación diferida documentada en 31-RESEARCH Pattern "Activación diferida" | role-match — sin precedente exacto en el repo, sí en RESEARCH |
| `frontend/js/views/analytics.js` (NUEVO) | view (orquestador) | request-response, paralelo | `frontend/js/views/timeline.js` (`loadPage`, estados por sección) | exact — mismo rol de orquestador de una vista |
| `frontend/js/views/analytics-charts.js` (NUEVO) | component (charts) | transform (render) | `frontend/js/views/dashboard-events.js` (instancia de `Chart`, `updateChart`) | exact — mismo molde de instanciación Chart.js, tipografía a corregir (12px, no 9-11px) |
| `frontend/js/views/analytics-range.js` (NUEVO) | component (filtros) | request-response (cortesía de validación) | `frontend/js/views/timeline-filters.js` (`filterParams`, chips excluyentes) | exact — mismo patrón de chips + querystring en servidor |
| `frontend/js/views/analytics-ranking.js` (NUEVO) | component (lista) | transform (render) | `frontend/js/views/timeline-row.js` (`timelineRow`, anti-XSS, `isSafeMediaUrl`) | exact — misma convención innerHTML-vacío + textContent |
| `frontend/js/views/analytics-export.js` (NUEVO) | component (descarga) | file-I/O (descarga) | `frontend/js/views/dashboard-events.js::bindEventExport` | exact |
| `tests/test_analytics_api.py` (NUEVO) | test (integración) | request-response | `tests/test_events_api.py` (fixtures `sf`/`client`, patch de `get_session_factory`) | exact |
| `tests/test_repositories.py` (MODIFICADO — 4 tests de presupuesto) | test (perf) | batch | `TEST_query_performance_100k` / `TEST_timeline_*_under_budget_10k` | exact |
| `tests/test_migrations.py` (MODIFICADO — caso v3→v4) | test (unit) | batch | `TEST_migration_v3_creates_timeline_index` / `TEST_migration_v3_is_idempotent` / `TEST_fresh_db_has_timeline_index` | exact |
| `tests/test_frontend_modules.py` (MODIFICADO — `LOCKED_JS` + no-aggregation) | test (estático) | — | bloque `LOCKED_JS` ya extendido por la Fase 30 | exact |
| `scripts/seed_events.py` (MODIFICADO — `--persons`/`--zones`) | utility (script) | batch | el propio script (Fase 30) | exact — extensión, no reemplazo |
| `tests/test_security_regression.py` (sin cambios de código, cobertura automática) | test (seguridad) | — | `TEST_all_v2_endpoints_rate_limited` ya recorre `/api/v2/*` | exact — no requiere tocar el fichero, solo verificar que pasa |

## Pattern Assignments

### `backend/api/v2/analytics.py` (router, request-response)

**Analog:** `backend/api/v2/context.py` (verbatim para el molde de router) + `backend/api/v2/events.py` (para filtros/paginación y para el manejo de 400/422)

**Imports pattern** (`context.py:14-27`):
```python
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.config import Settings, get_settings
from backend.database import get_session_factory
from backend.storage.repositories import DetectionStatRepo

router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])
```
Para el router de la Fase 31: el `prefix` **ya está tomado** por `context.py` (`/api/v2/analytics`). FastAPI permite dos `APIRouter` con el mismo prefix incluidos por separado (confirmado en 31-RESEARCH Q1/Standard Stack) — usar el mismo prefijo, no inventar uno nuevo (`/api/v2/analytics-v2` sería incorrecto). Además importar `asyncio` (para `asyncio.to_thread`) y `EventType` de `backend.events.types`.

**`configure()` inyectado desde el lifespan** (`context.py:30-36`, verbatim, mismo patrón que documenta 31-RESEARCH Pattern 3):
```python
_camera_manager: Any = None

def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager
```

**Validación de rango con 422 automático de Pydantic** — mismo estilo que `context.py:114` (`days: int | None = Query(default=None, ge=1, le=90)`) y `deps.py::pagination_limit`. Aplicar a `from`/`to`/rango máximo de 90 días y a `panel`/`format` como `Literal[...]` (según recomienda 31-RESEARCH Q6, no como cadena libre con `if`).

**Manejo de 400 con enums inválidos** (`events.py:84-88`, para cualquier parámetro tipo `Literal`/enum):
```python
try:
    types = [EventType(t) for t in (type or [])] or None
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc))
```

**Rate limit — no opcional en ningún endpoint** (`context.py:109-110`, `events.py:68-69`):
```python
@router.get("/hourly")
@limiter.limit(V2_RATE_LIMIT)
async def get_hourly(request: Request, ...) -> dict[str, Any]:
    ...
```
`tests/test_security_regression.py::TEST_all_v2_endpoints_rate_limited` recorre automáticamente todas las rutas de `/api/v2`; si falta el decorador en un endpoint nuevo, ese test lo detecta sin tocarlo.

**Enriquecimiento fuera del event loop** (patrón nuevo pero con precedente exacto en `main.py:1146` para `get_heatmap`, ya citado en 31-RESEARCH Code Examples):
```python
pipeline = _camera_manager.get(camera_id) if _camera_manager else None
recognizer = getattr(pipeline, "recognizer", None)
if recognizer is not None and getattr(recognizer, "available", False):
    names = {p["id"]: p["name"] for p in await asyncio.to_thread(recognizer.list_persons)}
else:
    names = {}
```

**Docstring de excepción de seguridad** (a diferencia de `context.py:9-11`, que es "solo recuentos"): el router de analítica **sí** devuelve `person_id` y nombre en `/persons`, y eso hay que dejarlo escrito en el docstring del módulo o del endpoint, exactamente como pide 31-RESEARCH § Security Domain ("Fuga de identidad por un endpoint de conteos").

---

### `backend/storage/repositories.py::AnalyticsRepo` (service/repo, CRUD-agregación)

**Analog primario:** `DetectionStatRepo.hourly_baseline()` (`repositories.py:411-480`) para el molde de docstring-con-justificación-de-diseño y para el patrón de doble agregación.
**Analog secundario:** `EventRepo._filter_conditions()` / `EventRepo.query()` (`repositories.py:102-191`) para `bindparams` seguros y construcción de condiciones.

**Import pattern** (cabecera de `repositories.py`, ya usada por ambas clases existentes):
```python
from sqlalchemy import and_, func, select, text, tuple_, bindparam, String
from sqlalchemy.ext.asyncio import AsyncSession
from backend.storage import models
```

**Núcleo — doble ventana en una sola consulta** (código ya escrito y medido en 31-RESEARCH § Code Examples, listo para trasplantar):
```python
BUCKET_HOUR_DAYS = 7   # <=7 dias -> cubo horario; por encima, cubo diario (Q2)

def _bucket_expr(bucket: str):
    """substr sobre el TEXT ISO de ancho fijo — 2,3x mas rapido que strftime.
    El formato esta protegido por TEST_datetime_storage_format_is_fixed_width_iso."""
    return "substr(ts,1,13)" if bucket == "hour" else "substr(ts,1,10)"

async def hourly(self, camera_id, cur_from, cur_to, bucket):
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

**Ranking con `INDEXED BY`** (única consulta de la fase que necesita hint — 31-RESEARCH Q5/Code Examples):
```python
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
En SQLAlchemy expresado con `select(...).with_hint(models.Event, "INDEXED BY idx_events_analytics")` si se prefiere el constructor sobre `text()`.

**`bindparams`, nunca f-strings** — misma regla que `EventRepo._filter_conditions()` línea 139-144 (filtro `rule` con `json_each`):
```python
conditions.append(text(
    "EXISTS (SELECT 1 FROM json_each(events.payload, '$.rules') je WHERE je.value = :rule)"
))
params["rule"] = rule
```

**Error handling / degradación:** ninguna de las consultas de `AnalyticsRepo` lanza excepción de negocio; el patrón de "silla vacía" está en el router (`raise HTTPException(...)`), no en el repo — igual que `EventRepo`/`DetectionStatRepo` hoy.

---

### `backend/storage/models.py` (model, índice nuevo)

**Analog:** `Event.__table_args__` ya existente (`models.py:104-112`), que la Fase 30 extendió con `idx_events_ts_id`.

```python
__table_args__ = (
    Index("idx_events_ts", ts.desc()),
    Index("idx_events_type_ts", "type", ts.desc()),
    Index("idx_events_cam_ts", "camera_id", ts.desc()),
    Index("idx_events_person", "person_id", ts.desc()),
    Index("idx_events_ts_id", ts.desc(), id.desc()),
    # Fase 31 (OPS-12/14): covering index para occupancy/known-unknown/ranking.
    # Anchura de 5 columnas medida — ver 31-RESEARCH.md "Anchura del índice".
    Index("idx_events_analytics", "camera_id", "ts", "person_id", "zone_id", "track_id"),
)
```
Este `Index()` cubre **bases nuevas** (vía `create_all()`); las existentes necesitan la migración de abajo — mismo patrón dual que dejó la Fase 30.

---

### `backend/storage/migrations.py` (migration, v3→v4)

**Analog exacto:** `_migrate_v2_to_v3` (`migrations.py:167-176`), literal excepto el SQL y el número de versión.

```python
SCHEMA_VERSION = 4          # era 3 (Fase 30)

def _migrate_v3_to_v4(conn: Connection) -> None:
    """Indice compuesto de analitica (Fase 31, OPS-12/OPS-14).
    ...
    """
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_events_analytics "
        "ON events (camera_id, ts, person_id, zone_id, track_id)"))
    _record_version(conn, 4)      # el literal 4, NUNCA SCHEMA_VERSION (Pitfall 3)

MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (2, "esquema v2 completo", _migrate_v1_to_v2),
    (3, "indice compuesto de la linea temporal", _migrate_v2_to_v3),
    (4, "indice compuesto de analitica", _migrate_v3_to_v4),
]
```

**Regla de oro repetida en el propio `migrations.py:92-95`:** `_record_version()` graba SIEMPRE el literal de la migración, nunca la constante `SCHEMA_VERSION` — es exactamente el Pitfall que la Fase 30 dejó documentado con nombre y apellido.

---

### `backend/pipeline/detection.py::compose_heatmap` (service, transform)

**Analog:** el propio método (`detection.py:167-185`), cambio de una línea + método hermano nuevo.

```python
# Línea 180, cambio único (D-13):
colored = cv2.applyColorMap(temp, cv2.COLORMAP_INFERNO)   # era COLORMAP_JET
```

**Método nuevo `heatmap_scale()`** (no existe analog directo; se compone con el mismo `with self._lock:` que ya usa `compose_heatmap` y `get_object_boxes` línea 164):
```python
def heatmap_scale(self) -> dict[str, float] | None:
    """Pico y media de la mascara acumulada, para la leyenda numerica del panel 3.
    La escala es siempre relativa (D-12): el pico es el 100%, no una cifra de personas."""
    with self._lock:
        mask = None if self._heat_mask is None else self._heat_mask.copy()
    if mask is None:
        return None
    peak = float(mask.max())
    if peak <= 0:
        return None
    return {"peak": peak, "mean": float(mask.mean())}
```

---

### `backend/main.py` (bootstrap, routers + lifespan)

**Analog:** bloque de `context_v2_module.configure(camera_manager)` (`main.py:586-587`) y de los `include_router` (`main.py:757-772`).

```python
# Dentro del lifespan, junto a las líneas 586-593:
from backend.api.v2 import analytics as analytics_v2_module
analytics_v2_module.configure(camera_manager)

# Junto al bloque de include_router (main.py:757-772):
app.include_router(analytics_v2_router)
```
El router de heatmap puede vivir en el mismo módulo `analytics.py` o en uno propio; si se separa, sigue el mismo molde de `configure()`.

**El endpoint v1 `/api/heatmap` (`main.py:1141-1152`) se deja intacto**, con `COLORMAP_JET` — no se toca ni se convierte en alias, mismo criterio que 31-RESEARCH Q7 documenta para el export v1.

---

### `frontend/js/views/analytics.js` (view, orquestador)

**Analog:** `frontend/js/views/timeline.js` — específicamente su patrón de estado por módulo con variables privadas (`_all`, `_loading`, `_cursor`...) y `loadPage()`/`_paintStates()` (`timeline.js:20-30, 63-70, 73-110`).

**Diferencia clave a respetar (D-08/D-09):** `timeline.js` hace una sola petición por carga; `analytics.js` debe lanzar **cuatro fetch en paralelo sin `Promise.all`**, cada uno resolviendo su propio estado de panel. El molde de "estado de carga / error / vacío" por sección es el de `_paintStates()` + `_show()` (`timeline.js:34-39, 63-70`) replicado una vez por panel en vez de una vez por lista completa.

```javascript
// timeline.js:34-39 — patron _show(), reutilizable tal cual para cada panel
function _show(id, on) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('hidden', !on);
  el.classList.toggle('flex', on);
}
```

**AbortController por tanda (D-09)** — no hay precedente exacto en el repo (timeline.js no aborta), así que este fragmento viene de RESEARCH, no de un analog: un `AbortController` nuevo por cambio de rango, pasado a cada `fetch`, y las respuestas de un controller abortado se descartan comparando contra el controller vigente en el momento de resolver la promesa (mismo patrón que cualquier "stale response" guard).

**`apiFetch`** (`timeline.js:9`, `frontend/js/api.js`) es el wrapper HTTP ya usado por toda la vista de operaciones — reutilizar, no inventar un segundo cliente fetch.

---

### `frontend/js/views/analytics-charts.js` (component, Chart.js)

**Analog:** `frontend/js/views/dashboard-events.js` líneas 53-104 (instanciación + `updateChart`), **con la corrección tipográfica que exige el UI-SPEC** (12px en vez de 9-11px, D-04).

```javascript
// dashboard-events.js:56-90 — molde de instanciacion, COPIAR LA ESTRUCTURA, no el tamano de fuente
const actChart = new Chart(
  document.getElementById('activity-chart').getContext('2d'),
  {
    type: 'bar',
    data: { labels: hours, datasets: [{ ... }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
          titleColor: '#94a3b8', bodyColor: '#f8fafc',
          titleFont: { size: 10 }, bodyFont: { size: 11 },   // <- en 31: size 12, no 10/11
          callbacks: { label: c => ` ${c.parsed.y} personas` },
        },
      },
      scales: {
        x: { grid: { color: 'rgba(51,65,85,0.3)', drawTicks: false }, border: { display: false },
             ticks: { color: '#475569', font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 } },  // <- 31: size 12
        y: { min: 0, grid: { color: 'rgba(51,65,85,0.3)', drawTicks: false }, border: { display: false },
             ticks: { color: '#475569', font: { size: 9 }, precision: 0, maxTicksLimit: 4 } },     // <- 31: size 12
      },
    },
  }
);
```

**`chart.resize()` en cada activación posterior** (D-03, sin precedente en el repo — patrón documentado en 31-RESEARCH § Code Examples "Activación diferida de las gráficas"):
```javascript
let analyticsBooted = false;
function activate(view) {
  ...
  if (!analyticsBooted) { analyticsBooted = true; bootAnalytics(); }
  else { resizeAnalyticsCharts(); }   // chart.resize() sobre cada instancia
}
```

**`aria-label` regenerado tras cada carga**, con los valores que ya manda el servidor (`peak`, `total`, `min` del payload — ver Pattern 4 de RESEARCH), nunca calculados en cliente (D-07).

---

### `frontend/js/views/analytics-range.js` (component, filtros)

**Analog:** `frontend/js/views/timeline-filters.js` — patrón de chips excluyentes/multi-selección (`bindFilterChips()`, líneas 112-133) y de querystring construido en cliente pero **resuelto** en servidor.

```javascript
// timeline-filters.js:126-132 — chips EXCLUYENTES (severidad): mismo patron para "Hoy/7 dias/30 dias/Personalizado"
$('tl-filter-severity')?.addEventListener('click', (e) => {
  const chip = e.target.closest('.filter-chip');
  if (!chip) return;
  const on = chip.classList.contains('active');
  document.querySelectorAll('#tl-filter-severity .filter-chip').forEach((c) => c.classList.remove('active'));
  chip.classList.toggle('active', !on);
});
```

**Mensaje de validación de rango exacto, ya en uso** (`dashboard-events.js:27`, citado literalmente por el UI-SPEC como cadena a reutilizar):
```javascript
deleteMsg.textContent = 'La fecha «Hasta» debe ser posterior a «Desde».';
```

**Persistencia en `localStorage`** (mismo patrón que `timeline-row.js:167-179`, `DISMISS_KEY`/`readDismissed`/`writeDismissed`, con `try/catch` para modo privado o cuota):
```javascript
const DISMISS_KEY = 'timeline.dismissed';
function readDismissed() {
  try {
    const raw = JSON.parse(localStorage.getItem(DISMISS_KEY) ?? '[]');
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}
function writeDismissed(ids) {
  try { localStorage.setItem(DISMISS_KEY, JSON.stringify(ids)); } catch { /* modo privado o cuota */ }
}
```
Para `analytics-range.js`: clave `analytics.range`, mismo `try/catch` doble.

---

### `frontend/js/views/analytics-ranking.js` (component, lista + tarjetas)

**Analog:** `frontend/js/views/timeline-row.js` — convención anti-XSS íntegra (`timelineRow()`, `paintDesc()`, líneas 1-8, 91-101, 103-162).

**Patrón obligatorio, citado literalmente por D-15 del UI-SPEC:**
```javascript
// timeline-row.js:1-8
// Patron obligatorio del repo (CodeQL js/xss): la estructura va por innerHTML con
// elementos VACIOS y todo dato del backend entra despues por textContent / dataset /
// propiedades del DOM.
row.innerHTML = `
  <span class="sev-bar" aria-hidden="true"></span>
  <span class="tl-time mono text-xs text-slate-400 tabular-nums flex-shrink-0"></span>
  ...`;
row.querySelector('.tl-time').textContent = time;   // dato del backend -> textContent, nunca interpolado
```

**Contraejemplo explícito a NO copiar** (`frontend/js/components/personGallery.js:28`):
```javascript
// MAL — no replicar en analytics-ranking.js:
row.innerHTML = `<span class="...">${p.name}</span>`;
```
El nombre de persona y el nombre de zona del ranking van por `textContent`, exactamente como hace `timeline-row.js` con `desc.textContent` / `paintDesc()`.

**`isSafeMediaUrl()` para el avatar** (`timeline-row.js:16-18`, verbatim, importable directamente si se reutiliza el módulo o se copia la función):
```javascript
export function isSafeMediaUrl(url) {
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//');
}
```

**Fila con altura fija y sin ser un botón entero** — mismo criterio que `.timeline-row` (fila de 52px con acciones discretas, no la fila entera clicable): `.rank-row` de 40px sigue el mismo principio.

---

### `frontend/js/views/analytics-export.js` (component, descarga)

**Analog exacto:** `frontend/js/views/dashboard-events.js::bindEventExport` (líneas 113-116), citado literalmente por D-10 del UI-SPEC y por 31-RESEARCH Q6.

```javascript
// dashboard-events.js:113-116 — patron completo a replicar, sin blob ni <a download>
export function bindEventExport() {
  const btn = document.getElementById('btn-export-csv');
  if (btn) btn.addEventListener('click', () => { window.location.href = '/api/events/export'; });
}
```
Para `analytics-export.js`: la URL lleva los parámetros del rango visible (`from`, `to`, `format=csv|json`, `panel=...`), construida con `URLSearchParams`, y pasada por `isSafeMediaUrl()` antes de asignarse a `window.location.href` (defensa en profundidad recomendada por 31-RESEARCH Q6, aunque la URL la construye el propio cliente).

**Botones deshabilitados mientras el panel carga/está vacío** (mismo criterio de opacidad que otros controles del repo, p. ej. `.ptz-btn.busy` en `components.css:15`):
```css
.ptz-btn.busy { opacity: 0.5; pointer-events: none; }
```

---

### `frontend/index.html` (estructura — tablist + grid)

**Analog:** la propia cabecera (`index.html:17-53`) y el `<main>` actual (`index.html:56`).

**Patrón de icono SVG estilo feather ya en uso** (`index.html:20-23`, `44-46`), a replicar en el `<nav role="tablist">`:
```html
<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
  <path d="..."/>
</svg>
```

**Cambio estructural obligatorio (Pitfall 8 de RESEARCH):** las clases `grid grid-cols-1 lg:grid-cols-5 gap-4 max-w-[1600px] mx-auto w-full` de `<main>` (línea 56) se mueven al `<section id="view-operaciones" role="tabpanel">`; `<main>` pasa a ser contenedor neutro con las dos secciones (`view-operaciones`, `view-analitica`) como hijos directos.

**Bloque derecho de cabecera con hueco para el tablist** (`index.html:31-52`): el `<nav role="tablist" aria-label="Vistas">` va entre el badge del modelo y `#cam-status`, sin reordenar nada existente.

---

### `frontend/js/app.js` (bootstrap — `initNav()`)

**Analog:** el propio `DOMContentLoaded` (`app.js:16-58`) — mismo criterio de "wiring de listeners primero, cargas después" ya establecido.

```javascript
// app.js:16-27 — patron de bind-then-load a extender con initNav()
document.addEventListener('DOMContentLoaded', () => {
  bindPtzControls();
  ...
  bindEventExport();
  bindAlertCenter();
  bindMarkPerson();
  // Fase 31: initNav() aquí, junto al resto de bind*()
  ...
});
```
`initNav()` se añade al bloque de binds (no de cargas): activa la pestaña resuelta del hash y engancha `hashchange`, sin llamar a `bootAnalytics()` salvo que el hash inicial ya sea `#analitica` (caso de recarga con la vista de analítica activa).

---

### `tests/test_analytics_api.py` (test, integración)

**Analog exacto:** `tests/test_events_api.py` — fixture `sf` con base temporal parcheada dentro del módulo del router (líneas 32-44) y fixture `client` con `ASGITransport` (líneas 47-52).

```python
# test_events_api.py:32-44 — replicar tal cual, cambiando events_module por analytics_module
@pytest_asyncio.fixture
async def sf(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events_api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    with patch.object(analytics_module, "get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as c:
        yield c
```
**Detalle no obvio:** como `AnalyticsRepo` usa `INDEXED BY idx_events_analytics` en el ranking, la base de test tiene que pasar por `run_migrations()` (o crearse ya con el índice vía `create_all()`, que sí lo declara en `Event.__table_args__`) — si no, la consulta del ranking falla con error de SQLite, no con datos vacíos.

---

### `tests/test_repositories.py` (test, perf, presupuesto)

**Analog exacto:** `TEST_query_performance_100k` (líneas 574-594) y el bloque `_BUDGET_10K_SECS` (líneas 597-628).

```python
# repositories.py:574-593 — molde de test de presupuesto a 100k
async def TEST_query_performance_100k(db, tmp_path):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    repo = EventRepo(sf)
    start = time.perf_counter()
    items, _ = await repo.query(camera_id="cam1", ts_from=..., ts_to=..., limit=50)
    elapsed = time.perf_counter() - start
    await engine.dispose()
    assert elapsed < 0.5, f"query took {elapsed:.3f}s, expected < 0.5s"
```
Para la Fase 31: presupuesto de **0.5s** por consulta (criterio 4 literal), con `AnalyticsRepo` en vez de `EventRepo`, y la base sembrada **debe** usar el `--persons`/`--zones` nuevo de `seed_events.py` (si no, ranking y ocupación miden sobre datos vacíos y "pasan por accidente" — Wave 0 Gap explícito en RESEARCH).

**Test de guarda del formato de fecha** (Pitfall 1 de RESEARCH, sin analog directo — nuevo, sigue el estilo de aserción de la suite):
```python
# TEST_datetime_storage_format_is_fixed_width_iso
assert typeof_ts == "text"
assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}", raw_ts)
```

---

### `tests/test_migrations.py` (test, unit — v3→v4)

**Analog exacto:** `TEST_migration_v3_creates_timeline_index` / `TEST_migration_v3_is_idempotent` / `TEST_fresh_db_has_timeline_index` (líneas 242-272) y el helper `make_v2_db()` (líneas 69-87).

```python
# test_migrations.py:242-272 — replicar la terna completa para v3->v4
def TEST_migration_v4_creates_analytics_index(tmp_path):
    db_path = tmp_path / "v3.db"
    make_v3_db(db_path)   # analogo a make_v2_db, pero parte de schema_version=3
    engine = create_engine(f"sqlite:///{db_path}")
    assert _index_names(engine, "idx_events_analytics") == []

    run_migrations(engine)

    assert _index_names(engine, "idx_events_analytics") == ["idx_events_analytics"]
    assert _schema_version(engine) == 4


def TEST_migration_v4_is_idempotent(tmp_path):
    ...  # run_migrations() dos veces, mismo assert final


def TEST_fresh_db_has_analytics_index(tmp_path):
    """Una base nueva lo hereda de Event.__table_args__, sin pasar por la migracion."""
    ...
```
`make_v3_db()` es un helper nuevo análogo a `make_v2_db()` (líneas 69-87): parte de `create_all()`, hace `DROP INDEX IF EXISTS idx_events_analytics` y fuerza `schema_version=3` en `app_config` — mismo razonamiento documentado en el docstring de `make_v2_db` sobre por qué el DROP es deliberado.

---

### `tests/test_frontend_modules.py` (test, estático)

**Analog exacto:** el propio `LOCKED_JS` (líneas 26-46), ya extendido una vez por la Fase 30 con los módulos de línea temporal y centro de alertas.

```python
LOCKED_JS = [
    ...,
    "views/timeline.js",
    "views/timeline-row.js",
    "views/timeline-virtualize.js",
    "views/timeline-filters.js",
    "components/alertCenter.js",
    "components/markPerson.js",
    # Fase 31: vista de analitica.
    "nav.js",
    "views/analytics.js",
    "views/analytics-charts.js",
    "views/analytics-range.js",
    "views/analytics-ranking.js",
    "views/analytics-export.js",
]
```
`TEST_line_limit` (líneas 59-66) cubre automáticamente los seis nuevos módulos sin cambios adicionales — solo hace falta que existan en disco y quepan en 300 líneas.

**Test nuevo — sin analog directo, patrón `assert not offenders` reutilizado de `TEST_line_limit`:**
```python
def TEST_analytics_no_client_aggregation():
    """D-07 / OPS-14: ni reduce, ni sort, ni filter, ni Math.max sobre datos del servidor."""
    offenders = []
    for rel in ("views/analytics.js", "views/analytics-charts.js", "views/analytics-range.js",
                "views/analytics-ranking.js", "views/analytics-export.js"):
        content = (FRONTEND / "js" / rel).read_text(encoding="utf-8")
        for forbidden in (".reduce(", ".sort(", ".filter(", "Math.max("):
            if forbidden in content:
                offenders.append(f"{rel}: {forbidden}")
    assert not offenders, f"agregacion en cliente detectada (D-07): {offenders}"
```
Nota: `.filter(` puede dar falso positivo legítimo en `analytics-range.js` si se usa `Array.prototype.filter` sobre datos puramente locales (p.ej. opciones de un `<select>`) — si ocurre, hay que decidir en el plan si se excluye esa línea concreta o se reescribe sin `.filter()`; no relajar el grep global.

---

### `scripts/seed_events.py` (utility, extensión)

**Analog:** el propio script — se modifica, no se sustituye.

```python
# seed_events.py:39-55 — hoy persons/zone_id SIEMPRE None (lineas 46-47):
rows.append((
    str(uuid.uuid4()), camera_id, rng.choice(_TYPES), ts.isoformat(sep=" "),
    rng.choice(_SEVERITIES),
    rng.randint(1, 500) if rng.random() < 0.7 else None,   # track_id
    None,   # person_id  <- Fase 31 necesita rellenar esto con --persons N
    None,   # zone_id    <- Fase 31 necesita rellenar esto con --zones N
    round(rng.uniform(0.4, 0.99), 2) if rng.random() < 0.8 else None,
    None, None, None, json.dumps({}),
))
```
Extender con `--persons N` (elige entre `N` ids con la misma proporción 35% medida en RESEARCH) y `--zones N` (proporción 60%, IDs tipo `"zona-1".."zona-N"`), preservando el `seed=42` determinista para reproducibilidad — el criterio 4 se midió exactamente así.

---

## Shared Patterns

### Router v2 con `configure()` inyectado desde el lifespan
**Source:** `backend/api/v2/context.py:29-38` (y replicado en `alerts.py:34-38`, `events.py` no lo necesita porque no toca estado vivo)
**Apply to:** `backend/api/v2/analytics.py`
```python
router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])
_camera_manager: Any = None

def configure(camera_manager: Any) -> None:
    global _camera_manager
    _camera_manager = camera_manager
```

### Rate limit compartido, nunca un decorador propio
**Source:** `backend/api/v2/deps.py:24-26`
**Apply to:** todos los endpoints de `analytics.py`
```python
from backend.api.v2.deps import V2_RATE_LIMIT, limiter

@router.get("/hourly")
@limiter.limit(V2_RATE_LIMIT)
async def get_hourly(request: Request, ...): ...
```

### `bindparams`, nunca f-strings, en SQL con entrada del cliente
**Source:** `backend/storage/repositories.py:126-129, 139-144` (`EventRepo._filter_conditions`)
**Apply to:** `AnalyticsRepo`, especialmente el parámetro `panel` del export y cualquier filtro de zona/persona
```python
text("... WHERE camera_id = :cam AND ts >= :prev_from ...").bindparams(cam=camera_id, ...)
```

### Migración idempotente con `_record_version(conn, N)` literal
**Source:** `backend/storage/migrations.py:91-99, 174-176`
**Apply to:** `_migrate_v3_to_v4`
```python
conn.execute(text("CREATE INDEX IF NOT EXISTS idx_events_analytics ON events (...)"))
_record_version(conn, 4)   # nunca SCHEMA_VERSION
```

### Anti-XSS: innerHTML vacío + textContent/dataset para datos del servidor
**Source:** `frontend/js/views/timeline-row.js:1-8, 112-122`
**Apply to:** `analytics-ranking.js` (nombres de persona y zona), `analytics-charts.js` (etiquetas de eje si se inyectan como HTML — no deberían, Chart.js las recibe como datos)
```javascript
row.innerHTML = `<span class="tl-desc ..."></span>`;   // vacio
row.querySelector('.tl-desc').textContent = describe(ev, personName);   // dato -> textContent
```

### `isSafeMediaUrl()` antes de cualquier sink de URL
**Source:** `frontend/js/views/timeline-row.js:16-18`
**Apply to:** `analytics-ranking.js` (avatar `<img>`), panel de heatmap (`<img>`), `analytics-export.js` (antes de `window.location.href`)
```javascript
export function isSafeMediaUrl(url) {
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//');
}
```

### Descarga server-generada, sin blob ni `<a download>` sintético
**Source:** `frontend/js/views/dashboard-events.js:113-116`
**Apply to:** `analytics-export.js`
```javascript
btn.addEventListener('click', () => { window.location.href = url; });
```

### `StreamingResponse` + `Content-Disposition` para export
**Source:** `backend/main.py:910-938` (`api_events_export`)
**Apply to:** `GET /api/v2/analytics/export` en `analytics.py`
```python
buf = io.StringIO()
writer = csv.DictWriter(buf, fieldnames=[...])
writer.writeheader(); writer.writerows(rows)
return StreamingResponse(
    iter([buf.getvalue()]), media_type="text/csv",
    headers={"Content-Disposition": f"attachment; filename={fname}"},
)
```
Diferencia obligatoria de esta fase (Q6 de RESEARCH): anteponer BOM UTF-8 (`buf.write('﻿')`) antes de `writeheader()` porque los nombres llevan acentos, a diferencia del export v1 (ASCII).

### Test de integración v2: fixture `sf` con patch del módulo del router
**Source:** `tests/test_events_api.py:32-44`
**Apply to:** `tests/test_analytics_api.py`
```python
with patch.object(analytics_module, "get_session_factory", return_value=factory):
    yield factory
```

### Test de presupuesto de rendimiento con `seed_events`
**Source:** `tests/test_repositories.py:574-593`
**Apply to:** los 4 tests de presupuesto `@100k` de `AnalyticsRepo`
```python
seed_events(db_file, n=100_000, days=30, camera_id="cam1")
start = time.perf_counter()
... await repo.<metodo>(...)
elapsed = time.perf_counter() - start
assert elapsed < 0.5
```

## No Analog Found

Ninguno. Los 21 ficheros de la fase tienen un analog directo o role-match en el código ya existente tras la Fase 30, incluidos los seis módulos frontend nuevos (D-14) — la vista de operaciones ya estableció el molde de orquestador/componente/anti-XSS que la vista de analítica reutiliza.

## Metadata

**Analog search scope:** `backend/api/v2/`, `backend/storage/`, `backend/pipeline/detection.py`, `backend/main.py`, `frontend/js/views/`, `frontend/js/components/`, `frontend/js/app.js`, `frontend/index.html`, `frontend/css/components.css`, `tests/`, `scripts/seed_events.py`
**Files scanned:** 21 analog candidates leídos completos o por rango dirigido (`events.py`, `alerts.py`, `context.py`, `deps.py`, `repositories.py` (secciones), `migrations.py`, `models.py`, `detection.py` (sección), `main.py` (secciones), `timeline.js`, `timeline-row.js`, `timeline-filters.js`, `dashboard-events.js`, `app.js`, `index.html` (cabecera), `components.css` (cabecera), `personGallery.js` (anti-patrón), `test_events_api.py`, `test_frontend_modules.py`, `test_repositories.py` (secciones), `test_migrations.py` (secciones), `seed_events.py`)
**Pattern extraction date:** 2026-08-22
