---
phase: 29
slug: vista-de-operaciones
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-20
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Compilado directamente por el orquestador a partir de `29-RESEARCH.md` § Validation Architecture (líneas 392-419), siguiendo la plantilla estándar de GSD.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=7.0 + pytest-asyncio >=0.24 (backend). No hay framework de test JS en el repo — confirmado por ausencia de `package.json` y por el docstring de `tests/test_frontend_modules.py` (Fase 28), que valida JS por sintaxis (`node --check`) y por línea/convención, no por ejecución. |
| **Config file** | `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto` |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_main.py -k tracks -q` (ajustar el fichero/patrón exacto según dónde acaben los tests nuevos de cada plan — ver Wave 0 Gaps) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~90 s (línea base del proyecto, CLAUDE.md § Tests) |

---

## Sampling Rate

- **After every task commit:** `.venv/Scripts/python.exe -m pytest tests/test_manager.py tests/test_stream.py tests/test_frontend_modules.py -q` (backend) + `node --check` sobre los ficheros JS tocados (frontend, sin runner de ejecución)
- **After every plan wave:** `.venv/Scripts/python.exe -m pytest tests/ -q` (suite completa)
- **Before `/gsd-verify-work`:** Full suite must be green + checklist manual de paridad visual (29-03 Task 3, mismo patrón que 28-09)
- **Max feedback latency:** ~90 s (duración de la suite completa)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|--------------------|-------------|--------|
| 29-01-01 | 01 | 1 | OPS-05 | — | `get_person_boxes()` filtra por `frame_ids()`, excluye tracks stale/fuera de cuadro | unit (pipeline) | `pytest tests/test_manager.py -q` | ❌ Wave 0 (crear `tests/test_manager.py` si no existe) | ⬜ pending |
| 29-01-02 | 01 | 1 | OPS-05 | Information Disclosure (mitigado) | Bucle `_tracks_broadcast_loop()` publica `type:"tracks"` a 2Hz por `/ws` ya autenticado (`verify_ws_token`), reutiliza `_broadcast()` con captura de excepciones por cliente | integration (WS) | `pytest tests/test_stream.py -k tracks -q` | ❌ Wave 0 | ⬜ pending |
| 29-02-01 | 02 | 1 | OPS-05 | — | `<canvas id="tracks-overlay">` insertado entre `#video-feed` y `#res-badge`, orden de DOM verificado | structural (HTML) | `python -c "...assert i < j < k..."` (ver 29-02-PLAN.md Task 1) | ✅ (verify ya escrito en el plan) | ⬜ pending |
| 29-02-02 | 02 | 1 | OPS-05 | — | Overlay se redibuja solo por el mensaje `tracks`, nunca toca `img.src`; sintaxis JS válida | syntax + convention | `node --check ... && pytest tests/test_frontend_modules.py -q` | ✅ (LOCKED_JS ya cubre estos ficheros) | ⬜ pending |
| 29-03-01 | 03 | 2 | OPS-04 | — | `setCamStatus(state)` de 3 estados (online/degradado/offline), combina `pipeline.degraded` + `health.connected` + ciclos de reconexión WS, nunca `dropped` | syntax + convention | `node --check ... && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 29-03-02 | 03 | 2 | OPS-04 | — | Paneles "Personas ahora"/"Alertas activas" renderizados; `dashboard.js` se mantiene ≤300 líneas (`TEST_line_limit`) | syntax + convention | `node --check ... && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 29-03-03 | 03 | 2 | OPS-04, OPS-06 | — | Paridad visual 1366×768 sin scroll, reconexión WS visible, overlay alineado con `object-fit:cover` | manual-only | — (checkpoint:human-verify, mismo patrón que 28-09) | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_manager.py` — confirmar si ya existe (`ls tests/`); si no, crearlo con el primer test de `get_person_boxes()` (29-01-01)
- [ ] Primer test `client.websocket_connect(...)` del repo — sin precedente literal que copiar (confirmado en RESEARCH.md, sin ningún test WS existente hoy); el ejecutor de 29-01-02 debe escribirlo desde cero siguiendo la API de `starlette.testclient.TestClient.websocket_connect`
- [ ] Framework install: ninguno — pytest/pytest-asyncio ya instalados, sin runner JS que instalar (fuera de alcance, Fase 34)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Reconexión WS visible sin recargar la página | OPS-06 | Sin runner JS/E2E en el repo (Fase 34 lo introduce); comportamiento de `websocket.js` solo verificable en navegador real | Cortar el backend, observar badge `#ws-badge` → "Reconectando" (ámbar) sin recargar, reiniciar backend, confirmar retorno a "Activo" (verde) en ≤30s (cap de `_wsRetry`) |
| Overlay de canvas alineado con el vídeo bajo `object-fit:cover` | OPS-05 | Geometría de escalado 2D solo verificable visualmente contra el stream real, no hay precedente local de canvas overlay en este proyecto | Abrir el dashboard con una persona en cuadro, confirmar que la bbox dibujada coincide con la posición real en el vídeo en al menos 3 posiciones de la escena (esquina, centro, borde) |
| Zero-scroll en 1366×768 con los 2 paneles nuevos | OPS-04, criterio de éxito 1 | Constraint visual de layout, no automatizable sin runner de navegador | Redimensionar viewport a 1366×768, confirmar ausencia de scroll vertical en la página con los paneles "Alertas activas"/"Personas ahora" añadidos (cubierto por 29-03 Task 3, mismo checkpoint que 28-09) |
| Reconocimiento de alerta activa en <3s | OPS-04, criterio de éxito 6 | Criterio de percepción humana, no automatizable | Mostrar la pantalla a un observador no familiarizado con el proyecto, cronometrar hasta que identifique si hay alerta activa |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (6/7 tareas automatizadas; la 7ª es el checkpoint manual explícito de 29-03, ya marcado como tal en el plan)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (solo la última tarea de la fase es manual)
- [x] Wave 0 covers all MISSING references (`tests/test_manager.py`, primer test WS)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-20 (orquestador, tras leer 29-RESEARCH.md § Validation Architecture y los 3 PLAN.md ya escritos)
