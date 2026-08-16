# Phase 26: Análisis de comportamiento - Context

**Gathered:** 2026-08-15
**Status:** Ready for planning
**Source:** Generado directamente desde ROADMAP.md + REQUIREMENTS.md + SPEC_v2.md §5.7,
contrastado con el código real (scope cerrado, sin discuss-phase)

<domain>
## Phase Boundary

El sistema pasa de responder "¿hay alguien?" a responder **"¿qué está ocurriendo?"**:
merodeo, carrera, inmovilidad prolongada, aglomeración y permanencia en zona, cada uno
con las magnitudes que lo justifican.

Hoy el pipeline sabe *dónde* está cada persona (tracks, zonas, línea de conteo) y *quién*
es (Fases 23-25: cara, identidad temporal, ReID), pero no interpreta el **movimiento** de
un track a lo largo del tiempo. Los seis tipos de evento de comportamiento ya existen en
el catálogo desde la Fase 19; cuatro de ellos no los emite nadie.

**Entra en esta fase:**
- `BehaviorAnalyzer` — analiza las trayectorias de los tracks y emite `LOITERING`,
  `RUNNING`, `IMMOBILE`, `CROWD_DETECTED`.
- Tiempo de permanencia en `ZONE_EXITED` (BEH-04 — hoy el evento se emite sin él).
- Umbrales configurables vía `backend/config.py` para los cuatro comportamientos.
- Payload con las magnitudes que justifican cada evento (BEH-05).

**No entra:**
- **Detección de caídas** — requiere estimación de pose (YOLO-pose). SPEC lo declara
  explícitamente fuera del alcance de v2.0 → backlog v2.1.
- `DIRECTION_CHANGED` — aparece en el docstring de SPEC §5.7 pero **no existe** en
  `EventType` ni en los 5 criterios de éxito del ROADMAP. Fuera de alcance.
- BEH-06..BEH-09 (multi-clase, objetos abandonados, contexto de escena) → Fase 27.

</domain>

<decisions>
## Implementation Decisions

### Umbrales y reglas (SPEC §5.7 — locked)

| Comportamiento | Regla | Default |
|---|---|---|
| `LOITERING` | tiempo en zona > `loiter_secs` **y** desplazamiento neto < `loiter_radius_px` | 120 s / 80 px |
| `RUNNING` | velocidad media > `run_speed_px_s` durante > 1 s | 350 px/s |
| `IMMOBILE` | desplazamiento < 20 px durante > 60 s | 20 px / 60 s |
| `CROWD_DETECTED` | tracks activos simultáneos >= `crowd_threshold` | 5 |

Todos configurables desde `backend/config.py` (pydantic-settings), como el resto.

### Hallazgos del código real que condicionan el diseño

Verificados antes de escribir este contexto — el planner debe partir de esto, no de la
lectura literal de SPEC §5.7:

**H-1 — Los 6 `EventType` ya existen** (`backend/events/types.py:24-34`):
`ZONE_ENTERED`, `ZONE_EXITED`, `LOITERING`, `RUNNING`, `IMMOBILE`, `CROWD_DETECTED`.
No hay que añadir tipos nuevos al catálogo. `DIRECTION_CHANGED` **no** existe.

**H-2 — `ZONE_ENTERED`/`ZONE_EXITED` ya se emiten y están cableados**:
`DetectionWorker._update_zones_and_heat` (`detection.py:249`) →
`EventEngine.process_zone` (`engine.py:117-138`). **Pero sin tiempo de permanencia.**
BEH-04 exige ese dato. Implementar la emisión de zona dentro de `BehaviorAnalyzer`,
como sugiere el docstring de SPEC §5.7, **duplicaría cada evento de zona**. El trabajo
real de BEH-04 es *añadir el dwell time al `ZONE_EXITED` existente*, no reimplementarlo.

**H-3 — El `TrackState` de SPEC §5.7 ya existe y es redundante.** El real
(`backend/pipeline/tracking.py:18-33`) ya tiene todos los campos que SPEC propone:
`track_id`, `first_seen`, `last_seen`, `centroid_history`, `zones`, `zone_entry_times`,
`person_id`, `identity_state`. **No crear un segundo `TrackState`** — sería una segunda
fuente de verdad sobre el estado de tracks, justo lo que `CLAUDE.md` prohíbe.

**H-4 (el más importante) — el historial existente es demasiado corto para los umbrales
de esta fase.** `centroid_history` es un `deque(maxlen=150)` de tuplas `(t, x, y)`
(`tracking.py:27`, `history_len=150` en `tracking.py:47`). A `detection_target_fps=8.0`
(`config.py:66`) eso son **~19 segundos** de historial. Pero `LOITERING` necesita mirar
120 s atrás e `IMMOBILE` 60 s. **Con el historial actual, ninguno de los dos se puede
calcular.** Cómo resolverlo es la decisión técnica central de la fase — ver preguntas
para RESEARCH abajo.

### Restricciones de arquitectura (de CLAUDE.md — no negociables)

- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- `TrackRegistry` es la fuente de verdad del estado de tracks; no duplicarla.
- Toda estructura con crecimiento potencial necesita política de expiración con test
  que la verifique (invariante de la Fase 22, ya aplicado a `TemporalVoter`,
  `IdentityStateMachine` y `TrackGallery` — aplica igual a lo que aporte esta fase).
- Reloj inyectado: nada de `time.monotonic()` dentro del dominio puro; se pasa `now`
  por parámetro (patrón establecido en las Fases 24 y 25).
- Cambio mínimo: no reescribir el pipeline de zonas ni el `EventEngine` existentes.

### Decisiones resueltas tras el research (locked, 2026-08-15)

El research cerró las preguntas técnicas y dejó 4 decisiones de producto. Resueltas
por el usuario:

**D-01 — Los eventos de comportamiento salen con severidad `INFO`.** Es el default del
catálogo (`types.py:49-57` no los incluye en `DEFAULT_SEVERITY`), así que es cambio
cero. Subirlos a `WARNING` activaría la grabación y subida automática de clips a Drive
(`upload_min_severity="warning"`, `config.py:115` → `recording.py:309`); si algún
comportamiento debe escalar, se hace con una regla en `rules.yaml`, no cambiando el
default. Reversible en una línea.

**D-02 — LOITERING usa la escena completa como zona implícita cuando no hay zonas
configuradas** (`zone_id=None`). Una instalación limpia tiene cero zonas
(`get_zones()` lee de BD y no hay seed), así que sin este fallback el evento no se
emitiría nunca y el criterio 1 no sería verificable. Se añade
`loiter_require_zone: bool = False` en config como escape para exigir zona explícita.

**D-03 — LOITERING e IMMOBILE coexisten.** Son señales distintas (merodear = quedarse
dando vueltas; inmovilidad = no moverse en absoluto) y cada una lleva sus propias
magnitudes en el payload. El aislamiento que exige el criterio 2 ("exactamente el
evento esperado y ninguno más") se consigue diseñando las trayectorias de test, **no**
metiendo supresión mutua en el dominio — sería lógica de política difícil de deshacer.

**D-04 — Con zonas solapadas se emite un LOITERING por zona.** El ancla de permanencia
se lleva por `(track, zona)`. Es lo correcto semánticamente (merodear en "entrada" y en
"jardín" son dos hechos distintos) y en la práctica multiplica el estado por 1-2.

### Preguntas para RESEARCH (decisión técnica, no de producto — RESUELTAS, ver 26-RESEARCH.md)

1. **¿Cómo se cubre la ventana temporal de 120 s (H-4)?** Dos caminos plausibles:
   (a) `BehaviorAnalyzer` mantiene su **propia** historia submuestreada por track
   (p. ej. 1 muestra/s → 120 muestras = 120 s, ~2 KB/track), siguiendo el patrón de
   estado acotado propio que ya usan `TemporalVoter`/`TrackGallery`; o (b) ampliar
   `history_len` de `TrackRegistry` (150 → ~1000), lo que multiplica la memoria de
   *todos* los consumidores del registry, no solo de esta fase. Investigar cuál encaja
   con el diseño real y con el invariante de memoria de la Fase 22, y medir el coste.
2. **¿Dónde corre `BehaviorAnalyzer`?** ¿En `DetectionWorker` (que ya tiene el `tracked`
   por frame, ya llama a `_update_zones_and_heat` y ya emite eventos vía `EventEngine`),
   o en otro sitio? Mirar el presupuesto de CPU del bucle caliente de detección y el
   patrón que siguieron las Fases 24/25 al elegir worker.
3. **¿Cómo se añade el dwell time a `ZONE_EXITED` sin romper nada (H-2)?**
   `zone_entry_times` ya existe en `TrackState`, pero ¿quién lo escribe hoy, si es que
   alguien lo hace? Trazar el código real: `EventEngine.process_zone` lleva su propio
   `_zone_inside` y puede no estar usando `zone_entry_times` en absoluto.
4. **`CROWD_DETECTED` es un evento de escena, no de track** — ¿cómo se evita que se
   emita en cada frame mientras dure la aglomeración? ¿Qué patrón de idempotencia usan
   ya los eventos de estado del `EventEngine` (p. ej. `camera_offline`)?
5. **Criterio 5: "usables como `when.event` en rules.yaml sin cambios en el RuleEngine"** —
   verificar leyendo el `RuleEngine` real si un `EventType` nuevo en una regla funciona
   sin tocar código, y qué exige el esquema (`config/rules.yaml`, SPEC §6.4).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato de la fase
- `propuesta_mejora/SPEC_v2.md` §5.7 — `BehaviorAnalyzer`, tabla de umbrales y defaults.
  Ojo: su `TrackState` propuesto es redundante (H-3) y su docstring menciona
  `ZONE_ENTERED/EXITED` y `DIRECTION_CHANGED` de forma engañosa (H-2, fuera de alcance).
- `propuesta_mejora/SPEC_v2.md` §9 (Phase 26) — ficheros y alcance.
- `.planning/ROADMAP.md` § Phase 26 — goal, dependencias y los 5 criterios de éxito.
- `.planning/REQUIREMENTS.md` § BEH — BEH-01..BEH-05 (BEH-06..09 son de la Fase 27).

### Código sobre el que se construye
- `backend/pipeline/tracking.py` — `TrackState` real (H-3) y `TrackRegistry`, incluido
  `centroid_history` y su `maxlen` (H-4).
- `backend/pipeline/detection.py` — `_update_zones_and_heat` (223-252) y el bucle
  caliente donde ya se emiten eventos por frame.
- `backend/events/engine.py` — `process_zone` (117-138), `process_tracks`, y el patrón
  de idempotencia de `camera_offline`.
- `backend/events/types.py` — catálogo de `EventType` (los 6 ya existen, H-1).
- `backend/events/rules.py` + `config/rules.yaml` — para el criterio 5.
- `backend/perception/face/identity.py` y `backend/perception/reid/gallery.py` —
  patrón de dominio puro con reloj inyectado y estado acotado (Fases 24/25).
- `backend/config.py` — bloques por fase con validadores de rango.

### Reglas del proyecto
- `CLAUDE.md` — invariantes de arquitectura y criterios de diseño.
- `.planning/STATE.md` — estado real de fases y checkpoints pendientes.

</canonical_refs>

<specifics>
## Specific Ideas

Criterios de éxito de ROADMAP § Phase 26 (los 5, verbatim — son los criterios de
aceptación de la fase):

1. Se emiten `LOITERING`, `RUNNING`, `IMMOBILE`, `CROWD_DETECTED`, `ZONE_ENTERED` y
   `ZONE_EXITED` con umbrales configurables.
2. Seis trayectorias sintéticas producen exactamente el evento esperado y ninguno más.
3. Cada evento incluye en `payload` las magnitudes que lo justifican.
4. El historial por track está acotado y no crece con el tiempo de sesión.
5. Los eventos de comportamiento son usables como `when.event` en `rules.yaml` sin
   cambios en el `RuleEngine`.

Magnitudes que BEH-05 exige en el payload (de SPEC §9 Phase 26 de la fase original):
`duration_s`, `speed_px_s`, `net_displacement_px`, `track_count` — cada evento lleva
las que lo justifican.

Ficheros previstos (SPEC §9 Phase 26 — contrastar con la realidad, como en las Fases
24 y 25 el research encontró que la lista de SPEC estaba incompleta o equivocada):
- Crear: `backend/perception/behavior.py`
- Modificar: `backend/pipeline/tracking.py`, `config/rules.yaml`
- Tests: `tests/test_behavior_analyzer.py`

</specifics>

<deferred>
## Deferred Ideas

- **Detección de caídas** — requiere pose (YOLO-pose); SPEC la declara fuera del alcance
  de v2.0 → backlog v2.1.
- **`DIRECTION_CHANGED`** — mencionado en el docstring de SPEC §5.7, sin `EventType` ni
  criterio de éxito que lo respalde. Si en el futuro se quiere, es fase aparte.
- **Multi-clase, objetos abandonados y contexto de escena** (BEH-06..BEH-09) → Fase 27.
- **Reglas nuevas en `rules.yaml` que usen estos eventos** — la fase debe *demostrar*
  que son usables (criterio 5), no poblar el fichero de reglas de producción; qué
  alertas quiere el usuario es decisión suya, no de esta fase.

</deferred>

---

*Phase: 26-an-lisis-de-comportamiento*
*Context gathered: 2026-08-15 — generado desde artefactos existentes + lectura del código real*
