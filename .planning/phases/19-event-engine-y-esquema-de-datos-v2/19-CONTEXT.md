# Phase 19: Event Engine, Rule Engine y esquema de datos v2 - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §6, §7, ADR-05, ADR-06
**Requirements:** EVT-01..EVT-05, RULE-01..RULE-04, DB-10..DB-14

<domain>
## Phase Boundary

Esta fase cambia el modelo mental del sistema: de "detecciones que se guardan" a "eventos tipados que se evaluan contra reglas".

**Dentro:** catalogo de 22 `EventType`, modelo `Event`, `EventBus`, `EventEngine`, `RuleEngine` con `rules.yaml`, esquema de datos v2 con `storage/` y migraciones idempotentes, conversion de `notifier.py` en accion de regla, agregacion de detecciones en `detection_stats`.

**Fuera:** eventos de comportamiento (`LOITERING`, `RUNNING`...) — la Fase 26 los emite, pero el catalogo se define completo ahora para que el contrato sea estable. Eventos de identidad avanzada (`IDENTITY_LOST`) — Fase 24. El editor visual de reglas — Fase 33.

**Criterio dominante:** el histórico de v1.2 sobrevive intacto a la migración.
</domain>

<decisions>
## Implementation Decisions

### Un unico objeto Event para tres consumidores
El mismo `Event` (Pydantic) viaja al `EventBus`, se persiste en `events` y se serializa al WebSocket. No hay DTOs intermedios ni mapeos. Si un consumidor necesita un campo, se anade al modelo, no se crea una variante.

### El catalogo se define completo desde ahora
Los 22 `EventType` se declaran en esta fase aunque solo unos pocos se emitan todavia. Motivo: el `type` acaba en la BD y en `rules.yaml`; cambiar el enum despues obliga a migrar datos y reglas de usuario.

### Detecciones agregadas, no persistidas
A 8 FPS de deteccion son ~700.000 filas al dia. `detection_stats` guarda una fila por minuto con `detections`, `unique_tracks`, `avg_confidence` y `max_concurrent`. El acumulador vive en memoria y se vuelca cada minuto.

### RuleEngine con Pydantic, sin eval
`rules.yaml` se valida contra modelos Pydantic. Una regla invalida se desactiva y se loguea; no tumba el arranque. Nunca se ejecuta codigo arbitrario del fichero de reglas.

### notifier.py deja de decidir
Hoy `Notifier` contiene la logica de "cuando alertar" (`alert_on_intrusion`, `alert_on_unknown`, `alert_cooldown_secs`). Esa logica se traduce a reglas equivalentes en `rules.yaml` y `Notifier` queda reducido a ejecutor de las acciones `telegram` y `webhook`. Las variables `.env` actuales siguen funcionando: se leen al generar el `rules.yaml` inicial.

### Migracion con red de seguridad
Antes de tocar el esquema, copia de `data/events.db` a `data/backups/events-{ts}.db`. Migraciones idempotentes registradas en `app_config['schema_version']`. Un test ejecuta la migracion dos veces seguidas y comprueba que el resultado es identico.

### camera_id en todas las tablas nuevas
Con default `'cam1'` para las migradas. La Fase 35 solo tendra que quitar el default, no anadir la columna.

### Claude's Discretion
- Si `EventBus` usa `asyncio.Queue` con fan-out manual o una lista de callbacks async.
- Formato exacto de `payload` por tipo de evento (dict libre validado por convencion, no por esquema estricto).
- Si `detection_stats` se vuelca con un `asyncio.Task` periodico o desde el propio `DetectionWorker`.
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` §6.1 (catalogo), §6.2 (estructura), §6.3 (WebSocket v2), §6.4 (rules.yaml), §7 (modelo de datos), ADR-05, ADR-06

### Codigo existente que se toca
- `backend/database.py` — `CrossingEvent` (24), `Zone` (34), `Capture` (44), `Recording` (53), `insert_event` (111), `get_events_filtered` (147), `get_stats_today` (357), `purge_old_events` (387)
- `backend/notifier.py` — `Notifier` (27), toda la logica de decision
- `backend/main.py` — `_broadcast` (63), `_drain_events` (75), `websocket_endpoint` (513)
- `backend/pipeline/detection.py` — `_emit_crossings` (creado en 18-01)

### Planificacion
- `.planning/ROADMAP.md` § Phase 19
- `.planning/phases/18-workers-desacoplados-e-inferencia-adaptativa/18-02-SUMMARY.md`
</canonical_refs>

<specifics>
## Specific Ideas

- El test de identidad de payload (EVT-02) es simple y valioso: publicar un `Event`, capturarlo en los tres consumidores y afirmar `a is b is c` o, si hay serializacion de por medio, que los tres `model_dump()` son iguales.
- El `debounce` necesita una clave compuesta `(rule_name, camera_id, person_id or track_id)`. Un debounce global por regla haria que la alerta de una persona silenciara la de otra.
- Al migrar `crossing_events`, el `type` es siempre `LINE_CROSSED` y la direccion (entrada/salida) va en `payload["direction"]`. No inventar `PERSON_ENTERED`/`PERSON_EXITED` retroactivamente: no hay informacion de zona en los datos de v1.
- El `rules.yaml` inicial debe generarse a partir de la configuracion `.env` existente para que el usuario no pierda sus alertas al actualizar.

## Deferred Ideas
</specifics>

<deferred>
## Deferred Ideas

- Editor visual de reglas → Fase 33.
- `POST /api/v2/rules/{id}/test` contra el historico → Fase 33.
- Eventos de comportamiento y de objetos → Fases 26 y 27 (el catalogo ya los contempla).
- Migracion a PostgreSQL → Fase 37 (los repositorios de esta fase la habilitan).
- Retencion diferenciada por severidad de evento → Fase 20.
</deferred>

---
*Context creado: 2026-08-07*
