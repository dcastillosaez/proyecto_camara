---
phase: 30-event-timeline-y-centro-de-alertas
plan: 12
subsystem: planning
tags: [puerta-de-fase, rendimiento, checkpoint-visual, trazabilidad, ops-07, ops-08, ops-09, ops-10, ops-11]

# Dependency graph
requires:
  - phase: 30-01
    provides: pipeline de eventos ordenado con payload.rules y mensaje WS type "event"
  - phase: 30-02
    provides: idx_events_ts_id, migracion v3 y EventRepo.query() multi-tipo/regla
  - phase: 30-05
    provides: router /api/v2/events con media, total, track-scope y assign-person
  - phase: 30-06
    provides: GET /api/v2/alerts agrupado por regla con silenciado en app_config
  - phase: 30-10
    provides: cableado completo del frontend (case event en el WS, initTimeline en app.js)
  - phase: 30-11
    provides: modal "Marcar como persona" con recorte precargado y repintado en sitio
provides:
  - "tests/test_repositories.py: 4 tests de rendimiento del criterio 3 con 10.000 eventos sembrados"
  - "Trazabilidad de los 6 criterios de exito del ROADMAP a comando o a evidencia humana"
  - "OPS-07..OPS-11 cerrados en REQUIREMENTS.md"
  - "Fase 30 cerrada en ROADMAP.md (12/12) y en STATE.md"
affects: [31 vista de analitica]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "El presupuesto del test de rendimiento se fija dos ordenes de magnitud por encima de lo medido para que no sea flaky en una maquina cargada"
    - "Los datos del test de rendimiento salen de scripts/seed_events.py (determinista, seed=42), nunca de un generador ad hoc"
    - "Los requisitos solo se marcan con evidencia: comando en verde o punto del checkpoint verificado"

key-files:
  created:
    - .planning/phases/30-event-timeline-y-centro-de-alertas/30-12-SUMMARY.md
  modified:
    - tests/test_repositories.py
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - .planning/STATE.md
    - .gitignore

key-decisions:
  - "El checkpoint visual se ejecuto contra el servidor real y 58 eventos historicos reales; los cuatro puntos que exigen senal de camara se difieren como 11o checkpoint manual, por decision explicita del usuario"
  - "OPS-07..OPS-11 se marcan igualmente: sus criterios deterministas estan verdes y la parte visual verificable con datos reales tambien, mismo criterio con el que la Fase 27 cerro BEH-06/08/09"
  - "El 500 de GET /api/v2/cameras/cam1/health (float inf no serializable) se documenta como bug preexistente y ajeno a la fase, verificado con git log main..HEAD sobre los ficheros implicados, y no se toca aqui"
  - "La paginacion profunda cuesta menos que la primera pagina: con el cursor (ts, id) la profundidad no se paga, con OFFSET se habrian descartado 5.000 filas"

# Metrics
duration: 55min
completed: 2026-08-21
---

# Phase 30 Plan 12: Puerta de la Fase 30 Summary

**El criterio de rendimiento queda medido con 10.000 eventos reales sembrados (peor caso 12,9 ms contra un presupuesto de 100 ms), la suite completa cierra en 607 passed / 2 skipped, el checkpoint visual se verifica con navegador contra el servidor real en todo lo que no exige señal de cámara, y OPS-07..OPS-11 quedan marcados con la Fase 30 cerrada en ROADMAP y STATE.**

## Performance

- **Duration:** ~55 min (Task 1 + resolución del checkpoint + Task 3)
- **Tasks completed:** 3/3

## Qué se construyó

### Task 1 — Criterio 3 medido con datos reales

Cuatro tests nuevos en `tests/test_repositories.py`, todos alimentados por
`scripts/seed_events.py` (determinista, `seed=42`) y nunca por un generador
inventado para la ocasión:

| Test | Qué mide | Medido en esta máquina |
|------|----------|------------------------|
| `TEST_timeline_first_page_under_budget_10k` | `query(limit=50)` sobre 10.000 eventos | 12,9 ms (incluye abrir la conexión) |
| `TEST_timeline_deep_cursor_page_under_budget_10k` | página 100 encadenando cursores, ≈ evento 5.000 | 2,0 ms |
| `TEST_timeline_multi_type_filter_under_budget_10k` | tres tipos + severidad (regresión del Pitfall 2) | 4,2 ms |
| `TEST_timeline_index_exists_after_init` | `idx_events_ts_id` presente en `sqlite_master` | — |

El presupuesto es de 100 ms, dos órdenes de magnitud por encima de lo medido, a
propósito: un test de rendimiento ajustado a la máquina de desarrollo es un test
que falla el martes por la mañana por motivos que no tienen nada que ver con el
código.

El dato interesante es que **la página profunda cuesta menos que la primera**.
Con el cursor `(ts, id)` la profundidad no se paga: el índice compuesto de 30-02
posiciona directamente. Con `OFFSET 5000` habría habido que descartar 5.000 filas
antes de devolver 50. Es exactamente la diferencia que motivó construir el cursor.

Suite completa: **607 passed, 2 skipped** (603 previos + 4). `test_architecture.py`,
`test_security_regression.py` y `test_rule_engine.py` en verde — este último **sin
un solo commit en toda la Fase 30**, como exigía el plan.

Commit: `51e86e9`.

### Task 2 — Checkpoint visual: qué se verificó y qué se difiere

El checkpoint se ejecutó **con el servidor real en marcha** desde la raíz del
repositorio (`.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0
--port 8000`) y automatización de navegador contra `http://localhost:8000/`, sobre
**58 eventos históricos reales** cargados desde `/api/v2/events?limit=50`.

**Verificado con evidencia real:**

- **Criterio 1 — contenido de la fila.** Confirmado sobre el DOM en vivo:
  `.timeline-row` pinta la barra de severidad por variable CSS `--sev`, la hora en
  `.mono`, la miniatura `.tl-thumb` con `tabindex="0" role="button"` y su
  `aria-label` correcto, la descripción en lenguaje llano ("La cámara se quedó sin
  señal", nunca el `CAMERA_OFFLINE` crudo), los chips de zona y de regla
  correctamente `hidden` cuando no aplican, y "Ver clip" / "Marcar como persona"
  `disabled` con el `title` exacto del contrato ("Este evento no tiene grabación" /
  "Este evento no tiene track asociado") en los eventos sin grabación ni track.
- **Criterio 2 — filtros.** La barra de filtros monta todos sus controles: chips de
  tipo, chips de severidad, selector de zona, entrada de persona, rango de fechas y
  los botones "Filtrar" / "Limpiar filtros".
- **Criterio 6 — centro de alertas (parcial).** Badge de la campana, apertura y
  cierre del cajón y trampa de foco al estilo `role="dialog"` confirmados en vivo,
  con un grupo real de `CAMERA_OFFLINE` bien renderizado; al no tener `rule_name`,
  el grupo oculta correctamente el botón de silenciar por ser no silenciable.
- **Criterio 7 — zero-scroll y accesibilidad.** A 1366×768: borde inferior del vídeo
  en 530 px, encabezados "Alertas activas" y "Personas ahora" en 102 px y 213 px,
  todos holgadamente dentro del viewport de 768 px. La zona de operaciones de la
  Fase 29 no necesita scroll; los paneles de línea temporal, ajustes y
  observabilidad que quedan más abajo sí lo necesitan, como prevé SPEC_v2 §8.3 —
  eso no forma parte de este criterio. `Escape` cierra el cajón y devuelve el foco
  a `#btn-alert-center`, comprobado leyendo `document.activeElement`. La fila en sí
  no tiene `tabindex`: solo la miniatura y las cuatro acciones son focalizables, no
  hay una parada de tabulación gigante.
- **Criterio 8 — consola limpia.** Sin `TypeError` ni errores de la fase.

**Diferido — exige la cámara física (192.168.1.132), no alcanzable desde este
entorno.** `CaptureWorker cam1: reconnecting in 30.0s...` confirma que el backoff
del invariante 8 funciona, pero no hay señal de vídeo:

- **Criterio 3** — fluidez percibida del scroll con miles de filas y ausencia de
  salto al recortar por arriba. El rendimiento del backend está probado (Task 1);
  lo que falta es el juicio humano sobre la sensación de scroll.
- **Criterio 4** — evento nuevo en menos de 1 s desde una detección real. Necesita
  un cruce de línea que atraviese el pipeline completo captura → detección →
  evento; no se puede sintetizar sin falsear justo lo que se quiere medir.
- **Criterio 5** — "Marcar como persona" con recorte real precargado, alcance
  retroactivo y repintado en sitio. Necesita un `UNKNOWN_PERSON` reciente con
  snapshot y `track_id`; ninguna fila del histórico actual los tiene.
- **Ciclo completo de silenciado** (parte del criterio 6): silenciar → grupo
  atenuado con "silenciada hasta HH:MM" → reactivar. No existe ahora mismo ningún
  grupo con `rule_name` activo porque no ha disparado ninguna regla. La mecánica de
  servidor ya está cubierta por los 16 tests automáticos de 30-06.

El usuario eligió explícitamente "diferir lo que exige cámara": queda registrado
como el **11º checkpoint manual del proyecto**, con el mismo patrón no bloqueante
que los diez anteriores (19-01, 19-02, 20-02, 21-01, 22-01, 23-02, 25-06, 26-05,
27-11, 29-03).

**Hallazgo ajeno a la fase.** Durante el recorrido, `GET /api/v2/cameras/cam1/health`
devuelve 500 con `ValueError: Out of range float values are not JSON compliant: inf`
cuando no fluyen frames — un FPS calculado con divisor cero. No es una regresión de
la Fase 30: `git log --oneline main..HEAD -- backend/api/v2/metrics.py
backend/observability.py backend/pipeline/rate.py` sale **vacío**, ningún commit de
esta fase toca esos ficheros. Merece su propio `/gsd:debug`, no se toca aquí
(límite de alcance: solo se auto-corrige lo que causa el cambio en curso).

### Task 3 — Cierre de la fase

- `REQUIREMENTS.md`: OPS-07, OPS-09, OPS-10 y OPS-11 marcados `[x]` (OPS-08 ya lo
  estaba desde 30-11).
- `ROADMAP.md`: Fase 30 marcada `[x]` en el índice con la nota del checkpoint
  diferido, `**Plans:** 12/12 plans complete` y 30-12 marcado.
- `STATE.md`: frontmatter (`stopped_at`, `last_updated`, `last_activity`,
  15 fases / 67 planes), `## Current Position` reescrita, fila de la Fase 30 en la
  tabla de estado (y de paso corregidas las de 28 y 29, que seguían diciendo "Sin
  planificar"), lista de checkpoints manuales ampliada de 9 a 11, `## Siguiente
  paso` apuntando a `/gsd:plan-phase 31` con las decisiones no obvias de la fase, y
  cobertura de tests actualizada a 607/2.

Commit: `d06de99`.

## Trazabilidad de los seis criterios del ROADMAP

| # | Criterio | Comando / evidencia |
|---|----------|---------------------|
| 1 | Hora, severidad, descripción legible, zona, miniatura y acciones | `pytest tests/test_frontend_modules.py -q` + **verificado en navegador** sobre 58 eventos reales |
| 2 | Filtros combinables resueltos en servidor con cursor | `pytest tests/test_repositories.py -k "cursor or filters or rule" -q`, `pytest tests/test_events_api.py -q` + barra de filtros verificada en navegador |
| 3 | 10.000 eventos navegables sin degradación perceptible | `pytest tests/test_repositories.py -k 10k -q` (12,9 / 2,0 / 4,2 ms contra 100 ms) — fluidez percibida **diferida** |
| 4 | Evento nuevo en menos de 1 s sin recargar | `pytest tests/test_event_bus.py -k "broadcast or rules_persisted" -q` — verificación con detección real **diferida** |
| 5 | "Marcar como persona" precarga el crop y actualiza retroactivamente | `pytest tests/test_repositories.py -k assign_person -q`, `pytest tests/test_events_api.py -k "track_scope or assign" -q` — recorrido visual **diferido** |
| 6 | El centro de alertas agrupa, silencia por regla y muestra qué regla disparó | `pytest tests/test_alerts.py -q` (16 tests) + badge, cajón, agrupación y foco **verificados en navegador**; ciclo de silenciado **diferido** |

## Por qué se marcan OPS-07..OPS-11 aun con checkpoint diferido

El criterio del proyecto es no marcar sin evidencia, y la evidencia existe: los
cinco requisitos tienen su parte determinista en verde (76 tests entre
`test_repositories.py`, `test_events_api.py`, `test_alerts.py`, `test_event_bus.py`,
`test_snapshots.py` y `test_frontend_modules.py`) y la parte visual verificable con
datos reales también. Lo diferido no es "si el código funciona" sino "cómo se
siente" con una cámara delante — juicio humano sobre fluidez y latencia percibida.
Es el mismo criterio con el que la Fase 27 cerró BEH-06, BEH-08 y BEH-09 difiriendo
su propia calibración con cámara real, y con el que la Fase 25 cerró REID-01..04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.claude-server.log` sin ignorar**
- **Found during:** Task 3, al preparar el commit
- **Issue:** el servidor de desarrollo que la sesión principal dejó en marcha
  escribe `.claude-server.log` en la raíz, apareciendo como fichero sin trackear
  en cada `git status` y con riesgo de acabar commiteado por accidente
- **Fix:** añadido a `.gitignore`
- **Files modified:** `.gitignore`
- **Commit:** `d06de99`

### Correcciones de estado fuera del guion estricto

La tabla "Estado de las 22 fases de v2.0" de `STATE.md` seguía marcando las Fases 28
y 29 como "Sin planificar" pese a estar completas en código (`ROADMAP.md` ya las
tenía cerradas). Se corrigen de paso, porque `STATE.md` es la fuente única de verdad
del proyecto y dejarla contradiciendo al ROADMAP en el mismo commit que cierra una
fase habría propagado el error.

## Deferred Issues

- **500 en `GET /api/v2/cameras/cam1/health`** con `float inf` no serializable
  cuando no fluyen frames. Preexistente, ajeno a la Fase 30 (verificado con `git log
  main..HEAD` sobre los ficheros implicados). Pendiente de `/gsd:debug`.
- **11º checkpoint manual** (30-12 Task 2, cuatro puntos): documentado arriba y
  registrado en `STATE.md`. Retomarlo con la cámara conectada, arrancando el
  servidor desde la raíz y siguiendo los puntos 2, 3, 4 y el ciclo de silenciado del
  punto 5 de `<how-to-verify>` en `30-12-PLAN.md`.

## Authentication Gates

Ninguno.

## Known Stubs

Ninguno.

## Self-Check: PASSED

- `tests/test_repositories.py`, `scripts/seed_events.py` y este SUMMARY existen en disco
- Commits `51e86e9`, `b29fdd9` y `d06de99` presentes en el historial
- `grep -c 10k tests/test_repositories.py` → 7 (≥ 3)
- `grep -c seed_events tests/test_repositories.py` → 7 (≥ 2)
- `git log --oneline main..HEAD -- tests/test_rule_engine.py` → 0 commits
- Suite completa: 607 passed, 2 skipped (131 s)
