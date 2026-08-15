---
phase: 25
slug: re-identificaci-n-de-personas-reid
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-13
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derivado de `25-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|---|---|
| **Framework** | pytest ≥7.0 + pytest-asyncio ≥0.24 (`asyncio_mode = auto`) |
| **Config file** | `pytest.ini` — `python_functions = TEST_*` (los tests nuevos deben llamarse `TEST_*`) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_track_gallery.py tests/test_reid_engine.py -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~5 s (rápido) / ~90 s (suite completa, 377 tests base) |

**Nota de entorno:** el worktree no tiene `.venv` propio. Usar
`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe`.

**Modelo real:** `tests/test_reid_engine.py` necesita `models/reid/osnet_x0_25_msmt17.onnx`
(producido por `scripts/fetch_models.py`). Si no está presente, el test hace `pytest.skip`,
**nunca falla** — mismo patrón que un entorno sin cámara real.

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_track_gallery.py tests/test_reid_engine.py tests/test_identity_state_machine.py -q`
- **After every plan wave:** `pytest tests/test_recognition_worker.py tests/test_memory_bounds.py tests/test_architecture.py tests/test_config.py -q`
- **Before `/gsd-verify-work`:** suite completa verde (≥377 + los nuevos) — la fase toca
  pipeline, eventos y configuración, y CLAUDE.md § Tests lo exige explícitamente.

---

## Per-Task Verification Map

| Req | Comportamiento | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|
| REID-01 | `embed()` devuelve 512D, norma L2 = 1 | unit | `pytest tests/test_reid_engine.py -k embedding_is_512d_l2_normalized -q` | ❌ W0 | ⬜ pending |
| REID-01 | p50 de `embed()` < 20 ms con warmup (≥30 iters), medido como mediana no como máximo | perf | `pytest tests/test_reid_engine.py -k latency_under_20ms -q` | ❌ W0 | ⬜ pending |
| REID-01 | Sin modelo ⇒ `available is False`, `embed()` → `None` | unit | `pytest tests/test_reid_engine.py -k degrades_gracefully -q` | ❌ W0 | ⬜ pending |
| REID-01 | Modelo con batch fijo ≠ 1 ⇒ `available is False` (blocker del research) | unit | `pytest tests/test_reid_engine.py -k rejects_fixed_batch -q` | ❌ W0 | ⬜ pending |
| REID-02 | Hereda con `sim > 0.7` y `< 15 s`; no hereda con `sim = 0.65`; no hereda pasados 16 s | unit | `pytest tests/test_track_gallery.py -k inherit -q` | ❌ W0 | ⬜ pending |
| REID-02 | No hereda si la identidad está en un track activo (conflicto) | unit | `pytest tests/test_track_gallery.py -k conflict -q` | ❌ W0 | ⬜ pending |
| REID-02 | `on_reid_result` no toca tracks CANDIDATE/CONFIRMED ni vota en el TemporalVoter | unit | `pytest tests/test_identity_state_machine.py -k reid -q` | ❌ W0 | ⬜ pending |
| REID-02 | Tras heredar por ReID, `on_tick` NO emite `IDENTITY_LOST` espurio | unit | `pytest tests/test_identity_state_machine.py -k reid_no_spurious_identity_lost -q` | ❌ W0 | ⬜ pending |
| REID-03 (criterio 3) | Persona confirmada, sin cara 10 s, reaparece con track_id nuevo → person_id conservado, exactamente 1 PERSON_RECOGNIZED, 0 UNKNOWN_PERSON | integración | `pytest tests/test_recognition_worker.py -k reid_recovers_identity_without_face -q` | ❌ W0 | ⬜ pending |
| REID-04 (criterio 5) | ≤1 llamada a `engine.embed` por track cada 2 s (motor mockeado, contando llamadas) | integración | `pytest tests/test_recognition_worker.py -k reid_inference_budget -q` | ❌ W0 | ⬜ pending |
| REID-04 | `TrackGallery` acotada tras 10.000 track_ids | unit | `pytest tests/test_memory_bounds.py -k track_gallery_bounded -q` | ❌ W0 | ⬜ pending |
| Criterio 4 | Dos vectores distintos no se fusionan; similitud logueada | unit + checkpoint manual | `pytest tests/test_track_gallery.py -k does_not_merge -q` + checkpoint con cámara real | ❌ W0 | ⬜ pending |
| — | `reid_inherit_identity=False` ⇒ `resolve` calcula, la FSM no cambia de estado, el contador sí sube | integración | `pytest tests/test_recognition_worker.py -k observation_only -q` | ❌ W0 | ⬜ pending |
| — | Validadores de `reid_*` rechazan valores fuera de rango | unit | `pytest tests/test_config.py -k reid -q` | ❌ W0 | ⬜ pending |
| Regresión | Ningún hilo hace `await`; `embed()` fuera de corrutinas | arquitectura | `pytest tests/test_architecture.py -q` | ✅ existe | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reid_engine.py` — REID-01, criterio 1. Necesita el modelo en
  `models/reid/`; si falta, `pytest.skip`, nunca fallo.
- [ ] `tests/test_track_gallery.py` — REID-02, criterios 2 y 4. **Vectores 512D
  construidos a mano, nunca `np.random`** — con ruido aleatorio el coseno entre dos
  embeddings independientes de OSNet sale 0.991 (colapso fuera de distribución),
  lo que invalidaría cualquier assert sobre el umbral 0.7.
- [ ] `scripts/fetch_models.py` — prerrequisito de `test_reid_engine.py`: descarga desde
  `kornia/osnet` (HF Hub), verifica sha256 `e78604f4...`, reescribe el eje batch a
  dinámico (el export público lo tiene fijo a 16 — blocker real, resuelto en research),
  guarda en `models/reid/`. Idempotente.
- [ ] `.gitignore` — añadir `models/`.
- [ ] `requirements.txt` — `onnx>=1.16` explícito (hoy solo transitiva de `insightface`;
  se usa directamente en `fetch_models.py`).
- Instalación de framework: ninguna, pytest/pytest-asyncio ya están.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|---|---|---|---|
| Tasa real de falsos positivos entre dos personas de ropa parecida | Criterio 4 | El umbral 0.7 se valida con vectores sintéticos, pero solo la cámara real da la distribución de similitudes de personas reales de esta escena | Con `reid_inherit_identity=False` (modo observación), dejar el sistema corriendo con 2+ personas de ropa similar; revisar el log de `similarity` por match y documentar el histograma en el SUMMARY antes de considerar activar `reid_inherit_identity=True` |

---

## Riesgo conocido de CI (heredado de la Fase 24, aplica igual aquí)

`pytest.ini` fija `python_functions = TEST_*`; en el CI Linux los `def test_*` no se
recogen. Todo test nuevo de esta fase debe llamarse `TEST_*`.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** aprobado 2026-08-13 — los 6 planes tienen `<automated>` en cada tarea; los huecos de Wave 0 los cubren 25-01 (fetch_models.py + test_reid_engine.py) y 25-03 (test_track_gallery.py).
