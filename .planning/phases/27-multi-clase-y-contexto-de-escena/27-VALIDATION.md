---
status: draft
phase: 27
---

# Validación — Fase 27: Multi-clase y contexto de escena

Extraído de la sección "Validation Architecture" de `27-RESEARCH.md`. Sirve
de contrato para el planner y para la puerta de fase final.

## Test Framework

| Propiedad | Valor |
|---|---|
| Framework | pytest + pytest-asyncio (`asyncio_mode = auto`) |
| Config file | `pytest.ini` — `python_functions = TEST_*` |
| Intérprete | `F:\Documentos\IA\Proyecto_Camara\.venv\Scripts\python.exe` (**el worktree no tiene `.venv` propio** — usar siempre esa ruta absoluta) |
| Quick run | `.venv/Scripts/python.exe -m pytest tests/test_object_analyzer.py -q` |
| Full suite | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90s) |

Convención obligatoria: todo test nuevo en `TEST_*` (no `test_*` — en Linux/CI
`test_*` no se recoge, solo Windows por case-insensitivity).

## Requisito → Test

| Req | Comportamiento | Comando | ¿Existe? |
|---|---|---|---|
| BEH-06 | `set_classes()` cambia clases sin recargar el modelo | `pytest tests/test_detector.py -k TEST_set_classes -q` | ❌ |
| BEH-06 | `classes=[]` se rechaza con 400 | `pytest tests/test_detection_config_api.py -k TEST_rejects_empty -q` | ❌ |
| BEH-06 | Config persiste en `app_config` y gana sobre env var | `pytest tests/test_repositories.py -k TEST_config_repo -q` | ❌ |
| BEH-06 | Regresión Fase 4: `sv.Detections` mixto no altera `get_counts()` | `pytest tests/test_detection_worker.py -k TEST_object_class_does_not_reach_line_zone -q` | ❌ |
| BEH-06 | Regresión: objetos no entran en `TrackRegistry` | `pytest tests/test_detection_worker.py -k TEST_objects_not_in_registry -q` | ❌ |
| BEH-06 | Criterio 6: p50 con 6 clases < 1.15× p50 con 1 | `pytest tests/test_detector.py -k TEST_multiclass_latency -q` | ❌ (ya medido manualmente: +4.7%) |
| BEH-07 | `OBJECT_LEFT` tras 60s inmóvil sin persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_left -q` | ❌ |
| BEH-07 | Criterio 5: un único `OBJECT_LEFT` por episodio | `pytest tests/test_object_analyzer.py -k TEST_object_left_latched -q` | ❌ |
| BEH-07 | Criterio 5: con persona presente no se emite | `pytest tests/test_object_analyzer.py -k TEST_no_left_with_person -q` | ❌ |
| BEH-07 | Objeto presente al arranque (warmup) nunca emite | `pytest tests/test_object_analyzer.py -k TEST_warmup_furniture -q` | ❌ |
| BEH-07 | Objeto en zona `exclude_objects` nunca emite | `pytest tests/test_object_analyzer.py -k TEST_excluded_zone -q` | ❌ |
| BEH-07 | `OBJECT_REMOVED` al desaparecer con persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_removed -q` | ❌ |
| BEH-07 | Desaparición sin persona cerca → silencio | `pytest tests/test_object_analyzer.py -k TEST_removed_needs_person -q` | ❌ |
| BEH-07 | Oclusión de 1 frame no dispara `OBJECT_REMOVED` | `pytest tests/test_object_analyzer.py -k TEST_occlusion_grace -q` | ❌ |
| BEH-07 | Estado acotado: TTL + cota dura | `pytest tests/test_memory_bounds.py -k TEST_object_analyzer_bounded -q` | ❌ |
| BEH-07 | `emit_object` traduce a `Event` con payload correcto | `pytest tests/test_event_engine.py -k TEST_emit_object -q` | ❌ |
| BEH-08 | Endpoint devuelve los 6 bloques del criterio 4 | `pytest tests/test_scene_context.py -k TEST_context_shape -q` | ❌ |
| BEH-08 | `known` cuenta solo `CONFIRMED`, no `CANDIDATE` | `pytest tests/test_scene_context.py -k TEST_known_requires_confirmed -q` | ❌ |
| BEH-09 | `hourly_baseline()` promedia por (día, hora), no por minuto | `pytest tests/test_repositories.py -k TEST_hourly_baseline -q` | ❌ |
| BEH-09 | `sample_days < 3` ⇒ `level == "unknown"` | `pytest tests/test_scene_context.py -k TEST_insufficient_history -q` | ❌ |
| BEH-09 | Hora parcial normalizada a tasa/minuto (Pitfall 7) | `pytest tests/test_scene_context.py -k TEST_partial_hour_normalised -q` | ❌ |
| — | Invariantes de arquitectura | `pytest tests/test_architecture.py -q` | ✅ |

## Criterios de éxito del ROADMAP → comando

| # | Criterio | Comando / evidencia |
|---|---|---|
| 1 | Clases configurables desde la UI | `pytest tests/test_detection_config_api.py -q` + checkpoint manual (marcar "mochila" y verla en el MJPEG — decisión ya tomada: SÍ overlay) |
| 2 | `OBJECT_LEFT` tras 60s sin persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_left -q` |
| 3 | `OBJECT_REMOVED` al desaparecer con persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_removed -q` |
| 4 | `/api/v2/analytics/context` con media móvil de 7 días | `pytest tests/test_scene_context.py -q` |
| 5 | Un único `OBJECT_LEFT`; con persona presente, ninguno | `pytest tests/test_object_analyzer.py -k "TEST_object_left_latched or TEST_no_left_with_person" -q` |
| 6 | 6 clases no suben la latencia >15% | `pytest tests/test_detector.py -k TEST_multiclass_latency -q` — ya medido: +4.7% (margen 3x) |

## Notas de diseño de test

- **Dominio puro (nivel 1)**: mismo molde que `tests/test_behavior_analyzer.py` —
  `ObjectAnalyzer` instanciado con diccionarios y `now` inventado, sin hilos/broker/asyncio.
- **Criterio 5 exige igualdad de conjuntos**, no membresía: `assert kinds == {ObjectKind.LEFT}`,
  y cubrir explícitamente "objeto inmóvil 70s CON persona a 100px" → `findings == []`.
- **Cableado (nivel 2)**: necesita un helper nuevo `_tracked_cls(boxes, tids, class_ids)` en
  `tests/test_detection_worker.py` — reutilizar, no duplicar con un cuarto helper.
- **Regresión crítica** (hallazgo del research, no estaba en el CONTEXT original): ByteTrack no
  es class-aware — un test debe probar explícitamente que una detección de objeto solapada con
  una de persona no le "roba" el `tracker_id`/tracking a la persona, y que `LineZone`/conteo de
  Fase 4 no ve nunca objetos.

## Wave 0 Gaps

- `tests/test_object_analyzer.py` (nuevo)
- `tests/test_scene_context.py` (nuevo)
- `tests/test_detection_config_api.py` (nuevo)
- Helper `_tracked_cls()` en `tests/test_detection_worker.py`
- Ampliaciones: `test_detector.py`, `test_config.py`, `test_event_engine.py`,
  `test_memory_bounds.py`, `test_repositories.py`, `test_detection_worker.py`
- Framework: ninguno nuevo — pytest ya configurado

## Seguridad (resumen, detalle completo en RESEARCH.md § Security Domain)

- El PUT de clases es el primer endpoint de esta fase que MUTA la configuración del pipeline
  en caliente — sin roles en el sistema, cualquiera con Basic Auth puede cegar la detección.
  Mitigación: rate limit (60/min, patrón ya usado en toda la superficie v2) + validación
  estricta (`0..79`, no vacío, sin duplicados) + evento `CONFIG_CHANGED` para trazabilidad.
- `classes=[]` debe rechazarse con 400 explícito (ciega el sistema en silencio si se permite).
- El endpoint de contexto nunca debe devolver nombres de persona/`person_id`, solo recuentos.
- `days` del endpoint de media móvil: `Query(ge=1, le=90)`, nunca interpolado en SQL crudo.
