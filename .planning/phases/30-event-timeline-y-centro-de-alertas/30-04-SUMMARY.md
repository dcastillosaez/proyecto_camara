---
phase: 30-event-timeline-y-centro-de-alertas
plan: 04
subsystem: api
tags: [snapshots, opencv, asyncio, staticfiles, config, retention]

# Dependency graph
requires:
  - phase: 30-01
    provides: make_event_pipeline() y _broadcast_event() — el punto exacto donde se engancha el hook y donde se rellena el bloque media
  - phase: 19-event-engine-y-esquema-v2
    provides: el campo Event.snapshot_path, declarado desde entonces y hasta ahora nunca escrito
provides:
  - "Settings.snapshot_* (5 ajustes) con validate_snapshot_dir (contención en el proyecto) y validate_snapshot_params (rangos)"
  - "_capture_event_snapshot(): recorte del bbox del último frame escrito como JPEG fuera del event loop"
  - "_purge_old_snapshots(): purga por directorio YYYYMMDD, enganchada al _purge_loop diario"
  - "snapshot_url() en backend/api/v2/deps.py: ruta en disco -> URL pública, compartida por main.py y el router de 30-05"
  - "mount /snapshots con la misma auth global que /gallery y /clips"
  - "media.snapshot_url resuelta en el mensaje WS type:\"event\""
affects: [30-05 router de eventos, 30-07 marcado de la card, 30-08 línea temporal en el frontend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hook inyectable en la fábrica del pipeline: el snapshot entra en la fila con el primer INSERT, sin segundo UPDATE"
    - "cv2.imwrite y shutil.rmtree siempre vía asyncio.to_thread desde corrutinas"
    - "Estado de módulo con cota dura (_SNAPSHOT_STATE_CAP) y barrido por antigüedad en vez de diccionario creciente"
    - "Agrupación por día (YYYYMMDD) para que la retención sea un rmtree por directorio, no un stat por fichero"

key-files:
  created:
    - tests/test_snapshots.py
  modified:
    - backend/config.py
    - backend/main.py
    - backend/api/v2/deps.py
    - tests/test_config.py
    - .gitignore

key-decisions:
  - "El snapshot se captura ANTES del INSERT: la ruta viaja en la misma fila desde la primera escritura y el mensaje WS ya sale con la URL resuelta"
  - "El hook va en su propio try/except: un disco lleno o un frame ausente no pueden impedir que el evento se persista"
  - "snapshot_url() vive en deps.py y no en main.py — un router importando main sería un ciclo de imports"
  - "Los tests usan un stub de Settings en vez de Settings(snapshot_dir=tmp_path): el validador nuevo rechaza tmp_path por diseño"
  - "data/snapshots/ añadido a .gitignore: el mount crea el directorio al importar la app y los JPEG son salida de runtime"

# Metrics
duration: 21min
completed: 2026-08-21
---

# Phase 30 Plan 04: Snapshot de evento Summary

**`Event.snapshot_path` pasa de campo muerto a dato real: cada evento con `bbox` deja un recorte JPEG en `data/snapshots/{YYYYMMDD}/{event_id}.jpg`, escrito con `cv2.imwrite` dentro de `asyncio.to_thread`, con la ruta ya en la fila persistida y la URL resuelta en el mensaje WS.**

## Performance

- **Duration:** ~21 min
- **Tasks:** 3
- **Files modified:** 5 (1 nuevo)
- **Commits:** 6 (3 de tests RED + 3 de implementación)

## Accomplishments

- La miniatura de la línea temporal deja de ser un marcador: `grep imwrite` solo devolvía la galería de personas ya identificadas y la miniatura de clip, así que ninguna fila de `events` tenía imagen propia. Ahora la tiene cualquier evento con `bbox`, identificado o no — que es justo el caso de `UNKNOWN_PERSON` sobre el que 30-05 monta "Marcar como persona".
- El recorte entra en la fila con el **primer** `INSERT`. El hook se ejecuta entre la evaluación de reglas y la persistencia, así que no hay un segundo `UPDATE` ni una ventana en la que el evento exista sin imagen.
- `cv2.imwrite` nunca corre en el event loop, y hay un test que lo prueba por identidad de función (`to_thread.await_args.args[0] is cv2.imwrite`), no por inspección de texto. Lo mismo con el `shutil.rmtree` de la purga.
- Tres cotas independientes sobre el disco (T-30-13): throttle de 5 s por `(camera_id, track_id)`, reescalado a 320 px de ancho y purga diaria a 30 días. `snapshot_enabled=False` apaga la función entera sin tocar código.
- El propio diccionario del throttle está acotado a 256 entradas con barrido por antigüedad — sin eso sería estado global creciente indexado por `track_id`, que es exactamente lo que `CLAUDE.md` prohíbe.

## Task Commits

1. **Task 1: Ajustes de configuración con validación de ruta** — `c2a1368` (test RED) + `a54ccb6` (feat)
2. **Task 2: `_capture_event_snapshot()` y `_purge_old_snapshots()`** — `e3d7b0b` (test RED) + `2efeec0` (feat)
3. **Task 3: Cableado — hook, URL pública, mount y retención** — `841f701` (feat)

## Files Created/Modified

- `backend/config.py` — cinco ajustes `snapshot_*`, `validate_snapshot_dir` (contención en `_PROJECT_ROOT`, réplica del patrón de `reid_model_path`) y `validate_snapshot_params` (anchura en [64, 1920], throttle en [0, 3600], retención en [0, 3650]).
- `backend/main.py` — `_snapshot_last`/`_SNAPSHOT_STATE_CAP`, `_capture_event_snapshot()`, `_purge_old_snapshots()`, parámetro `snapshot_hook` en `make_event_pipeline()` con su bloque `try` propio antes del `INSERT`, `media.snapshot_url` en `_broadcast_event()`, mount `/snapshots` y la llamada a la purga dentro de `_purge_loop`.
- `backend/api/v2/deps.py` — `snapshot_url()`, el traductor compartido ruta-en-disco → URL pública.
- `tests/test_snapshots.py` (nuevo, 11 tests) — recorte real en disco, `bbox=None`, deshabilitado, throttle por track, `to_thread`, clamp de coordenadas desbordadas, purga por directorio de día, traducción de URL, hook antes del `INSERT` sobre un `EventRepo` real en SQLite, supervivencia al fallo del hook y presencia del mount.
- `tests/test_config.py` — 4 tests de los ajustes nuevos.
- `.gitignore` — `data/snapshots/`.

## Decisions Made

Las del bloque `key-decisions`. Todas venían fijadas por el plan salvo la del stub de `Settings` en los tests, que se explica abajo.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Bloqueante] Los tests no pueden usar `Settings(snapshot_dir=tmp_path)`**

- **Found during:** Task 2
- **Issue:** El plan indicaba parchear `backend.main.get_settings` con `Settings(snapshot_dir=str(tmp_path/"snaps"))`, pero `validate_snapshot_dir` — que el propio plan manda escribir en la Task 1 — rechaza por diseño cualquier ruta fuera de `_PROJECT_ROOT`, y el `tmp_path` de pytest vive en el directorio temporal del sistema. Los dos requisitos se contradicen.
- **Fix:** Un helper `_settings(tmp_path, **over)` que devuelve un `SimpleNamespace` con los cinco atributos que la función lee. La alternativa (escribir en el árbol del repo durante los tests, o monkeypatchear `backend.config._PROJECT_ROOT`) era peor: la primera ensucia el working tree, la segunda desactiva justo el control de seguridad que se está probando en otro sitio. La validación real sigue cubierta por los 4 tests de `tests/test_config.py`.
- **Files modified:** `tests/test_snapshots.py`
- **Commit:** `e3d7b0b`

**2. [Rule 2 - Funcionalidad crítica ausente] `data/snapshots/` no estaba en `.gitignore`**

- **Found during:** Task 3
- **Issue:** El mount crea el directorio al importar `backend.main`, y en cuanto el sistema corra con cámara real los JPEG aparecerían como ficheros sin trackear. `data/thumbnails/` y `data/backups/` ya estaban ignorados por el mismo motivo; este quedaba fuera.
- **Fix:** Regla `data/snapshots/` junto a la de `data/thumbnails/`.
- **Files modified:** `.gitignore`
- **Commit:** `841f701`

**3. [Sustitución del test 4 de la Task 3]** El plan proponía `TestClient(app).get("/snapshots/<fichero>")` con la alternativa explícita de comprobar el mount en `app.routes` "si el mount usa el directorio real del proyecto". Es el caso: el mount se resuelve en tiempo de import contra `_settings.snapshot_dir`, así que servir un fichero exigiría escribir en `data/snapshots/` del repo. Se implementó la alternativa que el propio plan contemplaba (`TEST_snapshots_mount_is_registered`).

## Criterios de aceptación con matiz de `grep`

| Criterio | Esperado | Real | Motivo |
|---|---|---|---|
| `grep -n "snapshot_hook" backend/main.py` | ≥3 | 4 | Parámetro, guarda `if`, llamada `await` y paso en `lifespan`. Cumple de sobra. |

El resto de criterios de las tres tareas se verificaron literalmente: `def validate_snapshot_dir` (1), `_PROJECT_ROOT` dentro del validador nuevo, `to_thread(cv2.imwrite` (1, y `cv2.imwrite` aparece una sola vez en toda la función), `_SNAPSHOT_STATE_CAP` (2), `_purge_old_snapshots` (2), `def snapshot_url` (1), el mount `/snapshots` presente en `app.routes`, y `event.snapshot_path = path` en una línea anterior a `event_repo.insert` dentro de `_event_pipeline`.

## Verification

| Comando | Resultado |
|---|---|
| `pytest tests/test_config.py -k snapshot -q` | 4 passed |
| `pytest tests/test_snapshots.py -q` | 11 passed |
| `pytest tests/test_snapshots.py tests/test_event_bus.py -q` | 22 passed |
| `pytest tests/test_architecture.py tests/test_config.py -q` | 34 passed |
| `pytest tests/ -q` | **570 passed, 2 skipped** |
| `python -c "from backend.main import app; ..."` | `['/snapshots']` |

## Threat Model

Los cuatro riesgos del registro quedan mitigados en código:

- **T-30-11** (path traversal en el nombre del fichero): la ruta es `{snapshot_dir}/{event.ts:%Y%m%d}/{event.id}.jpg`. `event.id` es un `uuid4` generado en servidor (`Event.id` default_factory) y el directorio deriva del timestamp. Ninguna parte procede del cliente.
- **T-30-12** (mount apuntando fuera del proyecto): `validate_snapshot_dir` con `resolve()` + `is_relative_to(_PROJECT_ROOT)`, con dos tests (ruta absoluta fuera y traversal con `..`).
- **T-30-13** (disco lleno): throttle + reescalado + purga + interruptor, descritos arriba.
- **T-30-14** (latencia por `imwrite` en el event loop): `asyncio.to_thread`, verificado por test de identidad de función.

## Issues Encountered

Ninguno. La suite completa pasó a la primera y el flake de `test_upload_queue.py` que apareció en 30-01 no se reprodujo.

## User Setup Required

None. Los defaults funcionan sin tocar `.env`. Para apagarlo: `SNAPSHOT_ENABLED=false`.

## Next Phase Readiness

- 30-05 puede importar `snapshot_url` de `backend/api/v2/deps.py` directamente para el bloque `media` de la lista paginada; la función ya está probada.
- El contrato del mensaje WS no cambió de forma: `media` sigue teniendo las mismas cuatro claves, solo que `snapshot_url` ya no es siempre `null`.
- Las filas de `events` empiezan a poblarse con `snapshot_path` desde el primer evento con `bbox`, así que 30-08 tendrá miniaturas reales que renderizar en cuanto el sistema corra con cámara.

## Known Stubs

Ninguno. Las tres claves restantes de `media` (`recording_id`, `clip_url`, `thumbnail_url`) siguen a `null` en el WS, pero eso no es un stub de este plan: el `<interfaces>` del plan lo fija explícitamente ("el resto de claves las rellena el router en 30-05, no el WS").

## Self-Check: PASSED

- `backend/config.py` — FOUND (`validate_snapshot_dir`, `validate_snapshot_params`, 5 ajustes)
- `backend/main.py` — FOUND (`_capture_event_snapshot`, `_purge_old_snapshots`, `snapshot_hook`, mount `/snapshots`)
- `backend/api/v2/deps.py` — FOUND (`def snapshot_url`)
- `tests/test_snapshots.py` — FOUND (11 tests)
- Commits `c2a1368`, `a54ccb6`, `e3d7b0b`, `2efeec0`, `841f701` — FOUND en `git log`
- Suite completa: 570 passed, 2 skipped

---
*Phase: 30-event-timeline-y-centro-de-alertas*
*Completed: 2026-08-21*
