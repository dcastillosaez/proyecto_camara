# Phase 22: Deuda de seguridad y gestion de memoria - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §1.3
**Requirements:** SEC-15, SEC-16, PIPE-07

<domain>
## Phase Boundary

Cierra el bloque A. Dos frentes: la deuda de seguridad realmente pendiente y la garantia de que el sistema aguanta 24/7 sin crecer en memoria.

**Dentro:** eliminacion total de `pickle` del codigo de produccion, validacion de `yolo_model_path`, hardening de la superficie nueva de `/api/v2`, politica de expiracion verificada en todas las estructuras con crecimiento potencial, y una prueba de resistencia de 8 horas.

**Fuera:** las 12 vulnerabilidades de `vulnerabilidades.md` que ya estan corregidas en v1.2 — se verifican, no se reimplementan.

**Criterio dominante:** tras 8 horas de operacion continua, el RSS es estable y ninguna cola ha desbordado.
</domain>

<decisions>
## Implementation Decisions

### El estado real de la seguridad es mejor de lo que sugiere el documento
Verificado contra el codigo: 12 de las 14 vulnerabilidades de `vulnerabilidades.md` ya estan corregidas (CORS en `main.py:312`, slowapi en `main.py:302`, SAN en `ssl_utils.py:59`, headers en `main.py:320`, TTL de tokens en `auth.py:21`, cota de `limit` en `main.py:442`, `max_length` en `main.py:551`, validacion de `content_type` en `main.py:567`, `mask_rtsp_url` en `config.py:147`, permisos de clave en `ssl_utils.py:87`, SRI en `index.html:8`, `build_rtsp_url` en `config.py:134`).

Quedan dos: el `pickle.loads` residual (`recognizer.py:485`) y la validacion de `yolo_model_path`. Esta fase los cierra y verifica el resto con tests de regresion.

### pickle sale por completo, la migracion se hace una vez
Hoy `_blob_to_encoding` (`recognizer.py:479`) intenta `np.frombuffer` y cae a `pickle.loads` si falla. Eso mantiene viva la ruta de deserializacion insegura de forma permanente. La solucion es un script explicito `scripts/migrate_embeddings.py` que se ejecuta una vez, convierte todos los blobs y deja el codigo de produccion sin ninguna referencia a `pickle`.

Nota de oportunidad: la Fase 23 sustituye estos embeddings por ArcFace 512D de todas formas. Aun asi, esta fase los limpia — el bloque A no debe dejar deuda de seguridad abierta a la espera de una fase futura que podria retrasarse.

### La validacion de model path es de contencion, no de extension
Comprobar solo la extension `.pt` no impide `../../../../etc/algo.pt`. La validacion correcta es resolver el path y comprobar que esta contenido en el directorio del proyecto, ademas de la extension.

### La memoria se prueba, no se razona
Toda estructura con crecimiento potencial tiene un test de cota. La lista, derivada de las fases 17-21: `TrackRegistry._tracks` y `centroid_history`, cachés del reconocedor (`_tid_last_seen`, `get_cached`), debounce del `RuleEngine`, cola del `EventBus`, `RingFrameBuffer`, `_live_queue` del `RecordingWorker`, deques del `LatencyTracker`, estados de zona y heatmap.

### La prueba de 8 horas no va en CI
Se ejecuta como job manual o nocturno. En CI corre una version de 10 minutos con reloj acelerado y umbrales proporcionales.

### Claude's Discretion
- Si el hardening de `/api/v2` se hace con una dependencia comun o endpoint a endpoint.
- Umbral exacto de estabilidad de RSS (la spec dice ±10% tras la primera hora).
- Formato del informe de la prueba de resistencia.
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` §1.3 (estado real de vulnerabilidades), Phase 22
- `propuesta_mejora/vulnerabilidades.md` — documento original

### Codigo existente que se toca
- `backend/recognizer.py` — `_blob_to_encoding` (479), `_load` (489), migracion legacy (485-519), `prune` (337)
- `backend/config.py` — `yolo_model_path` (29)
- `backend/api/v2/*` — todo lo creado en las fases 17-21
- `backend/pipeline/tracking.py`, `backend/events/rules.py`, `backend/events/bus.py`, `backend/pipeline/prebuffer.py`

### Planificacion
- `.planning/ROADMAP.md` § Phase 22
- `.planning/phases/21-observabilidad-y-latencia-e2e/21-01-SUMMARY.md` — la linea base de metricas es la referencia de la prueba de resistencia
</canonical_refs>

<specifics>
## Specific Ideas

- El test `grep -rn "pickle" backend/` como criterio de aceptacion es literal y automatizable; conviene dejarlo como test de arquitectura junto a los de la Fase 18.
- Las metricas de la Fase 21 hacen la prueba de 8 h mucho mas util: en lugar de mirar solo el RSS, se pueden observar `queue_depth`, `active_tracks` y `prebuffer_bytes` a lo largo del tiempo. Un crecimiento monotono de cualquiera de ellos es el sintoma.
- Para la prueba de resistencia conviene un script que muestree `/api/v2/metrics` cada minuto a un CSV. Asi el analisis posterior es una grafica, no una impresion.
- `tracemalloc` con snapshots comparados a la hora 1 y a la hora 8 identifica el origen exacto de una fuga si la hay.
- El caso mas probable de fuga en este sistema son las cachés indexadas por `track_id`: los tracks son efimeros e ilimitados en el tiempo.

</specifics>

<deferred>
## Deferred Ideas

- Auditoria de seguridad externa → fuera de v2.0.
- Autenticacion por token/OAuth en lugar de basic auth → no esta en la propuesta; el sistema es LAN.
- Cifrado de los embeddings faciales en reposo → considerar en v2.1 si el sistema sale de la LAN.
- Rotacion automatica de la clave SSL → v2.1.
</deferred>

---
*Context creado: 2026-08-07*
