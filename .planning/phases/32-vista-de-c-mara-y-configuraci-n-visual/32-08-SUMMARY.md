---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 08
status: complete
completed: 2026-10-04
requirements: [OPS-16, OPS-17, OPS-18, OPS-19, OPS-20, SET-01, SET-02, SET-03, SET-04]
---

# 32-08 — Puerta de fase

La puerta se ejecutó a mano y el checkpoint visual lo hizo Claude con el servidor real y
el navegador integrado, contra una copia de la BD (`DB_PATH` apuntando al scratchpad)
para no tocar el `app_config` real al probar "Restaurar". El checkpoint no se limitó a
confirmar: encontró dos bugs de frontend que dejaban la vista Ajustes inutilizable y uno
del entorno de E2E. Los tres están corregidos y cubiertos por tests.

## Bugs encontrados en el checkpoint

1. **No había forma de guardar desde Ajustes.** `trackChange()` (`settings-save.js`)
   solo apuntaba el cambio en memoria. La barra "Guardar cambios" se pintaba únicamente
   al renderizar la sección y `markFieldDirty(row, true)` no se llamaba en ningún sitio,
   así que al editar un campo no aparecía nada. Ahora `trackChange` compara con el valor
   original (pasar el foco sin cambiar nada, o volver al valor de partida, deja la fila
   limpia), marca la fila y avisa a `settings-section.js`, que repinta solo la barra para
   no perder el foco del campo siguiente.
2. **Ajustes reescribía el hash de otras vistas.** `initSettings()` arranca en segundo
   plano con cualquier hash y `_openSection()` hacía `replaceState('#ajustes/camara')`
   siempre: al abrir `#camara` la URL quedaba como `#ajustes/camara` y una recarga llevaba
   a Ajustes. Ahora solo reescribe cuando Ajustes es la vista visible. De paso, Ajustes
   escucha `hashchange`: antes un `#ajustes/{sección}` pegado en la misma pestaña, o el
   botón atrás, no abría la sección pedida.
3. **La BD de E2E nunca se reiniciaba.** `data/e2e-events.db` se reutilizaba entre
   ejecuciones locales y acumulaba eventos (`CAMERA_OFFLINE` de cada arranque y los
   `CONFIG_CHANGED` del spec nuevo). Con unas decenas en la línea temporal, `clips.spec.js`
   y `live-event.spec.js` dejaban de encontrar su fila. `playwright.config.js` borra ahora
   las BD de E2E al empezar, solo en el proceso principal, como ya ocurre en CI.

## Hallazgo pendiente de decisión (no corregido)

El rate limit de la API v2 (60 peticiones/min por IP, `backend/api/v2/deps.py`, Fase 22)
es fácil de agotar con el propio dashboard: cada carga de página hace unas 15 llamadas v2,
5 de ellas a `GET /api/v2/config`. Con unas cuantas recargas en un minuto, Ajustes recibe
429 y muestra el error de carga. En la suite E2E pasaba lo mismo. `settings.spec.js`
espera a una ventana nueva del limitador antes del test que lo sufría, pero no se ha
tocado la política. Las salidas posibles (subir el límite, deduplicar las 5 peticiones
de configuración o eximir los GET de solo lectura) son decisiones de seguridad que
corresponden al usuario.

## Checkpoint visual (Task 2)

| Paso | Resultado |
|------|-----------|
| 1. Vista Cámara | ✓ Seis teselas con valor o "–"; la URL RTSP sale sin credenciales; los ajustes rápidos persisten sin botón ni recarga (`origin: runtime`). La cámara estaba sin señal: el vídeo en directo no se pudo comprobar con imagen real |
| 2. Árbol de Ajustes | ✓ Ocho secciones más "Cámaras". Reconocimiento muestra los fieldsets Rostro, Identidad temporal y Re-identificación. Cada fila tiene label, variable de entorno, rango y badges de origen y de aplicación |
| 3. Secretos | ✓ La API no envía el valor de ningún campo `secret` y la fila muestra "Configurado" o "Sin configurar" sin input |
| 4. 422 junto al campo | ✓ Tras el arreglo 1: "Debe estar entre 0.05 y 0.95." bajo el control, y la otra fila válida sigue pendiente |
| 5. Restaurar | ✓ Popover "Se borrarán 3 valores personalizados…", sin `confirm()`; los badges vuelven a "Valor por defecto" |
| 6. Consola | ✓ Sin errores JS. Solo aparecen el 422 provocado y un 502 de `/ptz/presets` (cámara sin conexión) |
| 7. 1366×768 | ✓ Vídeo y ajustes rápidos sin scroll; sin desbordamiento horizontal |

## Trazabilidad de los 7 criterios del ROADMAP

| # | Criterio | Evidencia |
|---|----------|-----------|
| 1 | Vista Cámara con live view y salud | `pytest tests/test_cameras_api.py -k health` (7 passed) + checkpoint paso 1 |
| 2 | Árbol de configuración completo | `pytest tests/test_config_api.py -k get_config` (5 passed) + paso 2 |
| 3 | Persistencia en `app_config` y aplicación en caliente | `pytest tests/test_config_api.py -k "put_config or persists"` (14 passed) + `settings.spec.js` |
| 4 | 422 legible junto al campo | `pytest tests/test_config_api.py -k "batch_returns_all_errors or unknown_field_returns_422 or cross_field"` (3 passed) + `settings.spec.js` |
| 5 | Restaurar por sección | `pytest tests/test_config_api.py -k restore` (3 passed) + paso 5 |
| 6 | `CONFIG_CHANGED` con el diff | `pytest tests/test_config_api.py -k "config_changed or secret_never_reaches_diff"` (2 passed) |
| 7 | Precedencia `app_config` > `.env` > default | `pytest tests/test_config_schema.py -k resolve_origin` (6 passed) |

Suites: pytest 883 passed y 16 skipped; Playwright 14/14, verde en dos ejecuciones
seguidas. Los 3 tests nuevos de `settings.spec.js` fallan contra el frontend sin los
arreglos.
