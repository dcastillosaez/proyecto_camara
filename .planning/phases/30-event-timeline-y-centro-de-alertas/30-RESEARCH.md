# Phase 30: Event Timeline y centro de alertas - Research

**Researched:** 2026-08-20
**Domain:** API REST paginada por cursor sobre SQLite/SQLAlchemy async + timeline virtualizada en JS vanilla (ES modules, sin librerías) + resolución de una condición de carrera real en el fan-out del `EventBus`
**Confidence:** HIGH — todo lo determinante está verificado leyendo el código real del repo y midiendo planes de consulta reales de SQLite (100.000 filas sintéticas, `EXPLAIN QUERY PLAN` + tiempos). Cero dependencias externas nuevas que investigar.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Diseño visual (ya fijado por 30-UI-SPEC.md — aprobado 6/6, no volver a preguntar)**
- **D-01:** Sin frameworks/dependencias nuevas. Reutiliza el sistema de diseño heredado de `29-UI-SPEC.md` (Tailwind CDN, `components.css`, tokens de spacing 4/8/16/24/32/48/64, tipografía de 4 tamaños 12/14/16/30px, color slate-950/900 + acento azul único). Ver `30-UI-SPEC.md` para el contrato completo (spacing, tipografía, color, copywriting, 21 elementos de copy en español).
- **D-02:** Severidad como sistema de color semántico propio: rojo=crítico, ámbar=advertencia, **slate neutro=info** (deliberadamente NO verde, para no chocar con "SISTEMA ONLINE" del header de la Fase 29); verde reservado a identidad confirmada.
- **D-03:** Ancla visual: la barra/punto de severidad es el ancla primaria de cada fila de la timeline; el contador de 30px (hero) es el ancla del cajón de alertas.
- **D-04:** Fila de altura fija de 52px con ventana de recorte de DOM de 400 filas (virtualización simple, no una librería) y compensación de `scrollTop` al recortar por arriba. Plan B si el salto de scroll es perceptible: subir la ventana a 1000 filas y no recortar.
- **D-05:** Evento nuevo con la lista desplazada hacia abajo NO fuerza el scroll — aparece como píldora flotante "N eventos nuevos" (criterio de éxito 4, sin ser intrusivo).
- **D-06:** "Marcar como persona" muestra aviso explícito del alcance retroactivo antes de confirmar ("Se aplicará también a los eventos anteriores de este track (N)") — sin `confirm()` nativo, modal propio reutilizando el patrón de `personGallery.js`.
- **D-07:** "Descartar" y "Silenciar" no son operaciones destructivas modales: descartar usa toast+deshacer de 5s, silenciar usa un popover con duración obligatoria como confirmación implícita. No se añade ningún `confirm()` nuevo a la fase.
- **D-08:** Acciones de fila en cajas de 32×32px (mínimo WCAG 2.5.8), campana de alertas del header 44×44px, miniatura 64×36px (ratio fijo).

**Backend — filtros, cursor y tiempo real (OPS-09, OPS-10)**
- **D-09:** Nuevo endpoint `GET /api/v2/events` (no existe hoy — `backend/api/v2/` solo tiene `context.py`, `detection.py`, `metrics.py`, `recordings.py`). Filtros combinables: `type[]`, `severity`, `person_id`, `zone_id`, `camera_id`, `from`, `to`, `cursor`, `limit<=200` (contrato ya fijado en `SPEC_v2.md` §8.1 — no renegociar la forma de los parámetros).
- **D-10:** Paginación por cursor, no por offset — con 10.000 eventos navegables (criterio 3), offset/`LIMIT-OFFSET` degrada. El cursor debe ser estable ante inserciones concurrentes (eventos nuevos llegando mientras se pagina hacia atrás en el tiempo).
- **D-11:** Los índices ya existentes en `backend/storage/models.py` (`idx_events_ts`, `idx_events_type_ts`, `idx_events_cam_ts`, `idx_events_person`) cubren los filtros por tipo/cámara/persona/tiempo — verificar en RESEARCH si hace falta un índice compuesto adicional para `severity`+`zone_id` combinados, o si se resuelven con los existentes + filtrado en aplicación sobre un resultado ya acotado por tiempo.
- **D-12:** El evento nuevo en <1s (criterio 4) se sirve por el canal WebSocket **ya existente** (`/ws`, con eventos ya emitidos hoy — ver `backend/main.py:303-306`, suscriptor `websocket_v1_compat`/`websocket_v2` al `event_bus`). No se requiere un nuevo tipo de mensaje WS para esto, a diferencia del `type: "tracks"` de la Fase 29 — los eventos YA se difunden en tiempo real, la fase solo tiene que consumirlos en la timeline sin recargar.

**"Qué regla disparó" (OPS-11) — el hueco técnico de mayor riesgo de la fase**
- **D-13:** Hoy `RuleEngine.evaluate()` (`backend/events/rules.py:169`) calcula qué reglas dispararon (`fired.append(rule.name)`) pero **no** persiste ese dato en el `Event`: la tabla `events` (`backend/storage/models.py:85-109`) no tiene columna `rule_name`, solo un campo genérico `payload = Column(JSON, default=dict)` sin usar hoy para esto.
- **D-14:** Restricción arquitectónica real que RESEARCH debe respetar: en `backend/main.py:293-306`, `_persist_event` (persistencia) y `_apply_rules` (RuleEngine) son suscriptores **independientes** del mismo `event_bus`, cada uno en su propia tarea asyncio — el comentario del código es explícito: *"el orden de suscripción no determina el de ejecución"*. Los dos reciben el mismo objeto `Event` por referencia (EVT-02), pero no hay garantía de que `_apply_rules` termine de mutar el evento antes de que `_persist_event` lo escriba en SQLite. Cualquier solución para exponer `rule_name` en el evento persistido debe resolver esta condición de carrera explícitamente (opciones a evaluar en RESEARCH: mover la evaluación de reglas delante de la persistencia en el pipeline en vez de como suscriptor paralelo del bus; persistir el evento primero y hacer un `UPDATE` desde `_apply_rules` cuando termine; o publicar un segundo evento/mensaje `rule_fired` correlacionado por `event.id` que el frontend consuma aparte). No asumir que "mutar el objeto antes de que acabe la task" es seguro sin verificarlo.
- **D-15:** Usar el campo `payload` (JSON) existente para guardar los nombres de regla disparados, no añadir una columna nueva ni migración de esquema — evita tocar Alembic/migraciones para esta fase, coherente con "cambio mínimo" (CLAUDE.md, Regla final).

**Centro de alertas — agrupación y silenciado (OPS-11, criterio 6)**
- **D-16:** El "silenciar por regla" opera sobre `Rule.name` (identificador ya existente en `backend/storage/models.py:187` tabla `rules` y en `backend/events/rules.py:46` `class Rule`), no sobre un ID de alerta individual — silenciar una regla debe dejar de generar nuevas entradas en el centro de alertas para esa regla hasta que expire la duración elegida.
- **D-17:** El popover de silenciado (D-07) exige duración obligatoria — RESEARCH debe decidir dónde persiste ese estado temporal (tabla nueva mínima tipo `muted_rules(rule_name, until, camera_id)`, o reutilizar `app_config` vía `ConfigRepo` con una clave estructurada — evaluar cuál es menos invasivo dado que no hay tabla de "silenciados" hoy).

### Claude's Discretion
- Forma exacta de la respuesta paginada de `GET /api/v2/events` (envelope `{items, next_cursor}` vs. cabecera `Link`, formato del cursor — opaco en base64 vs. timestamp+id compuesto legible).
- Si el WebSocket empuja el `Event` completo o solo un `id` que dispara un `GET /api/v2/events/{id}` — depende de cuánto payload ya se serializa hoy en `websocket_v2`/`websocket_v1_compat` (ver `backend/main.py`) y si basta reutilizarlo.
- Diseño exacto de la virtualización de 400 filas (IntersectionObserver vs. cálculo manual de scroll) — sin librería nueva, coherente con D-04.
- Estructura de datos concreta para el estado de "silenciado" (D-17) y su TTL de limpieza.
- Si `GET /api/v2/timeline` (mencionado en `SPEC_v2.md` §8.1 como endpoint separado "eventos agrupados por bloques") es necesario para esta fase o si `GET /api/v2/events` con filtros ya cubre el caso de uso — el wireframe de UI-SPEC no exige agrupación temporal visual explícita más allá de los separadores de hora (`.timeline-sep`, ya en 30-UI-SPEC.md).

### Deferred Ideas (OUT OF SCOPE)
- Vista de analítica (heatmap, ranking, tendencias) — Fase 31.
- Vista de cámara y árbol de configuración visual — Fase 32.
- Editor de reglas (`ruleEditor.js`, crear/editar reglas desde la UI) — no está en el alcance de OPS-07..11, esta fase solo consume `Rule.name` para mostrar qué regla disparó y permitir silenciarla, no editarla.
- `js/store.js` y router de vistas — seguirán diferidos hasta que una fase futura realmente lo necesite (ninguna de las Fases 29/30 lo ha requerido hasta ahora).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Descripción (REQUIREMENTS.md:249-253) | Soporte de este research |
|----|---------------------------------------|--------------------------|
| OPS-07 | Los eventos se presentan como línea temporal con hora, severidad, descripción, zona y miniatura | § Hallazgo 4 (miniatura: `snapshot_path` NUNCA se escribe hoy — hay que crearlo o degradar), § API `GET /api/v2/events` con mapa `media`, § Descripción llana (mapa de tipos → frase, y `person_name` NO está persistido) |
| OPS-08 | Cada evento ofrece acciones directas: ver vídeo, ver captura, marcar como persona y descartar | § Hallazgo 4 (clip vía `recordings.trigger_event_id`, no vía `event.recording_id`), § `POST /api/v2/events/{id}/assign-person`, § Descartar = estado de cliente en `localStorage` |
| OPS-09 | Los filtros de eventos se resuelven en servidor con paginación por cursor | § Hallazgo 1 (`EventRepo.query()` YA implementa cursor base64 `ts\|id` + filtros; falta multi-tipo, `total`, `rule`), § Índices (medición real 10k/100k) |
| OPS-10 | Un evento nuevo aparece en la interfaz en menos de un segundo | § Hallazgo 2 (el `/ws` que usa el frontend hoy SOLO recibe `LINE_CROSSED` en formato v1: D-12 es falso tal cual está escrito), § Nuevo mensaje `type:"event"` en `/ws` |
| OPS-11 | El centro de alertas agrupa alertas activas, muestra qué regla las disparó y permite silenciarlas | § Recomendación de la carrera (suscriptor único ordenado), § `GET /api/v2/alerts` + silenciado en `app_config` |
</phase_requirements>

---

## Summary

Tres cosas cambian el plan respecto a lo que asume el CONTEXT.md, y las tres están verificadas leyendo el código:

**1. `GET /api/v2/events` ya existe** (`backend/main.py:829-861`) y `EventRepo.query()` (`backend/storage/repositories.py:92-141`) ya implementa exactamente lo que pide D-10: filtros combinables + paginación por cursor opaco en base64 con la tupla `(ts, id)` y comparación por valor de fila (`tuple_(ts, id) < tuple_(cursor_ts, cursor_id)`). La fase **no inventa el patrón, lo extiende**: faltan multi-tipo (`type[]`), contador `total`, filtro por regla y el mapa de medios (miniatura/clip). El envelope actual es `{"events": [...], "cursor": ...}` y **no debe renombrarse**, porque `frontend/js/views/dashboard.js:274` (panel "Alertas activas" de la Fase 29) ya consume `data.events`.

**2. D-12 es incorrecto tal como está redactado.** El canal `/ws` que usa el frontend (`frontend/js/websocket.js:30`) **no** recibe los eventos tipados: `_broadcast_v1_compat` (`backend/main.py:106-123`) filtra `if event.type != EventType.LINE_CROSSED: return` y emite un mensaje `{"type":"detection", ...}` legacy sin `id`, sin `severity`, sin `zone_id` y sin `track_id`. El evento tipado completo sí viaja, pero por `/api/v2/ws` (`_broadcast_v2`, envelope `{"v":2,"kind":"event","data":{...}}`), a la que el frontend **no se conecta**. Es decir: hay que añadir un mensaje nuevo. Lo correcto es replicar la decisión de la Fase 29 (mensaje nuevo en el `/ws` legacy, un socket, token y backoff ya resueltos), no abrir una segunda conexión.

**3. La carrera de D-14 es real y peor de lo descrito.** `EventBus._consume()` (`backend/events/bus.py:65-69`) lanza `asyncio.ensure_future(...)` por cada suscriptor: los cuatro corren de verdad en paralelo, así que ninguna suposición de orden entre suscriptores es válida — ni siquiera "casi siempre funciona". Además la carrera no afecta solo a la persistencia: `_broadcast_v2` serializa el evento en su propia tarea, así que el push en vivo también puede salir sin el chip de regla. La recomendación es colapsar los cuatro suscriptores en **uno solo, ordenado** ("event_pipeline"), separando `RuleEngine.evaluate()` en `match()` (puro, sin `await`, sin E/S) + `run_actions()` (con `await`, lento, dispara Telegram/webhook/grabación). El pipeline queda: `match` → mutar `payload["rules"]` → `insert` → broadcast → `run_actions` en fire-and-forget. Ni segunda escritura, ni columna nueva, ni migración de datos, y la latencia de las acciones lentas no bloquea la persistencia (que es como se comporta hoy y no debe regresar).

Y dos huecos que el CONTEXT.md no menciona y que tocan directamente dos criterios de éxito: **`snapshot_path` nunca se escribe** (no hay `_snapshot_hook` configurado en ningún sitio; `grep imwrite` solo devuelve la galería de personas ya identificadas y la miniatura de clip), y **`person_name` no es columna de la tabla `events`** (`_to_row`/`_to_dto` en `repositories.py:47-80` no lo mapean), así que el nombre de la persona no sobrevive a la persistencia. Ambos afectan a "miniatura" (criterio 1) y a "precarga el crop" (criterio 5).

**Primary recommendation:** extender lo que ya existe en vez de crear paralelo — `EventRepo.query()` + `GET /api/v2/events` (movido a `backend/api/v2/events.py` como router, siguiendo la convención de `recordings.py`), un único suscriptor ordenado del bus que resuelve la carrera de reglas de raíz, un mensaje `type:"event"` nuevo en el `/ws` legacy, silenciado en `app_config` vía `ConfigRepo`, y un índice compuesto `idx_events_ts_id (ts DESC, id DESC)` que está medido y elimina el `TEMP B-TREE FOR ORDER BY` de todas las consultas filtradas.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Filtrado combinable + orden + paginación | Database (SQLite) | API | OPS-09 exige resolución en servidor; medido: SQLite hace la página en <1 ms con el índice correcto, filtrar en Python sobre 10k filas sería peor y viola el requisito |
| Cursor (codificación/decodificación) | API (`EventRepo`) | — | Ya implementado en `repositories.py:31-39`; el cliente lo trata como opaco |
| "Qué regla disparó" (cálculo) | Backend — event pipeline | — | `RuleEngine` es la única fuente; el frontend nunca reevalúa reglas |
| "Qué regla disparó" (persistencia) | Database (`events.payload`) | — | D-15; sin columna nueva |
| Agrupación de alertas por regla | API (`/api/v2/alerts`) | Browser | Agrupar en el navegador exigiría descargar todo el historial; se agrupa en el servidor sobre una ventana acotada |
| Estado "silenciada" | Database (`app_config`) | API | Debe sobrevivir a recarga de página y a reinicio del backend |
| Virtualización / recorte de DOM (400 filas) | Browser | — | Puramente de renderizado; el servidor no sabe nada de la ventana visible |
| Separadores de hora/día (`.timeline-sep`) | Browser | — | Derivables de `ts`; **no** justifican un `GET /api/v2/timeline` |
| "Descartar" (ocultar evento) | Browser (`localStorage`) | — | UI-SPEC: "No borra nada de la base de datos"; sin estado de servidor no hay endpoint ni migración |
| Miniatura / crop del evento | Backend (captura en el pipeline) + CDN-equivalente (`StaticFiles`) | API | La imagen solo existe en el momento del evento; el navegador no puede reconstruirla a posteriori |
| Enrolado + actualización retroactiva del track | API + Database | Browser | La actualización masiva es un `UPDATE` acotado; el navegador solo repinta las filas visibles |
| Push de evento nuevo (<1 s) | API (WebSocket) | Browser | Ya hay socket, token y backoff; añadir polling sería una regresión |

---

## Standard Stack

Cero dependencias nuevas. Stack cerrado por `CLAUDE.md` y confirmado en `requirements.txt` / `.venv`.

### Core (ya instalado, versiones verificadas en el venv del proyecto)

| Librería | Versión verificada | Propósito en esta fase | Por qué es la estándar aquí |
|----------|--------------------|------------------------|------------------------------|
| SQLAlchemy | 2.0.49 `[VERIFIED: .venv, import sqlalchemy.__version__]` | `EventRepo.query()` extendido, `UPDATE` retroactivo | Ya es el ORM del proyecto; `tuple_()` compila a comparación de valor de fila nativa de SQLite |
| SQLite (stdlib) | 3.49.1 `[VERIFIED: .venv python -c sqlite3.sqlite_version]` | Row-values (`(a,b) < (?,?)`, ≥3.15), `json_each` (JSON1 built-in ≥3.38), índices descendentes | Todas las técnicas propuestas están soportadas con margen; nada requiere una versión más nueva |
| FastAPI + slowapi | ya en uso | Router `/api/v2/events`, rate limit obligatorio | `TEST_all_v2_endpoints_rate_limited` (tests/test_security_regression.py:129) falla si un endpoint v2 no lleva `@limiter.limit(V2_RATE_LIMIT)` |
| pytest / pytest-asyncio | `pytest.ini`: `python_functions = TEST_*`, `asyncio_mode = auto` | Tests de la fase | Convención del repo: las funciones de test se llaman `TEST_*`, no `test_*` |
| `IntersectionObserver` (nativo) | — | Centinela de scroll infinito | Ya fijado por UI-SPEC; soportado por todos los navegadores objetivo |

### Supporting (ya en el repo, reutilizar)

| Asset | Ubicación | Cuándo usarlo |
|-------|-----------|---------------|
| `scripts/seed_events.py` `seed_events(db_path, n, days, camera_id)` | scripts/ | Sembrar 10.000/100.000 eventos para el test de rendimiento del criterio 3. **Ya usado** por `tests/test_repositories.py:245` (`TEST_query_performance_100k`) |
| `_encode_cursor` / `_decode_cursor` | `repositories.py:31-39` | Formato de cursor ya decidido y probado; no inventar otro |
| `openClipModal(src)` | `components/eventCard.js:97` | Acción "Ver clip" de la fila |
| `showToast(msg, type, ms)` | `views/dashboard.js` | Toast de descartar/deshacer y de error |
| `apiFetch(path, opts)` | `js/api.js` | Todas las llamadas nuevas; ya normaliza el error a `Error(detail)` |
| `pagination_limit(default=50, le=200)` | `api/v2/deps.py:29` | `limit` del endpoint (test de seguridad lo exige) |

### Alternatives Considered

| En vez de | Se podría usar | Trade-off |
|-----------|----------------|-----------|
| Cursor `(ts,id)` base64 | `LIMIT/OFFSET` | Rechazado por D-10 y porque ya está implementado el cursor. Además `OFFSET 9950` obliga a SQLite a recorrer 9.950 filas descartándolas |
| Mensaje nuevo en `/ws` | Conectar el frontend a `/api/v2/ws` | Dos sockets, dos tokens, dos backoffs y `/api/v2/ws` no manda `init`/`tracks`. Mismo criterio que la Fase 29 (que ya metió `tracks` en `/ws`) |
| Virtualización manual (UI-SPEC D-04) | `content-visibility: auto` en CSS | Podría bastar y es 1 línea, pero no está en el contrato de UI-SPEC y no resuelve el consumo de memoria del DOM. Mencionar solo como plan C si el plan B (1000 filas sin recortar) también falla |
| `app_config` para silenciados | Tabla `muted_rules` | Ver § Decisión D-17: tabla = `SCHEMA_VERSION` 2→3 + repo + tests, para <10 filas |

**Instalación:** ninguna. `pip install` no se ejecuta en esta fase.

**Version verification:** `.venv/Scripts/python.exe -c "import sqlalchemy, sqlite3; print(sqlalchemy.__version__, sqlite3.sqlite_version)"` → `2.0.49 3.49.1` `[VERIFIED: ejecutado en esta sesión]`.

---

## Architecture Patterns

### System Architecture Diagram — el camino de un evento, antes y después

```
ANTES (hoy, backend/main.py:299-306) — 4 suscriptores concurrentes, orden indeterminado
──────────────────────────────────────────────────────────────────────────────────────

  worker thread (DetectionWorker / RecognitionWorker / watchdog)
        │  EventEngine._publish()  →  bus.publish_threadsafe(event)
        ▼
   EventBus._queue  ──►  _consume()  ──┬─ ensure_future ─► _persist_event   ─► SQLite INSERT
                                       ├─ ensure_future ─► _broadcast_v1_compat ─► /ws (solo LINE_CROSSED)
                                       ├─ ensure_future ─► _broadcast_v2    ─► /api/v2/ws  (nadie escucha)
                                       └─ ensure_future ─► _apply_rules     ─► RuleEngine.evaluate()
                                                                                   │
                                                     muta event.payload  ◄─────────┘  ¡DEMASIADO TARDE!
                                                     (carrera con el INSERT y con el broadcast)

DESPUÉS (recomendado) — 1 suscriptor, secuencia explícita dentro de una sola task
────────────────────────────────────────────────────────────────────────────────

   EventBus._queue ──► _consume() ── ensure_future ─► _event_pipeline(event)
                                                          │
                       1. fired = rule_engine.match(event)         (puro, sync, sin E/S)
                       2. if fired: event.payload["rules"] = fired (mutación ANTES de leer)
                       3. await event_repo.insert(event)           (fila completa, una escritura)
                       4. await _broadcast_event(event, media)     ► /ws  {"type":"event", ...}
                          await _broadcast_v2(event)               ► /api/v2/ws (se conserva)
                          ensure_future(_broadcast_v1_compat(ev))  ► /ws  {"type":"detection"} (legacy)
                       5. ensure_future(rule_engine.run_actions(event, fired))
                                                          │
                                            Telegram / webhook / grabación / upload
                                            (lentos, NO bloquean 3 ni 4)

   navegador  ──GET /api/v2/events?…&cursor=…──►  EventRepo.query()  ──► SQLite (idx_events_ts_id)
              ◄── {events:[…], cursor, total, media:{…}}
              ──WS {"type":"event"} ──► timeline.onLiveEvent()  ─► inserta arriba  |  pill "N nuevos"
              ──GET /api/v2/alerts──► agrupa por payload.rules  ─► cajón de alertas + badge campana
```

### Recommended Project Structure

```
backend/
├── api/v2/
│   └── events.py            # NUEVO router: /api/v2/events, /{id}, /{id}/assign-person,
│                            # /api/v2/alerts, /api/v2/alerts/mute   (mover aquí el endpoint
│                            # que hoy vive suelto en main.py:829)
├── events/rules.py          # match() + run_actions(); evaluate() queda como wrapper
├── main.py                  # _event_pipeline (sustituye a los 4 subscribe()) + _broadcast_event
└── storage/
    ├── models.py            # + Index("idx_events_ts_id", ts.desc(), id.desc())
    ├── migrations.py        # SCHEMA_VERSION 2 → 3, migración "índice de timeline"
    └── repositories.py      # EventRepo: query() multi-tipo + total + rule; assign_person();
                             # RecordingRepo: by_trigger_event_ids()
frontend/
├── css/components.css       # + .timeline-row .timeline-sep .sev-dot .rule-chip .row-action
│                            #   .alert-group #alert-drawer     (hoy 82 líneas, tope 300)
├── index.html               # sustituye líneas 445-525 (card "Eventos recientes");
│                            # + botón campana 44×44 en el header (línea 42, junto a #clock);
│                            # + <aside id="alert-drawer">
└── js/
    ├── views/timeline.js    # NUEVO — render de filas, virtualización, cursor, filtros
    ├── components/alertCenter.js  # NUEVO — cajón, agrupación, silenciado, badge
    └── websocket.js         # + case 'event'
```

**Restricción mecánica que condiciona el reparto:** `tests/test_frontend_modules.py::TEST_line_limit` impone **300 líneas máximo por fichero** en todo `frontend/js/**` y `frontend/css/*`. `views/dashboard.js` está hoy en **290 líneas** — no cabe ni un helper más. Por eso `loadActiveAlerts()` (dashboard.js:263-290) debe **mudarse** a `components/alertCenter.js` (que ya alimenta el mismo panel top-3 según UI-SPEC), liberando ~28 líneas. Añadir la timeline dentro de `dashboard-events.js` (204 líneas) tampoco cabe: necesita fichero propio.

### Pattern 1: Router v2 con `configure()` para inyectar el estado vivo

Todos los routers v2 siguen el mismo molde y el planner debe replicarlo tal cual.

```python
# Source: backend/api/v2/detection.py:33-43 y context.py:28-37 (verificado)
router = APIRouter(prefix="/api/v2/events", tags=["events"])

_rule_engine: Any = None          # módulo-estado, no singleton oculto de negocio

def configure(rule_engine: Any = None) -> None:
    """Wire the live RuleEngine. Called once from main.py's lifespan."""
    global _rule_engine
    _rule_engine = rule_engine

@router.get("")
@limiter.limit(V2_RATE_LIMIT)              # OBLIGATORIO: test_security_regression.py:129
async def list_events(request: Request,    # 'request' es obligatorio para slowapi
                      limit: int = pagination_limit()) -> dict[str, Any]:
    ...
```

Registro en `main.py` al final del módulo, junto a los otros cuatro (`main.py:616-626`):
```python
from backend.api.v2.events import router as events_v2_router
app.include_router(events_v2_router)
```
y `configure(...)` dentro del `lifespan` (patrón de `main.py:449-452`).

**Cuidado con el prefijo:** `/api/v2/events` colisiona con el endpoint que ya existe en `main.py:829`. Hay que **borrar** el de `main.py` en el mismo commit en que se añade el router; si conviven, FastAPI resuelve por orden de registro y el resultado depende de dónde esté el `include_router`.

### Pattern 2: Suscriptor único ordenado (la solución a D-14)

```python
# Source: propuesto; sustituye a backend/main.py:287-306
async def _event_pipeline(event: Event) -> None:
    """Único suscriptor del bus. El orden aquí SÍ está garantizado: es una sola task."""
    fired: list[str] = []
    try:
        fired = rule_engine.match(event)          # puro: sin await, sin E/S, sin acciones
        if fired:
            event.payload["rules"] = fired        # mutación ANTES de cualquier lectura
    except Exception:
        logger.exception("RuleEngine.match failed for event %s", event.id)

    try:
        await event_repo.insert(event)            # la fila ya lleva payload.rules
    except Exception:
        logger.exception("Failed to persist event %s", event.id)

    try:
        await _broadcast_event(event)             # /ws  {"type": "event", ...}
        await _broadcast_v2(event)                # /api/v2/ws (contrato v2 intacto)
        asyncio.ensure_future(_broadcast_v1_compat(event))  # legacy: consulta la DB, no bloquear
    except Exception:
        logger.exception("Broadcast failed for event %s", event.id)

    if fired:
        asyncio.ensure_future(rule_engine.run_actions(event, fired))  # lentas, no bloquean nada

event_bus.subscribe("event_pipeline", _event_pipeline)
```

Y el corte en `RuleEngine`, conservando `evaluate()` para que `tests/test_rule_engine.py` siga verde sin tocarlo:

```python
# Source: propuesto sobre backend/events/rules.py:169-193
def match(self, event: Event) -> list[str]:
    """Reglas que casan y no están en debounce. Puro: sin await, sin efectos externos.
    El bookkeeping de debounce sí ocurre aquí — una regla 'casada' cuenta como disparada."""
    self._purge_stale(event.ts)
    fired = []
    for rule in self._rules:
        if not rule.enabled or not _matches(rule.when, event) or self._is_debounced(rule, event):
            continue
        self._last_fired[self._debounce_key(rule, event)] = event.ts
        fired.append(rule.name)
    return fired

async def run_actions(self, event: Event, fired: list[str]) -> None:
    for rule in (r for r in self._rules if r.name in fired):
        for action in rule.actions:
            handler = self._registry.get(action.type)
            ...  # cuerpo idéntico al bucle interno actual de evaluate()

async def evaluate(self, event: Event) -> list[str]:
    """Compatibilidad: match + run_actions, misma firma y semántica que antes."""
    fired = self.match(event)
    await self.run_actions(event, fired)
    return fired
```

**Por qué `match()` puede ser síncrono:** el bucle actual solo hace comparaciones en memoria (`_matches`) y aritmética de fechas; el único `await` está en el despacho de acciones. Verificado leyendo `rules.py:72-102` y `169-193`.

### Pattern 3: Consulta paginada con multi-tipo

```python
# Source: extensión de backend/storage/repositories.py:92-141 (verificado en ejecución)
from sqlalchemy import bindparam, text

if types:                       # list[EventType]
    if len(types) == 1:
        conditions.append(models.Event.type == types[0].value)
    else:
        # El '+' unario desactiva el uso de idx_events_type_ts para este término.
        # Sin él SQLite elige ese índice y ordena con TEMP B-TREE: 54 ms vs 0.5 ms @100k.
        conditions.append(
            text("+events.type IN :types").bindparams(bindparam("types", expanding=True))
        )
        params["types"] = [t.value for t in types]
```

`[VERIFIED: ejecutado en esta sesión contra una base de 100.000 filas — la consulta devuelve 50 filas en 4,07 ms vía SQLAlchemy ORM; el equivalente sin '+' tarda 54 ms]`

### Anti-Patterns to Avoid

- **Asumir orden entre suscriptores del `EventBus`.** `bus.py:68-69` lanza `ensure_future` en un bucle: los handlers corren concurrentes de verdad. Cualquier "primero persiste y luego..." entre suscriptores distintos es un bug latente.
- **Renombrar el envelope de `/api/v2/events`.** `dashboard.js:274` lee `data.events`. Añadir claves es seguro; renombrar rompe el panel de la Fase 29.
- **Meter la timeline en `dashboard.js`.** 290/300 líneas. El test de la Fase 28 falla al superar el tope.
- **Filtrar en el navegador** un array ya descargado (UI-SPEC lo prohíbe explícitamente y OPS-09 lo exige en servidor).
- **`await` de una acción de regla antes del `INSERT`.** Un webhook colgado dejaría el evento sin persistir; hoy no puede pasar y no debe empezar a poder.
- **Buscar por `track_id` sin acotar el tiempo.** Los ids de ByteTrack se reinician en cada arranque del pipeline (`sv.ByteTrack` se reinstancia, `backend/tracker.py:181`) y la tabla `tracks` **nunca se escribe** (`grep models.Track` → 0 escrituras). Un `WHERE track_id = 7` sin ventana temporal mezcla tracks de días distintos.
- **Un `<button>` por fila completa.** UI-SPEC: la fila no es botón; capturaría el foco 400 veces.

---

## Don't Hand-Roll

| Problema | No construyas | Usa en su lugar | Por qué |
|----------|---------------|-----------------|---------|
| Paginación estable por cursor | Un cursor nuevo (offset, `id` solo, timestamp solo) | `_encode_cursor`/`_decode_cursor` + `tuple_(ts, id)` ya en `repositories.py:31-39,121-125` | Ya resuelve empates de `ts` y es estable ante inserciones concurrentes; ya tiene tests |
| Reconexión WebSocket | Otro backoff | `websocket.js:76-84` (`_wsRetry` 1s→30s, `_wsCloseCount`) | Requisito OPS-06 ya cumplido en Fase 29; duplicarlo genera dos estados de conexión inconsistentes |
| Modal | Un modal nuevo | Patrón `#clip-modal` (`components.css:75-81`, `.open`) y `#enroll-modal` (`personGallery.js:44-46,112-124`) | El cierre por `Escape` y por clic en backdrop ya está implementado (y el handler global de `Escape` ya existe en `eventCard.js:182`) |
| Toast | Otro sistema de avisos | `showToast()` de `dashboard.js` + `.toast` de `components.css:44-49` | UI-SPEC lo fija explícitamente |
| Miniatura de clip | Generar thumbnails en el frontend | `GET /api/v2/recordings/{id}/thumbnail` (`api/v2/recordings.py:72-85`, ya con `Cache-Control: max-age=86400`) | Ya existe, ya cachea |
| Sembrar datos de prueba | Un generador ad-hoc en el test | `scripts/seed_events.py::seed_events` | Ya se usa en `test_repositories.py:245`; determinista (`seed=42`) |
| Escapar HTML de datos del backend | `innerHTML` con interpolación | `textContent` tras montar la estructura estática | Patrón obligatorio del repo por CodeQL `js/xss` — comentado en `eventCard.js:16-18` y `dashboard-events.js:121-124`. **Los nombres de persona y de regla van a la fila: es exactamente el vector que ese patrón evita** |

**Key insight:** esta fase casi no tiene "librería que elegir"; tiene "código propio que ya existe y hay que encontrar antes de reescribirlo". El coste real de la fase está en los tres huecos (carrera de reglas, ausencia de snapshots, `person_name` no persistido), no en la timeline en sí.

---

## Runtime State Inventory

No aplica en el sentido de rename/refactor, pero la fase sí toca estado ya existente en disco y hay que declararlo:

| Categoría | Encontrado | Acción requerida |
|-----------|-----------|------------------|
| Datos almacenados | `data/events.db` tabla `events` — filas históricas SIN `payload.rules`. El chip de regla estará vacío para todo lo anterior a la fase | Ninguna migración de datos: es información que no existía. Documentar que el chip solo aparece en eventos posteriores al despliegue |
| Datos almacenados (2) | `events.payload` ya contiene claves privadas `_emitted_at`, `_captured_at` (`engine.py:74-78`) y públicas (`direction`, `is_intrusion`, `state`, `votes`…) | La clave nueva `rules` convive sin colisión. **Verificar** que `When.payload` (match exacto por clave, `rules.py:98-101`) no se rompa: solo compara las claves declaradas en la regla, así que añadir `rules` es inocuo |
| Config de servicio vivo | `config/rules.yaml` — nombres de regla; se cargan en `lifespan` y no se recargan en caliente | Ninguna. La fase lee `rule_engine.rules` para poblar el selector/silenciado |
| Estado registrado en SO | Ninguno — no hay tarea programada ni servicio con nombre asociado a eventos. Verificado: `grep` de `Task Scheduler`/`pm2` en el repo = 0 | Ninguna |
| Secretos / env | Ninguno nuevo. `CAMERA_URL` y credenciales no intervienen | Ninguna |
| Artefactos de build | Ninguno (sin build step en frontend, sin paquete instalable) | Ninguna |
| Esquema | `app_config.schema_version = 2`. `run_migrations()` hace `return` temprano si `current >= SCHEMA_VERSION` (`migrations.py:169-170`) y `create_all()` **no** crea índices sobre tablas ya existentes | Si se añade `idx_events_ts_id` hay que subir `SCHEMA_VERSION` a 3 y añadir una entrada a `MIGRATIONS` con `CREATE INDEX IF NOT EXISTS` |

---

## Hallazgos concretos (lo que el planner necesita saber sí o sí)

### Hallazgo 1 — `GET /api/v2/events` y el cursor YA existen

`backend/main.py:829-861` expone hoy:

```
GET /api/v2/events?type=&severity=&person_id=&zone_id=&camera_id=&from=&to=&cursor=&limit=
→ {"events": [ …Event.model_dump_json… ], "cursor": "<base64 ts|id> | null"}
```

con `@v2_limiter.limit(V2_RATE_LIMIT)` y `limit = pagination_limit()` (cap 200, exigido por `tests/test_security_regression.py:176`). `EventRepo.query()` construye `WHERE` con `and_(*conditions)`, ordena `ts DESC, id DESC`, aplica `tuple_(ts,id) < tuple_(cursor_ts, cursor_id)` y devuelve `next_cursor` solo si la página vino llena.

**Lo que falta y hay que añadir:**

| Necesidad | Origen | Cambio |
|-----------|--------|--------|
| `type[]` multi-valor | D-09 / UI-SPEC (chips multi-selección) | `type: list[str] \| None = Query(default=None)`; `EventRepo.query(type=...)` acepta `EventType \| list[EventType] \| None` (mantener el nombre `type` evita tocar `backend/database.py:166,189`, que llaman con `type=EventType.LINE_CROSSED`) |
| `total` | UI-SPEC: "{N} de {total}" cuando hay filtros | `COUNT(*)` con las mismas condiciones. **Solo cuando hay algún filtro activo y solo en la primera página** (`cursor is None`): medido 21 ms @100k / 0,9 ms @10k. Pedirlo en cada página sería malgastarlo |
| `rule` | UI-SPEC: "Ver en la línea temporal" desde el cajón | `EXISTS (SELECT 1 FROM json_each(events.payload,'$.rules') je WHERE je.value = :rule)`. Medido 0,66 ms @100k con el índice compuesto. Usar `bindparam` (nunca f-string) |
| `media` | OPS-07/08 (miniatura + ver clip) | Ver Hallazgo 4 |

**Envelope recomendado (decisión de discreción):** conservar `{"events": [...], "cursor": ...}` y **añadir** claves. Motivo: `dashboard.js:274` ya lo consume; renombrar a `{items, next_cursor}` obligaría a tocar la Fase 29 sin ganar nada.

```jsonc
{
  "events": [ { "id": "…", "type": "INTRUSION", "ts": "…", "severity": "critical",
                "track_id": 12, "person_id": null, "zone_id": "jardin",
                "payload": { "rules": ["Intrusión nocturna"], "_emitted_at": 123.4 } } ],
  "cursor": "MjAyNi0wOC0yMFQxODozMDowMHxhYmMt…",   // null = no hay más
  "total": 137,                                     // null salvo 1ª página con filtros
  "media": {                                        // clave = event.id, solo los que tienen algo
    "6f0…": { "recording_id": 12,
              "clip_url": "/clips/clip_20260820_183000.mp4",
              "thumbnail_url": "/api/v2/recordings/12/thumbnail",
              "snapshot_url": null }
  }
}
```

`media` va como mapa hermano y **no** dentro del objeto evento a propósito: el docstring de `repositories.py:1-5` declara que el `Event` de Pydantic es "the single contract" y su forma persistida; meterle campos de presentación lo rompería y arrastraría a `/api/v2/ws`.

**Cursor inverso (scroll hacia arriba tras recortar el DOM):** no hace falta ninguno. Recomendación: la timeline guarda en memoria el array completo de eventos ya descargados (10.000 × ~250 B ≈ 2,5 MB, aceptable) y el DOM es solo una ventana sobre ese array. Recortar por arriba y volver a subir se resuelve repintando desde el array, sin red. Esto elimina un parámetro de API, elimina una clase de bug (páginas hacia atrás desalineadas con inserciones nuevas) y hace el plan B de D-04 trivial.

### Hallazgo 2 — el `/ws` que usa el frontend NO lleva los eventos tipados (corrige D-12)

Verificado en `backend/main.py:106-123` y `frontend/js/websocket.js:47-73`:

| Canal | Suscriptor | Qué manda hoy | Quién escucha |
|-------|-----------|----------------|----------------|
| `/ws` | `_broadcast_v1_compat` | **Solo** `LINE_CROSSED`, como `{"type":"detection","timestamp","direction","total_today","last_hour","person_name","is_intrusion"}` — sin `id`, `severity`, `type`, `zone_id`, `track_id` | `websocket.js` (el dashboard real) |
| `/ws` | `_broadcast` (directo) | `init`, `recording_started/uploaded/failed`, `tracks` | `websocket.js` |
| `/api/v2/ws` | `_broadcast_v2` | `{"v":2,"kind":"event","data":{…Event completo…}}` | **nadie** en el frontend |

Conclusión: la timeline no puede construirse con `type:"detection"` (le faltan severidad, tipo, zona y el `id` para las acciones). **Añadir un mensaje nuevo al `/ws` legacy**, exactamente como la Fase 29 hizo con `tracks`:

```jsonc
{ "type": "event",
  "event": { …Event.model_dump_json completo, ya con payload.rules… },
  "media": { "recording_id": null, "clip_url": null, "thumbnail_url": null, "snapshot_url": "/snapshots/…" } }
```

Se emite desde `_event_pipeline` paso 4 (después del `INSERT`, para que un `GET` posterior nunca devuelva 404 sobre un evento ya anunciado). En `websocket.js` es **un `case` más** en el dispatch existente (`msg.type === 'event'` → `timeline.onLiveEvent(msg.event, msg.media)`).

**Doble emisión que hay que gestionar:** un `LINE_CROSSED` disparará `type:"event"` y `type:"detection"`. El `case 'detection'` debe conservar `updateStat`, `bumpHourBar` y `showToast` (gráfica y contadores de la Fase 5) y **perder** la llamada a `addEvent(...)` — si no, el evento se pinta dos veces. `addEvent`, `applyFilters` y `bindEventFilters` de `dashboard-events.js:110-204` quedan obsoletos junto con el card `#events-list`; la fase debe borrarlos, no dejarlos huérfanos (el test `TEST_line_limit` no lo detecta, pero sí lo detectaría una revisión del `#events-list` inexistente lanzando `TypeError` en `document.getElementById(...).prepend`).

**Latencia:** el push sale del mismo proceso, sin polling; el presupuesto de OPS-10 (<1 s) tiene tres órdenes de magnitud de margen. `_broadcast_v2` ya instrumenta `latency_tracker.mark_ws_sent()` — conviene que el nuevo `_broadcast_event` **no** lo marque otra vez para no contaminar la métrica `EVENT_TO_WS`.

### Hallazgo 3 — la carrera de D-14: análisis y recomendación

**Confirmación del problema.** `EventBus._consume()`:

```python
# backend/events/bus.py:65-69  [VERIFIED: leído]
while True:
    event = await self._queue.get()
    for name, handler in list(self._subscribers.items()):
        asyncio.ensure_future(self._run_handler(name, handler, event))
```

Los cuatro handlers se programan como tareas independientes en el mismo tick. `_persist_event` (`await event_repo.insert`) y `_apply_rules` (`await rule_engine.evaluate`) se intercalan en el primer `await` de cada uno. Como `evaluate()` hace `await handler(...)` por cada acción, en la práctica **casi siempre** el INSERT gana la carrera y el `payload["rules"]` se escribiría *después* del commit: es decir, la mutación se perdería siempre, no "a veces". Y aunque ganara, el objeto ya habría sido serializado por `_broadcast_v2`. La carrera no es teórica.

**Opciones evaluadas:**

| Opción | Cómo | Veredicto |
|--------|------|-----------|
| **(a) Evaluar reglas antes de persistir, en un suscriptor único** | `match()` puro → mutar → `insert` → broadcast → `run_actions()` fire-and-forget | ✅ **RECOMENDADA** |
| (b) Persistir y luego `UPDATE` desde `_apply_rules` | `insert` → (más tarde) `UPDATE events SET payload=… WHERE id=…` | ❌ Rechazada |
| (c) Segundo mensaje `rule_fired` correlacionado por `event.id` | WS aparte, sin tocar la persistencia | ❌ Rechazada como solución principal |

**Justificación de (a):**
1. Es la **única** que garantiza el orden por construcción: dentro de una sola corrutina la secuencia está definida por el lenguaje, no por el scheduler. Suprime la clase entera de bug, no una instancia.
2. Resuelve a la vez los **tres** consumidores del dato: la fila persistida (historial y `GET`), el push WS en vivo y las acciones. (b) y (c) solo arreglan uno.
3. Mantiene **una sola escritura** por evento. En WAL, cada `UPDATE` extra es otra transacción y otro fsync amortizado; con ráfagas de eventos por track eso se nota antes que cualquier otra cosa de esta fase.
4. No requiere columna nueva ni migración de datos (respeta D-15).
5. Preserva la propiedad que hoy protege al sistema: **las acciones lentas nunca bloquean la persistencia**. Un `webhook` colgado con (a) sigue sin poder perder el evento, porque `run_actions` va después del `INSERT` y en fire-and-forget.
6. Coste medido en código: ~25 líneas en `main.py` (los 4 `subscribe` pasan a 1) y ~20 en `rules.py` (partir `evaluate`). `evaluate()` se conserva como wrapper, así que `tests/test_rule_engine.py` (9,6 KB de tests) sigue verde sin tocarse.

**Por qué se rechaza (b):** deja una ventana real en la que un `GET /api/v2/events` devuelve el evento sin su chip de regla — que es exactamente el bug que la fase viene a arreglar, solo que más estrecho y por tanto más difícil de reproducir. Además necesita un método nuevo de repo con semántica de "merge del JSON" (leer-modificar-escribir, con su propia carrera si dos reglas actualizan a la vez) y duplica las escrituras. Su única ventaja —no tocar `RuleEngine`— no compensa.

**Por qué se rechaza (c):** no persiste nada. El centro de alertas agrupa por regla sobre **historial** (`GET /api/v2/alerts` mira las últimas N horas, incluida la parte anterior a que se abriera la página), y la timeline muestra el chip en eventos antiguos. Un mensaje efímero no cubre OPS-11. Sí es útil como complemento futuro (p. ej. notificar el resultado de una acción), no como mecanismo primario.

**Riesgos de (a) y su mitigación:**

| Riesgo | Mitigación |
|--------|-----------|
| `match()` lanza excepción y tumba el pipeline | `try/except` por paso (como en el snippet); un fallo de reglas no debe impedir persistir |
| El broadcast queda detrás del `INSERT` (~1 ms en WAL) | Aceptable: presupuesto de 1 s. A cambio se gana read-your-writes |
| `_broadcast_v1_compat` hace `await get_stats_today()` (consulta a la DB) por evento | Dejarlo en `ensure_future` al final: no muta el evento, solo lee |
| `tests/test_event_bus.py` o de arquitectura asumen 4 suscriptores | Verificado: **ningún test referencia los nombres de suscriptor de `main.py`** (`grep 'persistence\|_apply_rules' tests/` → 0 coincidencias). Vía libre |

**Clave del payload:** `payload["rules"] = ["<Rule.name>", …]` (lista, porque varias reglas pueden casar el mismo evento — `evaluate()` ya devuelve lista). No usar singular `rule`.

### Hallazgo 4 — no hay imagen del evento: `snapshot_path` nunca se escribe

`[VERIFIED: grep imwrite en backend/ → solo main.py:440 (galería de personas ya identificadas) y pipeline/recording.py:355 (miniatura de clip). grep snapshot_hook → solo la declaración y el fallback "sin snapshot_hook configurado, se ignora" en events/actions.py:117-121. No hay setting snapshot_dir en config.py]`

Consecuencias directas sobre el UI-SPEC:

| Fuente de miniatura (UI-SPEC §Fila, punto 3) | Estado real |
|---|---|
| 1º `snapshot_path` del evento | **Siempre `null` hoy.** Nadie escribe ese campo |
| 2º `/api/v2/recordings/{recording_id}/thumbnail` | Existe y funciona, **pero** `event.recording_id` tampoco se escribe nunca; el vínculo real es `recordings.trigger_event_id → events.id` (lo pone `_on_clip_ready`, `main.py:353-357`) |
| 3º marcador con icono de cámara | Sería el caso del 100 % de las filas si no se hace nada |

Y sobre el criterio 5 ("Marcar como persona **precarga el crop**"): la galería (`data/gallery/{person_id}/*.jpg`) solo se escribe en `on_identified` (`main.py:424-439,466`), es decir **solo para personas ya reconocidas**. Un `UNKNOWN_PERSON` —el caso exacto en el que quieres marcar a alguien— no tiene ninguna imagen guardada.

**Opciones para el planner (decidir explícitamente, no dejar implícito):**

1. **Recomendada — implementar el snapshot de evento** (habilita criterios 1 y 5 de verdad). Un paso más en `_event_pipeline`, antes del `insert`: si el evento trae `bbox` y su severidad no es `info` (o su tipo está en una lista corta), tomar el último frame con `camera_manager.get(cam).get_frame()` (ya se usa así desde código async en `enroll_face`, `main.py:923`), recortar y escribir `data/snapshots/{YYYYMMDD}/{event_id}.jpg` con `await asyncio.to_thread(cv2.imwrite, …)` (nunca `imwrite` directo en el event loop), y fijar `event.snapshot_path`. Montar `app.mount("/snapshots", StaticFiles(...))` igual que `/gallery` y `/clips` (`main.py:630-637`). Coste: ~40 líneas + 1 setting + throttle. Riesgos: disco (una JPEG de 64×36…320×180 son KB) y que el frame haya avanzado unos ms respecto al evento (irrelevante para un crop de contexto). **Ojo:** esto convierte el `_snapshot_hook` de `actions.py` —hoy muerto— en algo real; conviene cablearlo por ahí (`event_actions.configure(snapshot_hook=…)`) para no crear un segundo mecanismo.
2. **Mínima** — sin snapshot: la miniatura cae siempre al marcador salvo eventos con clip, y "Marcar como persona" usa `use_current_frame=true` (la cámara *ahora*, no el evento). Cumple la letra de OPS-08 pero no el criterio 5 ("precarga el crop"), y deja la timeline visualmente pobre. Si se elige esta, hay que decirlo en el plan y en el SUMMARY, no descubrirlo en el checkpoint visual.

**Resolución del clip/miniatura sin `event.recording_id`:** añadir `RecordingRepo.by_trigger_event_ids(ids: list[str]) -> dict[str, dict]` con `WHERE trigger_event_id IN (:ids)`, una sola consulta por página (≤200 ids). La tabla `recordings` es pequeña y no tiene índice por `trigger_event_id`; un escaneo completo ahí es despreciable comparado con añadir otro índice.

### Hallazgo 5 — `person_name` no sobrevive a la persistencia

`Event` (Pydantic) tiene `person_name` (`events/types.py:68`) pero `models.Event` **no tiene esa columna** y `_to_row`/`_to_dto` (`repositories.py:47-80`) no la mapean. Es decir:

- El evento que llega por WebSocket **sí** trae `person_name` (viene del objeto en memoria, lo pone `emit_identity`, `engine.py:233`).
- El mismo evento leído por `GET /api/v2/events` **no**: sale con `person_name = None` y solo `person_id`.

Para la timeline eso significa que "Juan entró en la zona jardín" no se puede componer solo con la respuesta del endpoint. Además, las personas viven en **otra base de datos**: `PersonRecognizer` usa `settings.db_path.replace("events.db","persons.db")` (`main.py:335`) con su propia tabla `persons` (`recognizer.py:337`), mientras que la tabla `persons` de `models.py:44` está sin usar para identidad. **No hay JOIN posible en SQL.**

**Recomendación:** el frontend carga una vez `GET /persons` (ya lo hace `personGallery.js:6` cada 30 s) y mantiene un `Map<person_id, name>` para resolver el nombre al pintar la fila. Es la única vía sin fusionar bases de datos, que está fuera de alcance. Documentarlo: si una persona se renombra, las filas ya pintadas no cambian hasta el siguiente refresco del mapa.

*(Alternativa descartada: persistir `person_name` como columna nueva — desnormaliza, exige migración y contradice D-15.)*

### Hallazgo 6 — actualización retroactiva por `track_id` (criterio 5)

Restricciones verificadas:
- `events.track_id` **no tiene índice** (los cuatro índices son por `ts`, `type+ts`, `camera_id+ts`, `person_id+ts`). Medido: `COUNT(*) WHERE track_id=? AND camera_id=?` = 23 ms @100k / ~2 ms @10k. Aceptable a la escala de la fase.
- La tabla `tracks` (con `started_at`/`ended_at`) **nunca se escribe** — no se puede acotar la ventana consultándola.
- Los ids de ByteTrack **se reinician** al recrear el tracker (`backend/tracker.py:181`), así que `track_id=7` de hoy y `track_id=7` de anteayer son personas distintas.

**Algoritmo recomendado (determinista y testeable):**

```
1. GET /api/v2/events/{id}  → ancla: camera_id, track_id, ts
2. SELECT id, ts, type FROM events
   WHERE camera_id=:cam AND track_id=:tid AND ts BETWEEN :ts-6h AND :ts+6h
   ORDER BY ts                              -- acotado ⇒ usa idx_events_cam_ts / ts_id
3. En Python: quedarse con el bloque CONTIGUO que contiene el ancla, cortando en el
   primer hueco > TRACK_GAP_SECS (p. ej. 60 s; ByteTrack pierde el track a los
   LOST_TRACK_BUFFER=60 frames ≈ 4 s @15 fps, así que 60 s es un margen holgado).
4. UPDATE events SET person_id=:pid,
          severity = CASE WHEN type='UNKNOWN_PERSON' THEN 'info' ELSE severity END
   WHERE id IN (:ids)                       -- lista explícita, nunca WHERE track_id
5. Devolver {"person_id": …, "updated": N, "event_ids": [...]}
```

El paso 2 y 3 sirven además al **preview** que exige D-06/UI-SPEC ("Se aplicará también a los eventos anteriores de este track (N)"): el mismo cálculo, sin el `UPDATE`. Recomendación de API: `GET /api/v2/events/{id}/track-scope` → `{"count": N, "from": ts, "to": ts}`, y `POST /api/v2/events/{id}/assign-person` con `{"name": "..."}` o `{"person_id": N}`.

El enrolado en sí debe delegar en lo que ya existe (`/api/enroll_face`, que valida `content_type`, tamaño ≤10 MB y `max_length=100` del nombre — con tests de regresión de seguridad asociados). Duplicar esa validación en un endpoint nuevo sería regresión de seguridad; llamar al recognizer directamente desde el nuevo endpoint obliga a replicarla. **Recomendación:** el frontend hace primero `POST /api/enroll_face` (obtiene `person_id`) y luego `POST /api/v2/events/{id}/assign-person {"person_id": …}`. Dos llamadas, cero duplicación de validaciones.

### Hallazgo 7 — índices: medición real, no conjeturas

Banco de pruebas ejecutado en esta sesión: SQLite 3.49.1, tabla `events` con el esquema real y los 4 índices reales, **100.000 filas** (10× el objetivo del criterio 3) y una copia de **10.000 filas**. Consulta patrón: `SELECT * … ORDER BY ts DESC, id DESC LIMIT 50`.

**@100.000 filas, solo con los índices actuales:**

| Consulta | Plan | Tiempo |
|----------|------|--------|
| Primera página sin filtro | `SCAN … USING INDEX idx_events_ts` + **TEMP B-TREE FOR LAST TERM OF ORDER BY** | 0,56 ms |
| Cursor profundo `(ts,id) < (?,?)` | `SEARCH … idx_events_ts (ts<?)` + TEMP B-TREE | 0,49 ms |
| `severity + zone_id + rango 30 d` | `SEARCH … idx_events_ts (ts>? AND ts<?)` + TEMP B-TREE | 0,74 ms |
| **`type IN (3 valores) + severity`** | `SEARCH … idx_events_type_ts (type=?)` + **TEMP B-TREE FOR ORDER BY** | **53,7 ms** |
| `severity` sola, rango completo | **`SCAN events`** (tabla) + TEMP B-TREE | 19,0 ms |
| `COUNT(*)` con filtros | `SCAN events` | 18,8 ms |
| Filtro por regla (`json_each`) | `SCAN … idx_events_ts` + subconsulta correlacionada | 1,15 ms |
| `COUNT(*) WHERE track_id=? AND camera_id=?` | `SEARCH … idx_events_cam_ts` | 23,2 ms |

**@100.000 filas, tras `CREATE INDEX idx_events_ts_id ON events (ts DESC, id DESC)`:**

| Consulta | Plan | Tiempo |
|----------|------|--------|
| Primera página | `SCAN … idx_events_ts_id` — **sin TEMP B-TREE** | 0,62 ms |
| Cursor profundo | `SEARCH … idx_events_ts_id ((ts,id)<(?,?))` — seek exacto por valor de fila | 0,50 ms |
| `severity` sola | `SCAN … idx_events_ts_id` | 0,60 ms (**×32**) |
| Filtro por regla | `SCAN … idx_events_ts_id` | 0,66 ms |
| `type IN (3) + severity` | sigue eligiendo `idx_events_type_ts` + TEMP B-TREE | 54,3 ms (sin mejora) |
| `type IN (3) + severity` con **`+events.type`** | `SCAN … idx_events_ts_id` | **0,52 ms** (×104) |

**@10.000 filas (la escala real del criterio 3), solo índices actuales:** el peor caso es `type IN + severity` con **1,66 ms**; `severity` sola 1,01 ms; `COUNT` filtrado 0,90 ms; cursor profundo 0,39 ms.

**Conclusiones y recomendación:**

1. **A 10.000 eventos el criterio 3 se cumple ya, sin tocar nada** (todo ≤1,7 ms). Cualquier degradación perceptible que aparezca en el checkpoint vendrá del renderizado, no de SQLite. Esto reorienta el esfuerzo del plan hacia la virtualización.
2. **Añadir `idx_events_ts_id (ts DESC, id DESC)` igualmente.** Es la única forma de que el cursor por valor de fila haga *seek* en el índice en vez de filtrar tras leer la fila, y elimina el `TEMP B-TREE` de toda consulta filtrada. Da 10× de margen (mantiene <1 ms a 100k) por el coste de un índice en una tabla que ya tiene cuatro. Requiere `SCHEMA_VERSION` 2→3 (`create_all()` no añade índices a tablas existentes, verificado en `migrations.py:99-100` + `run_migrations` con `return` temprano).
3. **NO añadir índices compuestos por `severity` ni por `zone_id`** (responde a D-11): con `idx_events_ts_id`, `severity` sola baja a 0,60 ms y `severity+zone+rango` a 0,88 ms. Un índice por combinación de filtros sería 2^n índices para nada — y SQLite usa **un** índice por referencia de tabla, así que ni siquiera se combinarían.
4. **El único caso patológico medido es `type IN (…)` con ≥2 valores.** SQLite prefiere `idx_events_type_ts` y luego ordena todo el conjunto. Escape verificado: prefijo `+` unario en ese término (`+events.type IN :types`), que desactiva el índice solo ahí. Aplicarlo **únicamente** cuando se piden ≥2 tipos.
5. **`with_hint()` de SQLAlchemy NO sirve aquí.** `[VERIFIED: compilado en esta sesión — select().with_hint(models.Event, "INDEXED BY idx_events_ts_id") produce "FROM events" sin la cláusula; el dialecto SQLite de SQLAlchemy 2.0.49 ignora los hints genéricos]`. Si alguien planifica `INDEXED BY`, tiene que ir por `text()`.
6. **`ANALYZE`:** no es responsable de las mejoras (se comprobó dejando las estadísticas y quitando el índice: el plan malo vuelve). No hace falta añadirlo al arranque.

### Hallazgo 8 — dónde guardar el silenciado (resuelve D-17)

**Decisión: `app_config` vía `ConfigRepo`, clave `alerts.muted_rules`.**

```jsonc
// ConfigRepo.set("alerts.muted_rules", { … })
{ "Intrusión nocturna": { "until": "2026-08-20T19:15:00", "camera_id": null } }
```

Justificación frente a una tabla `muted_rules`:
- `ConfigRepo` ya existe, está probado (`test_repositories.py` lo importa) y hace upsert de un JSON arbitrario (`repositories.py:630-639`). Coste: 0 líneas de esquema.
- Una tabla nueva implica `SCHEMA_VERSION` +1 (ya se gasta uno en el índice; dos migraciones en una fase es peor), un repo nuevo, sus tests y su modelo, para almacenar **como mucho tantas filas como reglas haya en `rules.yaml`** (hoy un puñado).
- La cardinalidad y el patrón de acceso (lectura completa en cada `GET /api/v2/alerts`, escritura rara) son exactamente los de una clave de configuración, no los de una tabla.

**TTL/limpieza:** perezosa. Al leer, se descartan las entradas con `until <= now` y no se muestran; al escribir (silenciar o reactivar), se reescribe el diccionario ya purgado. Sin tarea de fondo, sin cron. Consecuencia aceptada: una entrada caducada puede quedar en la fila de `app_config` hasta la siguiente escritura; es invisible y ocupa bytes.

**Concurrencia:** `ConfigRepo.set` es leer-modificar-escribir sobre una fila. Con un operador y una pestaña es irrelevante, pero conviene serializar los `POST /api/v2/alerts/mute` con un `asyncio.Lock` de módulo (3 líneas) para que dos silenciados simultáneos no se pisen.

**Semántica del silencio — decidir explícitamente:** silenciar es **solo de presentación**. La regla sigue evaluándose, sus acciones siguen ejecutándose (sigue grabando el clip, sigue mandando el Telegram si así está configurado) y el evento sigue persistiéndose; lo que cambia es que su grupo sale atenuado en el cajón, no cuenta para el badge de la campana y desaparece del top-3 de la Fase 29. Motivo: silenciar desde la UI no debe hacerte **perder pruebas**. Si en el futuro se quiere un "mute duro" (suprimir acciones), sería un flag distinto y una decisión de producto aparte.

### Hallazgo 9 — `GET /api/v2/timeline`: NO hacerlo (resuelve el punto abierto de discreción)

El wireframe solo pide separadores por hora y por día (`.timeline-sep`, "Hoy · 18:00" / "12 ago · 09:00"). Con la lista ya ordenada por `ts DESC` que devuelve `/api/v2/events`, el separador se calcula comparando la hora de cada fila con la anterior: **una línea de JS**, cero red, cero SQL, y funciona igual durante el scroll infinito (el separador se inserta al añadir la página). Un endpoint de agrupación por bloques introduciría un segundo contrato de paginación que habría que mantener sincronizado con el primero. Dejarlo anotado como diferido a la Fase 31 si alguna vista de analítica necesita bloques agregados en SQL.

### Hallazgo 10 — "Descartar" (OPS-08): estado de cliente

UI-SPEC: *"oculta el evento de la línea temporal con toast de deshacer. No borra nada de la base de datos"*. Recomendación: `localStorage` con una clave `timeline.dismissed` = array de `event_id` con tope (p. ej. 500, FIFO). Sin endpoint, sin tabla, sin migración. Sobrevive a recargas —que es lo que el operador espera después de descartar— y el "Deshacer" de 5 s es simplemente no haber escrito todavía en `localStorage`, o quitar el id. El filtrado se aplica al pintar, nunca en la consulta (el servidor no debe saber qué ha descartado un navegador concreto).

---

## Code Examples

### Extender `EventRepo.query` con multi-tipo, total y regla

```python
# Source: extensión verificada de backend/storage/repositories.py:92-141
async def query(
    self, *,
    type: EventType | list[EventType] | None = None,   # se conserva el nombre: database.py lo usa
    severity: Severity | None = None,
    person_id: int | None = None, zone_id: str | None = None, camera_id: str | None = None,
    rule: str | None = None,
    ts_from: datetime.datetime | None = None, ts_to: datetime.datetime | None = None,
    cursor: str | None = None, limit: int = 50, with_total: bool = False,
) -> tuple[list[EventDTO], str | None, int | None]:
    conditions, params = [], {}
    types = [type] if isinstance(type, EventType) else (list(type) if type else [])
    if len(types) == 1:
        conditions.append(models.Event.type == types[0].value)
    elif len(types) > 1:
        # '+' unario: evita que SQLite elija idx_events_type_ts y ordene con TEMP B-TREE
        conditions.append(text("+events.type IN :types").bindparams(
            bindparam("types", expanding=True)))
        params["types"] = [t.value for t in types]
    if rule is not None:
        conditions.append(text(
            "EXISTS (SELECT 1 FROM json_each(events.payload, '$.rules') je WHERE je.value = :rule)"
        ))
        params["rule"] = rule
    # … resto de condiciones idéntico al actual, incluido el cursor tuple_(ts,id) < (…)
```

### Índice + migración

```python
# backend/storage/models.py — dentro de Event.__table_args__
Index("idx_events_ts_id", ts.desc(), id.desc()),   # cursor (ts,id) y ORDER BY sin TEMP B-TREE

# backend/storage/migrations.py
SCHEMA_VERSION = 3

def _migrate_v2_to_v3(conn: Connection) -> None:
    """Índice compuesto para la línea temporal (Fase 30). create_all() no crea índices
    sobre tablas que ya existen, por eso va explícito."""
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_events_ts_id ON events (ts DESC, id DESC)"))
    conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
    conn.execute(text(
        "INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', :v, :now)"),
        {"v": json.dumps(SCHEMA_VERSION), "now": datetime.datetime.now().isoformat(sep=" ")})

MIGRATIONS = [
    (2, "esquema v2 completo", _migrate_v1_to_v2),
    (3, "indice compuesto de la linea temporal", _migrate_v2_to_v3),
]
```

### Fila de la timeline sin XSS (patrón obligatorio del repo)

```javascript
// Source: patrón de frontend/js/components/eventCard.js:16-34 (CodeQL js/xss)
function timelineRow(ev, media, personName) {
  const row = document.createElement('div');
  row.className = 'timeline-row';
  row.dataset.id = ev.id;
  row.dataset.trackId = ev.track_id ?? '';
  row.style.setProperty('--sev', SEV_COLOR[ev.severity]);   // barra de 3px por variable CSS
  row.innerHTML = `
    <span class="sev-bar" aria-hidden="true"></span>
    <span class="tl-time mono text-xs text-slate-400"></span>
    <img class="tl-thumb" width="64" height="36" loading="lazy" alt="">
    <span class="tl-desc text-xs font-semibold text-slate-200 truncate"></span>
    <span class="tl-zone chip" hidden></span>
    <span class="tl-rule rule-chip mono" hidden></span>
    <span class="tl-actions"></span>`;
  // NUNCA interpolar: nombre de persona y nombre de regla vienen de datos del usuario
  row.querySelector('.tl-time').textContent = new Date(ev.ts)
      .toLocaleTimeString('es-ES', { hour12: false });
  row.querySelector('.tl-desc').textContent = describe(ev, personName);
  const rules = ev.payload?.rules ?? [];
  if (rules.length) {
    const chip = row.querySelector('.tl-rule');
    chip.textContent = `⚡ ${rules[0]}`;          // textContent, no innerHTML
    chip.title = rules.join(' · ');
    chip.hidden = false;
  }
  const thumb = row.querySelector('.tl-thumb');
  const src = media?.snapshot_url ?? media?.thumbnail_url;
  if (src) thumb.src = src; else thumb.replaceWith(placeholderThumb());
  return row;
}
```

### Centinela de scroll infinito (UI-SPEC: `IntersectionObserver`, nunca `scroll`)

```javascript
// rootMargin 200px: pide la página siguiente antes de llegar al final (UI-SPEC)
const io = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && cursor && !loading) loadNextPage();
}, { root: container, rootMargin: '200px' });
io.observe(sentinel);
```

---

## State of the Art

| Enfoque antiguo (en este repo) | Enfoque de esta fase | Impacto |
|---|---|---|
| Card `#events-list` con `addEvent()` y filtros client-side sobre `/api/events` (v1, tabla `crossing_events`) | Timeline sobre `/api/v2/events` (eventos tipados) con filtros en servidor | El endpoint v1 `/api/events` y `applyFilters()` quedan obsoletos para eventos; el CSV export (`/api/events/export`) sigue apuntando a v1 — decidir si se migra o se deja (queda fuera de OPS-07..11) |
| `type:"detection"` como único evento en vivo | `type:"event"` con el `Event` tipado completo | La gráfica horaria y los contadores siguen alimentándose de `detection`; no tocarlos |
| Reglas que "se pierden" tras dispararse (solo log/acciones) | `payload.rules` persistido | Historial auditable de qué regla disparó qué, base de OPS-11 |

**Obsoleto / a retirar en esta fase:**
- `dashboard-events.js::addEvent`, `applyFilters`, `bindEventFilters`, `_eventsFilterParams` y los `#filter-*` del HTML: sustituidos por la barra de filtros de la timeline.
- `loadActiveAlerts()` en `dashboard.js`: se muda a `alertCenter.js` y pasa a alimentarse de `/api/v2/alerts` (agrupado) en vez de `/api/v2/events?limit=10` filtrado en el navegador.
- Los cuatro `event_bus.subscribe(...)` de `main.py:303-306`: uno solo.

---

## Common Pitfalls

### Pitfall 1: Confiar en el orden entre suscriptores del bus
**Qué falla:** el chip de regla no aparece nunca (o aparece de forma intermitente) en los eventos persistidos.
**Por qué:** `bus.py:69` programa cada handler con `ensure_future`; el orden lo decide el scheduler y el primer `await` de cada handler.
**Cómo evitarlo:** un único suscriptor ordenado (Hallazgo 3).
**Señal temprana:** un test que publique un evento que case una regla y luego lea la fila con `EventRepo.get()` — hoy fallaría; debe ser uno de los primeros tests de la fase.

### Pitfall 2: `type IN (…)` degrada la consulta 100×
**Qué falla:** al activar 2-3 chips de tipo, la primera página tarda ~54 ms @100k (~1,7 ms @10k) por un `TEMP B-TREE FOR ORDER BY`.
**Por qué:** SQLite prefiere `idx_events_type_ts` y luego tiene que ordenar todo el conjunto por `ts,id`.
**Cómo evitarlo:** prefijo `+` unario en ese término cuando hay ≥2 tipos.
**Señal temprana:** `EXPLAIN QUERY PLAN` con `USE TEMP B-TREE FOR ORDER BY` (sin el "LAST TERM OF").

### Pitfall 3: `track_id` no es único en el tiempo
**Qué falla:** "Marcar como persona" asigna la identidad a eventos de otra persona de otro día.
**Por qué:** ByteTrack reinicia los ids al recrear el tracker; la tabla `tracks` nunca se escribe.
**Cómo evitarlo:** acotar por `camera_id` + ventana temporal + contigüidad (Hallazgo 6). Nunca `WHERE track_id = ?` a secas en un `UPDATE`.
**Señal temprana:** el preview "se aplicará a N eventos" devuelve un N absurdo (decenas o cientos).

### Pitfall 4: 300 líneas por módulo de frontend
**Qué falla:** `pytest tests/test_frontend_modules.py` en rojo al final de la fase.
**Por qué:** `TEST_line_limit` recorre `frontend/js/**/*.js` y `frontend/css/*.css` con tope 300. `dashboard.js` está a 290.
**Cómo evitarlo:** ficheros nuevos (`views/timeline.js`, `components/alertCenter.js`) y mudar `loadActiveAlerts` fuera de `dashboard.js`. Vigilar también `components.css` (82 → +7 bloques nuevos).
**Señal temprana:** `wc -l frontend/js/**/*.js` en cada commit.

### Pitfall 5: endpoint v2 sin rate limit o sin cap de `limit`
**Qué falla:** `TEST_all_v2_endpoints_rate_limited` y `TEST_all_v2_list_endpoints_have_limit_cap` en rojo.
**Por qué:** son tests de regresión de seguridad que recorren `app.routes` automáticamente.
**Cómo evitarlo:** `@limiter.limit(V2_RATE_LIMIT)` + `request: Request` en la firma + `limit = pagination_limit()` en todo endpoint de lista nuevo.

### Pitfall 6: doble pintado del evento de cruce de línea
**Qué falla:** cada `LINE_CROSSED` aparece dos veces en la timeline.
**Por qué:** llegan `type:"event"` (nuevo) y `type:"detection"` (legacy) para el mismo evento.
**Cómo evitarlo:** quitar `addEvent(...)` del `case 'detection'` conservando `updateStat`/`bumpHourBar`/`showToast`.

### Pitfall 7: `innerHTML` con nombre de persona o de regla
**Qué falla:** XSS almacenado; CodeQL `js/xss` lo marca.
**Por qué:** ambos son texto controlable por el usuario (nombre de enrolado, `rules.yaml`).
**Cómo evitarlo:** estructura estática por `innerHTML`, contenido por `textContent`/`dataset` (patrón ya documentado en `eventCard.js:16-18`).

### Pitfall 8: `cv2.imwrite` en el event loop
**Qué falla:** micro-pausas en el loop que afectan a MJPEG y WS.
**Por qué:** CLAUDE.md ("no ejecutar CPU pesado en el event loop"); `_event_pipeline` es una corrutina.
**Cómo evitarlo:** `await asyncio.to_thread(cv2.imwrite, path, crop)` si se implementa el snapshot (Hallazgo 4, opción 1).

### Pitfall 9: `total` en cada página
**Qué falla:** cada scroll dispara un `COUNT(*)` de 19-21 ms @100k.
**Cómo evitarlo:** calcular `total` solo en la primera página (`cursor is None`) y solo si hay filtros; devolver `null` en las siguientes y no tocar el contador del card.

### Pitfall 10: colisión de rutas `/api/v2/events`
**Qué falla:** comportamiento dependiente del orden de registro entre el endpoint de `main.py:829` y el router nuevo.
**Cómo evitarlo:** borrar el de `main.py` en el mismo commit que introduce `backend/api/v2/events.py`.

---

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|---|---|---|---|---|
| Python + venv | todo | ✓ | 3.12.10 (`.venv/Scripts/python.exe`) | — |
| SQLite (stdlib) | cursor, `json_each`, índices DESC | ✓ | 3.49.1 | — |
| SQLAlchemy async + aiosqlite | repos | ✓ | 2.0.49 | — |
| pytest / pytest-asyncio | tests | ✓ | `pytest.ini` con `asyncio_mode=auto` | — |
| `scripts/seed_events.py` | test de 10k del criterio 3 | ✓ | en repo | — |
| Cámara Tapo C212 real | checkpoint visual (miniaturas reales, evento en vivo <1 s) | ✗ en esta sesión | — | Checkpoint manual diferido, mismo patrón que los 8 checkpoints anteriores del proyecto (ver STATE.md); los tests deterministas cubren la lógica |
| Navegador para verificar virtualización | criterio 3 (sin degradación perceptible) | ✗ automatizable (no hay framework JS de test, sin `package.json`) | — | Checklist manual firmado en el SUMMARY de la puerta de fase, igual que hizo la Fase 28 (`test_frontend_modules.py` docstring) |

**Dependencias ausentes sin fallback:** ninguna bloquea la implementación.
**Dependencias ausentes con fallback:** verificación visual y con cámara real → checkpoint manual documentado, no automatizado.

---

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|-----------|-------|
| Framework | pytest + pytest-asyncio |
| Fichero de config | `pytest.ini` (`python_functions = TEST_*`, `asyncio_mode = auto`) — **las funciones de test deben llamarse `TEST_*`** |
| Fixtures compartidas | `tests/conftest.py` (`fake_frame`, `mock_video_capture`) + fixture local `db` en `tests/test_repositories.py:20-31` (async engine sobre `tmp_path`) |
| Quick run | `.venv/Scripts/python.exe -m pytest tests/test_repositories.py tests/test_rule_engine.py -q` |
| Full suite | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s; CLAUDE.md pide no lanzarla en cada paso) |

### Phase Requirements → Test Map

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|-----|----------------|------|----------------------|----------|
| OPS-09 | Filtros combinables + cursor devuelven páginas disjuntas y ordenadas | unit | `pytest tests/test_repositories.py -k "cursor or filters" -q` | ⚠ parcial (`TEST_query_by_type_and_range` existe; falta multi-tipo, `rule`, `total`) |
| OPS-09 | 10.000 eventos: primera página y página profunda por debajo del presupuesto | perf | `pytest tests/test_repositories.py -k performance -q` | ⚠ existe `TEST_query_performance_100k` (<0,5 s); añadir uno de página profunda con cursor |
| OPS-09 | El endpoint respeta `limit<=200` y lleva rate limit | security | `pytest tests/test_security_regression.py -k "v2" -q` | ✅ automático (recorre `app.routes`) |
| OPS-11 | Un evento que casa una regla se persiste **con** `payload.rules` | unit | `pytest tests/test_event_bus.py -k rules_persisted -q` | ❌ Wave 0 — **es el test que demuestra que la carrera está arreglada** |
| OPS-11 | `evaluate()` sigue comportándose igual tras partirlo en `match`/`run_actions` | unit | `pytest tests/test_rule_engine.py -q` | ✅ existe (9,6 KB); debe pasar **sin modificarse** |
| OPS-11 | Silenciar una regla la excluye del recuento y del top-3, y expira sola | unit | `pytest tests/test_alerts.py -q` | ❌ Wave 0 |
| OPS-10 | El pipeline emite `type:"event"` por `/ws` tras persistir | unit | `pytest tests/test_event_bus.py -k broadcast_order -q` | ❌ Wave 0 |
| OPS-08 | Asignación retroactiva actualiza solo el bloque contiguo del track | unit | `pytest tests/test_repositories.py -k assign_person -q` | ❌ Wave 0 |
| OPS-07/08 | Módulos nuevos ≤300 líneas y sin lógica inline | mecánico | `pytest tests/test_frontend_modules.py -q` | ✅ existe (añadir `views/timeline.js` y `components/alertCenter.js` a `LOCKED_JS`) |
| OPS-07 | Migración a `SCHEMA_VERSION=3` crea el índice y es idempotente | unit | `pytest tests/test_migrations.py -q` | ⚠ ampliar (el fichero ya prueba la migración v1→v2) |
| Criterio 1/3/4/5/6 | Aspecto visual, fluidez del scroll, <1 s percibido | manual | checkpoint firmado en el SUMMARY | ❌ manual por diseño (no hay runner JS) |

### Sampling Rate

- **Por commit de tarea:** el fichero tocado (`pytest tests/test_X.py -q`) — CLAUDE.md prohíbe la suite completa en cada paso.
- **Por merge de wave:** `pytest tests/test_repositories.py tests/test_rule_engine.py tests/test_event_bus.py tests/test_migrations.py tests/test_security_regression.py tests/test_frontend_modules.py -q`.
- **Puerta de fase:** suite completa verde (toca pipeline de eventos, API y configuración → CLAUDE.md § Tests punto 2) + checkpoint visual manual.

### Wave 0 Gaps

- [ ] `tests/test_event_bus.py` — dos tests nuevos: `rules_persisted` (evento que casa regla → fila con `payload.rules`) y `broadcast_order` (el mensaje WS sale después del insert y ya lleva `rules`). Cubren OPS-10/OPS-11.
- [ ] `tests/test_alerts.py` (nuevo) — agrupación por regla, silenciado, expiración por TTL, exclusión del top-3.
- [ ] `tests/test_repositories.py` — ampliar: `type` multi-valor, filtro `rule` vía `json_each`, `total`, cursor profundo con 10k filas sembradas, `assign_person` con contigüidad y con dos tracks homónimos separados en el tiempo (regresión del Pitfall 3).
- [ ] `tests/test_migrations.py` — `SCHEMA_VERSION=3`: el índice existe tras migrar una base v2 preexistente, y volver a migrar es no-op.
- [ ] `tests/test_frontend_modules.py` — añadir los dos módulos nuevos a `LOCKED_JS`.
- [ ] Framework: **ninguna instalación** — todo el instrumental existe.

---

## Security Domain

### Applicable ASVS Categories

| Categoría ASVS | Aplica | Control estándar en este repo |
|----------------|--------|-------------------------------|
| V2 Authentication | sí | Auth Basic global vía `FastAPI(dependencies=[Depends(verify)])`; los routers incluidos la heredan (documentado en `api/v2/deps.py:3-5`). **No añadir `Depends(verify)` por ruta** |
| V3 Session Management | sí (WS) | `issue_ws_token()` / `verify_ws_token()` con TTL (`TEST_vuln_05_ws_token_expires_after_ttl`); reutilizar el `/ws` existente hereda el control |
| V4 Access Control | parcial | El sistema es todo-o-nada, sin roles. **Nota:** `POST /api/v2/alerts/mute` y `assign-person` mutan estado; el mismo razonamiento de `detection.py:8-13` aplica (rate limit + validación estricta + rastro en el historial). Considerar emitir `CONFIG_CHANGED` al silenciar una regla, por trazabilidad |
| V5 Input Validation | sí | Pydantic/`Query` con `ge/le`; `pagination_limit()` cap 200; validar `severity`/`type` contra los enums y devolver 400 (patrón ya en `main.py:846-850`); duración de silenciado en una lista blanca (900/3600/28800 s), nunca un entero libre |
| V6 Cryptography | no | Nada nuevo cifra ni firma |
| V7 Error Handling | sí | `HTTPException(status_code, detail)`; el frontend ya normaliza vía `apiFetch` |
| V12 File Resources | sí (si se hace el snapshot) | Nombre de fichero derivado de `event_id` (uuid4), nunca de entrada del usuario; servir por `StaticFiles` bajo un directorio dedicado, como `/gallery` y `/clips` |

### Known Threat Patterns

| Patrón | STRIDE | Mitigación estándar |
|--------|--------|---------------------|
| XSS almacenado vía `person_name` / `Rule.name` en la fila o el chip | Tampering | `textContent`, nunca `innerHTML` interpolado (patrón obligatorio del repo, CodeQL `js/xss`) |
| Inyección SQL en el filtro `rule` (va dentro de un `text()`) | Tampering | `bindparam`, jamás f-string. Igual con `types` (`expanding=True`) |
| Path traversal en `snapshot_url` / `clip_url` | Tampering | URLs construidas en servidor a partir de ids; el cliente nunca envía rutas |
| DoS por `limit` enorme o por `COUNT(*)` en cada scroll | DoS | `pagination_limit()` (cap 200) + `total` solo en la primera página |
| Enumeración de identidades desde un endpoint de eventos | Info disclosure | `/api/v2/events` ya expone `person_id`; **no** añadir `person_name` a la respuesta (además de que no está persistido). El mismo criterio que `context.py:9-11` ("de solo recuentos, nunca identidad") |
| Silenciar una regla crítica sin rastro | Repudiation | Silencio solo de presentación (las acciones siguen corriendo) + registro del cambio |

---

## Assumptions Log

| # | Afirmación | Sección | Riesgo si es falsa |
|---|-----------|---------|--------------------|
| A1 | La ventana de contigüidad de track de 60 s (y el rango de ±6 h) es adecuada para el patrón real de la cámara | Hallazgo 6 | Se asigna la identidad a menos (o más) eventos de los esperados; se ajusta con un setting, no cambia el diseño |
| A2 | Guardar en memoria del navegador el array completo de 10.000 eventos (~2,5 MB) es aceptable | Hallazgo 1 | Si no lo fuera, hay que implementar cursor inverso; el diseño de la timeline no cambia, solo añade un parámetro |
| A3 | Los nombres de regla de `rules.yaml` no contienen caracteres que rompan el `json_each` exacto | Hallazgo 1 | Ninguno real: la comparación es por igualdad con bindparam, no por `LIKE` |
| A4 | Una ventana de 24 h es la adecuada para "alertas activas" del cajón | Hallazgo 8 | Solo afecta a cuántos grupos se ven; parametrizable |
| A5 | El operador espera que "Descartar" sobreviva a una recarga (de ahí `localStorage`) | Hallazgo 10 | Si no, se degrada a memoria de sesión: menos código |
| A6 | La duración de silenciado se limita a 15 min / 1 h / 8 h (UI-SPEC) y no hace falta "para siempre" | Hallazgo 8 | Solo cambia la lista blanca de validación |

*(Todo lo demás de este documento está verificado leyendo el código del repo o midiendo en esta sesión.)*

---

## Open Questions

1. **(RESOLVED — 30-04-PLAN.md)** ¿Se implementa el snapshot de evento (Hallazgo 4, opción 1) dentro de esta fase?
   - Lo que sabemos: sin él, la miniatura cae al marcador en casi todas las filas y "Marcar como persona" no puede precargar el crop del evento (usaría el frame actual). Ambas cosas están en los criterios 1 y 5.
   - Lo que no está claro: si el usuario prefiere cerrar OPS-07/08 al 100 % ahora (+~40 líneas, +1 directorio en disco, +1 mount) o aceptar la versión degradada y dejar el snapshot para una fase de medios.
   - Recomendación: **implementarlo**, acotado (solo eventos con `bbox` y severidad ≠ `info`, con throttle por track como el de la galería) y con un setting `snapshot_dir` + `snapshot_enabled`. Es la única pieza de la fase que crea datos nuevos, así que conviene decidirlo antes de planificar, no durante.
   - **Resuelto:** implementado en `30-04-PLAN.md` (opción 1, no la versión degradada) — `asyncio.to_thread` para `cv2.imwrite`, throttle por track, settings `snapshot_dir`/`snapshot_enabled`.

2. **(RESOLVED — 30-07-PLAN.md)** ¿Se migra también el botón "Exportar CSV" a v2?
   - `#btn-export-csv` apunta a `/api/events/export` (v1, `crossing_events`) y los filtros que le pasa (`direction`, `person_name`, `is_intrusion`) desaparecen con la barra de filtros vieja.
   - No está en OPS-07..11. Opciones: dejarlo funcionando con parámetros vacíos (exporta todo), ocultarlo, o exportar la consulta v2 actual (trabajo extra).
   - Recomendación: dejarlo intacto pero fuera de la barra de filtros nueva, y anotarlo para OPS-15 (Fase 31, "analítica exportable a CSV y JSON").
   - **Resuelto:** se deja intacto sin tocar filtros, anotado en `30-07-PLAN.md` para OPS-15/Fase 31 — sin trabajo extra en esta fase.

3. **(RESOLVED — 30-06-PLAN.md)** ¿El silenciado debe llegar también a las acciones (Telegram/grabación) o es solo visual?
   - Este research decide "solo visual" (Hallazgo 8) por seguridad de la evidencia, pero es una decisión de producto que el usuario podría querer al revés.
   - Recomendación: confirmar en el plan con una frase explícita en el SUMMARY; si se quisiera el mute duro, sería un segundo flag por regla, no un cambio de este diseño.
   - **Resuelto:** `30-06-PLAN.md` implementa el silenciado como solo-presentación (la regla sigue evaluando y ejecutando acciones), con criterio de aceptación explícito que lo verifica.

---

## Project Constraints (from CLAUDE.md)

Directivas accionables que el plan debe respetar (misma autoridad que las decisiones bloqueadas):

- **Stack cerrado.** Prohibido introducir WebRTC, Docker, PostgreSQL, React/Vue, bundlers "ni capas equivalentes sin decisión explícita". Esta fase no añade ninguna dependencia — ni de Python ni de JS.
- **Sin `python-dotenv`;** configuración por `pydantic-settings` + `@lru_cache` en `backend/config.py`. Cualquier setting nuevo (`snapshot_dir`, ventana de alertas, TTL) va ahí.
- **Nunca exponer credenciales RTSP** en código, logs, commits ni respuestas.
- **"No ejecutar CPU pesado en el event loop"** → cualquier `imwrite`/recorte va en `asyncio.to_thread`.
- **"No crear estado global oculto"** → el estado de módulo de los routers v2 se inyecta por `configure()` desde el `lifespan`, como hacen `detection.py` y `context.py`.
- **Tests:** durante la iteración solo el fichero afectado; suite completa antes de terminar porque la fase toca pipeline de eventos, API y configuración. Mantener `tests/test_architecture.py` verde.
- **Regla final:** "el cambio mínimo que resuelva el problema sin aumentar innecesariamente latencia, complejidad o acoplamiento" → de ahí que se extienda `EventRepo.query()` en vez de crear un repo de timeline, que el silenciado viva en `app_config`, y que se descarte `GET /api/v2/timeline`.
- **Trabajar desde la raíz del repo**, nunca desde `.claude/worktrees/*` (un worktree no comparte `.env` ni `.venv`, lo que ya causó un fallo real documentado).
- **Fuente de verdad de planificación:** `.planning/STATE.md`.

**Project skills:** `.claude/skills/supervision/` (referencia de la librería supervision para detección/tracking). No aplica a esta fase — no se toca `detector.py`, `tracker.py` ni el pipeline de captura. Su regla general sí aplica por analogía: *verificar la firma real en el código antes de usar una API, no fiarse de la memoria*, que es justamente lo que ha corregido D-09 y D-12 en este documento.

---

## Sources

### Primary (HIGH confidence) — código del repo leído en esta sesión
- `backend/events/bus.py:65-86` — fan-out con `ensure_future`, `publish_threadsafe`
- `backend/events/rules.py:46-193` — `Rule`, `_matches`, `RuleEngine.evaluate`, debounce
- `backend/events/engine.py:44-324` — `_publish`, `emit_line_crossing`, `emit_identity`
- `backend/events/actions.py:40-185` — `ActionRegistry`, `_snapshot_hook` sin cablear
- `backend/events/types.py:13-80` — contrato `Event`, `Severity`, `DEFAULT_SEVERITY`
- `backend/main.py:79-123, 260-306, 424-466, 616-637, 700-901` — broadcasts, `lifespan`, suscriptores, mounts, endpoints v1/v2, `/ws`
- `backend/storage/models.py:85-201` — tabla `events` e índices, `Rule`, `AppConfig`
- `backend/storage/repositories.py:31-141, 467-644` — cursor, `EventRepo.query`, `RecordingRepo`, `ConfigRepo`
- `backend/storage/migrations.py:24-180` — `SCHEMA_VERSION`, `run_migrations`, `create_all`
- `backend/api/v2/{deps,detection,context,recordings}.py` — convenciones de router, rate limit, paginación
- `backend/database.py:114-190` — `init_db`, llamadas a `EventRepo.query`
- `backend/recognizer.py:337-358` — `list_persons`, base `persons.db` separada
- `backend/tracker.py:170-195` — reinstanciación de `ByteTrack` (reinicio de ids)
- `frontend/js/{app,api,websocket}.js`, `frontend/js/views/{dashboard,dashboard-events}.js`, `frontend/js/components/{eventCard,personGallery}.js`, `frontend/css/components.css`, `frontend/index.html:18-44,210-227,440-534`
- `tests/{conftest,test_repositories,test_frontend_modules,test_security_regression}.py`, `pytest.ini`, `scripts/seed_events.py`
- `.planning/{ROADMAP,REQUIREMENTS,STATE}.md`, `propuesta_mejora/SPEC_v2.md` §8, `30-CONTEXT.md`, `30-UI-SPEC.md`, `CLAUDE.md`

### Primary — mediciones ejecutadas en esta sesión
- Banco SQLite con esquema real + 4 índices reales, 100.000 y 10.000 filas: `EXPLAIN QUERY PLAN` y tiempos de 14 consultas, antes y después de `idx_events_ts_id`, con y sin `+` unario.
- Compilación SQLAlchemy 2.0.49: `with_hint(... "INDEXED BY ...")` **no** se renderiza para SQLite; `text("+events.type IN :types")` con `bindparam(expanding=True)` sí y ejecuta en 4,07 ms @100k.
- Versiones: `sqlalchemy 2.0.49`, `sqlite3 3.49.1`, `Python 3.12.10`.

### Secondary (MEDIUM)
- Documentación de SQLite sobre valores de fila (≥3.15) y JSON1/`json_each` — corroborada empíricamente por las ejecuciones anteriores, así que no depende de la cita.

### Tertiary (LOW)
- Ninguna. No se usó búsqueda web: la fase no introduce librerías externas y todo lo determinante estaba en el repo o era medible.

---

## Metadata

**Desglose de confianza:**
- Stack y convenciones: **HIGH** — sin dependencias nuevas; todo verificado en el código y en el venv.
- API y cursor: **HIGH** — el endpoint y el cursor existen y se han leído; las extensiones están compiladas/ejecutadas.
- Índices y rendimiento: **HIGH** — medido con `EXPLAIN QUERY PLAN` y tiempos a 10k y 100k filas, no estimado.
- Resolución de la carrera de reglas: **HIGH** en el diagnóstico (código leído), **MEDIUM-HIGH** en la solución (el diseño es correcto por construcción, pero el refactor de `RuleEngine` no se ha ejecutado todavía; los tests de `test_rule_engine.py` son la red).
- Huecos de snapshot / `person_name`: **HIGH** — ausencia verificada por `grep` exhaustivo, no por memoria.
- Virtualización de 400 filas: **MEDIUM** — no hay forma de medirlo sin navegador; UI-SPEC ya trae plan B (1000 filas sin recortar) y este documento añade plan C (`content-visibility`).

**Research date:** 2026-08-20
**Valid until:** ~2026-09-20 (30 días — el objeto de estudio es el propio repo, estable; caduca si alguien toca `bus.py`, `repositories.py` o el esquema antes de ejecutar la fase).
