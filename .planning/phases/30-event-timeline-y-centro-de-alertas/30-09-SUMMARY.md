---
phase: 30-event-timeline-y-centro-de-alertas
plan: 09
subsystem: frontend
tags: [es-modules, alert-center, drawer, focus-trap, mute, xss]

# Dependency graph
requires:
  - phase: 30-06
    provides: GET /api/v2/alerts con agrupacion por regla ya resuelta en servidor, y POST /alerts/mute|unmute
  - phase: 30-07
    provides: los ids del DOM del cajon, la campana, el badge y el popover de silenciado
provides:
  - "frontend/js/components/alertCenter.js: loadAlerts(), bindAlertCenter(), openAlertDrawer(), closeAlertDrawer()"
  - "El panel top-3 'Alertas activas' de la Fase 29 alimentado desde la misma agrupacion en servidor"
  - "CustomEvent 'timeline:filter-rule' con {ruleName, eventType} — contrato pendiente de escucha (ver Hand-off)"
affects: [30-10 arranque y LOCKED_JS, 30-12 puerta de fase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Estructura estatica por innerHTML con nodos vacios + datos del backend por textContent/dataset (CodeQL js/xss): rule_name, zone_id y las descripciones nunca entran en una plantilla"
    - "Cero .filter()/.sort() sobre la respuesta: el orden por severidad, la agrupacion y el estado de silenciado los decide el servidor (30-06)"
    - "La duracion ES la confirmacion: el popover con 15min/1h/8h sustituye al dialogo nativo (D-07), y el valor sale de dataset.duration — lista blanca fijada por el marcado, nunca texto libre"
    - "Tras silenciar o reactivar, con exito o con error, siempre se relee el estado del servidor con loadAlerts(): la UI no puede afirmar 'silenciada' si el backend rechazo la operacion"
    - "Modulos desacoplados por eventos del DOM: alertCenter.js y timeline.js no se importan entre si"

key-files:
  created:
    - frontend/js/components/alertCenter.js
  modified:
    - frontend/js/views/dashboard.js
    - frontend/js/app.js
    - frontend/css/components.css
---

# Plan 30-09 — Centro de alertas en el navegador

- **Tasks:** 2/2
- **Commits:** 2

## Task Commits

1. **Task 1 — badge, cajon y agrupacion; retirada de `loadActiveAlerts` de `dashboard.js`** — `8023929`
2. **Task 2 — popover de silenciado con duracion obligatoria y reactivacion** — `cfcdefb`

## Accomplishments

### El modulo (`alertCenter.js`, 272 lineas)

`loadAlerts()` pide `GET /api/v2/alerts?hours=24` y con esa unica respuesta repinta tres
sitios a la vez: el badge de la campana, el cajon lateral y el top-3 de la Fase 29. No hay
ni un `.filter()` ni un `.sort()` sobre los datos — la agrupacion por regla, el orden por
severidad y el estado de silenciado vienen ya decididos del servidor, que era justamente el
motivo de construir `/api/v2/alerts` en 30-06 en lugar de agrupar en el navegador.

El badge sigue la regla del UI-SPEC: vacio y oculto con 0 alertas, el numero hasta 9, `9+`
a partir de 10, rojo si hay alguna critica y ambar si solo hay avisos. La campana lleva
`aria-label="Centro de alertas, N activas"` actualizado en cada repintado.

Cada grupo del cajon monta la estructura con `innerHTML` de nodos vacios y rellena despues
por `textContent`: el nombre de la regla lo escribe el operador en `rules.yaml`, asi que
nunca entra en una plantilla. Un grupo sin regla (los `type:*`) muestra el tipo en lenguaje
llano reutilizando `describe()` de `timeline-row.js`, no el identificador crudo del catalogo.
Los grupos silenciados **se quedan en la lista** atenuados, con chip ambar
"silenciada hasta HH:MM" y accion "Reactivar regla" — el operador tiene que poder ver de un
vistazo que se esta callando.

### El silenciado (Task 2)

El popover se abre anclado al boton que lo dispara, con las tres duraciones del contrato
(15 minutos / 1 hora / 8 horas) y el titulo `Silenciar «{regla}»`. La duracion elegida es la
confirmacion: cero `confirm()` nuevos en la fase, como fija D-07. El valor viaja como
`duration_secs` tomado de `dataset.duration`, es decir de una lista blanca fijada en el
marcado — el usuario nunca escribe un numero libre.

Tanto `muteRule()` como `unmuteRule()` llaman a `loadAlerts()` en el camino de exito **y** en
el de error (6 llamadas en total en el modulo). Si el backend rechaza la operacion, sale el
toast rojo con la copy literal del contrato y acto seguido se relee el estado real: la
interfaz no puede quedarse mintiendo.

### Accesibilidad del cajon

`role="dialog"` con foco atrapado: `trapTab()` cicla entre los elementos focalizables
visibles, `Escape` cierra primero el popover si esta abierto y solo despues el cajon, y al
cerrar el foco vuelve a la campana. El clic en el backdrop cierra; el clic en cualquier
punto que no sea el popover ni su boton lo cierra a el.

### La mudanza desde `dashboard.js`

`loadActiveAlerts()` y `SEVERITY_RANK` desaparecen de `dashboard.js` (que baja de 290 a 244
lineas, recuperando margen sobre el limite de 300 de `TEST_line_limit`). El top-3 ya no
filtra `severity !== 'info'` ni ordena en el navegador sobre `GET /api/v2/events?limit=10`:
lo pinta `paintTop3()` con los tres primeros grupos no silenciados de la misma respuesta,
reproduciendo el marcado exacto que generaba `_statusRow`. Una regla silenciada desaparece
del top-3 sin logica adicional, porque el servidor ya la marca.

## Verification

| Comprobacion | Resultado |
|---|---|
| `tests/test_frontend_modules.py` | 8/8 en verde |
| `node --check` en `alertCenter.js`, `dashboard.js`, `app.js` | sin errores de sintaxis |
| Los 4 exports del bloque `<interfaces>` | 4/4 presentes |
| `wc -l frontend/js/components/alertCenter.js` | 272 (< 300) |
| `wc -l frontend/js/views/dashboard.js` | 244 (era 290) |
| `loadActiveAlerts` / `SEVERITY_RANK` en todo `frontend/js/` | 0 matches |
| `alerts/mute` / `alerts/unmute` / `duration_secs` / `dataset.duration` | 1 match cada uno |
| `confirm(` | 0 matches |
| `loadAlerts()` | 6 matches (>= 4 exigidos) |
| Copy literal "No se pudo silenciar la regla" / `Silenciar «` | 1 match cada uno |
| `alerts-active-list` (top-3 alimentado) | 1 match |
| Regla del badge de dos cifras (`9+`) | 1 match |
| Interpolacion de datos del backend en plantillas (`${g.`, `${group.`) | 0 matches |
| `Escape` | 2 matches |

**Pendiente de comprobacion manual** (no hay runner JS en el repo): con el servidor
arrancado, confirmar que la campana refleja el recuento real, que el cajon abre y atrapa el
foco, que silenciar atenua el grupo y lo saca del top-3, y que reactivar lo devuelve.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Bloqueante] El import de `app.js` no podia esperar a 30-10**

- **Found during:** Task 1
- **Issue:** el plan anotaba que "el import de `app.js` se corrige en 30-10", pero retirar
  `loadActiveAlerts` de `dashboard.js` deja a `app.js` importando un simbolo inexistente.
  Un import roto en un modulo ES aborta la carga del bundle entero: el dashboard se habria
  quedado en blanco desde este commit hasta 30-10.
- **Fix:** `app.js` importa `loadAlerts`/`bindAlertCenter` de `alertCenter.js` y sustituye la
  llamada de arranque. Es exactamente el cableado que 30-10 iba a hacer, adelantado por
  necesidad — 30-10 se encontrara esta parte hecha y solo tiene que anadir `initTimeline()`,
  el `case 'event'` del WebSocket y los modulos nuevos a `LOCKED_JS`.
- **Commit:** `8023929`

**2. [Rule 3 — Especificidad CSS] El badge se pintaba como circulo vacio con 0 alertas**

- **Found during:** Task 1
- **Issue:** `.hidden` de Tailwind (especificidad 0,1,0) no gana al selector de id que da
  forma al badge, asi que ocultarlo con `classList.add('hidden')` no surtia efecto.
- **Fix:** una regla en `components.css`: `#alert-badge.hidden { display: none; }`.
- **Commit:** `8023929`

### Desviaciones conscientes respecto al plan

- **`setInterval(loadAlerts, REFRESH_MS)` a nivel de modulo**, no dentro de
  `bindAlertCenter()`. El refresco de 5 s arranca al importar el modulo, igual que hacia el
  `setInterval` de `loadActiveAlerts` en `app.js` — se conserva la cadencia previa sin
  depender de que alguien llame al binder.
- **El error de carga no borra el badge.** Si `/api/v2/alerts` falla, se muestra el estado
  vacio del cajon pero el badge conserva su ultimo valor conocido: ponerlo a cero afirmaria
  "no hay alertas", que es peor que mostrar un dato de hace unos segundos.

## Hand-off para 30-10 — contrato sin escuchar

`gotoTimeline()` cierra el cajon, hace scroll a la lista y despacha
`CustomEvent('timeline:filter-rule', { detail: { ruleName, eventType } })` sobre `document`.
**Hoy nadie escucha ese evento**: `grep -rn "timeline:filter-rule" frontend/js/` devuelve
solo el despacho. La mitad emisora es la que este plan tenia asignada (`timeline.js` no esta
en su `files_modified`), pero mientras el oyente no exista, "Ver en la linea temporal"
cierra el cajon y hace scroll sin aplicar el filtro de la regla — y el criterio de exito 6
del ROADMAP lo exige.

**30-10 debe anadir el oyente en `timeline.js`**, traduciendo `detail.ruleName` al parametro
`rule` de `GET /api/v2/events` (o `detail.eventType` al chip de tipo cuando el grupo no tiene
regla) y llamando a `applyTimelineFilters()`. Es el mismo patron que 30-11 usa al escuchar
`timeline:mark-person`.

## Threat Flags

Ninguno. El nombre de regla —el unico dato de este modulo que escribe una persona, en
`rules.yaml`— llega al DOM por `textContent` en los tres sitios donde aparece (chip del
grupo, titulo del popover, fila del top-3), verificado por grep. La duracion del silenciado
sale de una lista blanca del marcado, no de entrada libre. El modulo no crea endpoints ni
toca almacenamiento del servidor: solo consume los tres de 30-06.
