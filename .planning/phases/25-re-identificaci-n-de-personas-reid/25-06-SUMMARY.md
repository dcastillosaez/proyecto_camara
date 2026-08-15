---
phase: 25-re-identificaci-n-de-personas-reid
plan: 06
subsystem: testing
tags: [phase-gate, regression, measurement, ci-coverage, checkpoint-deferred]

# Dependency graph
requires:
  - phase: 25-01
    provides: "scripts/fetch_models.py (OSNet ONNX, eje de batch dinámico), ReIDEngine (512D, p50 < 20 ms)"
  - phase: 25-02
    provides: "IdentityStateMachine.on_reid_result() — herencia de identidad por apariencia sin voto"
  - phase: 25-03
    provides: "TrackGallery — ventana, umbral, conflicto, intervalo y expiración acotada"
  - phase: 25-04
    provides: "Vía ReID cableada en RecognitionWorker (criterios 3 y 5, modo solo-observación)"
  - phase: 25-05
    provides: "7 parámetros reid_* en config.py + cableado real en manager.py/main.py"
provides:
  - "Evidencia de que los 5 criterios de éxito de ROADMAP § Phase 25 tienen un comando automatizado que los demuestra"
  - "Fase 25 cerrada en código y tests: REID-01..REID-04 completos, suite 413/413"
  - "Checkpoint manual del criterio 4 (tasa de falsos positivos con cámara real) registrado como diferido en STATE.md"
affects: [26]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - .planning/STATE.md

key-decisions:
  - "No hizo falta ningún cambio de código: la suite ya estaba verde (413/413) y REID-01..REID-04 ya estaban marcados [x] en REQUIREMENTS.md desde los planes 25-01/25-02/25-03. Este plan es puramente de verificación y documentación de trazabilidad."
  - "El checkpoint del criterio 4 (tasa de falsos positivos con personas reales) se difiere de forma explícita por falta de acceso a cámara real en esta sesión: no bloquea el cierre de la Fase 25 porque la mitad determinista ya está verde y reid_inherit_identity=False sigue siendo el default seguro (fail-safe, T-25-17)."

patterns-established: []

requirements-completed: [REID-01, REID-02, REID-03, REID-04]

# Metrics
duration: 35min
completed: 2026-08-15
---

# Phase 25 Plan 06: Puerta de fase — trazabilidad de los 5 criterios de éxito y checkpoint del criterio 4 Summary

**Suite completa verde (413/413, sin skips en `test_reid_engine.py`) y los 5 criterios de éxito de ROADMAP § Phase 25 verificados uno a uno con el comando `pytest -k` que los selecciona y pasa; REID-01..REID-04 confirmados completos. El checkpoint manual del criterio 4 (tasa de falsos positivos con cámara real) queda formalmente diferido — sin acceso a cámara en esta sesión, no bloquea el cierre de la fase.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-08-15
- **Completed:** 2026-08-15
- **Tasks:** 1 de 2 ejecutado (Task 2 es el checkpoint manual, diferido)
- **Files modified:** 3 (solo documentación de planificación: `REQUIREMENTS.md`, `ROADMAP.md`, `STATE.md`; 0 ficheros de código)

## Accomplishments

- `pytest tests/ -q` sale con código 0: **413 passed** (línea base pre-fase: 377 tras `24-06`; +36 tests netos de la Fase 25 completa, 25-01..25-06). Sin `skipped` en `tests/test_reid_engine.py` — el modelo OSNet está presente en `models/reid/`.
- Los 5 criterios de éxito de ROADMAP § Phase 25 tienen cada uno un comando `pytest -k` que los selecciona y pasa con código 0 (ninguno con "no tests ran").
- `REID-01`, `REID-02`, `REID-03`, `REID-04` confirmados `- [x]` en `.planning/REQUIREMENTS.md` (ya marcados incrementalmente por los planes 25-01/25-02/25-03 al completarse cada uno; `grep -c "^\- \[x\] \*\*REID-0" .planning/REQUIREMENTS.md` → 4).
- Latencia p50 de `embed()` remedida en **este equipo** (no la del research): **11,86 ms** sobre 30 iteraciones con 5 de warmup (min 11,63 ms, max 12,37 ms) — holgadamente por debajo del umbral de 20 ms del criterio 1.
- Checkpoint del criterio 4 (Task 2) formalmente diferido en `STATE.md`: pasa a ser el 7º checkpoint manual con cámara real abierto, junto a los 6 de fases anteriores (19-01, 19-02, 20-02, 21-01, 22-01, 23-02). No bloquea avanzar a la Fase 26.

## Tabla de trazabilidad — criterio → comando → test → resultado

| # | Criterio (verbatim de ROADMAP § Phase 25) | Comando | Resultado |
|---|---|---|---|
| 1 | ReIDEngine produce embeddings 512D con osnet_x0_25 ONNX en menos de 20 ms por crop en CPU | `pytest tests/test_reid_engine.py -k "embedding_is_512d_l2_normalized or latency_under_20ms" -q` | **2 passed** |
| 2 | TrackGallery hereda identidad de un track cerrado hace menos de 15 s con similitud > 0.7, y no la hereda si hay conflicto con un track activo | `pytest tests/test_track_gallery.py -k "inherit or conflict" -q` | **5 passed** |
| 3 | Una persona identificada que se gira de espaldas 10 s y vuelve conserva su person_id sin UNKNOWN_PERSON intermedio | `pytest tests/test_recognition_worker.py -k reid_recovers_identity_without_face -q` | **1 passed** |
| 4 | Dos personas distintas con ropa similar no se fusionan; tasa de falsos positivos documentada | `pytest tests/test_track_gallery.py -k does_not_merge -q` **+ checkpoint manual (Task 2, diferido)** | **1 passed** (mitad determinista) |
| 5 | ReID corre como máximo 1 vez cada 2 s por track | `pytest tests/test_track_gallery.py -k needs_embedding_respects_interval -q` y `pytest tests/test_recognition_worker.py -k reid_inference_budget -q` | **1 passed** + **1 passed** |
| Regresión | Arquitectura, cota de memoria, máquina de estados de identidad no rotas por la Fase 25 | `pytest tests/test_architecture.py tests/test_memory_bounds.py tests/test_identity_state_machine.py -q` | **48 passed** |

Ninguno de los 7 comandos salió con código distinto de 0 ni imprimió "no tests ran".

## Criterio 1 — cifras medidas en este equipo

`TEST_reid_latency_under_20ms` mide p50 con `statistics.median` sobre 30 muestras (5 de warmup previas, para no pagar la inicialización de los kernels de ONNX Runtime en la medición). Ejecutado aparte para registrar la cifra exacta (no solo el veredicto pass/fail):

| Métrica | Valor |
|---|---|
| p50 (mediana, 30 muestras) | **11,86 ms** |
| min | 11,63 ms |
| max | 12,37 ms |
| Umbral del criterio 1 | < 20 ms |

La cifra del research (`25-RESEARCH.md`) era 5,50 ms en el equipo del research; en este equipo (compartido, con jitter del planificador de Windows) sale más alta pero sigue con margen amplio bajo los 20 ms.

## Criterio 3 — escenario medido

**Qué se mockeó:** `recognizer.process_crop_scored` — devuelve match facial solo mientras el `track_id` activo coincide con un diccionario mutable `match_track`; en cuanto el track pasa a ser el nuevo `track_id` (reaparición "de espaldas"), el mock deja de devolver cara para nadie. `reid_engine` es un mock que devuelve el mismo vector para cualquier crop (misma persona, similitud garantizada).

**Qué fue real:** `RecognitionWorker`, `IdentityStateMachine`, `TrackGallery`, `TrackRegistry` y `EventEngine` — el flujo completo de FSM + galería + eventos corre sin mocks, solo la fuente de "verdad visual" (cara y apariencia) está controlada por el test para reproducir el escenario determinísticamente.

**Secuencia:** track 1 visible → 3 votos coherentes → `CONFIRMED`. Desaparece (`match_track["id"] = None`, `frame_ids` vacío) → `_sync_identity` real lo marca `TEMPORARILY_LOST`. `TrackRegistry.prune()` suelta el track viejo (simula el TTL de `DetectionWorker`). Reaparece con un `track_id` nuevo (como haría ByteTrack tras una oclusión), sin cara disponible pero con la misma apariencia — ReID hereda el `person_id` vía `on_reid_result()`, sin `UNKNOWN_PERSON` intermedio y sin segundo `PERSON_RECOGNIZED`.

## Criterio 5 — escenario medido, escalado del reloj y cota superior

`TEST_reid_inference_budget`: los 2 s de intervalo de producción (`reid_min_interval_secs` por defecto en `config.py`) se comprimen a **0,5 s** en el test, con el tick del worker corriendo a 20 FPS para que el límite observado no sea el ritmo del tick sino el gate real de `TrackGallery.needs_embedding()`. Publicando frames durante 1 s real:

- `engine.embed.call_count` debe ser `>= 1` (la vía ReID se ejecutó de verdad — si no, el test no mide nada).
- Cota superior admitida: `<= 4` llamadas en 1 s con intervalo de 0,5 s (se esperarían 2 exactas; se admite hasta el doble por jitter del planificador de Windows en máquina compartida). Sin el gate de `needs_embedding()`, a 20 FPS de tick habría 20 llamadas en el mismo segundo — la cota de 4 sigue demostrando una reducción de al menos 5x.

`TEST_gallery_needs_embedding_respects_interval` (unitario, sin reloj real): con `interval=2.0`, `needs_embedding(1, 0.0)` es `True` (primera vez), tras `update(now=0.0)` es `False` en `t=1.9` y vuelve a `True` exactamente en `t=2.0` — el límite es una comparación `>=`, no `>`.

## Consecuencias abiertas

- **El criterio 4 solo está cerrado en su mitad determinista.** `TEST_gallery_does_not_merge_distinct_identities` prueba que dos vectores 512D distintos (coseno controlado, nunca `np.random`) no cruzan el umbral de 0,7 y por tanto no se fusionan. La mitad de datos reales — la distribución real de similitudes entre dos personas de esta escena, con ropa parecida — es exactamente lo que mide el checkpoint de la Task 2, diferido por falta de cámara. El research (`25-RESEARCH.md` Pitfall 2) midió que contenido no relacionado ya roza 0,71 de coseno con OSNet real, justo por encima del umbral: es la razón por la que este checkpoint importa y no es un formalismo.
- **`reid_inherit_identity=False` es el default** y activarlo es una decisión de producto **fuera** del alcance de esta fase (CONTEXT § Deferred Ideas). Solo debería considerarse activar el flag después de que el checkpoint de la Task 2 aporte el histograma real de similitudes.
- **Un track heredado por apariencia no revalida con cara hasta `revalidate_after` (120 s).** Es la palanca (Pitfall 5 del research de la Fase 24, reutilizada por la vía ReID) que decide cuánto tiempo puede vivir una herencia incorrecta por apariencia antes de que la FSM la corrija con una revalidación facial fallida.
- **Con más de 4 tracks concurrentes, el intervalo efectivo de ReID por track supera los 2 s** (asunción A3 del research de la Fase 25) — degradación segura: menos coste computacional, nunca más. No es un bug, es el comportamiento esperado del gate compartido de `TrackGallery.needs_embedding()`.
- **Discrepancias D-1/D-2 de ADR-04/SPEC_v2.md §4.3:** el modelo real (`osnet_x0_25`) pesa 907 KB y tiene ~0,22M parámetros — las cifras del ADR (9 MB, 2,2M parámetros) corresponden a `osnet_x1_0`, un modelo distinto y más grande. Anotado aquí para quien reescriba el ADR; no se corrige el documento en esta fase (fuera de alcance de una puerta de fase).
- **`models/` está gitignored.** Un clon nuevo del repositorio necesita ejecutar `scripts/fetch_models.py` antes de que `tests/test_reid_engine.py` deje de saltarse (`pytest.skip`, nunca fallo — decisión de 25-01).
- **Checkpoints de cámara real:** el de esta fase (criterio 4, Task 2) queda diferido y registrado en `STATE.md` como el 7º checkpoint manual abierto, sin relación de bloqueo con los 6 de fases anteriores (19-01, 19-02, 20-02, 21-01, 22-01, 23-02).

## Task Commits

Este plan no modificó ningún fichero de código — la suite ya estaba verde y `REQUIREMENTS.md` ya tenía REID-01..REID-04 marcados desde los planes 25-01/25-02/25-03. No hay commits de tarea de código; solo el commit final de metadatos (SUMMARY/STATE/ROADMAP/REQUIREMENTS).

## Files Created/Modified

- `.planning/phases/25-re-identificaci-n-de-personas-reid/25-06-SUMMARY.md` - este documento
- `.planning/REQUIREMENTS.md` - verificado (ya estaba con REID-01..REID-04 en `[x]`, sin cambios)
- `.planning/ROADMAP.md` - plan `25-06` marcado `[x]`, criterio 4 anotado como verificado en su parte determinista con tasa real pendiente de checkpoint, Fase 25 marcada completa en la lista de bloques
- `.planning/STATE.md` - Fase 25 marcada `✓ Completa (código)` en la tabla de 22 fases, progreso 8→9 fases completas (36%→41%), 6→7 checkpoints manuales abiertos, decisión de la puerta de fase añadida, "Siguiente paso" apunta a `/gsd:plan-phase 26`

## Decisions Made

Ver `key-decisions` en el frontmatter: no hizo falta ningún fix de código, la puerta de fase pasó a la primera ejecución de la suite completa; el checkpoint del criterio 4 se difiere de forma explícita y documentada, sin bloquear el cierre de la fase.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. No se encontró ninguna regresión que arreglar (Rule 1/2/3) porque la suite ya estaba verde desde el cierre de `25-05`. La Task 2 (checkpoint manual) se ejecutó según el flujo previsto en el propio plan para el caso sin cámara: "Si no hay acceso a la cámara ahora mismo, escribe 'diferir'" — este es exactamente ese caso, documentado como tal.

## Issues Encountered

None.

## User Setup Required

Ninguno para cerrar esta fase en código. Para ejecutar el checkpoint diferido cuando haya acceso a cámara real: ver Task 2 de `25-06-PLAN.md` (arrancar el sistema con la cámara real, provocar el escenario de dos personas con ropa de color parecido durante al menos 15 minutos, recoger las líneas `ReID: track` y los contadores de `/api/v2/cameras/{id}/health`).

## Next Phase Readiness

- Fase 25 (Re-identificación de personas, ReID) completa en código y tests: 6/6 planes, REID-01..REID-04 cerrados, suite 413/413.
- Fase 26 (Análisis de comportamiento) puede planificarse: depende de la Fase 25, ya completa en código.
- Consecuencia abierta que sí conviene revisar antes de activar `reid_inherit_identity` en producción: el checkpoint diferido del criterio 4 (Task 2 de este plan), que da la única medida real de si el umbral de 0,7 sigue siendo seguro en esta escena concreta.

---
*Phase: 25-re-identificaci-n-de-personas-reid*
*Completed: 2026-08-15*

## Self-Check: PASSED

Verificado: `pytest tests/ -q` → 413 passed (código 0). Los 7 comandos de la tabla de trazabilidad ejecutados, todos código 0, sin "no tests ran". `grep -c "^\- \[x\] \*\*REID-0" .planning/REQUIREMENTS.md` → 4. `.planning/phases/25-re-identificaci-n-de-personas-reid/25-06-SUMMARY.md` existe y supera 60 líneas. `grep -n "Fase 25" .planning/STATE.md` devuelve más de 6 líneas. `grep -n "criterio 4" .planning/STATE.md` devuelve al menos 1 línea (checkpoint diferido registrado).
