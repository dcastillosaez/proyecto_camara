# Phase 33: Editores visuales de zonas, líneas y reglas - Pattern Map

**Mapped:** 2026-08-24
**Files analyzed:** 15 (10 backend, 5 frontend/tests grouped)
**Analogs found:** 15 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/storage/repositories.py` (add `LineRepo`) | model/repository | CRUD | `ZoneRepo` / `RuleRepo` (same file, lines 704-793) | exact — same file, sibling class |
| `backend/api/v2/zones.py` (NEW) | route/controller | CRUD + hot-reload trigger | `backend/api/v2/events.py` (router shape) + `backend/main.py:1097-1150` (`api_upsert_zone`, validation) | role-match |
| `backend/api/v2/lines.py` (NEW) | route/controller | CRUD + hot-reload trigger | `backend/api/v2/zones.py` (once written, same phase) / `main.py:1097-1150` | role-match |
| `backend/api/v2/rules.py` (NEW) | route/controller | CRUD + request-response (test) | `backend/api/v2/config.py` (validation batch, 422 shape) + `main.py:998-1006` (old GET to replace) | role-match |
| `backend/pipeline/detection.py` (add `set_lines`/`_rebuild_line_states`) | service/worker | event-driven (dirty-flag hot-reload) | `set_zones`/`_rebuild_zone_states` in the same file (lines 135-139, 483-544) | exact — same file, sibling method |
| `backend/pipeline/manager.py` (add `CameraPipeline.set_lines`) | service (facade) | passthrough/CRUD | `CameraPipeline.set_zones` (lines 322-327, same file) | exact — same file, sibling method |
| `backend/tracker.py` (refactor `PersonTracker` to N lines) | model/service | event-driven | `_zone_states` list pattern in `backend/pipeline/detection.py:520-544` (list-of-dict rebuild), and `PersonTracker.reconfigure_line`/`get_counts` (this same file, lines 120-152) | role-match — cross-file pattern transplant |
| `backend/events/rules.py` (expose public match for test mode) | service (pure function) | transform | `_matches`/`RuleEngine.match` (this same file, lines 72-102, 169-188) | exact — same file, new public wrapper |
| `backend/main.py` (wire new routers, retire old `/api/v2/rules` GET) | config/bootstrap | — | `app.include_router(events_router)` pattern already used for `/api/v2/events`, `/api/v2/config` | exact |
| `tests/test_zones_api.py`, `tests/test_lines_api.py`, `tests/test_rules_api.py` (NEW) | test | integration | `tests/test_detection_config_api.py`, `tests/test_config_api.py` (existing API test style, not read in full — see below) | role-match |
| `frontend/js/components/zoneEditor.js` (rewrite: canvas draw + v2 CRUD) | component | event-driven (canvas) + CRUD | itself, legacy version (this repo, form+`/api/zones` v1) for CRUD list/save/delete UX; `frontend/js/components/videoCanvas.js` for canvas math | exact (CRUD UX) + role-match (canvas) |
| `frontend/js/components/lineEditor.js` (NEW, or folded into `zoneEditor.js`) | component | event-driven (canvas) + CRUD | `videoCanvas.js` (canvas/letterbox math) + `zoneEditor.js` (CRUD list/save/delete UX) | role-match |
| `frontend/js/views/rules-editor.js` (NEW) | view/orchestrator | CRUD forms + request-response (`/test`) | `frontend/js/views/settings-field.js` (field renderers by type) + `settings-save.js` (diff/422 mapping) | role-match |
| `frontend/js/views/camera.js` (mount editor panel) | view/orchestrator | — | itself (existing `initCamera`/`activateCameraFeed` pattern, this file) | exact — same file |
| `frontend/css/components.css` (add `.modal`, `.zone-editor`, `.vertex-handle`) | style | — | none (confirmed absent by RESEARCH.md) — see "No Analog Found" | no analog |

## Pattern Assignments

### `backend/storage/repositories.py` — add `LineRepo`

**Analog:** `ZoneRepo` in the same file (lines 704-751). Copy the class shape verbatim, swap `models.Zone` for `models.Line` and the field set (`start_x_frac`, `start_y_frac`, `end_x_frac`, `end_y_frac` instead of `polygon`/`kind`/`schedule`).

```python
# Fuente: backend/storage/repositories.py:704-751 (código real)
class ZoneRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def list(self, camera_id: str | None = None) -> list[dict[str, Any]]:
        q = select(models.Zone)
        if camera_id is not None:
            q = q.where(models.Zone.camera_id == camera_id)
        async with self._sf() as session:
            result = await session.execute(q)
            return [self._to_dict(z) for z in result.scalars().all()]

    async def upsert(
        self, zone_id: str, camera_id: str, name: str, polygon: list, kind: str | None = None,
        schedule: dict | None = None, enabled: bool = True,
    ) -> None:
        async with self._sf() as session:
            async with session.begin():
                existing = await session.get(models.Zone, zone_id)
                if existing:
                    existing.camera_id = camera_id
                    existing.name = name
                    existing.polygon = polygon
                    existing.kind = kind
                    existing.schedule = schedule
                    existing.enabled = enabled
                else:
                    session.add(models.Zone(
                        id=zone_id, camera_id=camera_id, name=name, polygon=polygon,
                        kind=kind, schedule=schedule, enabled=enabled,
                    ))

    async def delete(self, zone_id: str) -> bool:
        async with self._sf() as session:
            async with session.begin():
                z = await session.get(models.Zone, zone_id)
                if z:
                    await session.delete(z)
                    return True
        return False
```

`models.Line` already exists (`backend/storage/models.py:182-192`) with `id, camera_id, name, start_x_frac, start_y_frac, end_x_frac, end_y_frac, enabled` — no migration needed, only the repo class is missing. `RuleRepo` (same file, lines 754-793) is the sibling to copy for `upsert`-with-`updated_at` semantics if lines ever need a timestamp (they currently don't have one in the model — don't invent one).

---

### `backend/api/v2/zones.py` / `backend/api/v2/lines.py` (NEW routers)

**Analog 1 — router shape and auth/rate-limit inheritance:** `backend/api/v2/events.py` (full file read, 165 lines).

```python
# Fuente: backend/api/v2/events.py:1-39 (código real)
"""API v2 — eventos tipados...
Auth and rate limiting: the app applies auth globally (FastAPI(dependencies=[Depends(verify)])),
so routers included via app.include_router() inherit it automatically — no per-route
Depends(verify) needed here. Rate limiting (SEC-16, Fase 22) uses the shared limiter/rate
value from backend/api/v2/deps.py.
"""
from fastapi import APIRouter, Body, HTTPException, Query, Request
from backend.api.v2.deps import V2_RATE_LIMIT, limiter, pagination_limit, snapshot_url
from backend.database import get_session_factory
from backend.storage.repositories import EventRepo, RecordingRepo

router = APIRouter(prefix="/api/v2/events", tags=["events"])

def _event_repo() -> EventRepo:
    return EventRepo(get_session_factory())

@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_events(request: Request, ...) -> dict[str, Any]:
    ...
```

Use the same `prefix="/api/v2/zones"` / `"/api/v2/lines"` shape, a `_zone_repo()`/`_line_repo()` factory function exactly like `_event_repo()`, and `@limiter.limit(V2_RATE_LIMIT)` on every route (matches the threat-model row in RESEARCH.md "Rate-limit en `/rules/{id}/test`").

**Analog 2 — validation + hot-reload wiring (the part `events.py` doesn't show):** `backend/main.py:1103-1142` (`api_upsert_zone`/`api_delete_zone`, legacy v1). This is the ONLY existing example in the repo of "validate polygon, persist, then push to the live pipeline" — copy its validation checks even though the new router targets `ZoneRepo`/v2 columns, not `upsert_zone()`/v1.

```python
# Fuente: backend/main.py:1107-1142 (código real, v1 — usar como referencia de validación,
# no de persistencia: la persistencia del router nuevo va contra ZoneRepo/v2)
@app.post("/api/zones")
async def api_upsert_zone(request: Request):
    """Create or update a zone. Body: {id, name, polygon_json, enabled?}."""
    body = await request.json()
    zone_id = str(body.get("id", "")).strip()
    name = str(body.get("name", "")).strip()
    polygon_json = body.get("polygon_json", "[]")
    enabled = bool(body.get("enabled", True))
    if not zone_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
    if len(zone_id) > 50 or len(name) > 100:
        raise HTTPException(status_code=400, detail="id/name too long")
    try:
        pts = _json.loads(polygon_json) if isinstance(polygon_json, str) else polygon_json
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="polygon_json must be a JSON array with ≥3 points")
    await upsert_zone(zone_id, name, _json.dumps(pts), enabled)
    zones = await get_zones()
    if rtsp_stream is not None:
        rtsp_stream.set_zones(zones)          # <-- hot-reload push, copy this call shape
    return {"zones": zones}
```

For the new v2 router, the hot-reload push becomes `for pipeline in camera_manager.all(): pipeline.set_zones(await zone_repo.list(camera_id=pipeline.id))` (or `set_lines`) — see the `CameraManager`/`CameraPipeline` pattern below. Follow `backend/api/v2/config.py`'s `configure(camera_manager, ...)` module-level wiring function (lines 43-53) to receive the live `CameraManager` instance from `main.py`'s lifespan instead of importing a global.

**Validation for points/coordinates (V5 ASVS row in RESEARCH.md):** reuse the exact `len(pts) < 3` / range check above; add a `0.0 <= x <= 1.0` per-point check since the legacy endpoint didn't need it (v1 never validated fraction range, v2 must, per RESEARCH.md Anti-patterns).

---

### `backend/api/v2/rules.py` (NEW router + `POST /rules/{id}/test`)

**Analog 1 — batch validation with structured 422 errors:** `backend/api/v2/config.py` (PUT handler, not fully read in this pass but referenced by RESEARCH.md and consumed by `settings-save.js` — see below). The 422 envelope shape consumed by the frontend is:

```javascript
// Fuente: frontend/js/views/settings-save.js:85-99 (código real) — contrato que el
// router de reglas debe replicar si el formulario de reglas reutiliza el mismo
// manejo de error 422 en el frontend
if (res.status === 422) {
  const body = await res.json().catch(() => ({}));
  const errors = body.detail?.errors ?? body.errors ?? [];
  for (const err of errors) {
    const row = panel?.querySelector(`.cfg-row[data-field-key="${err.field}"]`);
    if (!row) continue;
    setFieldError(row, err.message);
  }
}
```

So the rules router should return `{"detail": {"errors": [{"field": "...", "message": "..."}]}}` (or equivalent) on `422` if `rules-editor.js` is to reuse `settings-save.js`'s error-mapping helpers, OR `rules-editor.js` writes its own mapper — planner's discretion, but the shape must be decided explicitly since `Rule`/`When`/`Action` are nested Pydantic models (validation errors will have dotted paths like `when.time_range`).

**Analog 2 — old endpoint to retire:** `backend/main.py:998-1006`.

```python
# Fuente: backend/main.py:998-1006 (código real, a sustituir por el router nuevo)
@app.get("/api/v2/rules")
async def api_v2_rules(request: Request):
    return {
        "rules": [json.loads(r.model_dump_json()) for r in rule_engine.rules],
        "invalid": [{"name": name, "reason": reason} for name, reason in rule_engine.invalid_rules],
    }
```

Keep this GET's response shape (`rules`/`invalid`) when porting into the new router — `settings-section.js:71-80` already consumes `data.rules` for the read-only "reglas_cargadas" subsection in Ajustes (D-03 says that subsection stays, pointed at whatever the final route is).

**Analog 3 — `POST /rules/{id}/test`, pure evaluation building block:** `backend/events/rules.py:72-102` (`_matches`) and `:169-188` (`RuleEngine.match`, for the debounce-free loop shape). Per Pitfall 6, do NOT import `_matches` with its underscore — add a public method on `RuleEngine`:

```python
# Fuente: backend/events/rules.py:169-188 (código real) — usar como plantilla del
# nuevo metodo publico test_rule()/would_match(), SIN tocar self._last_fired
def match(self, event: Event) -> list[str]:
    self._purge_stale(event.ts)
    fired: list[str] = []
    for rule in self._rules:
        if not rule.enabled:
            continue
        if not _matches(rule.when, event):
            continue
        if self._is_debounced(rule, event):
            continue
        self._last_fired[self._debounce_key(rule, event)] = event.ts
        fired.append(rule.name)
    return fired
```

New public wrapper (add to `RuleEngine`, no debounce/no mutation):
```python
def would_match(self, when: When, event: Event) -> bool:
    """Public, side-effect-free wrapper around _matches() for /rules/{id}/test (RULE-05)."""
    return _matches(when, event)
```

**Analog 4 — event query for the test corpus:** `backend/storage/repositories.py:152-193` (`EventRepo.query`, full signature read above) — call `await event_repo.query(limit=500)` (no filters) to get "últimos 500 eventos", exactly as `backend/api/v2/events.py:94-96` already does for `/api/v2/events`.

---

### `backend/pipeline/detection.py` — add `set_lines`/line rebuild

**Analog:** the existing `set_zones`/`_update_zones_and_heat`/`_rebuild_zone_states` trio, all in this same file.

```python
# Fuente: backend/pipeline/detection.py:135-139 (dirty-flag setter, código real)
def set_zones(self, zones: list[dict]) -> None:
    """Replace the active interest zones list. Thread-safe."""
    with self._lock:
        self._zones = list(zones)
        self._zones_dirty = True
```

```python
# Fuente: backend/pipeline/detection.py:483-491 (rebuild-on-dirty gate, código real)
def _update_zones_and_heat(self, tracked, shape, captured_at=0.0, processed_at=0.0) -> None:
    fh, fw = shape[:2]
    with self._lock:
        dirty = self._zones_dirty
        self._zones_dirty = False
        zones_snap = list(self._zones)
    if dirty or self._zone_frame_size != (fw, fh):
        self._zone_frame_size = (fw, fh)
        self._rebuild_zone_states(zones_snap, fw, fh)
```

```python
# Fuente: backend/pipeline/detection.py:520-544 (rebuild, fracción→píxel, código real)
def _rebuild_zone_states(self, zones: list[dict], fw: int, fh: int) -> None:
    states: list[dict] = []
    for z in zones:
        if not z.get("enabled", True):
            continue
        try:
            pts = np.array(
                [[int(p[0] * fw), int(p[1] * fh)] for p in json.loads(z["polygon_json"])],
                dtype=np.int64,
            )
            if len(pts) < 3:
                continue
            states.append({..., "zone": sv.PolygonZone(polygon=pts), ...})
        except Exception:
            logger.warning("DetectionWorker: zone %s invalid polygon_json, skipped", z.get("id"))
    with self._lock:
        ...
```

For lines, the rebuild target isn't `sv.PolygonZone` — it's N `sv.LineZone` instances that live inside `PersonTracker` (see next section), not inside `DetectionWorker._zone_states`. `set_lines()`/`_lines_dirty` on `DetectionWorker` should just forward the fraction→pixel conversion to `PersonTracker.reconfigure_lines()` (plural, new) at rebuild time, mirroring the same dirty-flag gate shown above — do not duplicate `PolygonZone`-style state tracking for lines inside `detection.py` itself, since counting state (`in`/`out` per line) belongs in `PersonTracker`.

---

### `backend/pipeline/manager.py` — add `CameraPipeline.set_lines`

**Analog:** `CameraPipeline.set_zones`, same file.

```python
# Fuente: backend/pipeline/manager.py:322-327 (código real)
def set_zones(self, zones: list[dict]) -> None:
    if self.detection:
        self.detection.set_zones(zones)

def get_zone_stats(self) -> list[dict]:
    return self.detection.get_zone_stats() if self.detection else []
```

`CameraManager.all()` (line 432) is how the new `/api/v2/lines` router reaches every live pipeline to push the hot-reload, same as the legacy `if rtsp_stream is not None: rtsp_stream.set_zones(zones)` call in `main.py:1129` — but iterating `camera_manager.all()` instead of a single global, since v2 is multi-camera-shaped even though the project only runs 1 camera today.

---

### `backend/tracker.py` — refactor `PersonTracker` from 1 line to N lines

**Analog for the list-of-dict-state shape to adopt:** `backend/pipeline/detection.py`'s `_zone_states` (list of `{"id", "name", "zone", "inside", "entries", "current"}` dicts, rebuilt on dirty flag) — apply the same shape to lines: `_line_states: list[dict]` with `{"id", "name", "line": sv.LineZone(...), "in_count", "out_count", "crossed_ids"}`.

**Existing single-line methods to generalize (this same file, already read in full, 204 lines):**

```python
# Fuente: backend/tracker.py:38-43 (constructor, único LineZone — código real)
self._line_zone = sv.LineZone(
    start=start, end=end,
    triggering_anchors=[sv.Position.BOTTOM_CENTER],
    minimum_crossing_threshold=self.CROSSING_THRESHOLD,
)
```

```python
# Fuente: backend/tracker.py:144-152 (hot-swap ya existente, código real —
# YA es thread-safe; el trabajo es llamarlo desde N líneas en vez de 1 y
# desde un endpoint en caliente en vez de solo al construir el pipeline)
def reconfigure_line(self, start: sv.Point, end: sv.Point) -> None:
    """Replace the LineZone with new pixel coordinates. Thread-safe."""
    with self._lock:
        self._line_zone = sv.LineZone(
            start=start, end=end,
            triggering_anchors=[sv.Position.BOTTOM_CENTER],
            minimum_crossing_threshold=self.CROSSING_THRESHOLD,
        )
```

```python
# Fuente: backend/tracker.py:60-93 (update(), único trigger — código real,
# generalizar el bucle "for line in self._lines" en vez de una sola línea)
def update(self, detections: sv.Detections) -> tuple[sv.Detections, list[dict[str, Any]]]:
    tracked = self._byte_tracker.update_with_detections(detections)
    if tracked.tracker_id is not None:
        tracked = self._smoother.update_with_detections(tracked)
    crossed_in, crossed_out = self._line_zone.trigger(tracked)
    ...
```

```python
# Fuente: backend/tracker.py:120-127 (get_counts(), global — código real,
# debe pasar a devolver un dict por línea: {"line_id": {"in":.., "out":.., "total":..}})
def get_counts(self) -> dict[str, int]:
    with self._lock:
        return {"in": self._in_count, "out": self._out_count, "total": len(self._crossed_ids)}
```

Keep `ByteTrack`/`DetectionsSmoother` shared across all lines (one tracker per camera, not per line — a person crosses multiple lines with the same identity); only the `LineZone`+counters become a list. This mirrors exactly how `ObjectTracker` (same file, lines 155-205) deliberately differs from `PersonTracker` by *not* sharing state it doesn't need — same discipline applies to keeping tracking shared but crossing-state per-line.

---

### `backend/events/rules.py` — expose public test hook

Already covered above (`would_match`). No additional analog beyond the file itself.

---

### `frontend/js/components/videoCanvas.js` — canvas/letterbox math to reuse

**Full file already read (137 lines).** The function to invert is `normalizedBoxToCanvasRect`:

```javascript
// Fuente: frontend/js/components/videoCanvas.js:82-101 (código real)
// D-06/Pitfall 1: object-fit:cover recorta el frame fuente para llenar la
// caja mostrada — hay que deshacer ese recorte con scale=max()+offset centrado,
// usando naturalWidth/naturalHeight (resolución intrínseca), nunca width/height.
function normalizedBoxToCanvasRect(box, img, canvas) {
  const iw = img.naturalWidth, ih = img.naturalHeight;
  const cw = canvas.width, ch = canvas.height;
  if (!iw || !ih || !cw || !ch) return null;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2;
  const offsetY = (ch - drawH) / 2;
  const [x1, y1, x2, y2] = box;
  return {
    x: offsetX + x1 * iw * scale, y: offsetY + y1 * ih * scale,
    w: (x2 - x1) * iw * scale, h: (y2 - y1) * ih * scale,
  };
}
```

The RESEARCH.md-drafted inverse (click → fraction) already spells out the exact math to write, same variable names:

```javascript
// Basado en: frontend/js/components/videoCanvas.js:86-101 — inversa a escribir
function canvasClickToFrac(clickX, clickY, img, canvas) {
  const iw = img.naturalWidth, ih = img.naturalHeight;
  const cw = canvas.width, ch = canvas.height;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2, offsetY = (ch - drawH) / 2;
  return { x_frac: (clickX - offsetX) / drawW, y_frac: (clickY - offsetY) / drawH };
}
```

**Resize/sync pattern to reuse for the new editor canvas** (own `<canvas>` element, same technique as `#tracks-overlay`):

```javascript
// Fuente: frontend/js/components/videoCanvas.js:76-80, 129-137 (código real)
function syncCanvasToImage(canvas, img) {
  const rect = img.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;
}

let _tracksResizeObserver = null;
export function initTracksOverlay() {
  const canvas = document.getElementById('tracks-overlay');
  const img = document.getElementById('video-feed');
  if (!canvas || !img || _tracksResizeObserver) return;
  syncCanvasToImage(canvas, img);
  _tracksResizeObserver = new ResizeObserver(() => syncCanvasToImage(canvas, img));
  _tracksResizeObserver.observe(img);
}
```

The zone/line editor canvas needs its own `ResizeObserver` instance (don't share `_tracksResizeObserver`'s module-level singleton — it's private to `videoCanvas.js` and only syncs `#tracks-overlay`), but should copy this exact `syncCanvasToImage` + `ResizeObserver` shape against `#camera-feed`.

**Note:** `videoCanvas.js` draws using `naturalWidth/naturalHeight`, never `width/height` — the RESEARCH.md Anti-patterns section calls this out explicitly ("Reinferir zoom/pan/`object-fit` con matemáticas nuevas... ya existe `normalizedBoxToCanvasRect`"). Any new editor code must import/reuse this exact scale/offset calculation, not recompute it.

---

### `frontend/js/components/zoneEditor.js` — existing legacy CRUD list/form (full file read, 104 lines)

This file **already exists** and is NOT canvas-based — it's a manual coordinate-JSON text input (`zone-points-input`) writing to `/api/zones` (v1 legacy). Per D-02, the new editor must write against `/api/v2/zones` (`ZoneRepo`), so this file needs a substantial rewrite, not just an extension. Keep its list-render/delete-confirm/toast UX pattern (below); replace the manual-JSON-textarea add-flow with the canvas draw-flow.

```javascript
// Fuente: frontend/js/components/zoneEditor.js:68-102 (código real) — patrón de
// lista + borrado con confirm() + toast a conservar (solo cambia el endpoint)
export async function loadZones() {
  try {
    const res = await fetch('/api/zones');
    if (!res.ok) return;
    const data = await res.json();
    const zones = data.zones ?? [];
    ...
    zones.forEach(z => {
      const row = document.createElement('div');
      ...
      row.querySelector('.btn-del-zone').addEventListener('click', async () => {
        if (!confirm(`¿Eliminar la zona "${z.name}"?`)) return;
        try {
          const r = await fetch(`/api/zones/${encodeURIComponent(z.id)}`, { method: 'DELETE' });
          if (r.ok) { showToast(`Zona "${z.name}" eliminada`, 'info'); loadZones(); }
          else showToast('Error al eliminar zona', 'error');
        } catch { showToast('Sin respuesta', 'error'); }
      });
      list.appendChild(row);
    });
  } catch {}
}
```

**Import convention to keep:** `import { showToast } from '../views/dashboard.js';` — every existing frontend component/view in this project imports toasts from `dashboard.js`, not from a shared `toast.js` module. Follow the same import path in any new editor/orchestrator file.

**Validation precedent already in this file** (client-side, before the fetch — still needed even though the server also validates):
```javascript
// Fuente: frontend/js/components/zoneEditor.js:30-39 (código real)
let pts;
try {
  pts = JSON.parse(zonePoints);
  if (!Array.isArray(pts) || pts.length < 3) throw new Error();
} catch {
  zoneMsg.textContent = 'Puntos inválidos. Ejemplo: [[0.1,0.1],[0.9,0.1],[0.5,0.9]]';
  ...
}
```
The canvas-based editor replaces free-text JSON entry with clicks, but should keep an equivalent "≥3 points" guard client-side before POSTing, mirroring the server-side check in `main.py:1122`/the new v2 router.

---

### `frontend/js/views/rules-editor.js` (NEW)

**Analog 1 — field-type renderers to reuse/extend:** `frontend/js/views/settings-field.js` (full file read, 298 lines). The rule form needs widgets for `event` (enum), `zone` (enum/select from `/api/v2/zones`), `camera` (str/enum), `time_range` (two `time` inputs), `days` (list_int, exactly like `schedule_days`), `min_confidence`/`duration_gte` (float), `person` (str) — nearly 1:1 with existing renderers:

```javascript
// Fuente: frontend/js/views/settings-field.js:139-160 (enum + time renderers, código real)
function _renderEnum(field, controlWrap, sectionKey) {
  const select = document.createElement('select');
  select.className = 'filter-input filter-select w-[140px]';
  for (const v of field.enum_values ?? []) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v;
    if (v === field.value) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => trackChange(sectionKey, field.key, select.value));
  controlWrap.appendChild(select);
}

function _renderTime(field, controlWrap, sectionKey) {
  const input = document.createElement('input');
  input.type = 'time';
  input.className = 'filter-input w-[96px]';
  input.value = field.value ?? '';
  input.addEventListener('change', () => trackChange(sectionKey, field.key, input.value));
  controlWrap.appendChild(input);
}
```

```javascript
// Fuente: frontend/js/views/settings-field.js:162-189 (list_int con chips, código real
// — reutilizar tal cual para days [0..6] del cuerpo When.days)
function _renderListInt(field, controlWrap, sectionKey) {
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap gap-1 justify-end';
  const active = new Set(field.value ?? []);
  const isDays = field.key === 'schedule_days';
  const entries = isDays
    ? WEEKDAY_LABELS.map((label, id) => [id, label])
    : Object.entries(COCO_CLASS_LABELS).map(([id, label]) => [Number(id), label]);
  for (const [id, label] of entries) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.textContent = label;
    ...
  }
  controlWrap.appendChild(wrap);
}
```

**Anti-XSS convention to keep** (stated in this file's own header comment, apply identically in `rules-editor.js`):
```
// Anti-XSS (patron de timeline-row.js): createElement/textContent siempre, nunca innerHTML
// interpolando datos de servidor (label/hint/env/mensaje 422).
```

**Analog 2 — save/validate/422-mapping engine:** `frontend/js/views/settings-save.js` (full file read, 181 lines) — `saveSection`'s fetch/422/success flow is the template for `saveRule`/`testRule`:

```javascript
// Fuente: frontend/js/views/settings-save.js:63-118 (código real, patrón a replicar
// para POST/PUT /api/v2/rules — sección "Guardar")
export async function saveSection(sectionKey) {
  ...
  let res;
  try {
    res = await fetch('/api/v2/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section: sectionKey, changes }),
    });
  } catch {
    showToast('No se pudo guardar la configuración. Los cambios siguen aquí, inténtalo de nuevo.', 'error');
    return;
  }
  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    const errors = body.detail?.errors ?? body.errors ?? [];
    for (const err of errors) {
      const row = panel?.querySelector(`.cfg-row[data-field-key="${err.field}"]`);
      if (!row) continue;
      setFieldError(row, err.message);
    }
    return;
  }
  ...
}
```

For `POST /api/v2/rules/{id}/test`, model the fetch/response handling the same way but render `{"would_fire": N, "total_checked": 500}` (per RESEARCH.md's data-flow diagram) instead of mapping field errors — a simple result banner, not a form-error mapper.

---

### `frontend/js/views/camera.js` — mount point for the editor panel (D-03)

**Full file already read (119 lines).** The relevant precedent is `activateCameraFeed()`'s "activate once, guard re-entry" pattern — the zone/line editor should follow the same guard when it lazily mounts its own canvas over `#camera-feed`:

```javascript
// Fuente: frontend/js/views/camera.js:32-37 (código real)
let _feedActivated = false;
export function activateCameraFeed() {
  if (_feedActivated) return;
  _feedActivated = true;
  const img = document.getElementById('camera-feed');
  if (img) img.src = '/video_feed';
}
```

`initCamera()` (lines 114-119) is the single entry point called from `nav.js`/`app.js` on first tab switch — any new `initZoneEditor()`/`initRulesEditor()` should be called from here (or from a dedicated init hooked the same way `app.js` wires `initCamera`/`initSettings`, per the Fase 32-07 commit history: "wiring de app.js (initCamera/initCameraQuick/initSettings)").

---

## Shared Patterns

### Auth / rate limiting (all new routers)
**Source:** `backend/api/v2/events.py:1-10` (docstring) + `backend/api/v2/deps.py` (`limiter`, `V2_RATE_LIMIT = "60/minute"`, `pagination_limit`).
**Apply to:** `backend/api/v2/zones.py`, `backend/api/v2/lines.py`, `backend/api/v2/rules.py` — every route decorated `@limiter.limit(V2_RATE_LIMIT)`, no per-route `Depends(verify)` (inherited globally from `FastAPI(dependencies=[Depends(verify)])`).

### Hot-reload dirty-flag (zones already proven, lines need the same treatment)
**Source:** `backend/pipeline/detection.py:135-139` (`set_zones`) + `:483-491` (dirty-flag gate) + `backend/pipeline/manager.py:322-327` (`CameraPipeline.set_zones`).
**Apply to:** `backend/pipeline/detection.py` (`set_lines`), `backend/pipeline/manager.py` (`CameraPipeline.set_lines`), and the new `/api/v2/lines` router's write handlers (push to `camera_manager.all()` after persisting, mirroring `main.py:1129`/`1141`'s `rtsp_stream.set_zones(zones)` calls).

### Fraction-normalized coordinates, never pixels
**Source:** `backend/pipeline/detection.py:521-538` (`p[0]*fw, p[1]*fh` at rebuild time) + `frontend/js/components/videoCanvas.js:86-101` (`normalizedBoxToCanvasRect`).
**Apply to:** every payload the new editor POSTs (`polygon: [[x_frac, y_frac], ...]`, `start_x_frac/start_y_frac/end_x_frac/end_y_frac`) and every canvas draw/read in `zoneEditor.js`/`lineEditor.js`.

### Toast notifications + confirm-before-delete
**Source:** `frontend/js/components/zoneEditor.js:92-98` (`import { showToast } from '../views/dashboard.js'`, `confirm()` before DELETE).
**Apply to:** all new/rewritten frontend files in this phase — keep the same import path and the native `confirm()` for destructive zone/line deletes (rules editor's own destructive actions, if any, should follow the same convention UNLESS the "Restaurar" popover precedent in `settings-save.js:120-149` is deemed a better fit for a specific flow — that file explicitly avoids `confirm()` per D-07 of Fase 30, so if the rules editor gets a "discard"/"delete rule" action with meaningful blast radius, prefer the popover pattern over `confirm()`, matching the newer convention).

### Anti-XSS: `createElement`/`textContent`, never `innerHTML` with server data
**Source:** `frontend/js/views/settings-field.js:5-6` (docstring), consistently applied throughout that file and `settings-section.js`.
**Apply to:** every new frontend file that renders zone/line names, rule names, or any other server-supplied string.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `frontend/css/components.css` (`.modal`, `.zone-editor`, `.vertex-handle`) | style | — | RESEARCH.md confirms no `.modal`/`.dialog` class exists anywhere in `components.css` today — this is genuinely new CSS, not a variant of an existing pattern. Follow the existing file's general conventions (Tailwind utility-first + a handful of custom component classes like `.cfg-row`/`.filter-chip`/`.cam-toggle` already seen above) rather than inventing a new naming scheme. |
| `tests/test_zones_api.py`, `tests/test_lines_api.py`, `tests/test_rules_api.py` | test | integration | Not read in this pass (RESEARCH.md already flags them as Wave-0 gaps, files don't exist yet). Planner should locate `tests/test_config_api.py` or `tests/test_detection_config_api.py` at plan time as the concrete pytest fixture/client pattern to copy (async test client + `get_session_factory` override), since this pattern-mapping pass prioritized backend/frontend source analogs within the 3-5 strong-match budget. |

## Metadata

**Analog search scope:** `backend/api/v2/`, `backend/storage/`, `backend/pipeline/`, `backend/tracker.py`, `backend/events/rules.py`, `backend/main.py`, `frontend/js/components/`, `frontend/js/views/`.
**Files scanned:** 15 read in full or targeted ranges (`repositories.py`, `models.py`, `detection.py` x2 ranges, `manager.py` x1 range, `tracker.py`, `events/rules.py`, `main.py` x2 ranges, `api/v2/events.py`, `api/v2/config.py` x1 range, `api/v2/deps.py` x1 range, `videoCanvas.js`, `camera.js`, `zoneEditor.js`, `settings-field.js`, `settings-save.js`, `settings-section.js`), plus `Glob`/`wc -l` survey of both `backend/api/v2/` and `frontend/js/**`.
**Pattern extraction date:** 2026-08-24
