---
phase: 30-event-timeline-y-centro-de-alertas
plan: 10
subsystem: frontend
tags: [websocket, arranque, es-modules, filtros, contrato-de-modulos]

# Dependency graph
requires:
  - phase: 30-08
    provides: "initTimeline(), onLiveEvent(), setTimelineOffline(), refreshPersonNames() y applyTimelineFilters()"
  - phase: 30-09
    provides: "bindAlertCenter(), loadAlerts() y el CustomEvent 'timeline:filter-rule'"
provides:
  - "websocket.js: case 'event' -> onLiveEvent(msg.event, msg.media) y aviso de sin tiempo real atado al onopen/onclose"
  - "app.js: initTimeline() en el arranque y refreshPersonNames() cada 30 s"
  - "timeline-filters.js: setFocusFilter(ruleName, eventType) — el filtro de regla que no tiene control propio en la barra"
  - "timeline.js: oyente de 'timeline:filter-rule' (cierra el contrato que 30-09 dejo emitiendo al vacio)"
  - "LOCKED_JS con los cinco modulos de la Fase 30"
affects: [30-11 marcar como persona, 30-12 puerta de fase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Un case mas en el dispatch por msg.type del socket que ya existe, nunca una segunda conexion (mismo criterio que type:'tracks' en la Fase 29)"
    - "El aviso de desconexion se cuelga del onopen/onclose existente: cero mecanismos nuevos de deteccion, el backoff 1s->30s sigue siendo el unico"
    - "El estado de filtro que no tiene control en la barra (rule) vive con el resto del estado de filtros, no disperso en timeline.js"
    - "Comparacion de tipos por dataset recorriendo los chips, nunca montando un selector CSS con texto que viene del servidor"

key-files:
  created: []
  modified:
    - frontend/js/websocket.js
    - frontend/js/app.js
    - frontend/js/views/timeline.js
    - frontend/js/views/timeline-filters.js
    - tests/test_frontend_modules.py

key-decisions:
  - "El oyente de 'timeline:filter-rule' vive en timeline.js pero el estado del foco en timeline-filters.js: timeline.js estaba a 273 de 300 lineas y filterParams() es el unico sitio donde el parametro `rule` puede entrar sin duplicar la construccion del querystring"
  - "Si el tipo del grupo de alertas tiene chip propio en la barra se enciende el chip en vez de guardar un foco invisible: el operador ve reflejado en la barra el filtro que le acaban de aplicar"
  - "_matchesActiveFilters() replica la pertenencia a payload.rules que el servidor resuelve con json_each: sin eso, con un filtro de regla activo un evento en vivo de otra regla se colaba en la lista"

# Metrics
duration: 18min
completed: 2026-08-21
---

# Phase 30 Plan 10: Cableado de la línea temporal y el centro de alertas Summary

**La línea temporal ya está viva: arranca con el dashboard, recibe los eventos tipados por el `/ws` que ya existía sin pintar dos veces el cruce de línea, avisa cuando se cae la conexión y se sincroniza sola al volver — y "Ver en la línea temporal" del centro de alertas por fin aplica el filtro de la regla en vez de solo hacer scroll.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2 del plan + 1 añadida (hueco de 30-09)
- **Files modified:** 5
- **Commits:** 3

## Task Commits

1. **Task 1 — `websocket.js`: `case 'event'` y aviso de sin tiempo real** — `dbd2f98`
2. **Task 2 — `app.js`: arranque de la timeline y `LOCKED_JS` actualizado** — `fbe7721`
3. **Task 3 (añadida) — el oyente de `timeline:filter-rule`** — `60235b6`

## Accomplishments

### El socket (Task 1)

Un `else if` más al final del `onmessage`, con el mismo molde que el `'tracks'` de la Fase 29:
`onLiveEvent(msg.event, msg.media)`. El payload lo emite `_broadcast_event()` en
`backend/main.py:137` con la forma exacta que el plan documentaba, así que no hubo que
adaptar nada en el camino.

El riesgo real de este plan era el doble pintado del `LINE_CROSSED`: el backend lo emite
por `type:"detection"` (Fase 5) **y** por `type:"event"` (Fase 30). Está cortado por dos
sitios independientes — el `case 'detection'` ya no pinta filas desde 30-07 (`addEvent(`
a cero en todo el fichero, verificado) y `onLiveEvent()` descarta cualquier id que ya esté
en `_all`. Lo que sí sigue en el `case 'detection'` es lo que solo él sabe hacer:
`updateStat`, `bumpHourBar` y el toast del cruce.

El aviso de "sin tiempo real" se cuelga del `onopen`/`onclose` que ya existían, una línea
en cada uno. Ni un segundo detector de desconexión, ni un `_wsRetry` tocado: el diff sobre
las variables del backoff está vacío.

### El arranque (Task 2)

`app.js` llegaba con parte del trabajo hecho — 30-09 tuvo que adelantar el cableado del
centro de alertas para no dejar un import roto — así que aquí solo faltaba `initTimeline()`
y el refresco de nombres. `initTimeline()` va **antes** de `connectWS()`: el
`IntersectionObserver` y los controles tienen que existir cuando llegue el primer
`type:"event"`, o el evento se descarta contra un DOM que aún no está.

`setInterval(refreshPersonNames, 30000)` acompaña al `setInterval(loadPersons, 30000)` que
ya estaba. `person_name` no viaja persistido en el evento (Hallazgo 5): la fila lo resuelve
contra el `Map<person_id, name>` de la timeline, y si ese mapa se queda rancio una persona
recién enrolada sigue apareciendo como "Desconocido" hasta recargar la página.

`LOCKED_JS` incorpora los cinco módulos de la fase: los cuatro de la timeline —30-08 acabó
partiéndola en cuatro, no en dos— y `components/alertCenter.js`. `TEST_line_limit` los
vigila desde ya: `timeline.js` queda en 283 de 300 líneas.

### El hueco que dejó 30-09 (Task 3)

`gotoTimeline()` despachaba `timeline:filter-rule` y **nadie escuchaba**. El criterio de
éxito 6 del ROADMAP exige que "Ver en la línea temporal" filtre, no solo desplace.

El oyente vive en `initTimeline()`, pero el estado del foco está en `timeline-filters.js`,
donde vive el resto del estado de filtros. La razón no es solo el espacio (aunque
`timeline.js` estaba a 273 de 300): `filterParams()` es el único punto donde se construye
el querystring, y meter el parámetro `rule` en otro sitio significaba duplicar esa
construcción y arriesgarse a que un filtro se aplicara a la primera página y no a la
siguiente.

`setFocusFilter(ruleName, eventType)` limpia la barra y deja como único filtro el de la
alerta. Con nombre de regla, `rule` viaja al servidor —que ya lo soportaba desde 30-05,
resolviéndolo con `EXISTS ... json_each(payload,'$.rules')`— y sale su chip azul con su
"×" como cualquier otro filtro. Sin regla (los grupos `type:*`), si el tipo tiene chip
propio en la barra se enciende ese chip, para que el operador vea reflejado el filtro que
le acaban de aplicar; si no lo tiene, se guarda como foco y se pinta un chip con la
descripción en lenguaje llano de `describe()`, no con el identificador crudo. La
comparación con los chips se hace recorriéndolos y mirando `dataset.type`, nunca montando
un selector CSS con texto que viene del servidor.

## Verification

| Comprobación | Resultado |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/ -q` | **603 passed, 2 skipped** |
| `tests/test_frontend_modules.py` | 8/8 en verde |
| `tests/test_security_regression.py` | 21/21 en verde |
| `node --check` en los 4 módulos JS tocados | sin errores de sintaxis |
| `msg.type === 'event'` en `websocket.js` | 1 match |
| `onLiveEvent(msg.event, msg.media)` | 1 match |
| `setTimelineOffline` en `websocket.js` | 3 (import + `onopen` + `onclose`) |
| `addEvent(` en `websocket.js` | 0 matches |
| `updateStat` / `bumpHourBar` / `showToast` | 7 matches, siguen en el bloque `'detection'` |
| `git diff websocket.js \| grep _wsRetry\|_wsCloseCount` | vacío — el backoff no se tocó |
| `wc -l frontend/js/websocket.js` | 94 (< 300) |
| `initTimeline\|bindAlertCenter\|loadAlerts\|refreshPersonNames` en `app.js` | 7 (≥ 6) |
| `loadActiveAlerts` en `app.js` | 0 matches |
| `setInterval(refreshPersonNames, 30000)` | 1 match |
| Módulos nuevos en `LOCKED_JS` | 5 (los 4 de timeline + alertCenter) |
| `grep -rn "timeline:filter-rule" frontend/js/` | **2 matches: el despacho y el oyente** (antes 1) |
| `wc -l` timeline.js / timeline-filters.js | 283 / 133 — por debajo de 300 |

**Pendiente de comprobación manual** (no hay runner JS en el repo). Con el servidor
arrancado hay que confirmar: que un evento real aparece en la lista sin recargar y en menos
de un segundo; que un cruce de línea aparece **una sola vez**; que al parar el backend sale
la barra ámbar y al rearrancarlo la lista se sincroniza sola; y que "Ver en la línea
temporal" desde una alerta deja la lista filtrada por esa regla con su chip azul. Es el
checklist que firma 30-12 como puerta de fase.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Funcionalidad crítica ausente] El contrato `timeline:filter-rule` no tenía oyente**

- **Found during:** después de Task 2, cerrando el hand-off de 30-09
- **Issue:** `alertCenter.js:79` despachaba `CustomEvent('timeline:filter-rule')` y ningún
  módulo lo escuchaba: `grep -rn "timeline:filter-rule" frontend/js/` devolvía solo el
  despacho. "Ver en la línea temporal" cerraba el cajón y hacía scroll sin filtrar nada, y
  el criterio de éxito 6 del ROADMAP exige que filtre. Ni 30-08 ni 30-09 tenían el otro
  extremo en su `files_modified`; este plan es el último que toca el cableado antes de la
  puerta de fase.
- **Fix:** `setFocusFilter(ruleName, eventType)` en `timeline-filters.js` (estado del foco,
  parámetro `rule` en el querystring y su chip activo) y el oyente en `initTimeline()`, que
  llama a `applyTimelineFilters()`. Mismo patrón de desacoplamiento que el resto de la fase:
  ninguno de los dos módulos importa al otro.
- **Files modified:** `frontend/js/views/timeline.js`, `frontend/js/views/timeline-filters.js`
- **Commit:** `60235b6`

**2. [Rule 1 — Bug] Con filtro de regla activo, un evento en vivo de otra regla se colaba**

- **Found during:** Task 3
- **Issue:** `_matchesActiveFilters()` comprobaba tipo, severidad, zona, persona y fechas,
  pero no `rule` — el parámetro no existía cuando se escribió. Con el filtro puesto desde
  una alerta, cualquier evento nuevo del socket se insertaba en la lista aunque no fuera de
  esa regla, contradiciendo el chip que el propio operador estaba viendo.
- **Fix:** una comprobación más, replicando en cliente la pertenencia que el servidor
  resuelve con `json_each(payload,'$.rules')`: `if (rule && !(ev.payload?.rules ?? []).includes(rule)) return false;`
- **Files modified:** `frontend/js/views/timeline.js`
- **Commit:** `60235b6`

### Desviaciones conscientes respecto al plan

- **`LOCKED_JS` lleva cinco entradas, no tres.** El plan proponía tres y autorizaba añadir
  `views/timeline-virtualize.js` "solo si 30-08 llegó a crearlo". Lo creó, y además
  `views/timeline-filters.js`: los cuatro módulos de la timeline entran en el contrato.
- **`app.js` ya venía medio hecho.** El plan describía retirar `loadActiveAlerts` y añadir
  `bindAlertCenter()`/`loadAlerts()`; 30-09 lo adelantó por necesidad (import roto). Aquí
  solo se añadió lo que faltaba de verdad: `initTimeline()` y `setInterval(refreshPersonNames)`.

## Known Stubs

Ninguno. Los cinco ficheros tocados ejecutan comportamiento real. Lo único que sigue sin
oyente en la fase es `timeline:mark-person`, que es exactamente el trabajo de 30-11.

## Threat Flags

Ninguno. No aparece superficie nueva: este plan no crea endpoints, no toca almacenamiento
ni cambia el `verify_ws_token` del `/ws`. Las dos disposiciones `mitigate` del
`<threat_model>` quedan cubiertas — T-30-35 porque `onLiveEvent()` entrega el evento a
`timelineRow()`, que escribe todo dato del backend por `textContent` (30-08), y el mensaje
llega por un socket que ya exige token en el `accept()`; T-30-36 con `addEvent(` a cero en
`websocket.js` más el descarte por id repetido en `onLiveEvent()`. El nombre de regla que
introduce Task 3 nunca entra en un selector CSS ni en una plantilla: viaja como valor de
`URLSearchParams` hacia el servidor y llega al DOM por `textContent` dentro de
`paintActiveChips()`.

## Self-Check: PASSED

- `frontend/js/websocket.js` — FOUND (94 líneas)
- `frontend/js/app.js` — FOUND (56 líneas)
- `frontend/js/views/timeline.js` — FOUND (283 líneas)
- `frontend/js/views/timeline-filters.js` — FOUND (133 líneas)
- `tests/test_frontend_modules.py` — FOUND
- Commits `dbd2f98`, `fbe7721`, `60235b6` — FOUND
