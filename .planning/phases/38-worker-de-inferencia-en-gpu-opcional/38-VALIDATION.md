---
phase: 38
slug: worker-de-inferencia-en-gpu-opcional
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-08
---

# Phase 38 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (convención `TEST_*`, ver `pytest.ini`) |
| **Config file** | `pytest.ini` (ya existe; `python_functions = TEST_*`, marcador `perf` registrado) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/<fichero_afectado>.py -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | quick ~5-25 s · suite completa ~90 s |

---

## Sampling Rate

- **After every task commit:** `quick run command` sobre el fichero de test tocado
- **After every plan wave:** suite completa (`pytest tests/ -q`)
- **Before `/gsd-verify-work`:** suite completa en verde
- **Max feedback latency:** 25 s por tarea, 90 s por ola

Regla del proyecto (CLAUDE.md § Tests): durante la iteración, solo el fichero o `-k <patrón>`
afectado. La suite completa se reserva para el cierre de ola y de fase.

---

## Restricción estructural de esta fase

**Todo se valida sin GPU.** El `.venv` tiene `torch 2.11.0+cpu` y `onnxruntime` CPU-only,
y esta fase no instala nada (decisión del usuario, ver `38-CONTEXT.md`). Por tanto:

- La lógica de selección, el orden de providers y el fallback se prueban con dobles
  (`monkeypatch.setattr` sobre el símbolo importado en el módulo — patrón vigente en
  `tests/test_reid_engine.py:81-97` y `tests/test_face_engine.py:64-74`).
- La equivalencia de la ruta CPU (SCALE-12) se valida de verdad y sin dobles: es la ruta
  que corre hoy en esta máquina.
- La aceleración real (criterio 3 del ROADMAP, ≥3× FPS) **no es validable en esta fase**.
  Queda como pendiente explícito, no como criterio dado por bueno.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 38-01 T1 — `Settings.inference_device` + `FieldDef` | 38-01 | 1 | SCALE-12 | unit | `.venv/Scripts/python.exe -m pytest tests/test_config_schema.py tests/test_config.py -q` | ⬜ pending |
| 38-01 T2 — `resolve_device()` + sondas por familia | 38-01 | 1 | SCALE-11 | unit | `.venv/Scripts/python.exe -m pytest tests/test_inference_device.py -q` | ⬜ pending |
| 38-02 T1 — `PersonDetector(device=...)` + warm-up CUDA | 38-02 | 2 | SCALE-11, SCALE-12 | unit | `.venv/Scripts/python.exe -m pytest tests/test_detector.py tests/test_architecture.py -q` | ⬜ pending |
| 38-02 T2 — tests de ruta CPU intacta y fallback | 38-02 | 2 | SCALE-12 | unit | `.venv/Scripts/python.exe -m pytest tests/test_detector.py -q -m "not perf"` | ⬜ pending |
| 38-03 T1 — `ReIDEngine(providers=...)` + efectivo | 38-03 | 2 | SCALE-11, SCALE-12 | unit | `.venv/Scripts/python.exe -m pytest tests/test_reid_engine.py -q` | ⬜ pending |
| 38-03 T2 — `FaceEngine(providers=...)` + `ctx_id` derivado | 38-03 | 2 | SCALE-11, SCALE-12 | unit | `.venv/Scripts/python.exe -m pytest tests/test_face_engine.py -q` | ⬜ pending |
| 38-03 T3 — `PersonRecognizer.face_providers` | 38-03 | 2 | SCALE-11 | unit | `.venv/Scripts/python.exe -m pytest tests/test_recognizer_orchestration.py tests/test_face_engine.py -q` | ⬜ pending |
| 38-04 T1 — `manager.stats()['devices']` | 38-04 | 3 | SCALE-11 | unit | `.venv/Scripts/python.exe -m pytest tests/test_manager.py -q` | ⬜ pending |
| 38-04 T2 — `factory` resuelve device + `DEGRADED_MODE` | 38-04 | 3 | SCALE-11 | unit | `.venv/Scripts/python.exe -m pytest tests/test_manager.py tests/test_architecture.py -q` | ⬜ pending |
| 38-04 T3 — `main` cablea face + `/health` expone devices | 38-04 | 3 | SCALE-11, SCALE-12 | integración | `.venv/Scripts/python.exe -m pytest tests/test_cameras_api.py -q` | ⬜ pending |
| 38-05 T1 — arnés de benchmark CPU vs CUDA | 38-05 | 4 | SCALE-11 | perf (skip) | `.venv/Scripts/python.exe -m pytest tests/test_inference_benchmark.py -q` | ⬜ pending |
| 38-05 T2 — `38-GPU-NOTES.md` + nota en `REQUIREMENTS.md` | 38-05 | 4 | SCALE-11, SCALE-12 | documental | `.venv/Scripts/python.exe -m pytest tests/test_inference_benchmark.py -q` + grep de las cadenas exigidas en el plan | ⬜ pending |
| 38-05 T3 — checkpoint: log de arranque por motor | 38-05 | 4 | SCALE-11 | manual | — (verificación humana, ver § Manual-Only Verifications) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Cobertura exigida por criterio de éxito

| Criterio ROADMAP | Cómo se valida sin GPU | Automatizable |
|---|---|---|
| 1. Detección automática con log claro | Doble que simula `CUDAExecutionProvider` presente/ausente; se asevera el dispositivo elegido y el mensaje de log | Sí |
| 2. Los tres motores usan el proveedor adecuado, seleccionable por config | Se asevera la lista de providers pasada a `InferenceSession` y el `ctx_id` de insightface, con `auto`/`cpu`/`cuda` | Sí |
| 3. FPS ≥3× con GPU, medido | **No validable en esta fase** — sin stack GPU instalado. Se deja el arnés listo y el número pendiente | No |
| 4. Sin GPU, comportamiento idéntico a Fase 37 | Suite completa en verde + aserción explícita de que en CPU no se pasa `device` a Ultralytics ni se toca `CUDA_VISIBLE_DEVICES` | Sí |
| 5. Fallo de init cae a CPU y emite DEGRADED_MODE | Doble que hace fallar la construcción en GPU; se asevera dispositivo final CPU y la emisión de `DEGRADED_MODE` | Sí |
| 6. Batching opcional y desactivable | Decisión documentada de no implementarlo (`38-CONTEXT.md` decisión 6) — se verifica que no existe código de batching | Sí |

---

## Wave 0 Requirements

- [x] `tests/test_inference_device.py` — creado por el plan 38-01, tarea 2 (ola 1)
- [x] Registro del campo nuevo en `config_schema` — plan 38-01, tarea 1 (ola 1) — sin él, `tests/test_config_schema.py:24-26`
      se pone en rojo por desigualdad de conjuntos

*El resto de infraestructura ya existe: `pytest.ini`, `conftest.py`, marcador `perf` y la
metodología de medición p50 de `tests/test_detector.py:216-269`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|---|---|---|---|
| Aceleración real en CUDA y cifra del ≥3× | Criterio 3 | Requiere instalar `torch` cu12x y `onnxruntime-gpu`, fuera del alcance de la fase | Con el stack GPU instalado, ejecutar el arnés de benchmark de la fase contra la misma fuente en `cpu` y en `cuda`, y comparar p50 de FPS sostenido |
| Log de arranque con el dispositivo por motor | Criterio 1 | Se automatiza la selección, pero la legibilidad del log la juzga una persona | Arrancar el backend y leer las tres líneas de dispositivo |

---

## Validation Sign-Off

- [x] Todas las tareas tienen verificación automatizada o dependencia declarada de Wave 0
- [x] Continuidad de muestreo: no hay 3 tareas seguidas sin verificación automatizada
- [x] Wave 0 cubre las referencias MISSING (`tests/test_inference_device.py` y el `FieldDef` los crea el plan 38-01, ola 1)
- [x] Sin flags de watch-mode
- [x] Latencia de feedback < 25 s por tarea
- [x] `nyquist_compliant: true` en el frontmatter

**Approval:** aprobado por el planner (2026-09-08) — 12 de 13 tareas con verificación automatizada; la única manual es el checkpoint del log de arranque, declarado en § Manual-Only Verifications
