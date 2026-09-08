---
phase: 38
slug: worker-de-inferencia-en-gpu-opcional
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| *(lo rellena el planner: una fila por tarea, con el comando exacto)* | | | SCALE-11 / SCALE-12 | | | ⬜ pending |

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

- [ ] Fichero de test nuevo para el selector de dispositivo (a nombrar por el planner)
- [ ] Registro del campo nuevo en `config_schema` — sin él, `tests/test_config_schema.py:24-26`
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

- [ ] Todas las tareas tienen verificación automatizada o dependencia declarada de Wave 0
- [ ] Continuidad de muestreo: no hay 3 tareas seguidas sin verificación automatizada
- [ ] Wave 0 cubre las referencias MISSING
- [ ] Sin flags de watch-mode
- [ ] Latencia de feedback < 25 s por tarea
- [ ] `nyquist_compliant: true` en el frontmatter

**Approval:** pending
