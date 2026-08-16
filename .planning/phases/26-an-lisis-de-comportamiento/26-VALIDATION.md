---
phase: 26
slug: an-lisis-de-comportamiento
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-15
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derivado de `26-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|---|---|
| **Framework** | pytest 9.0.3 + pytest-asyncio (`asyncio_mode = auto`) |
| **Config file** | `pytest.ini` — `python_functions = TEST_*` (los tests nuevos deben llamarse `TEST_*`) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_behavior_analyzer.py -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~2 s (rápido) / ~90 s (suite completa) |
| **Línea base** | **413/413** tras `25-06` |

**Nota de entorno:** el worktree no tiene `.venv` propio. Usar
`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe`.

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_behavior_analyzer.py -q`
- **After every plan wave:** `pytest tests/test_behavior_analyzer.py tests/test_event_engine.py tests/test_detection_worker.py tests/test_memory_bounds.py -q`
- **Before `/gsd-verify-work`:** suite completa verde — la fase toca pipeline, eventos y
  configuración, y CLAUDE.md § Tests punto 2 lo exige explícitamente.
- **Barrera de arquitectura:** `pytest tests/test_architecture.py -q` debe seguir verde —
  `behavior.py` no debe importar `fastapi`, y el código nuevo en `detection.py` no debe
  introducir `await`.

---

## Per-Task Verification Map

| Req | Comportamiento | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|
| BEH-01 | LOITERING con umbrales configurables (tiempo en zona + desplazamiento neto) | unit | `pytest tests/test_behavior_analyzer.py -k loiter -q` | ❌ W0 | ⬜ pending |
| BEH-02 | RUNNING sobre ventana de 1 s | unit | `pytest tests/test_behavior_analyzer.py -k running -q` | ❌ W0 | ⬜ pending |
| BEH-02 | IMMOBILE 20 px / 60 s | unit | `pytest tests/test_behavior_analyzer.py -k immobile -q` | ❌ W0 | ⬜ pending |
| BEH-03 | CROWD_DETECTED con ≥ `crowd_threshold` tracks | unit | `pytest tests/test_behavior_analyzer.py -k crowd -q` | ❌ W0 | ⬜ pending |
| BEH-04 | `duration_s` (tiempo de permanencia) en ZONE_EXITED | unit (async) | `pytest tests/test_event_engine.py -k zone_dwell -q` | ⚠️ fichero existe, test no | ⬜ pending |
| BEH-05 | Magnitudes en el payload, con los nombres exactos | unit | `pytest tests/test_behavior_analyzer.py -k payload -q` | ❌ W0 | ⬜ pending |
| Criterio 2 | Seis trayectorias sintéticas → exactamente el evento esperado y **ninguno más** | unit | `pytest tests/test_behavior_analyzer.py -k trajectory -q` | ❌ W0 | ⬜ pending |
| Criterio 4 | Estado por track acotado, no crece con la sesión (10.000 tracks efímeros) | unit | `pytest tests/test_memory_bounds.py -k behavior -q` | ⚠️ fichero existe, test no | ⬜ pending |
| Criterio 5 | Usables como `when.event` sin tocar `RuleEngine`, **cargado desde YAML real** | unit | `pytest tests/test_rule_engine.py -k behavior -q` | ⚠️ fichero existe, test no | ⬜ pending |
| Idempotencia | Cada comportamiento emite **una vez por episodio**, no por frame | unit | `pytest tests/test_behavior_analyzer.py -k latch -q` | ❌ W0 | ⬜ pending |
| Config | Defaults y validadores de rango de los umbrales | unit | `pytest tests/test_config.py -k behavior -q` | ⚠️ fichero existe, test no | ⬜ pending |
| Cableado | End-to-end desde `DetectionWorker` | integración | `pytest tests/test_detection_worker.py -k behavior -q` | ⚠️ fichero existe, test no | ⬜ pending |
| Regresión | Sin `await` en hilos, `behavior.py` sin dependencias web | arquitectura | `pytest tests/test_architecture.py -q` | ✅ existe | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_behavior_analyzer.py` — fichero nuevo. Cubre BEH-01/02/03/05 y los
  criterios 1, 2 y 3.
- [ ] Helper de trayectorias sintéticas (`_walk(...)`) — **local al fichero de test**,
  no en `conftest.py`: el repo mantiene los helpers junto a sus tests (`_tracked` en
  `test_detection_worker.py:27`, `_fake_tracked` en `test_memory_bounds.py:34`).
- [ ] Ampliar `tests/test_event_engine.py` — dwell time en ZONE_EXITED.
- [ ] Ampliar `tests/test_memory_bounds.py` — cota del estado del analizador (criterio 4).
- [ ] Ampliar `tests/test_rule_engine.py` — criterio 5 vía `load_rules` sobre un YAML
  temporal (`tmp_path`), **no** solo `Rule.model_validate`: hay que probar el camino real.
- [ ] Ampliar `tests/test_config.py` — defaults y validadores (patrón `TEST_reid_*`).
- [ ] Ampliar `tests/test_detection_worker.py` — cableado end-to-end.
- Instalación de framework: ninguna, pytest + pytest-asyncio ya están.

---

## Restricciones de test que el research dejó fijadas

**El campo se llama `duration_s`, no `duration` ni `dwell_s`.** `backend/events/rules.py:88-91`
lee **literalmente** `payload["duration_s"]` para resolver `duration_gte`. Si BEH-05 usa
otro nombre, el criterio 5 se cumple a medias y en silencio: la regla cargaría bien pero
`duration_gte` nunca dispararía.

**El criterio 2 se afirma sobre el CONJUNTO de tipos emitidos, no sobre la presencia.**
"Exactamente el evento esperado y ninguno más" exige comparar el set completo
(`{e.type for e in eventos} == {EventType.RUNNING}`), no `assert RUNNING in tipos` —
si no, un test pasaría aunque la trayectoria emitiera además un IMMOBILE espurio.

**Idempotencia: cada comportamiento emite una vez por episodio.** Sin latch, una persona
parada 10 minutos genera ~4.800 eventos `IMMOBILE` a 8 FPS. El docstring de `EventEngine`
(`engine.py:3-4`) llama a esto el fallo conceptual de v1. `debounce_secs` de `rules.yaml`
**no** sirve como sustituto: actúa después de persistir y difundir.

---

## Riesgo conocido de CI (heredado de las Fases 24-25)

`pytest.ini` fija `python_functions = TEST_*`; en el CI Linux los `def test_*` no se
recogen. Todo test nuevo de esta fase debe llamarse `TEST_*`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|---|---|---|---|
| — | — | — | — |

**Todos los criterios de la fase son verificables con trayectorias sintéticas.** No hace
falta cámara real: el analizador es dominio puro con reloj inyectado, igual que
`TemporalVoter`/`IdentityStateMachine`/`TrackGallery` de las Fases 24-25.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
