---
status: draft
phase: 28
---

# Validación — Fase 28: Refactor del frontend a módulos ES

Extraído de la sección "Validation Architecture" de `28-RESEARCH.md`. Sirve
de contrato para el planner y para la puerta de fase final.

## Test Framework

| Propiedad | Valor |
|---|---|
| Framework | pytest (`pytest>=7.0`, `pytest-asyncio>=0.24`) — convención `python_functions = TEST_*` en `pytest.ini` |
| Config file | `pytest.ini` (raíz del repo) |
| Quick run | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -q` (fichero nuevo, Wave 0) |
| Full suite | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90s, 519 tests antes de esta fase) |

No existe framework de test JS en el repo (sin `package.json`). Solo las
propiedades mecánicas del refactor (ficheros existen, límite de líneas, tipo
MIME real, SRI intacto) son automatizables con pytest; la paridad funcional
completa sigue siendo un checklist manual firmado en el SUMMARY (mismo
criterio que 27-10).

## Requisito → Test

| Req | Comportamiento | Comando | ¿Existe? |
|---|---|---|---|
| OPS-01 | Cada módulo JS locked por 28-CONTEXT.md existe bajo `frontend/js/` | `pytest tests/test_frontend_modules.py -k modules_exist -q` | ❌ |
| OPS-02 | Ningún fichero en `frontend/js/**/*.js` ni `frontend/css/*.css` supera 300 líneas | `pytest tests/test_frontend_modules.py -k line_limit -q` | ❌ |
| OPS-03 | `index.html` no contiene `<script>`/`<style>` inline (salvo el único `<script type="module" src="/static/js/app.js">` y las 2 CDN de cabecera) | `pytest tests/test_frontend_modules.py -k no_inline_logic -q` | ❌ |
| OPS-03 | `/static/js/app.js` se sirve con `Content-Type` que contiene `javascript` vía la app ASGI real (landmine de MIME en Windows) | `pytest tests/test_frontend_modules.py -k mime_type -q` | ❌ |
| OPS-03 | SRI de Chart.js sigue intacto en una sola línea | `pytest tests/test_security_regression.py -k chartjs -q` | ✅ (ya existe, no debe romperse) |
| OPS-03 | `backend/main.py` sirve `/` y `/static/*` sin cambios de comportamiento | `pytest tests/test_main.py -q` (o el fichero que ya cubra las rutas de `main.py`) | Verificar cobertura existente en Wave 0 |
| OPS-03 | Paridad funcional completa (vídeo, PTZ+presets, contadores, chart, toggles cámara, resoluciones, grabaciones+Drive, personas+galería, zonas CRUD, clases detectadas, filtros, salud, observabilidad, WS+reconexión) | manual-only — sin framework de test JS | Checklist firmado en el SUMMARY |

## Criterios de éxito del ROADMAP → comando

| # | Criterio | Comando / evidencia |
|---|---|---|
| 1 | `css/` + `js/{views,components}` existe; `index.html` sin lógica inline (criterio redefinido, ver 28-CONTEXT.md) | `pytest tests/test_frontend_modules.py -k "modules_exist or no_inline_logic" -q` |
| 2 | `frontend/js/app.js` es el entry point real | `pytest tests/test_frontend_modules.py -k app_entry_point -q` + lectura manual (no debe quedar como stub de 2 líneas) |
| 3 | Ningún módulo > 300 líneas | `pytest tests/test_frontend_modules.py -k line_limit -q` |
| 4 | Paridad funcional total con v1.2 | Checklist manual firmado en el SUMMARY (servidor real + navegador) |
| 5 | FastAPI sirve `/static` y SRI de Chart.js se mantiene | `pytest tests/test_frontend_modules.py -k mime_type -q` + `pytest tests/test_security_regression.py -k chartjs -q` |
| 6 | Carga inicial < 1s en LAN | Medición manual documentada en el SUMMARY (DevTools Network desde un segundo dispositivo de la LAN, no `localhost`) — si no hay acceso a un segundo dispositivo en la sesión de ejecución, diferir explícitamente como checkpoint (mismo patrón que los 9 checkpoints de cámara real ya diferidos) |

## Notas de diseño de test

- `tests/test_frontend_modules.py` recorre `frontend/js/**/*.js` y `frontend/css/*.css`
  con `pathlib.Path.rglob` + `str.splitlines()` para el recuento de líneas —
  sin parseo JS, solo recuento de ficheros y líneas.
- El test de `no_inline_logic` debe comprobar la AUSENCIA de `<style>` y de
  bloques `<script>` sin `type="module"`/`src`, no solo contar líneas —
  usar una expresión regular simple sobre el contenido de `index.html`
  (`re.search(r"<style", html)` debe ser `None`; cualquier `<script>` sin
  `src=` debe ser `None` salvo las 2 etiquetas CDN del `<head>`).
- El test de `mime_type` debe usar `starlette.testclient.TestClient` contra
  la app real (`backend.main.app`), pidiendo `/static/js/app.js` y
  comprobando `"javascript" in response.headers["content-type"]` — no
  mockear `mimetypes`, es precisamente el mecanismo real el que hay que
  verificar (ver 28-RESEARCH.md, landmine de registro de Windows).
- Los ficheros locked por `28-CONTEXT.md` (lista exacta de `views/`+`components/`)
  deben verificarse por nombre exacto, no por glob genérico — un test que
  solo compruebe "existe algún fichero en `js/views/`" no detectaría que
  falta `zoneEditor.js` si se creó con otro nombre.

## Wave 0 Gaps

- `tests/test_frontend_modules.py` (nuevo) — cubre OPS-01/OPS-02/OPS-03 mecánicos.
- Ningún fixture nuevo necesario — `tests/test_security_regression.py::TEST_vuln_14_chartjs_cdn_has_subresource_integrity` ya cubre el SRI y no requiere cambios, solo debe seguir en verde.
- Confirmar en Wave 0 si existe ya un test que cubra las rutas `/` y `/static` de `backend/main.py`; si no, añadir un caso mínimo en `tests/test_frontend_modules.py` en vez de crear un fichero nuevo solo para eso.

## Seguridad (resumen, detalle completo en RESEARCH.md § Security Domain)

- No hay superficie de ataque nueva: la fase no añade endpoints, no cambia
  autenticación/autorización, no introduce dependencias de terceros.
- Al mover `addEvent`/`_recRow` a sus nuevos módulos, mantener el patrón ya
  existente de `textContent` (no `innerHTML`) para datos que vienen del
  backend (`person_name`, timestamps) — comentario explícito ya presente en
  `index.html:1094-1097` citando CodeQL `js/xss`; no perderlo al copiar.
- No tocar el CSP (`script-src ... 'unsafe-inline'`) en esta fase — los 2
  handlers `onerror`/`onclick` inline del `<img id="video-feed">` y el botón
  "Reintentar conexión" dependen de `'unsafe-inline'` y no son parte del
  alcance de esta fase (ver 28-RESEARCH.md Pitfall 3).
