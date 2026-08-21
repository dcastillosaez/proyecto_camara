---
phase: 30-event-timeline-y-centro-de-alertas
plan: 11
subsystem: frontend
tags: [modal, enrolado, identidad, track, repintado-en-sitio, ops-08]

# Dependency graph
requires:
  - phase: 30-03
    provides: EventRepo.track_scope() y EventRepo.assign_person() con la triple cota del bloque de track
  - phase: 30-05
    provides: GET /api/v2/events/{id}/track-scope y POST /api/v2/events/{id}/assign-person
  - phase: 30-07
    provides: marcado del modal dedicado #mark-person-modal en index.html
  - phase: 30-08
    provides: la fila despacha CustomEvent('timeline:mark-person', {eventId, trackId, snapshotUrl})
  - phase: 30-10
    provides: convencion de cableado por CustomEvent ya establecida en initTimeline()
provides:
  - "frontend/js/components/markPerson.js: modal de marcado completo (precarga, alcance, enrolado, asignacion)"
  - "applyPersonAssignment(eventIds, personId, name) exportado por timeline.js: repintado en sitio sin perder scroll"
  - "bindMarkPerson() cableado en app.js junto al resto de bind*()"
affects: [30-12 puerta de fase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Enrolado en dos llamadas a proposito: /api/enroll_face conserva sus validaciones y /assign-person solo propaga un person_id ya enrolado"
    - "El alcance retroactivo lo calcula el servidor; el cliente solo muestra el N y envia el event_id ancla"
    - "Repintado en sitio: se guarda scrollTop, se llama render() y se restaura — nunca loadPage({reset:true})"
    - "Los nombres de persona se asignan a option.value/textContent por propiedad, jamas interpolados en un template"

key-files:
  created:
    - frontend/js/components/markPerson.js
  modified:
    - frontend/js/views/timeline.js
    - frontend/js/app.js
    - tests/test_frontend_modules.py

key-decisions:
  - "El modal se abre SIEMPRE antes de resolver track-scope y /persons: si una de las dos falla se ve el error en #mark-person-error, nunca un modal a medio abrir"
  - "Sin recorte disponible se cae a use_current_frame=true y se dice explicitamente en el aviso de alcance, en vez de bloquear la accion"
  - "El blob del snapshot se reenvuelve con un content_type permitido (jpeg/png/webp) para no chocar con el 415 de enroll_face si el servidor sirviera un tipo raro"
  - "El error muestra el detail del backend (415/413/422) cuando existe y cae al literal generico del UI-SPEC si no; el toast rojo siempre usa el literal exacto"
  - "applyPersonAssignment recibe los event_ids que devuelve el backend, no los de la previsualizacion: el alcance real es el del UPDATE"

# Metrics
duration: 21min
completed: 2026-08-21
---

# Phase 30 Plan 11: Marcar como persona Summary

**El modal de marcado abre con el recorte del evento ya cargado, dice cuántos eventos del mismo track van a recibir la identidad antes de confirmar, enrola contra `/api/enroll_face` reutilizando sus validaciones y repinta en sitio las filas afectadas sin recargar la lista ni mover el scroll.**

## Performance

- **Duration:** ~21 min
- **Tasks:** 2
- **Files modified:** 4 (1 nuevo)

## Qué se construyó

`frontend/js/components/markPerson.js` (169 líneas) escucha el `CustomEvent('timeline:mark-person')` que la fila ya despachaba desde 30-08 — misma convención que el `timeline:filter-rule` de 30-10, así que ni la timeline importa el modal ni el modal importa la fila.

Al abrirse:

1. Pinta `#mark-person-preview` con el `snapshotUrl` del evento. Si el evento no tiene recorte, oculta la imagen y añade al aviso que se usará el frame actual de la cámara.
2. `GET /api/v2/events/{id}/track-scope` → escribe con `textContent` el literal del contrato: `Se aplicará también a los eventos anteriores de este track (N).`
3. `GET /persons` → llena el `<datalist>` con las personas ya conocidas, asignando `option.value` por propiedad.

Al confirmar: `FormData` con el blob del recorte → `POST /api/enroll_face` → `POST /api/v2/events/{id}/assign-person` con el `person_id` devuelto → `applyPersonAssignment(event_ids, person_id, name)` → toast verde `Identidad aplicada a N eventos de este track.`

`applyPersonAssignment()` en `timeline.js` actualiza el `Map<person_id, name>`, marca `person_id` en los eventos del bloque, baja la severidad de los `UNKNOWN_PERSON` a `info` (mismo criterio que el `UPDATE` del backend) y repinta guardando y restaurando `scrollTop`. Ninguna llamada de red, ninguna página perdida.

## Decisiones no obvias

**El enrolado sigue siendo dos llamadas.** Es lo que pedía el plan y sigue siendo lo correcto: `/api/enroll_face` ya valida `content_type`, tamaño ≤10 MB y `max_length=100`, con rate limit propio y tests de regresión. Un endpoint "enrolar y asignar de una vez" habría duplicado esas validaciones o, peor, se las habría saltado.

**El blob se reenvuelve.** `fetch(snapshotUrl).blob()` hereda el `Content-Type` que sirva el backend. Si por lo que sea no es `image/jpeg|png|webp`, `enroll_face` responde 415. Se comprueba el tipo y se reenvuelve con `image/jpeg` por defecto — el coste es una copia de un JPEG pequeño y evita un fallo silencioso desde el lado del operador.

**El error se ve dos veces a propósito.** En `#mark-person-error` va el motivo concreto (el `detail` del backend: "No face detected in the provided image", por ejemplo), porque es accionable dentro del modal. En el toast rojo va el literal exacto del UI-SPEC. No es redundancia: uno explica, el otro cumple el contrato de copy.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Funcionalidad crítica] Normalización del `content_type` del recorte**
- **Found during:** Task 2
- **Issue:** el plan aparejaba `fd.append('image', blob, 'snapshot.jpg')` directamente. Si el snapshot se sirviera con un `Content-Type` fuera de `_ALLOWED_IMAGE_TYPES`, `enroll_face` devolvería 415 y el operador vería un error incomprensible en una imagen que sí es válida.
- **Fix:** se comprueba `blob.type` contra el mismo juego de tipos del backend y se reenvuelve con `image/jpeg` si no encaja.
- **Files modified:** frontend/js/components/markPerson.js
- **Commit:** e173181

**2. [Rule 2 - Copy del contrato] Toast rojo además del mensaje en el modal**
- **Found during:** Task 2
- **Issue:** el pseudocódigo del plan solo llamaba a `showError(...)`. El UI-SPEC exige explícitamente un toast rojo con el literal `No se pudo guardar la identidad. Inténtalo de nuevo.` para este error.
- **Fix:** se emite el toast con el literal exacto y se reserva `#mark-person-error` para el `detail` accionable del backend.
- **Files modified:** frontend/js/components/markPerson.js
- **Commit:** e173181

**3. [Rule 3 - Límite de módulo] `timeline.js` rozaba las 300 líneas**
- **Found during:** Task 2
- **Issue:** con `applyPersonAssignment()` el módulo quedaba exactamente en 300 líneas — el test pasa (`> 300` es el fallo) pero el criterio del plan es `< 300` y no dejaba margen para 30-12.
- **Fix:** se comprimió el comentario del bloque nuevo; queda en 299.
- **Files modified:** frontend/js/views/timeline.js
- **Commit:** e173181

**4. [Rule 3 - Contrato mecánico] `components/markPerson.js` añadido a `LOCKED_JS`**
- **Found during:** Task 2 (previsto en los criterios de aceptación)
- **Issue:** el módulo nuevo no estaba en la lista de módulos locked de `tests/test_frontend_modules.py`, así que ni su existencia ni su límite de líneas quedaban protegidos.
- **Fix:** entrada añadida junto a `components/alertCenter.js`.
- **Files modified:** tests/test_frontend_modules.py
- **Commit:** e173181

### Nota de secuenciación

El botón `#btn-mark-person-confirm` se cablea en la Task 2, no en la Task 1 como sugería la redacción del plan. La Task 1 no tenía todavía `onConfirm()` y engancharlo a un placeholder habría dejado un stub en el árbol. El commit de la Task 1 deja el modal abriéndose y cerrándose correctamente, con el botón inerte durante un único commit.

## Verification Evidence

- `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` → **8 passed**
- `.venv/Scripts/python.exe -m pytest tests/ -q` → **603 passed, 2 skipped** en 124,87 s
- `node --check` sobre `markPerson.js`, `timeline.js` y `app.js` → sin errores de sintaxis
- `wc -l` → `markPerson.js` 169, `timeline.js` 299 (ambos < 300)
- Criterios de aceptación por `grep`: un único punto de llamada a `/api/enroll_face` (línea 140), un `assign-person`, un `track-scope`, un `'/persons'`, los tres literales del UI-SPEC exactos, `setBusy` × 3 (definición + `true` + `finally`), `confirm(` → 0 matches, `export function applyPersonAssignment` presente y `scrollTop = keep` presente.

### Comprobación manual — pendiente

La verificación visual que pide el plan (modal abriéndose con el recorte real, N razonable en el aviso — señal temprana del Pitfall 3 si saliera en decenas o cientos — y filas del track cambiando en sitio al confirmar) **no se ha ejecutado en este plan**: requiere cámara conectada, eventos reales con `track_id` y el motor de reconocimiento disponible (`enroll_face` devuelve 503 sin él). Queda para el checklist manual de la puerta de fase 30-12, que ya es el sitio donde se firma la paridad funcional del resto de la fase.

## Threat Mitigations Applied

| Threat ID | Mitigación implementada |
|-----------|-------------------------|
| T-30-37 | El enrolado pasa por `/api/enroll_face`; no se creó ningún camino alternativo. El blob se normaliza a un `content_type` permitido, pero las validaciones de tamaño, tipo y longitud del nombre siguen siendo las del backend |
| T-30-38 | El alcance lo calcula el servidor (`track_scope`); el cliente envía solo el `event_id` ancla y repinta con los `event_ids` que devuelve el `UPDATE`, no con los de la previsualización |
| T-30-39 | `applyPersonAssignment()` solo toca el modelo y llama a `render()` (que usa `textContent`); el `datalist` asigna `option.value` por propiedad |
| T-30-40 | `setBusy(true)` deshabilita el botón durante toda la operación y lo restaura en `finally` |

## Known Stubs

Ninguno.

## Self-Check: PASSED

- `frontend/js/components/markPerson.js` — FOUND
- `frontend/js/views/timeline.js` (`applyPersonAssignment`) — FOUND
- `frontend/js/app.js` (`bindMarkPerson`) — FOUND
- Commit `72e4a90` — FOUND
- Commit `e173181` — FOUND
