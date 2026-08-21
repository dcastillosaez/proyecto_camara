# Phase 30: Event Timeline y centro de alertas - Context

**Gathered:** 2026-08-20
**Status:** Ready for planning
**Source:** Generado directamente por el orquestador a partir de ROADMAP.md, REQUIREMENTS.md, 30-UI-SPEC.md (ya aprobado, 6/6 dimensiones) y una inspección del backend/frontend actuales — sin sesión interactiva de `/gsd-discuss-phase` (suficiente contexto ya disponible, mismo criterio que la Fase 29).

<domain>
## Phase Boundary

Sustituir la tabla plana de eventos (`#events-list` en `frontend/index.html`) por una línea temporal accionable con filtros combinables resueltos en servidor, paginación por cursor, scroll infinito hasta 10.000 eventos, actualización en tiempo real (<1s) vía WebSocket, y un centro de alertas (cajón lateral) que agrupa alertas activas, muestra qué regla las disparó y permite silenciarlas por regla. Incluye "Marcar como persona" con precarga del crop y actualización retroactiva de los eventos del mismo track. NO incluye: vista de analítica (heatmap/rankings, Fase 31), vista de cámara/configuración visual (Fase 32), editor de reglas (`ruleEditor.js`, fuera de alcance — solo se consume `Rule.name` ya definido, no se edita), ni router/`js/store.js` (la fase sustituye el card existente en la misma página, no crea una vista nueva enrutada).

</domain>

<decisions>
## Implementation Decisions

### Diseño visual (ya fijado por 30-UI-SPEC.md — aprobado 6/6, no volver a preguntar)
- **D-01:** Sin frameworks/dependencias nuevas. Reutiliza el sistema de diseño heredado de `29-UI-SPEC.md` (Tailwind CDN, `components.css`, tokens de spacing 4/8/16/24/32/48/64, tipografía de 4 tamaños 12/14/16/30px, color slate-950/900 + acento azul único). Ver `30-UI-SPEC.md` para el contrato completo (spacing, tipografía, color, copywriting, 21 elementos de copy en español).
- **D-02:** Severidad como sistema de color semántico propio: rojo=crítico, ámbar=advertencia, **slate neutro=info** (deliberadamente NO verde, para no chocar con "SISTEMA ONLINE" del header de la Fase 29); verde reservado a identidad confirmada.
- **D-03:** Ancla visual: la barra/punto de severidad es el ancla primaria de cada fila de la timeline; el contador de 30px (hero) es el ancla del cajón de alertas.
- **D-04:** Fila de altura fija de 52px con ventana de recorte de DOM de 400 filas (virtualización simple, no una librería) y compensación de `scrollTop` al recortar por arriba. Plan B si el salto de scroll es perceptible: subir la ventana a 1000 filas y no recortar.
- **D-05:** Evento nuevo con la lista desplazada hacia abajo NO fuerza el scroll — aparece como píldora flotante "N eventos nuevos" (criterio de éxito 4, sin ser intrusivo).
- **D-06:** "Marcar como persona" muestra aviso explícito del alcance retroactivo antes de confirmar ("Se aplicará también a los eventos anteriores de este track (N)") — sin `confirm()` nativo, modal propio reutilizando el patrón de `personGallery.js`.
- **D-07:** "Descartar" y "Silenciar" no son operaciones destructivas modales: descartar usa toast+deshacer de 5s, silenciar usa un popover con duración obligatoria como confirmación implícita. No se añade ningún `confirm()` nuevo a la fase.
- **D-08:** Acciones de fila en cajas de 32×32px (mínimo WCAG 2.5.8), campana de alertas del header 44×44px, miniatura 64×36px (ratio fijo).

### Backend — filtros, cursor y tiempo real (OPS-09, OPS-10)
- **D-09:** Nuevo endpoint `GET /api/v2/events` (no existe hoy — `backend/api/v2/` solo tiene `context.py`, `detection.py`, `metrics.py`, `recordings.py`). Filtros combinables: `type[]`, `severity`, `person_id`, `zone_id`, `camera_id`, `from`, `to`, `cursor`, `limit<=200` (contrato ya fijado en `SPEC_v2.md` §8.1 — no renegociar la forma de los parámetros).
- **D-10:** Paginación por cursor, no por offset — con 10.000 eventos navegables (criterio 3), offset/`LIMIT-OFFSET` degrada. El cursor debe ser estable ante inserciones concurrentes (eventos nuevos llegando mientras se pagina hacia atrás en el tiempo).
- **D-11:** Los índices ya existentes en `backend/storage/models.py` (`idx_events_ts`, `idx_events_type_ts`, `idx_events_cam_ts`, `idx_events_person`) cubren los filtros por tipo/cámara/persona/tiempo — verificar en RESEARCH si hace falta un índice compuesto adicional para `severity`+`zone_id` combinados, o si se resuelven con los existentes + filtrado en aplicación sobre un resultado ya acotado por tiempo.
- **D-12:** El evento nuevo en <1s (criterio 4) se sirve por el canal WebSocket **ya existente** (`/ws`, con eventos ya emitidos hoy — ver `backend/main.py:303-306`, suscriptor `websocket_v1_compat`/`websocket_v2` al `event_bus`). No se requiere un nuevo tipo de mensaje WS para esto, a diferencia del `type: "tracks"` de la Fase 29 — los eventos YA se difunden en tiempo real, la fase solo tiene que consumirlos en la timeline sin recargar.

### "Qué regla disparó" (OPS-11) — el hueco técnico de mayor riesgo de la fase
- **D-13:** Hoy `RuleEngine.evaluate()` (`backend/events/rules.py:169`) calcula qué reglas dispararon (`fired.append(rule.name)`) pero **no** persiste ese dato en el `Event`: la tabla `events` (`backend/storage/models.py:85-109`) no tiene columna `rule_name`, solo un campo genérico `payload = Column(JSON, default=dict)` sin usar hoy para esto.
- **D-14:** Restricción arquitectónica real que RESEARCH debe respetar: en `backend/main.py:293-306`, `_persist_event` (persistencia) y `_apply_rules` (RuleEngine) son suscriptores **independientes** del mismo `event_bus`, cada uno en su propia tarea asyncio — el comentario del código es explícito: *"el orden de suscripción no determina el de ejecución"*. Los dos reciben el mismo objeto `Event` por referencia (EVT-02), pero no hay garantía de que `_apply_rules` termine de mutar el evento antes de que `_persist_event` lo escriba en SQLite. Cualquier solución para exponer `rule_name` en el evento persistido debe resolver esta condición de carrera explícitamente (opciones a evaluar en RESEARCH: mover la evaluación de reglas delante de la persistencia en el pipeline en vez de como suscriptor paralelo del bus; persistir el evento primero y hacer un `UPDATE` desde `_apply_rules` cuando termine; o publicar un segundo evento/mensaje `rule_fired` correlacionado por `event.id` que el frontend consuma aparte). No asumir que "mutar el objeto antes de que acabe la task" es seguro sin verificarlo.
- **D-15:** Usar el campo `payload` (JSON) existente para guardar los nombres de regla disparados, no añadir una columna nueva ni migración de esquema — evita tocar Alembic/migraciones para esta fase, coherente con "cambio mínimo" (CLAUDE.md, Regla final).

### Centro de alertas — agrupación y silenciado (OPS-11, criterio 6)
- **D-16:** El "silenciar por regla" opera sobre `Rule.name` (identificador ya existente en `backend/storage/models.py:187` tabla `rules` y en `backend/events/rules.py:46` `class Rule`), no sobre un ID de alerta individual — silenciar una regla debe dejar de generar nuevas entradas en el centro de alertas para esa regla hasta que expire la duración elegida.
- **D-17:** El popover de silenciado (D-07) exige duración obligatoria — RESEARCH debe decidir dónde persiste ese estado temporal (tabla nueva mínima tipo `muted_rules(rule_name, until, camera_id)`, o reutilizar `app_config` vía `ConfigRepo` con una clave estructurada — evaluar cuál es menos invasivo dado que no hay tabla de "silenciados" hoy).

### Claude's Discretion
- Forma exacta de la respuesta paginada de `GET /api/v2/events` (envelope `{items, next_cursor}` vs. cabecera `Link`, formato del cursor — opaco en base64 vs. timestamp+id compuesto legible).
- Si el WebSocket empuja el `Event` completo o solo un `id` que dispara un `GET /api/v2/events/{id}` — depende de cuánto payload ya se serializa hoy en `websocket_v2`/`websocket_v1_compat` (ver `backend/main.py`) y si basta reutilizarlo.
- Diseño exacto de la virtualización de 400 filas (IntersectionObserver vs. cálculo manual de scroll) — sin librería nueva, coherente con D-04.
- Estructura de datos concreta para el estado de "silenciado" (D-17) y su TTL de limpieza.
- Si `GET /api/v2/timeline` (mencionado en `SPEC_v2.md` §8.1 como endpoint separado "eventos agrupados por bloques") es necesario para esta fase o si `GET /api/v2/events` con filtros ya cubre el caso de uso — el wireframe de UI-SPEC no exige agrupación temporal visual explícita más allá de los separadores de hora (`.timeline-sep`, ya en 30-UI-SPEC.md).

</decisions>

<specifics>
## Specific Ideas

- El wireframe de referencia es `SPEC_v2.md` §8.1 (endpoints) — orientativo para la forma de la API, ya refinado por `30-UI-SPEC.md` para la parte visual.
- Precedente directo de paginación/filtros combinables en este proyecto: ninguno hoy expone cursor — es la primera vez que se introduce este patrón, documentarlo bien para que Fases 31/32 lo reutilicen si aplica.
- "10.000 eventos navegables sin degradación perceptible" (criterio 3) es el criterio más exigente de la fase en el backend; "evento nuevo en <1s" (criterio 4) es el más exigente en el frontend — cualquier ambigüedad de diseño debe resolverse a favor de estos dos, no de funcionalidad adicional no pedida.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato visual (fuente de verdad para UI)
- `.planning/phases/30-event-timeline-y-centro-de-alertas/30-UI-SPEC.md` — contrato de diseño completo, aprobado (6/6 dimensiones), sustituye cualquier decisión visual no explícita en este CONTEXT.md

### Alcance funcional y criterios de éxito
- `.planning/ROADMAP.md` § Phase 30 — goal, dependencias (Fase 29), requisitos OPS-07..OPS-11, 6 criterios de éxito
- `.planning/REQUIREMENTS.md` líneas 249-253 — descripción completa de OPS-07..OPS-11

### Especificación técnica
- `propuesta_mejora/SPEC_v2.md` §8.1 — contrato de endpoints `/api/v2/events`, `/api/v2/timeline` (filtros, paginación por cursor)
- `propuesta_mejora/SPEC_v2.md` §8.2 — estructura de frontend objetivo (`js/components/eventCard.js`, `alertCenter.js` — no existe aún, es de esta fase)

### Convenciones del proyecto
- `CLAUDE.md` — invariantes críticos, stack cerrado, Regla final ("cambio mínimo")
- `.planning/phases/29-vista-de-operaciones/29-CONTEXT.md` y `29-UI-SPEC.md` — sistema de diseño y patrones heredados directamente

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `frontend/js/components/eventCard.js` (189 líneas): ya tiene `openClipModal()` y `bindEventCardControls()` — patrón de tarjeta de evento con thumbnail y modal de clip a extender, no reescribir desde cero.
- `frontend/js/components/personGallery.js`: modal de enrolado (`enrollModal`/`enrollForm`, `bindPersonGallery()`) — patrón directo a reutilizar para el modal de "Marcar como persona" (D-06).
- `frontend/index.html` líneas ~469-514: barra de filtros actual (`#filter-direction`, `#filter-person`, `#filter-intrusion`, `#filter-from`, `#filter-to`) y `#events-list` — el card a sustituir ya existe con filtros básicos client-side; la fase los mueve a resolución en servidor.
- `backend/pipeline/manager.py:346` `get_object_boxes()` y el loop de tracks de la Fase 29 (`_tracks_broadcast_loop`) — precedente de "pull periódico + broadcast WS" si hiciera falta un mecanismo similar para alertas agrupadas en vivo.
- `backend/storage/repositories.py:42` `class EventRepo` — punto de extensión natural para el nuevo método de consulta paginada por cursor con filtros combinables.
- `backend/storage/repositories.py:579` `class RuleRepo` — ya gestiona reglas persistidas, candidato para extender con el estado de "silenciado por regla" (D-17) si se decide no crear tabla nueva.

### Established Patterns
- `event_bus` con suscriptores independientes por tarea (`backend/main.py:299-306`) — cualquier nuevo suscriptor (p.ej. para invalidar caché o recalcular agrupación de alertas) sigue el mismo patrón `event_bus.subscribe(name, handler)`.
- Invariante "ningún hilo hace await, ninguna corrutina ejecuta inferencia" (CLAUDE.md #5/#6) no aplica directamente aquí (fase de API/frontend, no de pipeline de captura), pero el patrón de "nunca bloquear el event loop con trabajo pesado" sí aplica a la consulta paginada sobre 10.000 filas — usar SQLAlchemy async (ya el estándar del proyecto) e índices, no post-filtrado en Python sobre todo el resultset.
- `frontend/js/app.js` (bootstrap real desde Fase 28) — punto de registro de listeners de arranque para la nueva timeline y el cajón de alertas.

### Integration Points
- `frontend/index.html` — shell puro tras la Fase 28; el card de `#events-list` se sustituye in situ, se añade un `<aside>`/cajón lateral para el centro de alertas sin crear una vista nueva ni tocar el router (no existe router, es SPA de una sola página).
- WebSocket: reutilizar `frontend/js/websocket.js` (ya con backoff y dispatch por `case`, extendido en la Fase 29 con `type: "tracks"`) añadiendo el manejo del evento ya emitido para refrescar la timeline sin recargar.

</code_context>

<deferred>
## Deferred Ideas

- Vista de analítica (heatmap, ranking, tendencias) — Fase 31.
- Vista de cámara y árbol de configuración visual — Fase 32.
- Editor de reglas (`ruleEditor.js`, crear/editar reglas desde la UI) — no está en el alcance de OPS-07..11, esta fase solo consume `Rule.name` para mostrar qué regla disparó y permitir silenciarla, no editarla.
- `js/store.js` y router de vistas — seguirán diferidos hasta que una fase futura realmente lo necesite (ninguna de las Fases 29/30 lo ha requerido hasta ahora).

</deferred>

---

*Phase: 30-event-timeline-y-centro-de-alertas*
*Context gathered: 2026-08-20*
