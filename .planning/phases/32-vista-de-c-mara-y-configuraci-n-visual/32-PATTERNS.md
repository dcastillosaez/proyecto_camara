# Phase 32: Vista de cámara y configuración visual - Pattern Map

**Mapped:** 2026-08-23
**Files analyzed:** 13 (7 backend/test, 6 frontend, 1 CSS extension)
**Analogs found:** 12 / 13

## Precondition (blocks everything below)

Verified in this session: `frontend/js/nav.js` **does not exist**, `frontend/index.html`
has no `role="tablist"`, and `frontend/js/views/` has no `camera.js`/`settings.js`. Fase 31
is only planned (`.planning/phases/31-vista-de-anal-tica/*-PLAN.md`), not executed — zero
commits of its code. `tests/test_frontend_modules.py::LOCKED_JS` still lists only the
Fase 28/30 modules (`app.js`, `api.js`, `websocket.js`, `views/dashboard*.js`,
`components/*.js`, `views/timeline*.js`, `components/alertCenter.js`,
`components/markPerson.js`) — no `nav.js`, no Fase 31 view modules.

Per 32-RESEARCH.md Pitfall 5: the first wave of Fase 32 must not touch `nav.js` until
Fase 31 has actually executed and the file exists in the tree. Everything in this
PATTERNS.md that touches `nav.js` / the tablist assumes Fase 31's code is present.
`frontend/css/components.css` currently measures **163 lines** against the 300-line cap
(`tests/test_frontend_modules.py::TEST_line_limit`); Fase 31 will add its own classes to
the same shared file before Fase 32 does — re-measure before budgeting the 8 new `.cfg-*`
classes (Pitfall 6).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/api/v2/config.py` | controller (router) | request-response + CRUD (batch) | `backend/api/v2/detection.py` | exact |
| `backend/api/v2/config_schema.py` | config/data | transform (declarative registry) | `backend/api/v2/detection.py` (`AVAILABLE_CLASSES` tuple) | role-match |
| `backend/storage/repositories.py` (`ConfigRepo.delete`) | model/repository | CRUD | `ConfigRepo.get`/`set`/`get_all` (same class, lines 795-818) + `ZoneRepo.delete`/`RuleRepo.delete` (lines 735, 778) | exact |
| `tests/test_config_api.py` | test | integration | `tests/test_detection_config_api.py` | exact |
| `frontend/js/views/camera.js` | view/controller | request-response + polling | `frontend/js/views/dashboard-observability.js` (health tick) + `frontend/js/views/dashboard.js` (`loadCamStatus`/`loadPipelineHealth`) | role-match |
| `frontend/js/views/camera-quick.js` | component/controller | event-driven (save-on-change) | `frontend/js/components/detectionClasses.js` | role-match |
| `frontend/js/views/settings.js` | view/orchestrator | request-response | `frontend/js/views/timeline.js` (orchestrator that wires child modules) | role-match |
| `frontend/js/views/settings-section.js` | component (render) | transform | `frontend/js/views/timeline-row.js` (row renderer from server data) | role-match |
| `frontend/js/views/settings-field.js` | component (render) | transform | `frontend/js/components/detectionClasses.js` (`renderDetectionClasses`) | partial |
| `frontend/js/views/settings-save.js` | controller (save/diff) | CRUD (batch write) + event-driven | `frontend/js/components/alertCenter.js` (popover confirm + PUT) | role-match |
| `frontend/js/nav.js` (extend) | provider/router | event-driven | *(does not exist yet — blocked, see Precondition)* | no analog (blocked) |
| `frontend/js/views/dashboard-observability.js` (extend) | view | polling | itself (extend in place) | exact |
| `frontend/css/components.css` (extend, `.cfg-*`) | style | — | existing `.cam-toggle`/`.filter-input`/`.filter-chip`/`.card`/`.ptz-btn` blocks in same file | exact |

## Pattern Assignments

### `backend/api/v2/config.py` (controller, request-response/CRUD)

**Analog:** `backend/api/v2/detection.py` (read completely — 118 lines)

**Imports pattern** (lines 20-31):
```python
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.config import get_settings
from backend.database import get_session_factory
from backend.storage.repositories import ConfigRepo

router = APIRouter(prefix="/api/v2/config", tags=["config"])
```
No `Depends(verify)` per-route — auth is global (`FastAPI(dependencies=[Depends(verify)])`),
routers inherit it. Rate limiting via `@limiter.limit(V2_RATE_LIMIT)` from `deps.py`.

**Wiring pattern** (lines 35-43, `configure()` injected once from lifespan):
```python
_camera_manager: Any = None
_event_engine: Any = None

def configure(camera_manager: Any, event_engine: Any = None) -> None:
    """Wire the live CameraManager/EventEngine instances. Called once from main.py's lifespan."""
    global _camera_manager, _event_engine
    _camera_manager = camera_manager
    _event_engine = event_engine

def _config_repo() -> ConfigRepo:
    return ConfigRepo(get_session_factory())
```
`_config_repo()` as a module-level factory is the exact seam tests patch
(`patch.object(config_module, "_config_repo", return_value=fake_repo)`) — reuse verbatim,
do not read the DB directly.

**Core "persist before propagate" pattern** (lines 106-117, PUT):
```python
# Persistir ANTES de propagar: si el proceso muriera entre ambos pasos, el arranque
# siguiente (main.py, precedencia app_config > env var) aplicaria lo que el operador
# pidio en vez de perderlo.
await _config_repo().set(CONFIG_KEY, list(ids))
if _camera_manager is not None:
    for pipeline in _camera_manager.all():
        pipeline.set_detection_classes(list(ids))
if _event_engine is not None:
    _event_engine.config_changed(datetime.datetime.now(), classes=list(ids))
return _classes_payload(list(ids))
```
For `PUT /api/v2/config`, adapt this into: validate batch (min/max + `Settings` candidate
re-validation per RESEARCH Pattern 3) → 422 with **all** errors if any invalid → for the
valid subset, `ConfigRepo.set(key, value)` per field → for keys in the 3 known hot-apply
set (`yolo_classes`, `process_width`/`process_height`, zones), call the matching
`CameraPipeline.set_*()` → one `_event_engine.config_changed(now, section=..., diff={...})`
call for the whole section (not one per field — D-09).

**Origin resolution pattern** (RESEARCH.md Pattern 2, derived from `get_classes()` lines 78-81):
```python
persisted = await _config_repo().get(CONFIG_KEY)
active = list(persisted) if persisted else list(get_settings().yolo_classes)
```
Extend to three-way compare (`runtime` if in `overrides`, else `env` if `!= field.default`,
else `default`) per `FieldDef` — see 32-RESEARCH.md Pattern 2 for the full snippet already
verified against this code.

**Concurrency pattern for read-modify-write** — `backend/api/v2/alerts.py` lines 30, 44-52,
144-150 (`_mute_lock = asyncio.Lock()`, serializes read-modify-write against a single
`app_config` row). Not strictly needed for `config.py` since each field is its own row
(`ConfigRepo.set` is per-key, not read-modify-write of a shared blob), but replicate the
lock if the PUT batches writes against any single shared key (e.g. a future
`alerts.muted_rules`-style aggregate).

---

### `backend/api/v2/config_schema.py` (declarative registry, new — no direct analog)

**Analog for style:** `backend/api/v2/detection.py` lines 46-53 (`AVAILABLE_CLASSES` tuple
+ `LOCKED_CLASS_IDS` frozenset as a hand-written whitelist, not introspected).
```python
AVAILABLE_CLASSES: tuple[tuple[int, str], ...] = (
    (0, "person"), (1, "bicycle"), (2, "car"),
    (3, "motorcycle"), (24, "backpack"), (28, "suitcase"),
)
LOCKED_CLASS_IDS: frozenset[int] = frozenset({0})
```
Same shape scales to `FieldDef` tuples per section (see 32-RESEARCH.md Pattern 1 for the
full `@dataclass(frozen=True) class FieldDef` and `DETECCION_PERSONAS: tuple[FieldDef, ...]`
example — already written against this codebase, copy from there rather than re-deriving).

**Ranges must cite `backend/config.py` model_validators, not be invented** (RESEARCH
Pitfall 3). Cross-field invariants already exist and must be reused, not reimplemented, at
lines:
```python
# backend/config.py:309-325 — identity_vote_window >= identity_min_votes, etc.
# backend/config.py:327-344 — reid_similarity_threshold in (0,1], reid_interval_secs > 0
# backend/config.py:346-366 — behavior params, run_window_secs <= 12.0
# backend/config.py:368-393 — object params, context_low_ratio < context_high_ratio
# backend/config.py:395-407 — snapshot params, snapshot_max_width in [64, 1920]
```
Batch validation should build a candidate `Settings` and re-run these via
`Settings(**{**current.model_dump(), **changes})` (constructor, not `model_copy`, per
RESEARCH Assumption A1 — verify against installed pydantic before committing to this).

**Secret masking precedent (what NOT to copy as-is):**
```python
# backend/main.py:1197-1210 — GET /api/alerts/config
@app.get("/api/alerts/config")
async def api_alerts_config():
    s = get_settings()
    return {
        "webhook_url": s.alert_webhook_url,   # LEAK — sent unmasked, contradicts D-12
        "telegram_configured": bool(s.alert_telegram_token and s.alert_telegram_chat_id),
        ...
    }
```
`telegram_configured: bool(...)` is the correct pattern to copy for `secret` fields; the
raw `webhook_url` on the line above is the anti-pattern (32-RESEARCH.md Anti-Patterns,
Pitfall/threat table). `config_schema.py` must mark `webhook_url` as `secret: true` and
never serialize it — do not import or wrap this endpoint's `webhook_url` field.

**RTSP masking (readonly, always-masked field):**
```python
# backend/config.py:429-438
def mask_rtsp_url(url: str) -> str:
    """Replace credentials in RTSP URL with *** for safe logging."""
    ...
```
Call this server-side for the read-only "Cámara → Captura" RTSP URL field; never construct
masking in JS.

---

### `backend/storage/repositories.py` — `ConfigRepo.delete()` (model, CRUD, new method)

**Analog:** same class, existing methods (lines 795-818):
```python
class ConfigRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

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

    async def get_all(self) -> dict[str, Any]:
        async with self._sf() as session:
            result = await session.execute(select(models.AppConfig))
            return {r.key: r.value for r in result.scalars().all()}
```
**Delete analog in the same file** — `ZoneRepo.delete()` (line 735) and `RuleRepo.delete()`
(line 778) both follow this exact shape:
```python
# backend/storage/repositories.py:778-785 (RuleRepo.delete, structurally identical to
# ZoneRepo.delete at 735)
async def delete(self, rule_id: str) -> bool:
    async with self._sf() as session:
        async with session.begin():
            r = await session.get(models.Rule, rule_id)
            if r:
                await session.delete(r)
                return True
    return False
```
`ConfigRepo.delete(self, key: str) -> bool` should copy this shape exactly, swapping
`models.Rule`/`rule_id` for `models.AppConfig`/`key`. "Restore section" (OPS-20) then
iterates `FieldDef.key` for that section and calls `delete()` per key present in
`app_config` — no new store, no prefixed keys (RESEARCH Anti-Patterns).

---

### `tests/test_config_api.py` (test, integration)

**Analog:** `tests/test_detection_config_api.py` (read completely — 154 lines)

**Client + repo double pattern** (lines 15-35):
```python
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from httpx import ASGITransport
import backend.main as main_module
from backend.api.v2 import detection as detection_module

async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")

def _fake_repo(get_return=None) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=get_return)
    repo.set = AsyncMock(return_value=None)
    return repo
```
For `config.py`, extend `_fake_repo` with `get_all = AsyncMock(return_value={...})` and
`delete = AsyncMock(return_value=True)`.

**Wiring reset fixture** (lines 38-41):
```python
@pytest.fixture(autouse=True)
def _reset_detection_wiring():
    yield
    detection_module.configure(None, None)
```
Copy verbatim with `config_module` in place of `detection_module`.

**Order-of-operations assertion pattern** (lines 126-146, `TEST_put_persists_before_propagating`):
```python
parent = MagicMock()
parent.attach_mock(repo.set, "config_set")
parent.attach_mock(pipeline.set_detection_classes, "pipeline_set")
...
call_names = [c[0] for c in parent.mock_calls]
assert call_names.index("config_set") < call_names.index("pipeline_set")
```
Reuse this exact technique to assert "persist before propagate" and "persist before
`config_changed`" for the new PUT.

**Precedence test at module level** (lines 149-153): `main_module._resolve_active_classes`
is tested as a pure function outside the HTTP layer — same approach recommended for the
new origin-resolution helper in `config_schema.py`/`config.py` (unit test the resolver
function directly, not only through the HTTP round trip).

---

### `frontend/js/views/camera.js` (view/controller, polling)

**Analog 1 (health/status loaders):** `frontend/js/views/dashboard-observability.js` (read
completely — 65 lines):
```javascript
export async function loadHealth() {
  try {
    const res = await fetch('/api/health');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('health-cpu').textContent = d.cpu_percent >= 0 ? `${d.cpu_percent.toFixed(1)}%` : '–';
    ...
  } catch {}
}
```
Fetch → `if (!res.ok) return` → `textContent` assignment (never `innerHTML` for server
data, per the anti-XSS convention) → swallow errors silently is the house style for a
polling read. `camera.js` should follow this exactly for the RTSP status card and its
6 metric tiles, reading `/api/v2/cameras/{camera_id}/health` for the RTSP card and reusing
the same `/api/health` + `/api/v2/metrics` payloads `dashboard-observability.js` already
parses (do not re-fetch differently — extend the existing module per UI-SPEC "Refresco").

**Analog 2 (deferred `<img>` activation pattern):** UI-SPEC directs re-use of the "activate
only when tab becomes visible" pattern already used for Chart.js in Fase 31 (not present in
codebase yet — Fase 31 not executed; treat as a **new pattern to establish**, not one to
copy from existing code). When Fase 31 lands, the equivalent module to inspect first is
whatever wires `<canvas>`/Chart.js lazily in `frontend/js/views/` — check its shape before
writing `camera.js`'s lazy `<img src>` assignment.

**RTSP masked display:** never build the mask in JS. Fetch the already-masked string from
`GET /api/v2/cameras/{camera_id}/health` (server applies `mask_rtsp_url()`; if that field
isn't already exposed there, `config.py`'s GET schema is the fallback source — do not add a
third source).

**CaptureHealth fields to render** (source of truth, `backend/pipeline/capture.py:26-36`):
```python
@dataclass
class CaptureHealth:
    camera_id: str
    connected: bool
    fps: float
    reconnects: int
    last_frame_age_s: float
    native_resolution: tuple[int, int] | None
    frames_captured: int
```
Already served by `GET /api/v2/cameras/{camera_id}/health` (`backend/main.py:1173-1190`,
via `asdict(pipeline.health)` plus `capture_fps`/`detection_fps`/`broker_stats`/`stats()`).
No backend change needed for this endpoint — `camera.js` is a pure consumer.

---

### `frontend/js/views/camera-quick.js` (component, event-driven save-on-change)

**Analog:** `frontend/js/components/detectionClasses.js` (read completely — 68 lines)
```javascript
export async function saveDetectionClasses() {
  const msg = document.getElementById('detection-classes-msg');
  const checkboxes = document.querySelectorAll('.detection-class-checkbox');
  const classes = Array.from(checkboxes).filter(cb => cb.checked).map(cb => parseInt(cb.dataset.classId, 10));
  checkboxes.forEach(cb => cb.disabled = true);
  try {
    const res = await fetch('/api/v2/detection/classes', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classes }),
    });
    if (res.ok) {
      showToast('Clases activas actualizadas', 'success');
      renderDetectionClasses(await res.json());
    } else {
      const d = await res.json().catch(() => ({}));
      msg.textContent = d.detail ?? 'Error al guardar.';
      ...
      await loadDetectionClasses();  // revierte al estado real del servidor
    }
  } catch { ... }
}
```
This is the "save on change, disable control while in flight, revert to server truth on
error" pattern — exactly D-13's contract (4 quick controls, PUT on change, no save button).
**Caveat:** this reads `PUT /api/v2/detection/classes` (Fase 27's dedicated endpoint). Per
D-13, `camera-quick.js` must instead PUT `/api/v2/config` for all 4 controls including
classes — do not reuse the Fase-27 endpoint directly, only the interaction pattern.

**Caveat on the chips claim:** 32-UI-SPEC.md and 32-RESEARCH.md both describe the "clases
detectadas" control as "chips conmutables con `aria-pressed`, reutilizando el componente de
Detección". Verified against the actual code: `detectionClasses.js` renders **checkboxes**
inside `<label>` rows (`<input type="checkbox" class="detection-class-checkbox">`), not
`aria-pressed` chip buttons. There is no `aria-pressed` chip component for COCO classes in
the codebase today. Flag this discrepancy to the planner: either (a) build a new chip
variant for `camera-quick.js`/`settings-field.js`'s `list[int]` type, matching the
`.filter-chip` CSS class (`aria-pressed`, already used for `schedule_days` per UI-SPEC), or
(b) reuse the checkbox pattern as-is and treat the UI-SPEC's "chips" wording as
aspirational. Do not assume the aria-pressed chip component already exists for classes.

**Debounce requirement (D-13, confidence slider):** no existing debounce utility found in
the codebase (`frontend/js/` has no `debounce.js`/`lodash`); implement inline
(`setTimeout`/`clearTimeout`) inside `camera-quick.js`, consistent with "cero dependencias
nuevas" (UI-SPEC Design System).

---

### `frontend/js/views/settings-save.js` (controller, batch diff + destructive confirm)

**Analog for destructive popover confirmation (D-11 "Restaurar valores por defecto"):**
`frontend/js/components/alertCenter.js` (mute/silence flow) + matching markup in
`frontend/index.html:792-800`.
```javascript
// frontend/js/components/alertCenter.js:158-176 (paraphrased — module-level target var,
// never stored in the DOM; textContent for server-derived title)
let _muteTarget = null;
function openMutePopover(ruleName) {
  const pop = $('alert-mute-popover');
  const title = $('alert-mute-title');
  _muteTarget = ruleName;
  title.textContent = `Silenciar «${ruleName}»`;      // dato del backend: textContent
  pop.classList.add('open');
}
function closeMutePopover() {
  _muteTarget = null;
  $('alert-mute-popover')?.classList.remove('open');
}
```
```html
<!-- frontend/index.html:792-800 -->
<div id="alert-mute-popover" class="bg-slate-800 border border-slate-700 rounded-xl p-3 flex flex-col gap-2">
  <p id="alert-mute-title" class="text-xs font-semibold text-slate-200"></p>
  <div class="flex gap-1">
    <button class="filter-chip" data-duration="900">15 minutos</button>
    ...
  </div>
  <p class="text-xs text-slate-500">No verás estas alertas durante ese tiempo...</p>
</div>
```
`settings-save.js`'s "Restaurar «{sección}»" popover should follow this exact shape:
module-level `_restoreTarget` variable (not DOM-stored), `textContent` for the
server-derived section name and count, "click outside closes" delegated listener
(`alertCenter.js` lines 249-250: `if (!e.target.closest('#popover-id, [data-trigger]')) close()`),
`Escape` closes it (line 266). Swap the 3 duration chips for the two buttons
"Restaurar {N} valores" (red, `.filter-chip`-adjacent but destructive-colored) / "Cancelar".

**Analog for PUT + toast + revert-on-error:** `detectionClasses.js::saveDetectionClasses`
(above) — same disable-while-in-flight / `showToast` / revert-to-server-truth shape, but
`settings-save.js` differs in two contract points the analog does NOT have: (1) explicit
save button (not save-on-change) with `.busy` state — copy that specific bit from
`.ptz-btn.busy` CSS (`frontend/css/components.css:15`, `opacity: 0.5; pointer-events: none;`
already exists, apply the same class name/behavior to the save button); (2) 422 must map
per-field errors back to individual `.cfg-row` elements and NOT discard the pending diff
(D-10) — no existing analog does partial-failure field mapping; this is new logic, but the
"disable controls while PUT in flight" half is directly reusable.

**`CONFIG_CHANGED` diff emission** — same backend call as `config.py`'s PUT
(`EventEngine.config_changed`, `backend/events/engine.py:315-324`):
```python
def config_changed(self, now: datetime.datetime, **detail: Any) -> None:
    self._publish(EventType.CONFIG_CHANGED, ts=now, payload=dict(detail))
```
`settings-save.js` doesn't call this directly (it's backend-side), but its PUT payload
shape (`{section, changes}`) must map cleanly to what the router turns into `detail=` here
— no `secret` fields in `detail`, ever (D-12).

---

### `frontend/js/views/settings.js` / `settings-section.js` / `settings-field.js`

**No exact analog exists** for a schema-driven tree+form renderer — this is genuinely new
UI in this codebase. Closest partial precedents to imitate structurally:

- **Orchestrator wiring multiple child modules from one entry point:**
  `frontend/js/views/timeline.js` (13.4K, reads full schema/state and delegates rendering
  to `timeline-row.js`, filtering to `timeline-filters.js`, virtualization to
  `timeline-virtualize.js`) — same "one orchestrator, several single-purpose child modules"
  shape `settings.js` needs for `settings-section.js`/`settings-field.js`/`settings-save.js`.
- **Row renderer built entirely from server-sent data, never static HTML:**
  `frontend/js/views/timeline-row.js` — same discipline `settings-field.js` needs (every
  `label`/`hint`/`env`/`default`/error message from the server goes through `textContent`/
  `dataset`, never `innerHTML` with interpolated server strings — the anti-XSS convention
  explicitly named in 32-UI-SPEC.md's closing section applies here more than anywhere else
  in the project since the entire config tree is server-authored).
- **`aria-pressed` toggle chips for a fixed whitelist:** none found with that exact ARIA
  attribute in the current codebase (see caveat above under `camera-quick.js`) — `.filter-chip`
  CSS class exists and is used with `.active` class toggling (`components.css:123-128`), but
  no JS file currently sets `aria-pressed` on it. `settings-field.js`'s `list[int]` control
  type (COCO classes, `schedule_days`) will be the first to establish this pattern; there's
  no existing JS to copy the ARIA wiring from, only the CSS.

---

## Shared Patterns

### Auth / rate limiting
**Source:** `backend/api/v2/deps.py` (imported by every `/api/v2/*` router)
**Apply to:** `backend/api/v2/config.py`
```python
from backend.api.v2.deps import V2_RATE_LIMIT, limiter
...
@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def get_config(request: Request) -> dict[str, Any]: ...
```
No per-route `Depends(verify)` needed — inherited from the app-level dependency.

### Router registration in `main.py` lifespan
**Source:** `backend/main.py:589-593` (detection/alerts pattern) + `760-772` (`include_router`)
**Apply to:** the new `config.py` router
```python
from backend.api.v2 import detection as detection_v2_module
detection_v2_module.configure(camera_manager, event_engine)
from backend.api.v2 import alerts as alerts_v2_module
alerts_v2_module.configure(event_engine)
# → add: from backend.api.v2 import config as config_v2_module
#        config_v2_module.configure(camera_manager, event_engine)
...
from backend.api.v2.detection import router as detection_v2_router
app.include_router(detection_v2_router)
# → add: from backend.api.v2.config import router as config_v2_router
#        app.include_router(config_v2_router)
```

### Precedence resolution (`runtime > .env > default`)
**Source:** `backend/api/v2/detection.py:78-81` (two-way: runtime vs. absent) and
`backend/api/v2/alerts.py:44-52` (`_load_muted`, purge-on-read pattern for a JSON blob key)
**Apply to:** `config.py`'s GET resolver — extend to the three-way compare in
32-RESEARCH.md Pattern 2 (not previously needed by either existing precedent, since neither
compares against `Settings` default — this is new territory, flagged as RESEARCH Pitfall 4
for list/dict fields specifically).

### Frontend module line-limit & lock-list contract
**Source:** `tests/test_frontend_modules.py` (`LINE_LIMIT = 300`, `LOCKED_CSS`, `LOCKED_JS`)
**Apply to:** every new frontend file in this phase. Each new file must be added to
`LOCKED_JS`/`LOCKED_CSS` in the same plan that creates it (Fase 30/31 precedent). Current
measured sizes: `components.css` 163 lines, `app.js` 58 lines, `dashboard-observability.js`
65 lines — all comfortably under 300, but `components.css`'s margin must be re-measured
after Fase 31 lands (Pitfall 6) before adding the 8 `.cfg-*` classes.

### Anti-XSS convention (server data never via innerHTML)
**Source:** established across `dashboard-observability.js`, `alertCenter.js`,
`detectionClasses.js` — every one of them uses `textContent`/`.value`/`dataset` for
server-sourced strings, and only ever puts **constant, literal** markup (no interpolated
server data) inside `innerHTML` (e.g. `detectionClasses.js:18-21` interpolates
`cls.id`/`cls.name` into `innerHTML` via a template literal — note this is actually a
**mild existing violation** of the strict convention 32-UI-SPEC.md states, since `cls.name`
is server data inside `innerHTML`; it works today only because class names come from a
fixed whitelist tuple, not free text. Do not repeat this shortcut in `settings-field.js`,
where `label`/`hint` are free-form strings — use `textContent` assignment on separate
nodes, never string-interpolated `innerHTML`, exactly as 32-UI-SPEC.md's closing section
mandates).
**Apply to:** all new frontend files, especially `settings-field.js`, `settings-section.js`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/js/nav.js` (extension) | provider/router | event-driven | File doesn't exist yet — Fase 31 unexecuted. Blocked; verify existence before planning this edit (Pitfall 5). |
| `frontend/js/views/settings.js`, `settings-section.js`, `settings-field.js` | view/component | transform (schema→DOM) | No schema-driven tree/form renderer exists anywhere in this codebase; closest partial precedents (`timeline.js`/`timeline-row.js`) only cover list rendering, not a nested tablist + fieldset + per-type control renderer. Build fresh, following the anti-XSS and module-size conventions listed under Shared Patterns. |
| `.cfg-tree`/`.cfg-node`/`.cfg-row`/`.cfg-badge`/`.cfg-applies`/`.cfg-savebar` CSS | style | — | No config-tree UI exists yet; only spacing/color tokens are inherited (documented fully in 32-UI-SPEC.md's own Spacing/Color sections, which is itself the authoritative source for these — no codebase file to copy from beyond the already-cited `.ptz-btn.busy`, `.cam-toggle`, `.filter-chip`, `.card` blocks). |

## Metadata

**Analog search scope:** `backend/api/v2/`, `backend/storage/repositories.py`,
`backend/events/engine.py`, `backend/pipeline/manager.py`, `backend/pipeline/capture.py`,
`backend/config.py`, `backend/main.py`, `frontend/js/`, `frontend/css/components.css`,
`frontend/index.html`, `tests/test_detection_config_api.py`, `tests/test_frontend_modules.py`
**Files scanned:** 16 read in full or targeted ranges (detection.py, alerts.py,
repositories.py [ConfigRepo/ZoneRepo/RuleRepo sections], engine.py [config_changed],
config.py [validators + mask_rtsp_url], capture.py [CaptureHealth], manager.py [3 hot-apply
methods], main.py [health/alerts-config endpoints + lifespan wiring],
test_detection_config_api.py, test_frontend_modules.py, app.js, dashboard-observability.js,
detectionClasses.js, alertCenter.js [popover slice], components.css [class list], index.html
[popover markup])
**Pattern extraction date:** 2026-08-23
