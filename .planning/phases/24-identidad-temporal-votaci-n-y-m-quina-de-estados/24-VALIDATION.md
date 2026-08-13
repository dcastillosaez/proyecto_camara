---
phase: 24
slug: identidad-temporal-votaci-n-y-m-quina-de-estados
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-12
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derivado de `24-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥7.0 + pytest-asyncio ≥0.24 |
| **Config file** | `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto` |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~5 s (rápido) / ~90 s (suite completa, 326 tests base) |

**Convención obligatoria:** las funciones de test se nombran `TEST_*`, no `test_*`.
`pytest.ini` fija `python_functions = TEST_*`; en Linux (CI) los `def test_*` **no se
recogen**. Ver "Riesgo conocido de CI" abajo.

**Nota de entorno:** el worktree no tiene `.venv` propio. Usar
`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe`.

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py -q`
- **After every plan wave:** `pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py tests/test_recognition_worker.py tests/test_recognizer_orchestration.py tests/test_memory_bounds.py tests/test_event_engine.py tests/test_architecture.py -q`
- **Before `/gsd-verify-work`:** suite completa verde — la fase toca pipeline, eventos y
  configuración, y CLAUDE.md § Tests lo exige explícitamente en ese caso.
- **Max feedback latency:** ~5 s (rápido), ~15 s (wave), ~90 s (puerta de fase)

---

## Per-Task Verification Map

| Req | Comportamiento | Test Type | Automated Command | File Exists | Status |
|-----|---------------|-----------|-------------------|-------------|--------|
| FACE-07 | `TemporalVoter` confirma solo con `min_votes` coherentes en `window` y ratio ≥ `min_ratio` | unit | `pytest tests/test_temporal_voting.py -q` | ❌ W0 | ⬜ pending |
| FACE-07 | Votos alternando 2 identidades → `verdict()` = `(None, 0.0)` (criterio 3) | unit | `pytest tests/test_temporal_voting.py -k ratio -q` | ❌ W0 | ⬜ pending |
| FACE-08 | Las 6 transiciones, una por test (criterio 1) | unit | `pytest tests/test_identity_state_machine.py -q` | ❌ W0 | ⬜ pending |
| FACE-08 | `identity_state` legible desde el registry | unit | `pytest tests/test_track_registry.py -k identity_state -q` | ❌ W0 (fichero existe) | ⬜ pending |
| FACE-09 | 200 frames de persona conocida → exactamente 1 `PERSON_RECOGNIZED` (criterio 2) | unit | `pytest tests/test_identity_state_machine.py -k single_recognition -q` | ❌ W0 | ⬜ pending |
| FACE-09 | `UNKNOWN_PERSON` se emite al pasar CANDIDATE → UNKNOWN, una sola vez | unit | `pytest tests/test_identity_state_machine.py -k unknown_emitted_once -q` | ❌ W0 | ⬜ pending |
| FACE-09 | `EventEngine` publica los 3 tipos de identidad con su payload | integración | `pytest tests/test_event_engine.py -k identity -q` | ❌ W0 (fichero existe) | ⬜ pending |
| FACE-10 | Pérdida + recuperación de track → mismo `person_id`, 0 identidades nuevas (criterio 4) | integración | `pytest tests/test_identity_state_machine.py -k track_recovery -q` | ❌ W0 | ⬜ pending |
| FACE-11 | `revalidate_after`=120 s dispara re-check; 3 ciclos fallidos → `IDENTITY_LOST` (criterio 5) | unit, reloj simulado | `pytest tests/test_identity_state_machine.py -k revalidate -q` | ❌ W0 | ⬜ pending |
| FACE-11 | Reducción ≥70% de llamadas a `process_crop`, **track NO confirmado** estático (criterio 6) | integración | `pytest tests/test_recognition_worker.py -k inference_budget -q` | ❌ W0 (fichero existe) | ⬜ pending |
| FACE-11 | El re-reconocimiento usa la confianza del voter, no `TrackState.confidence` | unit | `pytest tests/test_recognition_worker.py -k trigger_confidence -q` | ❌ W0 (fichero existe) | ⬜ pending |
| Fase 22 | `TemporalVoter` acotado tras 10.000 tracks | unit | `pytest tests/test_memory_bounds.py -k voter -q` | ❌ W0 (fichero existe) | ⬜ pending |
| Fase 22 | `IdentityStateMachine` acotada por `lost_ttl` | unit | `pytest tests/test_memory_bounds.py -k state_machine -q` | ❌ W0 (fichero existe) | ⬜ pending |
| Regresión | Ningún hilo hace `await`; inferencia fuera de corrutinas | arquitectura | `pytest tests/test_architecture.py -q` | ✅ existe | ⬜ pending |
| Regresión | Orquestación de `recognizer.py` sigue OK tras retirar `_votes` | unit | `pytest tests/test_recognizer_orchestration.py -q` | ✅ existe (**actualizar**) | ⬜ pending |
| Regresión | `TEST_recognizer_cache_bounded` afirma `len(r._votes) == 10` | unit | `pytest tests/test_memory_bounds.py -k recognizer_cache -q` | ✅ existe (**actualizar**) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_temporal_voting.py` — nuevo, cubre FACE-07
- [ ] `tests/test_identity_state_machine.py` — nuevo, cubre FACE-08..FACE-11 y criterios 1-5
- [ ] Extender `tests/test_memory_bounds.py` — 2 tests de cota (invariante Fase 22)
- [ ] Extender `tests/test_event_engine.py` — emisión de los 3 eventos de identidad
- [ ] Extender `tests/test_recognition_worker.py` — presupuesto de inferencias (criterio 6) y disparador por confianza de identidad
- [ ] Actualizar `tests/test_recognizer_orchestration.py` y `test_memory_bounds.py::TEST_recognizer_cache_bounded` al retirar `_votes`
- [ ] Añadir el método nuevo al set `INFERENCE_CALLS` de `tests/test_architecture.py:15-17` si se crea `process_crop_scored`
- [ ] Instalación de framework: ninguna, ya está todo

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | — |

**Todos los criterios de la fase son verificables con tests sintéticos.** No hace falta
cámara real: los embeddings y las secuencias de tracks se simulan, y `FaceEngine` se
mockea (patrón ya usado en `test_recognizer_orchestration.py`, evita cargar ONNX).

---

## Riesgo conocido de CI (no bloquea esta fase, pero afecta a su verificación)

`pytest.ini` fija `python_functions = TEST_*`. En Windows el `fnmatch` es
case-insensitive y se recogen los 232 tests; en el Ubuntu del CI los 69 tests escritos
como `def test_*` **no se ejecutan** (326 local vs 257 CI — la diferencia es exactamente
69). Además, el paso "Run tests" del workflow tiene `continue-on-error: true`, así que
un fallo no bloquea el check del PR.

**Implicación para esta fase:** todo test nuevo DEBE nombrarse `TEST_*` o no se
ejecutará en CI. Arreglar el desajuste de fondo es trabajo aparte, fuera del alcance
de la Fase 24.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
