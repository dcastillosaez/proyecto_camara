# Phase 25: Re-identificación de personas (ReID) - Context

**Gathered:** 2026-08-13
**Status:** Ready for planning
**Source:** Generado directamente desde ROADMAP.md + REQUIREMENTS.md + SPEC_v2.md
ADR-04/§5.6 (scope cerrado, sin discuss-phase)

<domain>
## Phase Boundary

El sistema mantiene la identidad de una persona cuando la cara deja de ser visible
(se gira de espaldas, sale de encuadre un momento, ocluida por otra persona), en vez
de perderla y volver a tratarla como desconocida al reaparecer.

Hoy (tras la Fase 24) la única vía de continuidad de identidad es
`IdentityStateMachine._claim_lost(person_id, now)`: exige que el track reaparecido
tenga un resultado **facial** que vote por el mismo `person_id`, dentro de `lost_ttl`
(30 s). Si la persona no muestra la cara al reaparecer (de espaldas, por ejemplo),
`_claim_lost` nunca se invoca — el track queda `TEMPORARILY_LOST` hasta que vence el
TTL y pasa a `UNKNOWN`. Esta fase añade una **segunda vía** de recuperación, por
apariencia (ropa/silueta), que actúa cuando la cara no está disponible.

**Entra en esta fase:**
- `ReIDEngine` — embeddings de apariencia (512D) por crop de persona, vía OSNet ONNX.
- `TrackGallery` — mantiene los embeddings de tracks cerrados recientemente y resuelve
  si un track nuevo hereda la identidad de uno de ellos.
- Disparo acotado: como máximo 1 inferencia ReID cada 2 s por track (criterio 5).
- Flag de seguridad `REID_INHERIT_IDENTITY`: en modo solo-observación, ReID calcula y
  registra la decisión de herencia sin aplicarla — para poder auditar falsos
  positivos antes de activarlo en producción.

**No entra (fuera de alcance):**
- Comportamiento (merodeo, carrera, aglomeración) → Fase 26.
- Multi-clase/objetos → Fase 27.
- Cualquier cambio a `TemporalVoter`/la votación facial — la Fase 25 añade una vía de
  recuperación adicional, no toca la existente.

</domain>

<decisions>
## Implementation Decisions

### Contratos (de SPEC_v2.md §5.6 — locked)

```python
class ReIDEngine:
    def embed(self, person_crop: np.ndarray) -> np.ndarray:  # 512D normalizado

class TrackGallery:
    """Mantiene continuidad de identidad cuando la cara no es visible."""
    def update(self, track_id: int, emb: np.ndarray, identity: int | None) -> None
    def resolve(self, track_id: int, emb: np.ndarray) -> tuple[int | None, float]:
        """Si un track nuevo se parece a un track reciente con identidad, la hereda."""
```

### ADR-04 (locked)

- Modelo: `osnet_x0_25` exportado a ONNX, ~2.2M parámetros, diseñado para ReID de
  personas, CPU-friendly. Se descarta `torchreid` completo (arrastra PyTorch).
- Política: ReID se calcula 1 vez cada N frames/segundos por track, no por frame.

### Política de herencia (SPEC §5.6 — locked)

Un track nuevo hereda identidad de un track cerrado hace **< 15 s** si la similitud
ReID es **> 0.7** **y** no hay conflicto con otro track activo que ya tenga esa
identidad. Umbral conservador deliberado (SPEC §9 Riesgo): una fusión errónea de
identidad es peor que no fusionar.

### Parámetros por defecto (locked, configurables vía `backend/config.py`)

- `reid_inherit_window_secs = 15.0` (ventana de herencia — más corta que
  `identity_lost_ttl_secs=30.0` de la Fase 24, porque ReID por apariencia es menos
  fiable que la votación facial y debe expirar antes)
- `reid_similarity_threshold = 0.7`
- `reid_interval_secs = 2.0` (máximo 1 inferencia ReID cada N s por track — criterio 5)
- `reid_inherit_identity: bool = False` (flag `REID_INHERIT_IDENTITY` — por defecto
  en modo **solo-observación**: calcula y registra la decisión de herencia sin
  aplicarla, hasta que se audite la tasa de falsos positivos con datos reales)

### Restricciones de arquitectura (de CLAUDE.md — no negociables)

- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- El estado compartido de tracks vive en `TrackRegistry`; no duplicar fuente de verdad
  con la que ya escribe `IdentityStateMachine`.
- Toda estructura con crecimiento potencial necesita política de expiración con test
  que la verifique (mismo invariante de la Fase 22 que ya aplicó a `TemporalVoter`/
  `IdentityStateMachine` — aplica igual a `TrackGallery`).
- Cambio mínimo: no reescribir `IdentityStateMachine`; ReID es una vía de recuperación
  **adicional**, no un reemplazo de `_claim_lost`.

### Preguntas para RESEARCH (no cerradas aquí — decisión técnica, no de producto)

1. **¿Dónde exactamente se integra `TrackGallery.resolve()` con
   `IdentityStateMachine`?** ¿Se llama desde dentro de la FSM (ampliando
   `_claim_lost` para intentar primero coincidencia de `person_id`+cara y luego,
   si falla, apariencia), o vive en el worker (`RecognitionWorker`/nuevo worker)
   como una vía paralela que alimenta a la FSM con un resultado equivalente al
   facial? Investigar el código real de `identity.py` y `recognition.py` tras la
   Fase 24 antes de decidir — no asumir desde el contrato de SPEC, que no lo
   especifica.
2. **¿De dónde sale el fichero `osnet_x0_25.onnx` real?** La Fase 23 usó
   `insightface`, que descarga sus propios modelos automáticamente; no hay
   precedente en este repo de descargar un ONNX de un tercero fuera de esa
   librería. Investigar una fuente fiable (release oficial de un export conocido,
   paquete pip con el modelo incluido, etc.) y si el proyecto necesita una
   "puerta de entrada bloqueante" como la de la Fase 23 (verificar que el modelo
   se descarga y ejecuta una inferencia real en Windows antes de comprometer el
   resto de la fase).
3. **¿Qué worker ejecuta la inferencia ReID?** ¿Un método más en
   `RecognitionWorker` (junto al facial), o un worker nuevo? Mirar el presupuesto
   de CPU y el patrón de `AdaptiveRate`/`min_track_age` ya usado.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato de la fase
- `propuesta_mejora/SPEC_v2.md` §5.6 — contratos de `ReIDEngine`/`TrackGallery` y
  política de herencia.
- `propuesta_mejora/SPEC_v2.md` ADR-04 — decisión de modelo (osnet_x0_25 ONNX).
- `propuesta_mejora/SPEC_v2.md` §9 (Phase 25) — ficheros a crear/modificar y riesgo.
- `.planning/ROADMAP.md` § Phase 25 — goal, dependencias, requisitos y los 5 criterios
  de éxito verificables.
- `.planning/REQUIREMENTS.md` § REID — REID-01 a REID-04, texto exacto.

### Código sobre el que se construye (Fase 24, ya completo)
- `backend/perception/face/identity.py` — `IdentityStateMachine`, `_claim_lost`,
  `IdentityState`, `IdentityTransition`. Es el mecanismo de continuidad de identidad
  existente; ReID añade una segunda vía de recuperación junto a este.
- `backend/pipeline/recognition.py` — `RecognitionWorker`, dueño del ciclo de vida de
  la FSM tras la Fase 24; candidato natural para alojar también ReID.
- `backend/pipeline/tracking.py` — `TrackRegistry`, `TrackState.identity_state`.
- `backend/events/engine.py` — `EventEngine.emit_identity`.
- `backend/perception/face/engine.py` — `FaceEngine` (Fase 23): patrón de referencia
  para un `*Engine` sobre ONNXRuntime en este repo — mismo patrón que `ReIDEngine`
  debería seguir.
- `backend/config.py` — bloque `# --- Identidad temporal (Fase 24 ...)`: patrón de
  cómo se añaden parámetros nuevos con pydantic-settings.

### Reglas del proyecto
- `CLAUDE.md` — invariantes de arquitectura, stack cerrado, criterios de diseño.
- `.planning/STATE.md` — estado real de fases y checkpoints pendientes.

</canonical_refs>

<specifics>
## Specific Ideas

Criterios de éxito de ROADMAP § Phase 25 (los 5, verbatim — son los criterios de
aceptación de la fase):

1. `ReIDEngine` produce embeddings 512D con `osnet_x0_25` ONNX en menos de 20 ms por
   crop en CPU.
2. `TrackGallery` hereda identidad de un track cerrado hace menos de 15 s con
   similitud > 0.7, y no la hereda si hay conflicto con un track activo.
3. Una persona identificada que se gira de espaldas 10 s y vuelve conserva su
   `person_id` sin `UNKNOWN_PERSON` intermedio.
4. Dos personas distintas con ropa similar no se fusionan; tasa de falsos positivos
   documentada.
5. ReID corre como máximo 1 vez cada 2 s por track.

Ficheros previstos (SPEC §9 Phase 25):
- Crear: `backend/perception/reid/{engine,gallery}.py`
- Modificar: `backend/pipeline/tracking.py`, `backend/events/engine.py` (y muy
  probablemente `backend/pipeline/recognition.py`/`manager.py`, no listados en SPEC
  §9 — la Fase 24 encontró exactamente este tipo de discrepancia; RESEARCH debe
  confirmar la lista real de ficheros con el código actual, no solo con SPEC)
- Tests: `tests/test_reid_engine.py`, `tests/test_track_gallery.py`

</specifics>

<deferred>
## Deferred Ideas

- **Activar `REID_INHERIT_IDENTITY=true` por defecto** — queda para cuando haya datos
  reales de falsos positivos que lo justifiquen (modo solo-observación durante el
  rodaje, como indica SPEC §9 Riesgo). No es parte del criterio de "hecho" de esta
  fase: la fase entrega el mecanismo y el flag, no la decisión de activarlo.
- **Comportamiento** (merodeo, carrera, aglomeración) → Fase 26, depende de esta.
- **Multi-clase/objetos** → Fase 27, depende de la 26.

</deferred>

---

*Phase: 25-re-identificaci-n-de-personas-reid*
*Context gathered: 2026-08-13 — generado desde artefactos existentes*
