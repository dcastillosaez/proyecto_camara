# Phase 30: Event Timeline y centro de alertas - Pattern Map

**Mapped:** 2026-08-20
**Files analyzed:** 16 (10 modified, 6 new) + ~5 test files
**Analogs found:** 16 / 16

> Nota: 30-RESEARCH.md ya contiene código propuesto extenso, verificado por
> ejecución/lectura directa del repo (líneas de origen citadas). Este documento
> no repite ese código; en su lugar ancla cada fichero nuevo/modificado al
> **analog real más cercano ya existente en el repo** para que el planner copie
> imports, forma de `configure()`, manejo de errores y convenciones concretas
> — el research cubre el *qué*, este documento cubre el *de dónde se copia el
> molde*.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/api/v2/events.py` (NUEVO) | router | request-response (CRUD lectura + 2 mutaciones) | `backend/api/v2/recordings.py` | exact |
| `backend/events/rules.py` (MODIFICAR: split `evaluate`→`match`+`run_actions`) | service | event-driven | mismo fichero (self-analog, refactor in place) | exact |
| `backend/main.py` (MODIFICAR: `_event_pipeline`, borrar 4 `subscribe`, borrar endpoint viejo) | service/wiring | event-driven | mismo fichero, patrón `configure()` de `context.py`/`detection.py` (líneas 449-453) | exact |
| `backend/storage/models.py` (MODIFICAR: `+Index`) | model | — | mismo fichero (self-analog) | exact |
| `backend/storage/migrations.py` (MODIFICAR: `SCHEMA_VERSION`3, `_migrate_v2_to_v3`) | migration | batch | mismo fichero, patrón `_migrate_v1_to_v2` | exact |
| `backend/storage/repositories.py` (MODIFICAR: `EventRepo.query` multi-tipo/total/rule, `assign_person`, `track_scope`, `RecordingRepo.by_trigger_event_ids`) | model/repository | CRUD | mismo fichero (self-analog: `EventRepo`, `ConfigRepo`, `RecordingRepo` ya existen) | exact |
| `frontend/js/views/timeline.js` (NUEVO) | view/component | CRUD + streaming (WS) | `frontend/js/views/dashboard-events.js` (render de filas + filtros) | role-match |
| `frontend/js/components/alertCenter.js` (NUEVO) | component | CRUD + event-driven | `frontend/js/components/personGallery.js` (panel + modal/popover + fetch) | role-match |
| `frontend/js/websocket.js` (MODIFICAR: `case 'event'`) | provider (WS dispatch) | streaming | mismo fichero (self-analog, ya tiene `case 'tracks'` de la Fase 29) | exact |
| `frontend/js/views/dashboard.js` (MODIFICAR: mudar `loadActiveAlerts`, enlace "Ver todas") | view | request-response | mismo fichero (self-analog) | exact |
| `frontend/js/views/dashboard-events.js` (MODIFICAR: borrar `addEvent`/`applyFilters`/`bindEventFilters`, conservar chart) | view | CRUD (a retirar) | mismo fichero (self-analog) | exact |
| `frontend/css/components.css` (MODIFICAR: `+.timeline-row .timeline-sep .sev-dot .rule-chip .row-action .alert-group #alert-drawer`) | config/estilo | — | mismo fichero, bloques `.event-item`/`.filter-input`/`#clip-modal` ya existentes | exact |
| `frontend/index.html` (MODIFICAR: sustituir card eventos, botón campana, `<aside id="alert-drawer">`) | template | — | mismo fichero (self-analog: sección "EVENTS LIST" líneas 445-525, header líneas 18-44) | exact |
| `tests/test_event_bus.py` (MODIFICAR/AMPLIAR) | test | event-driven | mismo fichero (self-analog) | exact |
| `tests/test_alerts.py` (NUEVO) | test | CRUD | `tests/test_repositories.py` (fixture `db`, estilo `TEST_*`) | role-match |
| `tests/test_repositories.py` (AMPLIAR) | test | CRUD | mismo fichero (self-analog) | exact |
| `tests/test_migrations.py` (AMPLIAR) | test | batch | mismo fichero (self-analog) | exact |
| `tests/test_frontend_modules.py` (AMPLIAR: `LOCKED_JS` +2) | test | mecánico | mismo fichero (self-analog) | exact |

---

## Pattern Assignments

### `backend/api/v2/events.py` (router, request-response)

**Analog:** `backend/api/v2/recordings.py` (completo, 102 líneas) + `backend/api/v2/deps.py` (completo, 32 líneas)

**Imports + auth pattern** (`recordings.py:1-22`, ya citado en RESEARCH Pattern 1):
```python
"""API v2 — recordings: listing, detail, thumbnail, retry-upload (Fase 20).

Auth and rate limiting: the app applies auth globally (FastAPI(dependencies=[Depends(verify)])),
so routers included via app.include_router() inherit it automatically — no per-route
Depends(verify) needed here, matching the v1 endpoints' convention. Rate limiting
(SEC-16, Fase 22) uses the shared limiter/rate value from backend/api/v2/deps.py.
"""
from __future__ import annotations
import datetime, json, os
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from backend.api.v2.deps import V2_RATE_LIMIT, limiter, pagination_limit
from backend.database import get_session_factory
from backend.storage.repositories import EventRepo, RecordingRepo, UploadState

router = APIRouter(prefix="/api/v2/recordings", tags=["recordings"])
```
Para `events.py`: `router = APIRouter(prefix="/api/v2/events", tags=["events"])`, y **añadir** `configure(rule_engine)` como en `context.py` (ver abajo) para poblar el selector de reglas de `/api/v2/alerts` — el router de recordings no necesita `configure()` porque no toca estado vivo del pipeline, pero `context.py`/`detection.py` sí, y ese es el molde correcto aquí.

**Endpoint de lista con rate limit + paginación obligatorios** (`recordings.py:29-52`, patrón exacto a replicar en `list_events`):
```python
@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_recordings(
    request: Request,
    camera_id: str | None = Query(default=None),
    ...
    limit: int = pagination_limit(),
):
    """docstring de una línea describiendo los filtros."""
    ...
    return {"recordings": recordings}
```
`request: Request` es obligatorio en la firma (lo exige `slowapi`/`@limiter.limit`), y `limit = pagination_limit()` (cap 200) es obligatorio en todo endpoint de lista — lo comprueba `tests/test_security_regression.py:129,176` recorriendo `app.routes` automáticamente.

**Validación de enum con 400 explícito** (`recordings.py:42-46`, mismo patrón que ya usa el endpoint viejo en `main.py:846-850`):
```python
if upload_state is not None:
    try:
        UploadState(upload_state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid upload_state: {upload_state}")
```
Aplicar igual para `type`/`severity` en `list_events` (ya lo hace el endpoint que se está moviendo, `main.py:846-850` — copiar tal cual).

**404 sobre recurso individual** (`recordings.py:55-61`):
```python
@router.get("/{recording_id}")
@limiter.limit(V2_RATE_LIMIT)
async def get_recording(request: Request, recording_id: int):
    rec = await _recording_repo().get(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    ...
```
Mismo molde para `GET /api/v2/events/{id}` y `GET /api/v2/events/{id}/track-scope`.

**Helper de repo por función módulo** (`recordings.py:25-26`):
```python
def _recording_repo() -> RecordingRepo:
    return RecordingRepo(get_session_factory())
```
Replicar como `_event_repo()` y `_config_repo()` en `events.py`.

**Deps compartidas** (`deps.py`, fichero completo — no reinventar):
```python
from fastapi import Query
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
V2_RATE_LIMIT = "60/minute"

def pagination_limit(default: int = 50, le: int = 200):
    return Query(default=default, ge=1, le=le)
```

**Patrón `configure()` para inyectar estado vivo** (`context.py:30-36`, análogo exacto a lo que necesita `events.py` para `rule_engine`):
```python
_camera_manager: Any = None

def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager
```
Wiring en `lifespan` (`main.py:449-453`):
```python
from backend.api.v2 import context as context_v2_module
context_v2_module.configure(camera_manager)

from backend.api.v2 import detection as detection_v2_module
detection_v2_module.configure(camera_manager, event_engine)
```
`events.py` necesita `configure(rule_engine)` para que `/api/v2/alerts` pueda leer `rule_engine.rules` (nombres de regla para el selector/silenciado) — mismo molde, un `configure()` más.

**Registro en `main.py`** (`main.py:616-626`, añadir una línea más al bloque ya existente):
```python
from backend.api.v2.recordings import router as recordings_v2_router
app.include_router(recordings_v2_router)
...
from backend.api.v2.context import router as context_v2_router
app.include_router(context_v2_router)
```
**Cuidado (Pitfall 10 de RESEARCH):** borrar el endpoint viejo `@app.get("/api/v2/events")` (`main.py:829-861`) en el mismo commit que se registra `events_v2_router`, para evitar colisión de prefijo.

---

### `backend/events/rules.py` (service, event-driven) — split `evaluate()`

**Analog:** el propio fichero, `RuleEngine.evaluate` actual (`rules.py:169-193`, leído completo arriba)

Patrón de la clase ya existente a preservar sin tocar: `_matches()` (líneas 72-102, puro, sync, ya sin `await`), `_is_debounced`/`_purge_stale`/`_debounce_key` (líneas 139-167, bookkeeping en memoria). El único cambio es partir el cuerpo de `evaluate()`:

```python
# rules.py:169-193 actual — el bucle que hay que partir en dos:
async def evaluate(self, event: Event) -> list[str]:
    self._purge_stale(event.ts)
    fired: list[str] = []
    for rule in self._rules:
        if not rule.enabled: continue
        if not _matches(rule.when, event): continue
        if self._is_debounced(rule, event): continue
        self._last_fired[self._debounce_key(rule, event)] = event.ts
        fired.append(rule.name)
        for action in rule.actions:
            handler = self._registry.get(action.type)
            if handler is None:
                logger.error("Accion desconocida %r en regla %r", action.type, rule.name)
                continue
            try:
                await handler(event, action, rule.name)
            except Exception:
                logger.exception("Accion %r de regla %r fallo", action.type, rule.name)
    return fired
```
RESEARCH ya da el código exacto de `match()`/`run_actions()`/`evaluate()`-wrapper (§ Pattern 2, "Y el corte en RuleEngine") — usar ese, no reinventar. Punto clave a preservar del original: el logging de acción desconocida/fallida (`logger.error`/`logger.exception`) debe seguir viviendo en `run_actions()`, no en `match()`.

---

### `backend/main.py` (wiring, event-driven) — `_event_pipeline`

**Analog:** el propio fichero, suscriptores actuales (`main.py:287-306`, leído completo arriba) + `_broadcast_v1_compat`/`_broadcast_v2` (`main.py:91-123`)

```python
# main.py:287-306 actual — los 4 subscribe() a colapsar en 1
async def _persist_event(event: Event) -> None:
    try:
        await event_repo.insert(event)
    except Exception:
        logger.exception("Failed to persist event %s", event.id)

async def _apply_rules(event: Event) -> None:
    try:
        await rule_engine.evaluate(event)
    except Exception:
        logger.exception("RuleEngine evaluation failed for event %s", event.id)

event_bus.subscribe("persistence", _persist_event)
event_bus.subscribe("websocket_v1_compat", _broadcast_v1_compat)
event_bus.subscribe("websocket_v2", _broadcast_v2)
event_bus.subscribe("rules", _apply_rules)
```
RESEARCH § Pattern 2 (código completo de `_event_pipeline`) es la implementación recomendada — nótese que reutiliza `_broadcast_v2` (`main.py:91-103`) y `_broadcast_v1_compat` (`main.py:106-123`) **sin modificarlos**, solo cambia quién los llama y en qué orden. El único añadido nuevo es `_broadcast_event` (mensaje `type:"event"` por `/ws`), que debe seguir el mismo molde try/except-por-paso que `_broadcast_v2` (captura excepciones de socket muerto, no de lógica de negocio).

**Try/except por paso, patrón ya establecido en el fichero** — cada suscriptor de hoy envuelve su única operación en su propio `try/except Exception: logger.exception(...)` para que un fallo no tumbe el bus; `_event_pipeline` debe conservar esa granularidad por paso (no un único `try` envolviendo los 3 pasos), exactamente como en el snippet de RESEARCH § Pattern 2.

---

### `backend/storage/models.py` (model) — índice compuesto

**Analog:** el propio fichero — los 4 `Index(...)` ya existentes en `Event.__table_args__` (citados en CONTEXT.md D-11: `idx_events_ts`, `idx_events_type_ts`, `idx_events_cam_ts`, `idx_events_person`). Añadir uno más con la misma forma:
```python
Index("idx_events_ts_id", ts.desc(), id.desc()),
```
(código exacto ya en RESEARCH § "Índice + migración").

---

### `backend/storage/migrations.py` (migration, batch)

**Analog:** el propio fichero, `_migrate_v1_to_v2` completo (líneas 91-158, leído arriba) y `MIGRATIONS`/`run_migrations` (líneas 160-180).

Patrón de migración idempotente a replicar para `_migrate_v2_to_v3`:
```python
def _migrate_v1_to_v2(conn: Connection) -> None:
    ...
    # 6. Record schema version.
    conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
    conn.execute(
        text("INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', :v, :now)"),
        {"v": json.dumps(SCHEMA_VERSION), "now": datetime.datetime.now().isoformat(sep=" ")},
    )

MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (2, "esquema v2 completo", _migrate_v1_to_v2),
]
```
`run_migrations()` (líneas 165-180) itera `MIGRATIONS` filtrando por `current >= target_version` — **no tocar esta función**, solo añadir una tupla a la lista y subir `SCHEMA_VERSION = 3`. Usar `CREATE INDEX IF NOT EXISTS` (idempotente por sintaxis SQL, no solo por el guard de versión) — código exacto ya en RESEARCH § "Índice + migración" (`_migrate_v2_to_v3`).

**Backup automático ya cubierto:** `_backup_db(engine)` (líneas 56-67) se invoca desde `run_migrations` antes de cualquier migración pendiente — no hace falta backup propio en `_migrate_v2_to_v3`.

---

### `backend/storage/repositories.py` (repository, CRUD)

**Analog:** el propio fichero — `EventRepo` completo (líneas 42-141+, leído arriba), `ConfigRepo` completo (líneas 621-645, leído arriba), `RecordingRepo` (mencionado en RESEARCH, no releído — ya se usa desde `recordings.py`).

**Cursor ya resuelto, no reinventar** (`repositories.py:31-39`):
```python
def _encode_cursor(ts: datetime.datetime, id_: str) -> str:
    raw = f"{ts.isoformat()}|{id_}".encode()
    return base64.urlsafe_b64encode(raw).decode()

def _decode_cursor(cursor: str) -> tuple[datetime.datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_ = raw.split("|", 1)
    return datetime.datetime.fromisoformat(ts_str), id_
```

**`EventRepo.query` actual, base a extender** (líneas 92-141, leído completo arriba) — RESEARCH § "Extender `EventRepo.query`" ya da el código de la extensión multi-tipo/`total`/`rule` con el prefijo `+` unario medido; usar ese, no re-derivarlo. Patrón de construcción de query a preservar: `conditions: list` + `and_(*conditions)` solo si `conditions` no está vacío (línea 132-133), nunca WHERE incondicional.

**`ConfigRepo` para el silenciado (D-17/Hallazgo 8)** — leer-modificar-escribir ya resuelto (líneas 625-639):
```python
async def get(self, key: str, default: Any = None) -> Any:
    async with self._sf() as session:
        row = await session.get(models.AppConfig, key)
        return row.value if row is not None else default

async def set(self, key: str, value: Any) -> None:
    async with self._sf() as session:
        async with session.begin():
            row = await session.get(models.AppConfig, key)
            now = datetime.datetime.now()
            if row is None:
                session.add(models.AppConfig(key=key, value=value, updated_at=now))
            else:
                row.value = value
                row.updated_at = now
```
No añadir un `AlertRepo` nuevo: `alerts.muted_rules` vive en `app_config` vía este `ConfigRepo` ya existente, tal como decide RESEARCH Hallazgo 8. Añadir el `asyncio.Lock` de módulo mencionado en RESEARCH solo alrededor de `POST /api/v2/alerts/mute` (en `events.py`, no en `ConfigRepo`, que es agnóstico de negocio).

**Nuevo método `assign_person` / `track_scope`** — seguir la forma de `insert`/`get` ya existentes (session + `async with`), y usar el algoritmo determinista de RESEARCH Hallazgo 6 (`SELECT` acotado por `camera_id + track_id + ventana de ±6h`, recorte en Python al bloque contiguo, `UPDATE ... WHERE id IN (:ids)` — nunca `WHERE track_id=?` a secas, Pitfall 3).

**Nuevo método `RecordingRepo.by_trigger_event_ids`** — mismo patrón `WHERE ... IN (:ids)` con `bindparam(expanding=True)` que ya usa el filtro `rule` de `EventRepo.query` (RESEARCH § Pattern 3).

---

### `frontend/js/views/timeline.js` (NUEVO — view/component, CRUD + streaming)

**Analog primario (render de filas + filtros a sustituir):** `frontend/js/views/dashboard-events.js` (fichero completo, 205 líneas, leído arriba)
**Analog secundario (fetch + paginación + estado vacío):** `frontend/js/components/eventCard.js::loadRecordings` (líneas 74-90)
**Analog de fetch con manejo de error:** `frontend/js/api.js::apiFetch` (fichero completo)

**Patrón de fetch ya estándar en el proyecto** (`api.js`, usar siempre, no `fetch` crudo con `.catch(() => {})` como hace código legado):
```javascript
export async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.status === 204 ? null : res.json();
}
```

**Patrón de construcción de fila sin XSS** (`dashboard-events.js:110-144`, `addEvent`, análogo directo de `timelineRow`; el snippet completo con el `.tl-*` de la Fase 30 ya está en RESEARCH § "Fila de la timeline sin XSS", que es la versión actualizada de este mismo patrón):
```javascript
// dashboard-events.js:110-144 — patrón: estructura estática por innerHTML,
// contenido dinámico por textContent tras montar. NUNCA interpolar
// direction/personName/total (llegan del backend) dentro del template string.
export function addEvent(ts, dir, total, personName, isIntrusion = false) {
  const list  = document.getElementById('events-list');
  ...
  item.innerHTML = `
    <svg ...>${arrow}</svg>
    <span class="ev-dir ${color} font-semibold uppercase text-xs w-6"></span>
    <span class="ev-ts text-slate-400 flex-1 mono text-xs"></span>
    ${nameTag}
    ${intrusionTag}
    <span class="ev-total text-slate-600 text-xs tabular-nums"></span>
  `;
  item.querySelector('.ev-dir').textContent = dir;
  item.querySelector('.ev-ts').textContent = ts;
  item.querySelector('.ev-total').textContent = `#${total}`;
  if (personName) item.querySelector('.ev-name').textContent = personName;
  list.prepend(item);
  while (list.children.length > 50) list.lastChild.remove();
  ...
}
```
Nota: `arrow`/`color` son constantes internas fijas (no datos del usuario) — solo `dir`, `ts`, `personName`, `total` cruzan a `textContent`. `nameTag`/`intrusionTag` en el `innerHTML` son *estructura condicional* (presencia de un `<span>` vacío), no contenido — coherente con Pitfall 7 de RESEARCH.

**Patrón de filtros → querystring → refetch → repintar lista completa** (`dashboard-events.js:147-185`, `_eventsFilterParams`/`applyFilters` — el molde de "reiniciar cursor y vaciar antes de pedir" que pide D-09/UI-SPEC es la evolución de este mismo patrón):
```javascript
function _eventsFilterParams() {
  const p = new URLSearchParams();
  ...
  p.set('limit', '200');
  if (dir)  p.set('direction', dir);
  ...
  return p;
}

export async function applyFilters() {
  const params = _eventsFilterParams();
  try {
    const res = await fetch('/api/events?' + params.toString());
    if (!res.ok) return;
    const data = await res.json();
    const list = document.getElementById('events-list');
    list.querySelectorAll('.event-item').forEach(el => el.remove());
    ...
  } catch {}
}
```
Para `timeline.js`: mismo esqueleto (parámetros → `apiFetch('/api/v2/events?' + params)` → limpiar contenedor → repintar), pero **cambiar el `catch {}` silencioso por el error state explícito** que pide UI-SPEC ("No se pudieron cargar los eventos." + "Reintentar carga") — el patrón legado de tragar errores no se copia, solo la forma de construir la query.

**Centinela `IntersectionObserver`:** código exacto ya en RESEARCH § "Centinela de scroll infinito" — no hay analog en el repo (primera vez que se usa `IntersectionObserver`), usar el snippet de RESEARCH tal cual.

**Restricción de tamaño de fichero:** `tests/test_frontend_modules.py::TEST_line_limit` impone 300 líneas. `dashboard-events.js` está en 205 líneas hoy y se queda solo con el chart tras retirar `addEvent`/`applyFilters`/`bindEventFilters`/`_eventsFilterParams` (~205-95=110 líneas). `timeline.js` es fichero nuevo, presupuesto propio de 300 líneas — si la virtualización + filtros + WS listener no caben, dividir en un módulo auxiliar (p. ej. `timeline-virtualize.js`), no exceder el tope.

---

### `frontend/js/components/alertCenter.js` (NUEVO — component, CRUD + event-driven)

**Analog primario (panel con fetch periódico + modal/popover + acciones):** `frontend/js/components/personGallery.js` (fichero completo, 173 líneas, leído arriba)
**Analog de agrupación/orden por severidad a migrar:** `frontend/js/views/dashboard.js::loadActiveAlerts` (líneas 263-289, leído arriba) — **se muda aquí tal cual**, según RESEARCH § "Recommended Project Structure" (libera ~28 líneas de `dashboard.js`, que está a 290/300).

```javascript
// dashboard.js:263-289 — patrón completo a mudar y adaptar a /api/v2/alerts:
const SEVERITY_RANK = { critical: 2, warning: 1, info: 0 };
export async function loadActiveAlerts() {
  const panel = document.getElementById('alerts-active-list');
  const empty = document.getElementById('alerts-active-empty');
  const checkedAt = document.getElementById('alerts-active-checked-at');
  if (!panel || !empty) return;
  try {
    const res = await fetch('/api/v2/events?limit=10');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const alerts = (data.events || [])
      .filter(e => e.severity && e.severity !== 'info')
      .sort((a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0))
      .slice(0, 3);
    panel.innerHTML = '';
    empty.style.display = alerts.length ? 'none' : '';
    alerts.forEach(ev => { ... });
  } catch {
    empty.style.display = '';
  }
  if (checkedAt) checkedAt.textContent = new Date().toLocaleTimeString('es-ES', { hour12: false });
}
```
Cambio funcional al mudarlo (por D-16/OPS-11): pasar de filtrar/ordenar un array de eventos en el navegador a consumir `GET /api/v2/alerts` (agrupado por regla, ya resuelto en servidor) — el *molde* de try/catch + `empty.style.display` + timestamp de última comprobación se conserva íntegro, solo cambia el endpoint y el shape de los datos.

**Patrón de modal con overlay + cierre por click-fuera + Escape** (`personGallery.js:109-118`, aplicable al cajón lateral `#alert-drawer` aunque sea slide-over y no modal centrado — el mecanismo de apertura/cierre es el mismo):
```javascript
document.getElementById('btn-enroll').addEventListener('click', async () => { ...; enrollModal.classList.remove('hidden'); });
document.getElementById('enroll-close').addEventListener('click', () => { enrollModal.classList.add('hidden'); });
enrollModal.addEventListener('click', e => { if (e.target === enrollModal) enrollModal.classList.add('hidden'); });
```
El manejador global de `Escape` para modales ya existe en `eventCard.js:182-188` — el cajón de alertas debe sumarse a ese mismo patrón de cierre (o replicarlo si el foco atrapado del cajón exige lógica propia de `role="dialog"`/`aria-modal`, que `personGallery.js` no tiene porque sus modales no exigen focus trap completo).

**Patrón de chip clicable / selección** (`personGallery.js:92-101`, aplicable al popover de duración de silenciado — 3 opciones, una se marca activa):
```javascript
named.forEach(p => {
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.textContent = `${p.name} (${p.sample_count ?? 1})`;
  chip.className = 'text-xs px-2.5 py-1 rounded-lg bg-slate-700 hover:bg-blue-600 ...';
  chip.addEventListener('click', () => { ...; chip.classList.add('bg-blue-600', 'text-white'); });
  knownList.appendChild(chip);
});
```

**Fetch periódico ya establecido** (`dashboard.js:290`, patrón `setInterval` a nivel de módulo):
```javascript
setInterval(loadActiveAlerts, 5000);
```
`alertCenter.js` hereda este `setInterval` al mudar la función (ajustar frecuencia si compite con el push WS del cajón, pero el molde de "poll de respaldo + push en vivo" es el mismo que ya usa el resto del dashboard).

---

### `frontend/js/websocket.js` (provider, streaming) — `case 'event'`

**Analog:** el propio fichero (completo, 86 líneas, leído arriba) — dispatch por `if/else if` sobre `msg.type` ya establecido:
```javascript
_ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'init') {
    ...
  } else if (msg.type === 'detection') {
    const ts = new Date(msg.timestamp).toLocaleTimeString('es-ES', { hour12: false });
    addEvent(ts, msg.direction, msg.total_today, msg.person_name ?? null, msg.is_intrusion ?? false);
    ...
    showToast(`Cruce ${msg.direction.toUpperCase()} detectado${who}${intrusionSuffix}`, msg.is_intrusion ? 'error' : 'success', 2000);
  } else if (msg.type === 'recording_started') {
    ...
  } else if (msg.type === 'tracks') {
    drawTracks(msg.tracks);
    renderPersonList(msg.tracks);
  }
};
```
Añadir `else if (msg.type === 'event') { timeline.onLiveEvent(msg.event, msg.media); }` como un `case` más, mismo molde exacto que `tracks` (Fase 29). **Pitfall 6 de RESEARCH:** quitar la llamada a `addEvent(...)` del bloque `'detection'` (conservando `updateStat`/`bumpHourBar`/`showToast`) para no pintar el mismo `LINE_CROSSED` dos veces.

**Reconexión — no tocar, ya cumple OPS-06** (líneas 76-84):
```javascript
_ws.onclose = () => {
  _wsCloseCount += 1;
  setWsConnected(false, _wsCloseCount);
  setWsStatus(false);
  setTimeout(connectWS, _wsRetry);
  _wsRetry = Math.min(_wsRetry * 2, 30000);
};
```
La barra ámbar "Sin tiempo real…" del UI-SPEC se ata a `setWsConnected(false, ...)`, ya invocado aquí — no crear un segundo mecanismo de detección de desconexión.

---

### `frontend/index.html` (template)

**Analog:** el propio fichero — sección "EVENTS LIST" a sustituir (líneas 445-525, leída completa arriba) y header (líneas 18-44, leído completo arriba).

**Estructura de card a preservar** (contenedor `.card`, cabecera con icono+título+badge+acciones, cuerpo con scroll interno, estado vacío):
```html
<div class="card bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col" style="min-height:0">
  <div class="flex items-center justify-between mb-3">
    <div class="flex items-center gap-2"> ...icono + <h2 class="text-sm font-semibold text-slate-200">...</h2></div>
    <div class="flex items-center gap-2"> ...badge + botones de acción de cabecera... </div>
  </div>
  ...
  <div id="events-list" class="overflow-y-auto flex flex-col gap-1.5" style="max-height:200px" aria-label="..." aria-live="polite">
    <div id="events-empty" class="flex flex-col items-center justify-center py-8 text-center"> ...icono + texto... </div>
  </div>
</div>
```
La timeline nueva reemplaza el contenido interno de este card (nuevo `id`, `max-height` según UI-SPEC `320px`/`240px`) conservando el mismo patrón de cabecera+badge+scroll interno+empty-state — UI-SPEC ya fija el contrato exacto de la fila (barra severidad + hora + miniatura + descripción + chips + 4 acciones de 32×32).

**Botón de cabecera 44×44 (campana), analog exacto:** no hay botón de icono suelto en el header hoy (los controles de header son badges de estado), pero `.ptz-btn` (`components.css:1-15`) ya define la caja 44×44 con estados hover/active/focus-visible — es la clase a reutilizar para `#btn-alert-center`:
```css
.ptz-btn {
  width: 44px; height: 44px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 10px; background: #1e293b; border: 1px solid #334155; color: #94a3b8;
  cursor: pointer; transition: background 120ms ease, color 120ms ease, border-color 120ms ease, transform 80ms ease;
}
.ptz-btn:hover  { background: #2d3f52; color: #e2e8f0; border-color: #475569; }
.ptz-btn:active { background: #2563eb; color: #fff; border-color: #3b82f6; transform: scale(0.92); }
.ptz-btn:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
```

**Modal/overlay a imitar para `#alert-drawer`** (`components.css:75-81`, `#clip-modal`):
```css
#clip-modal {
  display: none; position: fixed; inset: 0; z-index: 60;
  background: rgba(2,6,23,0.85); backdrop-filter: blur(6px);
  align-items: center; justify-content: center;
}
#clip-modal.open { display: flex; }
```
`#alert-drawer` usa el mismo mecanismo `display:none`→`.open`/`.class` con `backdrop-filter: blur(6px)`, pero como slide-over de 380px anclado a la derecha (no centrado) y `z-index: 50` (bajo `#clip-modal` que sigue en `z-index: 60`, para que un "Ver clip" desde el cajón pueda abrirse por encima).

---

## Shared Patterns

### Auth / Rate limit (todos los endpoints nuevos de `events.py`)
**Source:** `backend/api/v2/deps.py` (completo) + `backend/api/v2/recordings.py:29-31` (aplicación real)
**Apply to:** `list_events`, `get_event`, `get_track_scope`, `assign_person`, `list_alerts`, `mute_alert`
```python
@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_events(request: Request, ..., limit: int = pagination_limit()):
```
Sin `Depends(verify)` por ruta — la app lo aplica globalmente (`FastAPI(dependencies=[Depends(verify)])`).

### Error handling backend
**Source:** `backend/api/v2/recordings.py:42-46, 60-61, 77-81, 95-99` (4 variantes ya en el mismo fichero)
**Apply to:** todo endpoint nuevo de `events.py`
- Enum inválido → `HTTPException(400, detail=f"invalid X: {x}")`
- Recurso no encontrado → `HTTPException(404, detail="X not found")`
- Precondición de estado → `HTTPException(409, detail="...")` (ver `retry_upload`, aplicable si `assign_person` se llama sobre un evento sin `track_id`)

### Error handling frontend
**Source:** `frontend/js/api.js::apiFetch` (completo) — normaliza cualquier error de red/HTTP a `Error(detail)`
**Apply to:** `timeline.js`, `alertCenter.js` — usarlo en vez del `try { fetch(...) } catch {}` silencioso de código legado (`dashboard-events.js:163-185`, `personGallery.js:5-41`); UI-SPEC exige estados de error visibles ("No se pudieron cargar los eventos." + "Reintentar carga"), el patrón legado de tragar el error no cumple el contrato de esta fase.

### Toast
**Source:** `frontend/js/views/dashboard.js:19-28` (`showToast`, completo) + `components.css:44-49` (`.toast`)
**Apply to:** confirmación de "Descartar" (con deshacer), éxito/error de "Marcar como persona", error de "Silenciar"
```javascript
export function showToast(msg, type = 'info', ms = 3500) {
  const wrap = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${TOAST_STYLES[type] ?? TOAST_STYLES.info} border rounded-xl px-4 py-2.5 text-xs shadow-xl pointer-events-auto max-w-xs`;
  el.setAttribute('role', 'alert');
  el.textContent = msg;
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, ms);
}
```
`TOAST_STYLES` ya define `info`/`success`/`error`/`warn` — el toast verde de "Marcar como persona" es `success`, los de error de silenciar/enrolar son `error`. El toast de "Descartar — Deshacer" (D-07) necesita un botón dentro del toast, que no existe hoy en `showToast` — extenderlo con un parámetro opcional de acción, o montar un toast custom en `alertCenter.js`/`timeline.js` reutilizando solo `.toast`/`TOAST_STYLES` (decisión de implementación, no de patrón).

### XSS — nunca `innerHTML` con datos del backend
**Source:** `frontend/js/components/eventCard.js:16-18` (comentario) + `frontend/js/views/dashboard-events.js:121-124` (comentario + aplicación)
**Apply to:** `timeline.js` (nombre de persona, nombre de regla en el chip), `alertCenter.js` (mismos campos en las tarjetas de grupo)
```javascript
// r.filename/r.gdrive_id llegan del backend — se asignan via propiedades
// del DOM (dataset/href/textContent), nunca interpolados en innerHTML,
// para que un filename con marcado no se ejecute (CodeQL js/xss).
```
Regla mecánica: estructura estática (elementos vacíos) por `innerHTML`, todo dato variable del backend por `.textContent`/`.dataset` después de montar.

### Bus/pipeline de eventos — un único suscriptor ordenado
**Source:** `backend/main.py:287-306` (4 suscriptores actuales, a colapsar) + RESEARCH § Pattern 2 (`_event_pipeline` completo)
**Apply to:** `backend/main.py` únicamente — es la pieza central de la fase (resuelve D-14/Hallazgo 3), cualquier otro suscriptor futuro del `event_bus` debe evaluarse contra este mismo riesgo de orden indeterminado antes de añadirse.

### Migraciones idempotentes con backup automático
**Source:** `backend/storage/migrations.py:56-67, 165-180` (`_backup_db`, `run_migrations`, completos)
**Apply to:** `_migrate_v2_to_v3` — no reimplementar backup ni el guard de versión, solo añadir la función de migración y una tupla a `MIGRATIONS`.

---

## No Analog Found

Ninguno. Los 16 ficheros nuevos/modificados tienen analog directo (mismo fichero en refactor, o fichero hermano del mismo rol) porque la fase extiende infraestructura ya existente (`EventRepo`, `ConfigRepo`, routers v2, `event_bus`, `websocket.js`) en vez de introducir una capa nueva — coherente con la recomendación de RESEARCH ("casi no tiene librería que elegir; tiene código propio que ya existe y hay que encontrar antes de reescribirlo").

Único hueco genuino sin precedente en el repo: **`IntersectionObserver`** (scroll infinito) y la **virtualización de 400 filas con compensación de `scrollTop`** — no hay analog porque ninguna lista del proyecto ha necesitado paginar/recortar el DOM hasta ahora (`#events-list` con 50 elementos y `#recordings-list` con 20 no lo requieren). RESEARCH ya provee el snippet del centinela; el algoritmo de recorte+compensación de scroll debe diseñarse ex novo en el plan (UI-SPEC ya fija el contrato: ventana 400, recorte por arriba, plan B a 1000 filas sin recortar si el salto es perceptible).

## Metadata

**Analog search scope:** `backend/api/v2/`, `backend/events/`, `backend/storage/`, `backend/main.py`, `frontend/js/views/`, `frontend/js/components/`, `frontend/js/*.js`, `frontend/css/components.css`, `frontend/index.html`, `tests/test_repositories.py`, `tests/test_frontend_modules.py`
**Files read in full:** `backend/api/v2/recordings.py`, `backend/api/v2/deps.py`, `backend/api/v2/context.py`, `backend/events/rules.py`, `backend/storage/migrations.py`, `backend/storage/repositories.py` (líneas 1-150, 620-645), `backend/main.py` (líneas 79-208, 260-310, 424-474, 610-637, 825-862), `frontend/js/components/eventCard.js`, `frontend/js/components/personGallery.js`, `frontend/js/websocket.js`, `frontend/js/views/dashboard-events.js`, `frontend/js/views/dashboard.js` (líneas 1-45, 260-289), `frontend/js/api.js`, `frontend/css/components.css`, `frontend/index.html` (líneas 1-50, 440-529)
**Pattern extraction date:** 2026-08-20
