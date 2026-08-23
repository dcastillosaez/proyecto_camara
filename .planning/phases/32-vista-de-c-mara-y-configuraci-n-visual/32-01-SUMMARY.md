---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 01
subsystem: api
tags: [pydantic-settings, config-schema, sqlalchemy, fastapi]

# Dependency graph
requires:
  - phase: 27-multi-clase-y-contexto-de-escena
    provides: "precedente de precedencia app_config > .env (PUT /api/v2/detection/classes)"
  - phase: 30-event-timeline-y-centro-de-alertas
    provides: "segundo precedente de precedencia (alerts.muted_rules)"
provides:
  - "backend/api/v2/config_schema.py: FieldDef/Group/Section/ALL_SECTIONS (112 campos), all_fields(), field_by_key(), resolve_origin(), build_candidate_settings()"
  - "ConfigRepo.delete(key) para borrar overrides de app_config (OPS-20)"
affects: [32-02, 32-03, 32-04, 32-05, 32-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Esquema de configuracion servidor-driven: dataclasses frozen (FieldDef/Group/Section) como unica fuente de rangos/labels/secretos, sin copia en cliente"
    - "resolve_origin() de tres vias (runtime/env/default) comparando ConfigRepo.get_all() contra Settings, con enmascarado obligatorio de camera_url via mask_rtsp_url()"
    - "build_candidate_settings() usa el constructor completo de Settings (no model_copy) para re-ejecutar los model_validator cruzados"

key-files:
  created:
    - backend/api/v2/config_schema.py
    - tests/test_config_schema.py
  modified:
    - backend/storage/repositories.py
    - tests/test_repositories.py

key-decisions:
  - "ConfigRepo.delete() copia exactamente el molde de RuleRepo.delete()/ZoneRepo.delete() ya existentes en el mismo fichero"
  - "12 campos marcados secret=True (no 9): el detalle campo a campo de Task 2 marca tambien rtsp_user/tapo_user/dashboard_user como secret, mas estricto que el resumen del threat model de la propia PLAN.md"
  - "Servidor pasa a ser subseccion nueva de Camara (host/port/cors/ssl/dashboard), discrecion explicita del CONTEXT ya que el UI-SPEC no fija subsecciones"

patterns-established:
  - "Toda futura ampliacion de Settings debe anadir su FieldDef correspondiente en config_schema.py o TEST_all_fields_covers_every_settings_attribute rompe en CI"

requirements-completed: []  # SET-01..SET-03 avanzan (resolve_origin/build_candidate_settings/ConfigRepo.delete) pero no se cierran: SET-01 exige edicion en caliente vía HTTP, SET-03 exige 422 legible por HTTP — ambos llegan con el router de 32-02

# Metrics
duration: 25min
completed: 2026-08-23
---

# Phase 32 Plan 01: Esquema de configuracion declarativo Summary

**`config_schema.py` describe los 112 campos reales de `Settings` en 8 secciones fijas con label/hint/rango/secreto/aplicacion en caliente, mas `ConfigRepo.delete()` para poder borrar overrides — la base pura que 32-02 convierte en `GET/PUT /api/v2/config`.**

## Performance

- **Duration:** ~25 min (17:37–18:02 aprox., commits 17:52–18:02)
- **Tasks:** 4 (Task 0 verificacion + Tasks 1-3 de codigo/tests)
- **Files modified:** 4 (2 creados, 2 modificados)

## Estado de la dependencia Fase 31 (Task 0)

```
test -f frontend/js/nav.js && echo "nav.js EXISTE" || echo "nav.js NO EXISTE"
→ nav.js EXISTE

grep -c 'role="tablist"' frontend/index.html
→ 1 (frontend/index.html:37, <nav role="tablist" aria-label="Vistas">, con dos
  pestañas "Cámara"/tab-operaciones y "Analítica"/tab-analitica ya montadas)
```

La Fase 31 esta ejecutada (confirmado por STATE.md y por el arbol de trabajo): `nav.js`
existe con tres funciones exportadas (`grep -n "^export function"`):

```
export function registerAnalyticsBoot(bootFn, resizeFn)
export function activeView()
export function initNav()
```

Este es el contrato real que `32-07-PLAN.md` (wave 6, integracion de navegacion) debe
usar para anadir las pestanas "Camara"/"Ajustes" — no hay que reconstruir ningun
tablist ni asumir el contrato del UI-SPEC sin verificar. Nota: la nota de la
32-RESEARCH.md decia "Fase 31 solo tiene 11 PLAN.md sin ejecutar" — ese hallazgo
quedo obsoleto entre la investigacion (2026-08-23, antes) y la ejecucion de este plan
(2026-08-23, mas tarde el mismo dia): la Fase 31 se completo en el intervalo. Los
planes 32-01..32-06 no dependian de este armazon (backend puro / vistas propias) y no
se vieron afectados por el hallazgo desactualizado.

## Accomplishments
- `ConfigRepo.delete(key)` anadido, mismo molde que `RuleRepo.delete()`/`ZoneRepo.delete()`
- `backend/api/v2/config_schema.py` (1008 lineas): `FieldDef`/`Group`/`Section`, `ALL_SECTIONS`
  con las 8 secciones fijas y sus subsecciones, `all_fields()`/`field_by_key()`,
  `resolve_origin()` (tres vias + enmascarado de `camera_url`), `build_candidate_settings()`
  (constructor completo de `Settings`, re-ejecuta los `model_validator` cruzados)
- Cobertura exacta verificada por test: `set(Settings.model_fields) == {f.key for f in all_fields()}`
  — 112 campos, cero huecos, cero duplicados, cero claves inventadas
- `applies="hot"` restringido correctamente a las 3 unicas rutas reales
  (`yolo_classes`, `process_width`, `process_height`)
- Pitfall 4 (precedencia de listas) cerrado con test parametrizado sobre
  `yolo_classes` y `schedule_days`

## Task Commits

1. **Task 1: ConfigRepo.delete() + dataclasses FieldDef/Group/Section + resolvers** - `1ccaa7e` (feat)
2. **Task 2: Poblar ALL_SECTIONS con los 112 campos reales de Settings** - `dddc13f` (feat)
3. **Task 3: Tests de config_schema.py y de ConfigRepo.delete()** - `e404e4a` (test)

_Task 0 (verificacion de Fase 31) no genero commit propio — es de solo lectura, su
resultado queda documentado arriba, como pide el plan._

## Files Created/Modified
- `backend/api/v2/config_schema.py` - esquema declarativo completo (1008 lineas)
- `backend/storage/repositories.py` - `ConfigRepo.delete(key) -> bool`
- `tests/test_config_schema.py` - 12 tests nuevos
- `tests/test_repositories.py` - 2 tests nuevos de `ConfigRepo.delete()`

## Decisions Made
- **Servidor como subseccion nueva de Camara**: `host`/`port`/`cors_origins`/`ssl_certfile`/
  `ssl_keyfile`/`dashboard_user`/`dashboard_pass` no encajaban en ninguna de las 8 secciones
  fijas del UI-SPEC; el propio `32-CONTEXT.md` delega las subsecciones al planificador, y el
  plan ya fijaba esta asignacion explicitamente — se siguio tal cual.
- **12 campos secret, no 9**: el cuerpo de Task 2 marca `rtsp_user`/`tapo_user`/`dashboard_user`
  como `secret=True` ademas de sus tres contrasenas correspondientes y de los 6 secretos
  "obvios" (ssl_certfile/ssl_keyfile/alert_webhook_url/alert_telegram_token/
  gdrive_credentials_path/gdrive_token_path). El resumen del threat model (T-32-01) solo
  citaba 9 nombres de campo como ejemplo ilustrativo, no como lista cerrada; se siguio el
  detalle campo a campo de Task 2, que es mas explicito y mas conservador de cara a SET-04
  (ningun secreto sale nunca del servidor).

## Deviations from Plan

None — plan ejecutado tal como estaba escrito. La unica discrepancia notable (recuento de
9 vs 12 campos `secret`) es una inconsistencia interna entre el resumen del threat model y
el detalle de Task 2 dentro del propio PLAN.md, resuelta siguiendo la fuente mas especifica
(Task 2), documentada arriba en Decisions Made — no es un cambio de comportamiento respecto
a lo que el plan pedia.

## Issues Encountered
Ninguno. La unica correccion tecnica durante la implementacion fue de orden interno del
propio fichero nuevo (mover la llamada a `_rebuild_index()` despues de su definicion,
adelantada por error al escribir `ALL_SECTIONS` en dos pasadas) — corregida antes del
primer test, sin impacto en el resultado final ni en el historial de commits.

## Next Phase Readiness
- `config_schema.py` esta listo para que `32-02-PLAN.md` construya `GET/PUT /api/v2/config`
  sin re-derivar rangos ni nombres de campo.
- `ConfigRepo.delete()` desbloquea OPS-20 ("Restaurar valores por defecto") para 32-02.
- `nav.js` (Fase 31) ya expone `initNav()`/`activeView()`/`registerAnalyticsBoot()` reales
  para que `32-07-PLAN.md` los consulte sin bloquearse — sin necesidad de ejecutar la Fase 31
  de nuevo.
- Suite completa verde: **689 passed, 2 skipped** (+14 sobre el cierre de la Fase 31).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-23*

## Self-Check: PASSED

- FOUND: backend/api/v2/config_schema.py
- FOUND: tests/test_config_schema.py
- FOUND: .planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-01-SUMMARY.md
- FOUND commit: 1ccaa7e
- FOUND commit: dddc13f
- FOUND commit: e404e4a
