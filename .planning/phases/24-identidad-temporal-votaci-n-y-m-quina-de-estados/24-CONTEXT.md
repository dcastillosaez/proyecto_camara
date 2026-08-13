# Phase 24: Identidad temporal — votación y máquina de estados - Context

**Gathered:** 2026-08-12
**Status:** Ready for planning
**Source:** Generado directamente desde ROADMAP.md + REQUIREMENTS.md + SPEC_v2.md §5.5 (scope cerrado, sin discuss-phase)

<domain>
## Phase Boundary

Una persona pasa a ser "Juan" tras **evidencia coherente acumulada**, no tras un frame
afortunado, y sigue siendo Juan aunque se pierda momentáneamente el track.

Hoy (tras la Fase 23) el reconocimiento facial produce embeddings ArcFace 512D con
quality gating, pero la decisión de identidad es **por frame**: cada resultado de
`FaceEngine` se traduce en identidad sin memoria temporal. Eso produce tres problemas
que esta fase cierra:

1. Un único frame con buen score puede asignar una identidad equivocada.
2. Una visita genera N eventos de reconocimiento (uno por frame), no uno.
3. Perder y recuperar un track crea identidades duplicadas (`Juan_2`, `Juan_3`).

**Entra en esta fase:**
- `TemporalVoter` — ventana deslizante de votos por track.
- `IdentityStateMachine` — 4 estados explícitos y sus transiciones.
- Disparo del reconocimiento **por evento**, no cada N frames a ciegas.
- Emisión de `PERSON_RECOGNIZED` / `IDENTITY_LOST` desde la máquina de estados.

**No entra (fases posteriores):**
- ReID por apariencia cuando la cara no es visible → Fase 25.
- Mostrar el estado "verificando…" en la interfaz → bloque C (fases 29-30). Esta fase
  deja el estado disponible en el modelo de datos; no construye UI.

</domain>

<decisions>
## Implementation Decisions

### Contratos (de SPEC_v2.md §5.5 — locked)

```python
class TemporalVoter:
    """Ventana deslizante de votos por track."""
    def __init__(self, window: int = 8, min_votes: int = 3,
                 min_ratio: float = 0.6): ...
    def vote(self, track_id: int, person_id: int | None, score: float) -> None: ...
    def verdict(self, track_id: int) -> tuple[int | None, float]:
        """(person_id ganador, confianza agregada) o (None, 0.0)"""

class IdentityStateMachine:
    def on_face_result(self, track_id: int, person_id: int | None, score: float) -> Event | None
    def on_track_lost(self, track_id: int) -> Event | None
    def on_tick(self, now: float) -> list[Event]
    def state_of(self, track_id: int) -> IdentityState
```

### Estados y transiciones (locked)

- `UNKNOWN` → `CANDIDATE`: hay match por encima del umbral.
- `CANDIDATE` → `UNKNOWN`: votos insuficientes / incoherentes.
- `CANDIDATE` → `CONFIRMED`: N votos coherentes en la ventana.
- `CONFIRMED` → `TEMPORARILY_LOST`: track sin cara visible.
- `TEMPORARILY_LOST` → `CONFIRMED`: reaparece con match coherente.
- `TEMPORARILY_LOST` → `UNKNOWN`: vence `lost_ttl`.

### Parámetros por defecto (locked, configurables)

`min_votes=3`, `window=8`, `min_ratio=0.6`, `lost_ttl=30 s`, `revalidate_after=120 s`.
Van a `backend/config.py` vía pydantic-settings, como el resto de la configuración.

### Eventos

Usa los tipos ya existentes del catálogo (§6.1), sin inventar nuevos:
`PERSON_RECOGNIZED`, `UNKNOWN_PERSON`, `IDENTITY_LOST`.

- `PERSON_RECOGNIZED` se emite **al confirmar**, una sola vez por visita.
- `IDENTITY_LOST` se emite tras 3 revalidaciones fallidas consecutivas.

### Disparo por evento (FACE-11)

El reconocimiento deja de ejecutarse cada N frames. Se dispara solo cuando:
- aparece un track nuevo,
- la confianza del track es baja,
- vence `revalidate_after` (120 s) en un track `CONFIRMED`.

Objetivo medible: con 1 persona estática en escena, las inferencias faciales por
minuto bajan **al menos un 70%** respecto a la Fase 23.

### Restricciones de arquitectura (de CLAUDE.md — no negociables)

- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- El estado compartido de tracks vive en `TrackRegistry` (`pipeline/tracking.py`).
- Toda estructura con crecimiento potencial necesita política de expiración con test
  que la verifique (invariante de la Fase 22 — aplica a `TemporalVoter` y a
  `IdentityStateMachine`, ambas citadas explícitamente en su criterio 5).
- Cambio mínimo: no reescribir `recognizer.py`, que la Fase 23 ya dejó reducido a
  orquestación.

### Decisiones resueltas tras el research (locked, 2026-08-12)

El research encontró cuatro puntos que el SPEC no cerraba. Decisiones del usuario:

**Criterio 6 — se mide sobre un track NO confirmado.** Es el único escenario donde el
criterio tiene sentido: hoy un track que no llega a confirmarse reintenta el
reconocimiento indefinidamente (~120 inferencias/min), mientras que un track ya
identificado hace 0 inferencias porque `_next_candidate` lo filtra
(`recognition.py:147`) — medir ahí daría una reducción del 0% o incluso negativa,
ya que esta fase *añade* la revalidación cada 120 s. El SUMMARY debe documentar el
escenario exacto medido, no solo el porcentaje.

**`UNKNOWN_PERSON` se emite al entrar en UNKNOWN desde CANDIDATE.** Es decir, cuando
la votación descarta la identidad tras haber intentado identificar. Una sola vez por
track, coherente con el "un evento por visita" de FACE-09. No se emite al crear un
track ni por frame sin match.

**El disparador "confianza baja" (FACE-11) usa la confianza de identidad del voter**,
la que devuelve `TemporalVoter.verdict()` — no `TrackState.confidence`, que es la
confianza de detección de YOLO. Son conceptos distintos: una caja borrosa no implica
identidad dudosa.

**"Tres fallos consecutivos" (criterio 5) = tres ciclos de revalidación**, es decir
tres ventanas de `revalidate_after` vencidas sin match, no tres inferencias faciales
seguidas. Tolera frames malos puntuales y respeta el principio de "evidencia
coherente" de la fase.

### Decisiones resueltas tras la verificación de planes (locked, 2026-08-12)

El plan-checker encontró un fallo de diseño que ningún test cubría. Verificado en
código antes de aceptarlo.

**D-05 — La detección de "track perdido" NO usa `TrackRegistry.active_ids()`.**
`active_ids()` (`tracking.py:87-89`) devuelve todas las claves de `_tracks`, y lo único
que las borra es `prune(now, ttl=30.0)` (`detection.py:185`, `main.py:192`). Un track
sigue figurando como activo hasta 30 s después de que la persona desaparezca; como
ByteTrack asigna un `track_id` nuevo al reaparecer, la FSM lo tomaría como visita nueva
y emitiría un **segundo** `PERSON_RECOGNIZED` — exactamente lo que FACE-10 y el
criterio 4 prohíben. El fallo no aparece en tests sintéticos que llaman a
`on_track_lost()` directamente; solo en operación real con oclusiones de pocos segundos.

**Solución:** `DetectionWorker` publica el set de `track_id` realmente vistos en el
frame actual, y `RecognitionWorker` lo consume para alimentar `on_active_tracks`. Ese
set **ya se calcula** en `_emit_track_lifecycle` (`detection.py:191`:
`active_ids = {int(tid) for tid in ids}`); hoy solo se pasa a
`event_engine.process_tracks`. Es el dato preciso e inmediato, sin TTL de por medio.

Requisito de test: un test de integración que recorra la ruta real (no llamadas
directas a `on_track_lost`) con un `track_id` nuevo reapareciendo antes de `lost_ttl`,
verificando que **no** se emite un segundo `PERSON_RECOGNIZED`.

**D-06 — `revalidate_after` (120 s) se cuenta desde la última revalidación con éxito**,
no desde la confirmación inicial. Cada match coherente reinicia el contador
(`last_revalidation_at`), de modo que un track `CONFIRMED` se revalida de forma regular
cada 120 s mientras siga identificándose correctamente.

### Claude's Discretion

- Estructura interna del voto (deque, contadores) y cómo se agrega la confianza.
- Si `IdentityState` es `Enum` o `StrEnum`, y dónde vive exactamente.
- Reparto entre `identity.py` y los módulos que lo invocan.
- Nombres de los tests, más allá de los ficheros indicados en SPEC §9.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato de la fase
- `propuesta_mejora/SPEC_v2.md` §5.5 — máquina de estados, firmas de `TemporalVoter` e
  `IdentityStateMachine`, parámetros por defecto y criterio de aceptación clave.
- `propuesta_mejora/SPEC_v2.md` §9 (Phase 24) — ficheros a crear/modificar y riesgo.
- `.planning/ROADMAP.md` § Phase 24 — goal, dependencias, requisitos y los 6 criterios
  de éxito verificables.
- `.planning/REQUIREMENTS.md` § FACE — FACE-07 a FACE-11, texto exacto de cada requisito.

### Modelo de eventos
- `propuesta_mejora/SPEC_v2.md` §6.1 — catálogo de tipos de evento (usar los existentes).
- `backend/events/types.py` — `EventType` y `Event` reales en código.

### Código sobre el que se construye
- `backend/perception/face/engine.py` — `FaceEngine` (Fase 23), origen de los resultados.
- `backend/recognizer.py` — orquestación actual del reconocimiento.
- `backend/pipeline/tracking.py` — `TrackRegistry`, estado compartido de tracks.
- `backend/pipeline/recognition.py` — worker que hoy dispara el reconocimiento.
- `backend/events/engine.py` — dónde se emiten los eventos.

### Reglas del proyecto
- `CLAUDE.md` — invariantes de arquitectura, stack cerrado y criterios de diseño.
- `.planning/STATE.md` — estado real de fases y checkpoints pendientes.

</canonical_refs>

<specifics>
## Specific Ideas

Criterios de éxito de ROADMAP § Phase 24 (los 6, verbatim — son los criterios de
aceptación de la fase):

1. Los 4 estados (UNKNOWN, CANDIDATE, CONFIRMED, TEMPORARILY_LOST) y sus transiciones
   están testeados uno a uno.
2. Una secuencia de 200 frames de una persona conocida emite exactamente un
   PERSON_RECOGNIZED.
3. Con embeddings ruidosos alternando dos identidades, el track permanece en CANDIDATE
   y no confirma ninguna.
4. Cero identidades duplicadas tras pérdida y recuperación de track.
5. La revalidación tras 120 s funciona y tres fallos consecutivos emiten IDENTITY_LOST.
6. Las inferencias faciales por minuto con una persona estática bajan al menos un 70%
   respecto a la Phase 23.

Ficheros previstos (SPEC §9 Phase 24):
- Crear: `backend/perception/face/identity.py`
- Modificar: `backend/perception/face/engine.py`, `backend/events/engine.py`
- Tests: `tests/test_temporal_voting.py`, `tests/test_identity_state_machine.py`

Métrica citada en el criterio 4: `identities_created_total` = 0 en ese test.

</specifics>

<deferred>
## Deferred Ideas

- **Estado "verificando…" en la interfaz** — el riesgo de SPEC §9 (latencia de
  confirmación percibida) se mitiga mostrando el candidato en la UI desde el primer
  voto. La emisión del estado entra aquí; pintarlo es del bloque C (fases 29-30).
- **ReID por apariencia** para mantener identidad sin cara visible → Fase 25. Esta fase
  cubre la pérdida temporal por `lost_ttl`, no la re-identificación por ropa/silueta.
- **Checkpoint 23-02** (tasa de aciertos ArcFace vs dlib con datos reales) sigue
  pendiente de cámara real. No bloquea esta fase: la 24 depende de la 23 en código,
  que ya está completa.

</deferred>

---

*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Context gathered: 2026-08-12 — generado desde artefactos existentes*
