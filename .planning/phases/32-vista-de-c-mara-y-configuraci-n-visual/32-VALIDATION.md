---
phase: 32
slug: vista-de-c-mara-y-configuraci-n-visual
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-23
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Compilado
> directamente por el orquestador a partir de `32-RESEARCH.md` § Validation
> Architecture (líneas 402-438) y de los 8 `PLAN.md` ya escritos (32-01..32-08),
> siguiendo la misma plantilla que `31-VALIDATION.md` — este documento fue el único
> bloqueante que dejó `gsd-plan-checker` (Dimension 8/Check 8e), ya resuelto aquí.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest.ini`: `python_functions = TEST_*`, `asyncio_mode = auto`). Sin framework de test JS — los módulos nuevos se validan por sintaxis (`node --check`) y por `tests/test_frontend_modules.py` (`LOCKED_JS`, tope de 300 líneas, convención anti-XSS), no por ejecución. |
| **Config file** | `pytest.ini` (raíz del proyecto) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/test_config_api.py -q` (fichero nuevo, Wave 0 — ajustar al fichero tocado por cada tarea, ver el mapa de abajo) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~90 s (línea base del proyecto) |

---

## Sampling Rate

- **After every task commit:** el/los ficheros de test de esa tarea (ver columna `Automated Command`).
- **After every plan wave:** `.venv/Scripts/python.exe -m pytest tests/test_config_api.py tests/test_config_schema.py tests/test_repositories.py tests/test_frontend_modules.py -q` (todos los ficheros que la fase toca).
- **Before `/gsd-verify-work`:** Full suite must be green + los 7 criterios de éxito del ROADMAP trazados a un `pytest -k` o al checkpoint visual (32-08 Task 1) + checkpoint visual manual bloqueante (32-08 Task 2).
- **Max feedback latency:** ~90 s.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------------|-----------|--------------------|-------------|--------|
| 32-01-01 | 01 | 1 | — (informe) | Verificación temprana y no bloqueante de que `frontend/js/nav.js` y `role="tablist"` existen (dependencia Fase 31); deja constancia en el SUMMARY sin detener el wave | mechanical | `test -f frontend/js/nav.js && grep -q 'role="tablist"' frontend/index.html` (informativo, no falla el wave) | ✅ (script inline) | ⬜ pending |
| 32-01-02 | 01 | 1 | SET-01 | `ConfigRepo.delete()` — mismo molde que `ZoneRepo.delete`/`RuleRepo.delete`; dataclasses `FieldDef`/`Group`/`Section` sin lógica de negocio | unit | `pytest tests/test_repositories.py -k ConfigRepo -q` | ❌ Wave 0 | ⬜ pending |
| 32-01-03 | 01 | 1 | SET-02, SET-03 | `ALL_SECTIONS` puebla los 112 campos reales de `Settings` en las 8 secciones fijas del UI-SPEC, con `min`/`max`/`default`/`secret`/`readonly`/`applies` coherentes con el código, no inventados | unit | `pytest tests/test_config_schema.py tests/test_repositories.py -q` | ❌ Wave 0 | ⬜ pending |
| 32-01-04 | 01 | 1 | SET-01, SET-02, SET-03 | `tests/test_config_schema.py` (nuevo) — cobertura de `resolve_origin`, invariantes cruzados (`identity_vote_window >= identity_min_votes`, etc.) y de `ConfigRepo.delete()` | unit | `pytest tests/test_config_schema.py tests/test_repositories.py -q` | ❌ Wave 0 (creado por esta tarea) | ⬜ pending |
| 32-02-01 | 02 | 2 | OPS-18, SET-02 | `GET /api/v2/config` — esquema resuelto con `origin`/`applies`/`secret`; campos `secret` sin `value` (clave ausente, nunca `null`) | integration | `pytest tests/test_config_api.py -k get_config -q` | ❌ Wave 0 | ⬜ pending |
| 32-02-02 | 02 | 2 | OPS-19, SET-03, SET-04 | `PUT /api/v2/config` — validación por lote (todos los errores 422 a la vez, no el primero), persistir-antes-de-propagar, hot-apply solo por las 3 rutas reales, `CONFIG_CHANGED` con diff completo sin campos `secret` | integration | `pytest tests/test_config_api.py -k batch_validation_errors -q` | ❌ Wave 0 | ⬜ pending |
| 32-02-03 | 02 | 2 | OPS-20 | `POST /{section}/restore` — borra solo las filas `runtime` de `app_config` de esa sección (no escribe defaults encima); wiring en `main.py` | integration | `pytest tests/test_config_api.py -k restore_section -q` | ❌ Wave 0 | ⬜ pending |
| 32-03-01 | 03 | 3 | OPS-16, OPS-17, OPS-18 | 8 clases CSS nuevas (`.metric-tile`, `.rtsp-card`, `.cfg-*`) + fix de objetivo 44×44 en `.cam-toggle`; `components.css` medido contra el tope de 300 líneas antes de escribir | mechanical | `pytest tests/test_frontend_modules.py -k line_limit -q` | ✅ (test ya existe, se amplía) | ⬜ pending |
| 32-04-01 | 04 | 4 | OPS-16 | `camera.js` (activación diferida, tarjeta RTSP con `aria-live`, pie) + extensión de `dashboard-observability.js` para las teselas de métrica (sin `aria-live`, refresco 5 s) | mechanical | `node --check frontend/js/views/camera.js && pytest tests/test_frontend_modules.py -q` | ✅ (LOCKED_JS ampliado) | ⬜ pending |
| 32-04-02 | 04 | 4 | OPS-17 | `camera-quick.js` — 4 ajustes rápidos contra el mismo `PUT /api/v2/config` del árbol, sin endpoint paralelo; `debounce` 600 ms en el deslizador de confianza | mechanical | `node --check frontend/js/views/camera-quick.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-05-01 | 05 | 4 | OPS-18 | `settings-field.js` — un control por tipo del esquema (`bool`/`int`/`float`/`enum`/`time`/`list_str`/`secret`/`readonly`), badges de origen/aplicación siempre visibles, sin repetir el atajo anti-XSS de `detectionClasses.js` (usa `textContent`, no `innerHTML`) | mechanical | `node --check frontend/js/views/settings-field.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-05-02 | 05 | 4 | OPS-19, OPS-20, SET-03, SET-04 | `settings-save.js` — diff pendiente por sección, `PUT`, mapeo de errores 422 por fila (`aria-invalid`, `aria-describedby`), popover de "Restaurar valores por defecto" con recuento en el botón | mechanical | `node --check frontend/js/views/settings-save.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-06-01 | 06 | 5 | OPS-18 | `settings.js` — carga del esquema, árbol `role="tablist"` vertical con `↑`/`↓`/`Home`/`End`, deep-link `#ajustes/{sección}` | mechanical | `node --check frontend/js/views/settings.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-06-02 | 06 | 5 | OPS-18 | `settings-section.js` — panel de sección, `<fieldset>` por grupo, subsecciones de solo lectura (Zonas/Reglas) vía `external_source`, punto azul de cambios pendientes heredado al nodo padre | mechanical | `node --check frontend/js/views/settings-section.js && pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-07-01 | 07 | 6 | — (precondición) | **Bloqueante:** si `frontend/js/nav.js` sigue sin existir (dependencia Fase 31 no ejecutada), el plan se detiene aquí con instrucciones explícitas de ejecutar `/gsd-execute-phase 31` primero — no construye un tablist sustituto | mechanical | `test -f frontend/js/nav.js` (si falla, la tarea aborta el plan) | ⚠ condicional a la Fase 31 | ⬜ pending |
| 32-07-02 | 07 | 6 | OPS-16, OPS-17, OPS-18 | Extiende `nav.js` con las 2 pestañas nuevas ("Cámara", "Ajustes") + armazón HTML de ambos `tabpanel`, mismo mecanismo de hash-routing que la Fase 31 | mechanical | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-07-03 | 07 | 6 | OPS-16, OPS-17, OPS-18 | Wiring en `app.js` + `LOCKED_JS` ampliado con los 8 módulos nuevos de esta fase | mechanical | `pytest tests/test_frontend_modules.py -q` | ✅ | ⬜ pending |
| 32-08-01 | 08 | 7 | OPS-16..20, SET-01..04 | Suite completa en verde + trazabilidad: los 7 criterios de éxito del ROADMAP mapeados cada uno a un `pytest -k` concreto | perf/integration | `pytest tests/ -q` (incluye `-k health`, `-k get_config`, `-k batch_validation_errors`, `-k restore_section`, `-k config_changed_emits_diff`, `-k resolve_origin`) | ✅ | ⬜ pending |
| 32-08-02 | 08 | 7 | Criterios 1-7 del ROADMAP | Checkpoint visual bloqueante: vista Cámara y Ajustes con servidor real — secretos nunca visibles, badges correctos, popover de restaurar, 422 legible junto al campo | manual-only | — (`checkpoint:human-verify`, gate="blocking") | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_config_api.py` (nuevo) — contrato de `GET/PUT /api/v2/config` y `POST /{section}/restore`: esquema con origin/applies/secret, validación por lote (422 con todos los errores), persistir-antes-de-propagar, `CONFIG_CHANGED` sin campos secret, restaurar por sección (32-02-01, 32-02-02, 32-02-03, molde: `tests/test_detection_config_api.py`)
- [ ] `tests/test_config_schema.py` (nuevo) — `resolve_origin`, invariantes cruzados de `Settings` reutilizados (no un validador paralelo), los 112 campos de `ALL_SECTIONS` (32-01-03, 32-01-04)
- [ ] `tests/test_repositories.py::TEST_ConfigRepo_delete_*` — mismo molde que `ZoneRepo.delete`/`RuleRepo.delete` (32-01-02)
- [ ] `tests/test_frontend_modules.py` — `LOCKED_JS` ampliado con los 8 módulos nuevos (`camera.js`, `camera-quick.js`, `settings.js`, `settings-section.js`, `settings-field.js`, `settings-save.js` + extensiones de `dashboard-observability.js`/`nav.js`/`app.js`) + `line_limit` sobre `components.css` (32-03-01, 32-07-03)
- [ ] Framework: **ninguna instalación** — pytest ya instalado, sin runner JS que instalar.

Todos los ficheros de test "Wave 0" se crean/amplían **dentro de la misma tarea** que implementa el código correspondiente (patrón integrado, igual que las Fases 30 y 31).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| `frontend/js/nav.js` existe y expone el `role="tablist"` de la Fase 31 antes de que 32-07 lo extienda | Precondición de OPS-16/17/18 | Depende de si la Fase 31 se ha ejecutado; no automatizable sin acoplar el test a un estado de fase externo | Antes de ejecutar 32-07: `test -f frontend/js/nav.js`. Si falla, ejecutar `/gsd-execute-phase 31` primero (32-07-01 ya lo bloquea automáticamente) |
| La vista Cámara y Ajustes funcionan de extremo a extremo con el servidor real | Criterios 1-7 del ROADMAP de la Fase 32 | Requiere navegador real y, para el estado RTSP, la cámara conectada | Con el servidor arrancado desde la raíz: abrir `#camara`, confirmar retícula de salud (FPS/latencia/CPU/RAM/estado RTSP) y los 4 ajustes rápidos escribiendo por el mismo `PUT`; abrir `#ajustes`, navegar el árbol de 8 secciones, editar un campo, guardar y confirmar el badge de aplicación, forzar un 422 y confirmar el mensaje junto al campo, y "Restaurar valores por defecto" con el popover mostrando el recuento (32-08 Task 2) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (17/19 tareas automatizadas; las 2 manuales son la precondición bloqueante de 32-07 y el checkpoint humano de 32-08, ninguna consecutiva a la otra)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (4 ficheros de test nuevos/ampliados, todos listados arriba, integrados en sus tareas)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-23 (orquestador, tras leer `32-RESEARCH.md` § Validation Architecture, los 8 PLAN.md ya escritos y el `## ISSUES FOUND` de `gsd-plan-checker` — este documento y el marcado `(RESOLVED)` de los Open Questions de `32-RESEARCH.md` eran los dos únicos bloqueantes, ya resueltos)
