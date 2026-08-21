---
phase: 30-event-timeline-y-centro-de-alertas
plan: 08
subsystem: frontend
tags: [es-modules, timeline, cursor-pagination, intersection-observer, xss, localstorage]

# Dependency graph
requires:
  - phase: 30-05
    provides: GET /api/v2/events con envelope {events, cursor, total, media} y filtros combinables
  - phase: 30-07
    provides: los ids del DOM (#timeline-*, #tl-filter-*, #btn-tl-*) y las clases visuales de la fila
provides:
  - "frontend/js/views/timeline-row.js: timelineRow(), describe(), SEV_COLOR, isDismissed/dismiss/undismiss y undoToast()"
  - "frontend/js/views/timeline.js: initTimeline(), applyTimelineFilters(), onLiveEvent(), setTimelineOffline(), refreshPersonNames()"
  - "frontend/js/views/timeline-virtualize.js: paintWindow() y sepLabel() — ventana de DOM y separadores de bloque"
  - "frontend/js/views/timeline-filters.js: filterParams(), clearFilter(), clearAllFilters(), paintActiveChips(), bindFilterChips()"
  - "CustomEvent 'timeline:mark-person' con {eventId, trackId, snapshotUrl} — el contrato que escucha 30-11"
affects: [30-10 arranque y WebSocket, 30-11 marcar como persona, 30-12 puerta de fase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Estructura estatica por innerHTML con nodos vacios + datos por textContent/dataset/propiedades (CodeQL js/xss): nombre de persona, nombre de regla y zone_id nunca entran en una plantilla"
    - "Array completo en memoria + ventana de DOM: el recorte por arriba y el volver a subir se repintan desde memoria, sin cursor inverso ni segunda ruta de red"
    - "Dos objetivos para un mismo IntersectionObserver (centinela de abajo = pagina siguiente, centinela de arriba = deslizar la ventana): ni un solo listener de scroll"
    - "Los filtros de datos se construyen como querystring y se resuelven en servidor; la unica comprobacion local es la de los eventos que llegan por WebSocket"

key-files:
  created:
    - frontend/js/views/timeline-row.js
    - frontend/js/views/timeline.js
    - frontend/js/views/timeline-virtualize.js
    - frontend/js/views/timeline-filters.js
  modified:
    - frontend/css/components.css

key-decisions:
  - "Cuatro modulos en vez de dos: el tope de 300 lineas de tests/test_frontend_modules.py no daba para meter separadores, ventana y barra de filtros dentro de timeline.js (327 lineas en el primer intento)"
  - "undoToast() vive en timeline-row.js, junto al estado de descartados: showToast() de dashboard.js solo admite texto plano y aqui hace falta un boton 'Deshacer' dentro del toast"
  - "'Ver captura' abre la imagen en una pestana nueva con noopener: #clip-modal solo contiene un <video> y meterle un <img> condicional tocaria un modal compartido con la Fase 15"
  - "El detalle del error de red va a consola, no a un toast: el aviso visible es #timeline-error con la copy exacta del UI-SPEC, y duplicarlo en rojo seria ruido"
  - "El centinela superior es un div de 1px que pinta paintWindow() cuando start > 0, no un listener de scroll ni una medicion de alturas en JS"

# Metrics
duration: 22min
completed: 2026-08-21
---

# Phase 30 Plan 08: Línea temporal Summary

**La línea temporal ya funciona de punta a punta: pide páginas de 50 con cursor a `/api/v2/events`, filtra en servidor, pagina con dos centinelas de `IntersectionObserver`, mantiene el DOM en 400 filas compensando `scrollTop` al recortar, y coloca el evento en vivo arriba o en una píldora según dónde tenga el operador el scroll.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3
- **Files created:** 4 · **modified:** 1
- **Commits:** 3

## Task Commits

1. **Task 1 — `timeline-row.js`** — `8651509`
2. **Task 2 — motor de la timeline (`timeline.js` + los dos módulos auxiliares)** — `0deaf5a`
3. **Task 3 — evento en vivo, píldora y barra de sin-tiempo-real** — `2eb0652`

## Accomplishments

### La fila (`timeline-row.js`, 204 líneas)

Los siete elementos del UI-SPEC en orden —barra de severidad, hora `.mono`, miniatura
64×36, descripción, chip de zona, chip de regla y cuatro acciones— montados con el patrón
anti-XSS del repo: la plantilla `innerHTML` solo lleva nodos vacíos y constantes del
módulo (los SVG de los iconos), y todo lo que viene del backend entra después por
`textContent`, `dataset` o propiedades del DOM. `describe()` traduce los 22 valores reales
de `EventType` a frases en pasado y en lenguaje llano, con degradación a
`tipo con espacios en minúsculas` para cualquier tipo futuro que no esté en el mapa.

El nombre de una persona confirmada va en verde dentro de la frase y "Desconocido" hereda
el color de la severidad de la fila, resolviéndolo por partición del texto: si la frase
empieza por el "quién", ese trozo va en un `<span>` propio y el resto en un nodo de texto.
Ambos por `textContent`.

Las cuatro acciones llevan `aria-label` con la hora del evento ("Ver clip del evento de las
18:42:05"); "Ver clip" se deshabilita con el `title` del contrato cuando no hay grabación y
"Marcar como persona" cuando el evento no tiene `track_id`. La fila no es un `<button>` ni
lleva `tabindex`: solo las acciones y la miniatura son focalizables, para no meter 400
paradas de tabulador en el recorrido de teclado.

El descarte es estado de cliente en `localStorage` (`timeline.dismissed`, tope FIFO de
500), tolerante a modo privado, cuota llena y JSON corrupto, y se aplica al pintar — el
servidor nunca se entera de lo que ha ocultado un navegador concreto.

### El motor (`timeline.js`, 273 líneas)

`_all` guarda todos los eventos descargados y el DOM es solo una ventana de `MAX_ROWS = 400`
sobre él, anclada por `_start`. Al cargar una página nueva la ventana se desliza al final y
se compensa `scrollTop` con `filasEliminadas × 60` (52px de fila + 8px de gap), que es
justo para lo que la altura de la fila es fija. Volver a subir no vuelve a la red: cuando
asoma el centinela superior —un div de 1px que `paintWindow()` pinta solo si `_start > 0`—
la ventana retrocede 50 filas repintando desde memoria y compensando en el sentido
contrario. Así desaparece la necesidad del cursor inverso que planteaba el UI-SPEC: un
parámetro menos de API y toda una clase de bugs (páginas hacia atrás desalineadas con
inserciones nuevas) que no llega a existir.

Los dos centinelas comparten un único `IntersectionObserver` con `root` en la lista y
`rootMargin: '200px'`, distinguiéndose por el `id` del `target`. Ni un `addEventListener('scroll')`.

Los filtros viajan siempre al servidor: `type` repetido una vez por chip activo, `severity`
excluyente, `zone_id`, `person_id` resuelto contra el `Map<person_id, name>` de `/persons`,
y `from`/`to` con las horas de borde. Aplicar un filtro vacía la lista y reinicia el cursor
**antes** de pedir la primera página. Los chips azules de filtro activo llevan su "×"
individual y el contador del card alterna entre "{N} eventos" y "{N} de {total}".

Las acciones van por delegación sobre `#timeline-list`: "Ver clip" reutiliza
`openClipModal()`, "Descartar" repinta y saca el toast con "Deshacer" de 5 s, y "Marcar como
persona" despacha `timeline:mark-person` sobre `document` — la timeline no importa nada de
30-11, es 30-11 quien escucha.

### El evento en vivo (Task 3)

`onLiveEvent()` descarta lo que no cumple los filtros activos y lo que ya está en `_all`
(idempotente ante reconexiones del socket). Con la lista arriba (`scrollTop < 8`) inserta la
fila con `slide-in` y realza la barra de severidad 2 s; con el operador desplazado, acumula
en `_pending` y enciende la píldora "{N} eventos nuevos" sin tocar el scroll. `scrollTo`
aparece exactamente una vez en todo el módulo: dentro del handler de la píldora.
`setTimelineOffline()` enciende la barra ámbar y, al pasar de `true` a `false`, recarga la
primera página para sincronizar sin recargar la página.

## Verification

| Comprobación | Resultado |
|---|---|
| `tests/test_frontend_modules.py` | 8/8 en verde |
| `tests/test_security_regression.py` | 21/21 en verde |
| `node --check` en los cuatro módulos | sin errores de sintaxis |
| `wc -l` de los módulos nuevos | 273 / 204 / 107 / 67 — todos por debajo de 300 |
| Datos del backend interpolados en plantillas | 0 (`grep 'innerHTML' -A 12 \| grep '${ev.\|${personName\|${rules'`) |
| `data-action=` en la fila | 6 matches (4 botones + comprobaciones) |
| `IntersectionObserver` / `rootMargin: '200px'` / `MAX_ROWS = 400` | 1 match cada uno |
| `addEventListener('scroll'` | 0 matches |
| `catch {}` | 0 matches |
| Endpoint v1 `'/api/events` | 0 matches; `/api/v2/events` 1 match |
| `.filter(` sobre severity/type en el array descargado | 0 matches |
| `scrollTo`/`scrollIntoView` | solo en el handler de la píldora |

**Pendiente de comprobación manual** (no automatizable: no hay runner JS en el repo, tal y
como anota el bloque `<verification>` del plan). Con el servidor arrancado hay que confirmar
que la lista se llena, que los filtros repintan, que el scroll pide más páginas y que el
recorte a 400 filas no produce un salto perceptible — si lo produce, el plan B ya está
documentado en el propio módulo: subir `MAX_ROWS` a 1000 y dejar de recortar. Ojo: hasta que
30-10 llame a `initTimeline()` desde `app.js` y enganche `onLiveEvent` en `websocket.js`,
estos módulos no se cargan y el card sigue vacío. Es el estado esperado.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Bloqueante] Dos módulos no caben: se extraen cuatro**

- **Found during:** Task 2
- **Issue:** con separadores, ventana de DOM y barra de filtros dentro, `timeline.js` salía a
  327 líneas y `tests/test_frontend_modules.py::TEST_line_limit` lo tumbaba.
- **Fix:** el plan ya autorizaba `timeline-virtualize.js` (separadores + recorte); no bastaba,
  así que la barra de filtros salió a `timeline-filters.js` con la misma lógica y sin
  dependencia circular (`paintActiveChips` recibe el callback de borrado en vez de importar
  `applyTimelineFilters`). `timeline.js` queda en 273 líneas.
- **Commit:** `0deaf5a`

**2. [Rule 1 — Nombres inventados en el plan] `RECORDING_UPLOADED` no existe**

- **Found during:** Task 1
- **Issue:** el plan listaba `RECORDING_UPLOADED` entre los tipos a cubrir, pero
  `backend/events/types.py::EventType` no lo tiene. Sí tiene `RECORDING_FINISHED`,
  `OBJECT_REMOVED`, `PERSON_ENTERED` y `PERSON_EXITED`, que el plan no mencionaba.
- **Fix:** el mapa cubre los 22 valores reales del enum, leídos del código como pedía el
  propio plan. Un tipo desconocido no revienta: cae al texto degradado.
- **Commit:** `8651509`

**3. [Rule 3 — Clase CSS ausente] `.slide-in` no existía**

- **Found during:** Task 3
- **Issue:** `components.css` tiene el `@keyframes slide-in` pero solo lo consume
  `.event-item`; no había ninguna clase `.slide-in` que aplicar a la fila nueva.
- **Fix:** una línea en `components.css` (`.slide-in { animation: slide-in 200ms ease; }`)
  reutilizando el keyframe existente, tal como pedía el plan — sin inventar un tercer
  mecanismo de animación.
- **Commit:** `2eb0652`

**4. [Rule 2 — Accesibilidad] La miniatura no era alcanzable por teclado**

- **Found during:** Task 2
- **Issue:** el UI-SPEC dice que la miniatura es focalizable y abre la captura, pero un
  `<img>` no es focalizable de serie y `Enter` no dispara `click` sobre él.
- **Fix:** `tabindex="0"`, `role="button"` y `aria-label` con la hora en la miniatura (y en
  el marcador cuando no hay imagen), más un `keydown` en la lista que traduce `Enter`/`Espacio`
  a `click` sobre `.tl-thumb`.
- **Commit:** `0deaf5a`

### Desviaciones conscientes respecto al plan

- **"Ver captura" no usa `#clip-modal`.** El plan lo contemplaba ("si el modal lo soporta"):
  no lo soporta, solo tiene un `<video>` que además comparte la Fase 15. La imagen se abre en
  una pestaña nueva con `noopener`, que es la alternativa que el propio plan indicaba.
- **El error de carga no saca toast.** El plan pedía "nunca un `catch {}` silencioso"; se
  cumple mostrando `#timeline-error` (la copy exacta del UI-SPEC) y volcando el detalle del
  backend a `console.error`. Un toast rojo encima repetiría el mismo mensaje.
- **`refreshPersonNames()` es un envoltorio síncrono** sobre el cargador asíncrono, para
  respetar la firma `export function refreshPersonNames()` del bloque `<interfaces>`; devuelve
  la promesa, así que se puede seguir esperando.

## Threat Flags

Ninguno. Los cuatro riesgos del `<threat_model>` quedan mitigados como estaba previsto:
T-30-27 con el patrón `textContent` verificado por grep, T-30-28 asignando `img.src` por
propiedad (las URLs las construye el servidor a partir de ids), T-30-29 con la ventana de
400 filas y T-30-30 dejando todo filtro de datos en servidor. No aparece superficie nueva:
estos módulos no crean endpoints ni tocan almacenamiento del servidor.

## Known Stubs

Ninguno en los módulos de este plan. Los cuatro exportan comportamiento real. Lo que sigue
pendiente es de otro plan: nadie llama todavía a `initTimeline()` ni a `onLiveEvent()` —lo
hace 30-10— y `timeline:mark-person` no tiene oyente hasta 30-11.

## Self-Check: PASSED

- `frontend/js/views/timeline-row.js` — FOUND (204 líneas)
- `frontend/js/views/timeline.js` — FOUND (273 líneas)
- `frontend/js/views/timeline-virtualize.js` — FOUND (67 líneas)
- `frontend/js/views/timeline-filters.js` — FOUND (107 líneas)
- `frontend/css/components.css` — FOUND (160 líneas)
- Commits `8651509`, `0deaf5a`, `2eb0652` — FOUND
