---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: La v1.2 resolvió el pipeline funcional completo
status: executing
stopped_at: Fase 32 en marcha (2/8 planes) — 32-02 cerrado (GET/PUT/restore /api/v2/config, unico endpoint HTTP nuevo de la fase); SET-01..04 cerrados, OPS-18..20 avanzan sin cerrar (esperan interfaz). Siguiente paso: 32-03 (frontend, arranque de la vista Camara/Ajustes)
last_updated: "2026-08-23T18:16:00.000Z"
last_activity: 2026-08-23 -- 32-02 cerrado: router GET/PUT/restore de configuracion con validacion por lote y auditoria CONFIG_CHANGED, suite completa verde
progress:
  total_phases: 32
  completed_phases: 16
  total_plans: 90
  completed_plans: 80
  percent: 89
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-01)

**Core value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo, reconocimiento facial, grabación automática y métricas de sistema integrados en el mismo panel.
**Current focus:** Phase 32 — Vista de cámara y configuración visual (2/8 planes)

## Current Position

Milestone: v2.0 — Plataforma de Video Analytics
Phase: 32 (Vista de cámara y configuración visual) — EN MARCHA (2/8 planes)
Plan: 2 of 8 — 32-02 cerrado
Status: 32-02 cerrado; siguiente paso `/gsd:execute-phase 32` (32-03, arranque de frontend)

**32-02 construye el unico endpoint HTTP nuevo de la Fase 32.**
`backend/api/v2/config.py` (296 lineas) convierte el esquema declarativo de 32-01 en
`GET/PUT /api/v2/config` + `POST /{section}/restore`, registrados en el lifespan de
`main.py` junto a `detection_v2_module`. GET resuelve `origin`/`applies`/`secret` por
campo sobre las 8 secciones fijas; ningun campo `secret=True` lleva la clave `value` en
ningun origen y `camera_url` sale siempre enmascarada. PUT valida el lote completo en un
solo pase (rango por campo primero, invariantes cruzados de `Settings` despues via
`build_candidate_settings`, que reejecuta los `model_validator`) devolviendo TODOS los
errores 422 juntos, nunca solo el primero — verificado empiricamente que
`model_validator(mode="after")` con `raise ValueError(...)` produce `loc == ()`, asi que
el campo del error cruzado en la respuesta es la seccion, no el nombre del campo
concreto (aclaracion documentada en `32-02-SUMMARY.md`, no una desviacion: es el
algoritmo literal que pedia el plan). Persistir-antes-de-propagar verificado con
`attach_mock`: `ConfigRepo.set()` siempre antes que
`CameraPipeline.set_detection_classes()`/`set_process_size()`, las unicas 3 rutas reales
de aplicacion en caliente. `yolo_classes` reutiliza literalmente las 4 comprobaciones de
`detection.py` de la Fase 27 (vacia, rango COCO, duplicados, clase 0 obligatoria) en vez
de una redaccion paralela. `restore` borra solo filas `runtime` de una seccion — nunca
escribe defaults encima — con `CONFIG_CHANGED(restored=True)` solo si hubo algo que
borrar. 22 tests nuevos en `tests/test_config_api.py` (5 GET, 13 PUT, 3 restore, 1 de
wiring en `main.py`), suite completa **711 passed, 2 skipped** (+22 sobre el cierre de
32-01). SET-01..04 quedan cerrados; OPS-18, OPS-19 y OPS-20 avanzan pero no se cierran
(exigen interfaz visible, que llega con 32-04..32-06 y se marca en la puerta de fase
32-08). Ver `32-02-SUMMARY.md`.

**32-01 cierra la base declarativa de toda la Fase 32.** `backend/api/v2/config_schema.py`
(1008 líneas) describe los 112 parámetros reales de `Settings` — label en español llano,
hint, tipo, rango, sección, aplicación en caliente y si es secreto — en las 8 secciones
fijas del `32-UI-SPEC.md` (Cámara, Detección, Tracking, Reconocimiento, Zonas, Reglas,
Alertas, Almacenamiento), con una subsección "Servidor" nueva dentro de Cámara para
`host`/`port`/`cors_origins`/`ssl_*`/`dashboard_*` — discreción explícita del CONTEXT, ya
que el UI-SPEC fija los 8 nombres de sección pero no las subsecciones. Verificado por test,
no por inspección manual: `set(Settings.model_fields) == {f.key for f in all_fields()}` sin
huecos ni duplicados. `resolve_origin()` resuelve la precedencia de tres vías
(runtime/env/default, D-06) para escalares y para listas (`yolo_classes`, `schedule_days` —
Pitfall 4 de 32-RESEARCH.md, cerrado con test parametrizado) y enmascara `camera_url` de
forma obligatoria vía `mask_rtsp_url()` antes de que el valor salga de la función.
`build_candidate_settings()` usa el constructor completo de `Settings` (no `model_copy`,
que en pydantic 2.13.1 no revalida — Assumption A1 de 32-RESEARCH.md, confirmada) para
re-ejecutar los `model_validator` cruzados (`identity_vote_window >= identity_min_votes`,
`run_window_secs <= 12.0`, etc.) sin reimplementarlos en el futuro router de 32-02.
`ConfigRepo.delete(key)` se añadió copiando el molde exacto de `RuleRepo.delete()`/
`ZoneRepo.delete()`, desbloqueando OPS-20 ("Restaurar valores por defecto"). Doce campos
quedan marcados `secret=True` (no nueve, como sugería el resumen del threat model de la
propia PLAN.md): el detalle campo a campo de Task 2 marca también `rtsp_user`/`tapo_user`/
`dashboard_user` como secretos, no solo sus contraseñas — documentado como decisión en el
SUMMARY, sin desviación de comportamiento. Task 0 (verificación temprana de la Fase 31)
encontró que `nav.js` ya existe con tres funciones exportadas
(`registerAnalyticsBoot`/`activeView`/`initNav`) y que `frontend/index.html` ya tiene
`role="tablist"` con las pestañas Operaciones/Analítica — el hallazgo de 32-RESEARCH.md
("Fase 31 sin ejecutar") quedó obsoleto entre la investigación y la ejecución de este plan,
sin impacto porque 32-01..32-06 no dependen de ese armazón. Suite completa: **689 passed, 2
skipped** (+14 sobre el cierre de la Fase 31). Ver `32-01-SUMMARY.md`.

**La Fase 31 está completa.** La vista de analítica añade un segundo tab junto a
Operaciones: personas por hora/día con superposición del periodo anterior, ocupación
por zona, heatmap acumulado con leyenda relativa, ranking de personas con tendencia y
exportación CSV/JSON del rango visible. Las cuatro peticiones de cada tanda salen en
paralelo con un único `AbortController` por tanda (D-09) y las agregaciones se
calculan siempre en SQL — `TEST_analytics_no_client_aggregation` lo convierte en test
permanente, no en promesa del plan. OPS-12..OPS-15 quedan marcados.

**31-11 (puerta de fase) cerró las tres piezas.** `LOCKED_JS` incorpora los seis
módulos de la vista (`nav.js` + cinco `views/analytics*.js`) y
`TEST_analytics_no_client_aggregation` barre esos mismos ficheros buscando
`.reduce(`/`.sort(`/`.filter(`/`Math.max(`/`Math.min(` — encontró y forzó la
corrección de un incumplimiento real: el propio comentario de cabecera de
`analytics-ranking.js` citaba esas expresiones al explicar que no las usaba. Criterio 4
(presupuesto 500 ms @100k): `hourly` ~228-241 ms, `summary` ~346 ms, `occupancy` ~13-15
ms, `persons_ranking` ~13-14 ms — los cuatro por debajo del presupuesto, con menos margen
que lo estimado en 31-RESEARCH.md porque la medición compartió máquina con el servidor de
desarrollo ya en marcha para el checkpoint. Criterio 3 (presupuesto 100 KB): 565 bytes
(`/hourly` 30 días), 3210 bytes (`/hourly` 7 días), 1147 bytes (`/export json`). Migración
v3→v4 verificada sobre el backup automático real que `run_migrations()` generó el mismo
día antes de migrar `data/events.db` (1037 filas antes y después, `idx_events_analytics`
aparece, `schema_version` pasa a 4) — no una base sintética de test. Suite completa:
**675 passed, 2 skipped** (+68 sobre la Fase 30).

El checkpoint visual de Task 3, verificado con servidor y navegador reales, encontró una
**regresión real**: abrir `http://localhost:8000/#analitica` directamente (marcador,
recarga, URL pegada) dejaba las dos gráficas ancladas al tamaño de reserva de Chart.js
(300×150) para siempre — la trampa exacta que D-03 llevaba toda la fase advirtiendo,
pero en el único camino de arranque (hash ya presente al cargar) que ningún plan anterior
había ejercitado; activar la pestaña con un clic (el camino que sí se había probado)
funcionaba bien. Causa: `initNav()` resuelve el hash y llama a `activate()` de forma
síncrona dentro de `DOMContentLoaded`, y esa misma función crea las gráficas
(`createCharts()`) en el mismo tick en que retira `hidden` del contenedor — antes de que
el navegador confirme el recálculo de layout. Corregido en `nav.js`: la primera llamada a
`_boot()` se difiere con `requestAnimationFrame`, que sí garantiza layout aplicado antes
de medir el contenedor. Aplicado sin condicionar el origen de la activación (hash vs.
clic) por ser idempotente e inofensivo en ambos casos. Único otro `new Chart(` del
proyecto (`dashboard-events.js`) revisado y descartado: vive en la vista visible por
defecto, nunca se construye dentro de un contenedor recién revelado. Checkpoint aprobado
tras el fix; lo que exige actividad de cámara real (heatmap con datos genuinos, ranking
con personas reconocidas) queda diferido como **12º checkpoint manual**, mismo criterio
no bloqueante que los 11 anteriores. Ver `31-11-SUMMARY.md`.

**31-10 cerro el orquestador: `analytics.js` y `analytics-export.js` cablean por
primera vez el andamiaje de 31-03, las graficas de 31-07, el rango/ranking de 31-08
y los siete endpoints de 31-05/06/09 en una vista que funciona.** `initAnalytics()`
solo registra el arranque diferido en `nav.js` — quien no abre la pestana no paga
ni una peticion. `load(range)` cancela la tanda anterior con un unico
`AbortController` y dispara `summary`/`hourly`/`occupancy`/`persons` en paralelo
(sin combinador que aborte las tres buenas por la cuarta mala) mas `loadHeatmap()`
aparte; cada `loadPanel()` resuelve su propio estado y una respuesta rezagada de una
tanda abortada no toca el DOM ni decrementa el contador de la tanda nueva — la mitad
de D-09 que se olvida siempre. El panel del heatmap pregunta primero a
`/heatmap/scale` porque un `<img>` no puede distinguir un 404 (sin actividad) de un
503 (sin senal), pinta la leyenda relativa con el valor absoluto en el `title`, y
difiere su recarga con `activeView()` cuando la pestana esta oculta. Los cuatro
botones de exportacion validan la URL con `isSafeMediaUrl()` antes de
`window.location.href`, sin serializar nada en cliente — el servidor de 31-09 genera
el fichero. Import por namespace de `nav.js` (`import * as nav`) para que la unica
cita literal de `registerAnalyticsBoot` sea la llamada real, exigido por un criterio
de aceptacion de conteo exacto. `analytics.js` 211 lineas, `analytics-export.js` 47
—la valvula de escape del heatmap a `analytics-charts.js` no hizo falta—. Suite
dirigida verde (`tests/test_frontend_modules.py` 8 passed); plan solo de frontend,
sin relanzar la suite completa. OPS-12/14/15 quedan funcionalmente completos por
primera vez en la fase; OPS-13 avanza pero se cierra formalmente en la puerta de
fase 31-11, mismo patron que Fases 27/28/29/30. Siguiente: 31-11 (puerta de fase:
`LOCKED_JS` con los seis modulos y checkpoint visual con servidor real).

**31-09 anadio la exportacion CSV/JSON del rango visible.** Precondicion:
los cuerpos de `/hourly`, `/summary`, `/occupancy` y `/persons` se extrajeron
a `_hourly_payload`/`_summary_payload`/`_occupancy_payload`/`_persons_payload`
(funciones `async` de modulo), y los cuatro `@router.get` quedaron como
envoltorios de una linea — sin tocar ni una linea de los tests de 31-05/31-06.
`GET /api/v2/analytics/export` llama a esos MISMOS constructores: es la unica
forma real de garantizar "lo que se descarga es lo que se ve", en vez de
confiar en que dos implementaciones paralelas no diverjan. `format` y `panel`
son `Literal[...]` de FastAPI (422 de Pydantic, sin `if` de cuerpo), el CSV
lleva BOM UTF-8 (Excel en Windows rompe los acentos sin el) con cabecera en
castellano por panel y `delta_pct=None` como celda vacia, y el nombre del
fichero (`analitica-{panel}-{YYYYMMDD}_{YYYYMMDD}.csv` /
`analitica-{YYYYMMDD}_{YYYYMMDD}.json`) lo compone el servidor solo con
`panel` (tres valores fijos) y fechas ya validadas — ningun texto libre del
cliente llega al `Content-Disposition` (T-31-30). 10 tests nuevos, incluida
la equivalencia literal entre la seccion `hourly` del JSON y `GET /hourly`
con los mismos parametros. Peso real del JSON con 30 dias sembrados: 1847
bytes, muy por debajo del limite de 100 KB del criterio 3. Suite completa:
674 passed, 2 skipped. OPS-15 queda cerrado. Siguiente: 31-10 (orquestador
`analytics.js`, panel del heatmap y `analytics-export.js`).

**31-08 escribio los dos modulos de los extremos de la vista: rango y ranking.**
`frontend/js/views/analytics-range.js` (139 lineas, nuevo) expone
`initRange`/`currentRange` con los cuatro presets (`today`/`7d`/`30d`/`custom`)
resueltos con fechas locales inclusivas (nunca `toISOString()`, que da el dia
equivocado por la noche al este de Greenwich), persistencia en `localStorage`
con lista blanca de presets conocidos (T-31-28) y validacion del rango
personalizado **solo** al pulsar "Aplicar rango" con las dos cadenas de error
literales del 422 de `_resolve_range()` en 31-05 — la validacion de cliente es
cortesia, la autoridad es el servidor (T-31-29). `initRange()` no dispara
ninguna carga al arrancar: solo restaura el estado visual, para que 31-10 sea
el unico que decide cuando pedir datos.
`frontend/js/views/analytics-ranking.js` (123 lineas, nuevo) expone
`renderCards`/`renderRanking`: las cuatro tarjetas de tendencia sin color de
direccion (`#94a3b8` siempre, la flecha lo dice) y las filas del ranking con
la plantilla de nodos vacios + `textContent` que ya usa `timeline-row.js`
(D-15) — el nombre de una persona nunca se interpola en el marcado, a
diferencia del agujero real de `personGallery.js:28` que este modulo no
copia — y `isSafeMediaUrl()` (importada, no reimplementada) antes de asignar
cualquier avatar a `img.src` (T-31-27). Sin periodo anterior comparable, la
fila y la tarjeta dicen "sin comparación" en vez de inventar un porcentaje.
Un bug de indexado propio se detecto y corrigio antes de comitear: el
`querySelectorAll('span')` de la fila incluye el `.rank-initial` anidado
dentro de `.rank-avatar`, lo que desplazaba los indices numericos previstos
en el plan; se sustituyeron por selectores de clase (`.w-5`, `.truncate`,
`.text-base`, `.text-slate-500`, `.text-slate-400`), mas robustos que contar
posiciones en una plantilla con anidamiento. Suite dirigida verde
(`tests/test_frontend_modules.py` 8 passed); no toca pipeline/API/config, asi
que no se relanzo la suite completa. OPS-14 ya estaba cerrado por 31-04/31-05;
OPS-13 avanza pero no se cierra todavia (los modulos existen y pasan sus
criterios de aceptacion, pero nada los cablea al DOM hasta 31-10 y la puerta
de fase 31-11 es quien lo marca, mismo patron que las Fases 27/30). Siguiente:
31-09 (export CSV/JSON).

**31-07 escribio las dos graficas de Chart.js de la vista.**
`frontend/js/views/analytics-charts.js` (168 lineas, nuevo) expone
`createCharts`/`renderHourly`/`renderOccupancy`/`setCompare`/`resizeCharts`:
instancias creadas bajo demanda en la primera activacion de la pestana
(D-03, aun sin cablear — eso es 31-10), tipo de grafica/pico/comparacion
resueltos enteramente por el servidor de 31-05 (cero `.reduce()`/`.sort()`/
`.filter()`/`Math.max()`/`Math.min()`, verificado por lectura literal
incluidos los comentarios) y resumen accesible regenerado en cada carga
sobre el `aria-label` de cada `<canvas>`. Suite dirigida verde
(`tests/test_frontend_modules.py` 8 passed); no toca pipeline/API/config,
asi que no se relanzo la suite completa. Siguiente: 31-08 (rango y ranking).

**31-05 expone esas agregaciones por HTTP.** Nuevo router
`backend/api/v2/analytics.py` con `GET /hourly`, `/summary`, `/occupancy` y
`/persons`, montado desde el lifespan igual que el resto de routers v2. Los
nombres de persona en `/persons` se resuelven con
`asyncio.to_thread(recognizer.list_persons)` — nunca `ATTACH DATABASE` contra
`persons.db` desde el event loop. Peso real medido para el criterio 3: 565
bytes (`/hourly` 30 días, cubo diario) y 3210 bytes (`/hourly` 7 días, cubo
horario) — muy por debajo del límite de 100 KB. Suite completa: 658 passed, 2
skipped. Siguiente: 31-06 (heatmap v2, `/heatmap` y `/heatmap/scale`).

**31-04 puso las cuatro agregaciones de la fase en SQL.** `AnalyticsRepo`
(`backend/storage/repositories.py`) expone `hourly()`, `summary()`,
`occupancy()`, `persons_ranking()` y `person_avatars()`, todas resueltas sobre
`events` — nunca `detection_stats` — con parámetros siempre por diccionario,
nunca f-strings con datos del cliente. `bucket_for()` decide cubo horario
(≤7 días) o diario por encima, sobre `substr(ts,1,13)`/`substr(ts,1,10)` del
TEXT ISO de ancho fijo (2,3x más rápido que `strftime`). `persons_ranking()`
es la única consulta que necesita `INDEXED BY idx_events_analytics` —sin el
hint SQLite hace skip-scan y sube de 26,7 ms a 212,6 ms @100k—, y
`person_avatars()` resuelve el capture más reciente desde `captures`
(vive en `events.db`, no en `persons.db`) sin `JOIN persons` ni
`ATTACH DATABASE`. Las cuatro agregaciones quedan medidas por debajo del
presupuesto de 500 ms del criterio 4 sobre 100.000 eventos con identidad y
zona sembradas (`persons=60`, `zones=14`), con dos tests de regresión que
impiden medir sobre datos vacíos y un `EXPLAIN QUERY PLAN` que fija el uso del
índice del ranking. 20 tests nuevos, suite completa **637 passed, 2 skipped**.
Sin desviaciones de código de producción — un ajuste de redacción de test
donde el plan pedía un cubo con 0 eventos, irrealizable con `GROUP BY`. OPS-12
y OPS-14 ya estaban cerrados por 31-01/31-02; OPS-13 avanza pero no se cierra
todavía (el repositorio existe, pero nada "muestra" el ranking hasta el router
de 31-05 y la UI de 31-08). Ver `31-04-SUMMARY.md`.

**31-02 cerró el heatmap por el lado del pipeline.** `compose_heatmap` pasa de
`cv2.COLORMAP_JET` a `cv2.COLORMAP_INFERNO` (D-13: rampa perceptualmente
uniforme, se funde con un frame nocturno en vez de inventar fronteras de
arcoiris) y `DetectionWorker.heatmap_scale()` expone `{"peak", "mean"}` de la
máscara acumulada bajo `self._lock` — mismo molde que `get_object_boxes()` —,
devolviendo `None` tanto sin máscara como con pico 0 para que 31-06 distinga
404 de 503 al construir `GET /api/v2/analytics/heatmap/scale`. El endpoint v1
`/api/heatmap` no se tocó y hereda INFERNO por compartir `compose_heatmap`. 4
tests nuevos, suite de detección y arquitectura en verde. Ver `31-02-SUMMARY.md`.

**La Fase 30 está completa.** El card plano de "Eventos recientes" ya no existe:
en su sitio hay una línea temporal accionable de filas de 52 px con barra de
severidad, miniatura del snapshot, descripción en lenguaje llano, chips de zona y
de regla y cuatro acciones, filtros combinables resueltos **en servidor** con
paginación por cursor, scroll infinito con ventana de 400 filas, eventos en vivo
por el `/ws` que ya existía, centro de alertas en cajón lateral con agrupación por
regla y silenciado temporal, y "Marcar como persona" con el recorte precargado y
actualización retroactiva del track. OPS-07..OPS-11 quedan marcados.

**30-12 (puerta de fase) cerró las tres piezas.** La Task 1: cuatro tests nuevos
en `tests/test_repositories.py` miden el criterio 3 con 10.000 eventos sembrados
por `scripts/seed_events.py` (nunca un generador ad hoc) contra un presupuesto de
100 ms por consulta. Medido en esta máquina: primera página 12,9 ms (incluye abrir
la conexión), página 100 —unos 5.000 eventos dentro— 2,0 ms, y filtro de tres tipos
más severidad 4,2 ms. Que la página profunda cueste menos que la primera es justo
lo que tenía que salir: con el cursor `(ts, id)` la profundidad no se paga, con
`OFFSET` se habrían descartado 5.000 filas antes de devolver 50. Suite completa en
**607 passed, 2 skipped**, con `test_architecture.py`, `test_security_regression.py`
y `test_rule_engine.py` verdes — este último sin un solo commit de la Fase 30, como
exigía el plan.

La Task 2 (checkpoint visual) se resolvió **con el servidor real en marcha** y
navegador contra `http://localhost:8000/` sobre 58 eventos históricos reales.
Verificado con evidencia: contenido de la fila (criterio 1) —barra de severidad por
`--sev`, hora monoespaciada, miniatura con `role="button"` y su `aria-label`,
descripción en lenguaje llano y nunca `CAMERA_OFFLINE` crudo, chips ocultos cuando
no aplican, acciones deshabilitadas con el `title` exacto del UI-SPEC—; barra de
filtros completa (criterio 2); campana, badge, apertura/cierre del cajón y trampa de
foco (criterio 6, parcial); zero-scroll a 1366×768 con el borde inferior del vídeo en
530 px y los paneles de la Fase 29 en 102/213 px, más `Escape` devolviendo el foco a
`#btn-alert-center` y la fila sin `tabindex` propio (criterio 7); y consola limpia
(criterio 8). **La cámara real (192.168.1.132) no es alcanzable desde este entorno**
—`CaptureWorker cam1: reconnecting in 30.0s...` confirma el backoff del invariante 8,
pero no hay señal—, así que los criterios 3 (fluidez percibida del scroll), 4 (evento
nuevo en <1 s desde una detección real), 5 (marcar como persona sobre un
`UNKNOWN_PERSON` con recorte y `track_id`) y el ciclo completo silenciar → atenuar →
reactivar quedan **diferidos como 11º checkpoint manual**, decisión explícita del
usuario y mismo patrón no bloqueante que los diez anteriores.

Durante el recorrido apareció un fallo **preexistente y ajeno a la fase**:
`GET /api/v2/cameras/cam1/health` devuelve 500 con
`ValueError: Out of range float values are not JSON compliant: inf` cuando no fluyen
frames (FPS calculado con divisor cero). `git log main..HEAD` sobre
`backend/api/v2/metrics.py`, `backend/observability.py` y `backend/pipeline/rate.py`
sale **vacío**: ningún commit de la Fase 30 toca esos ficheros, así que no es una
regresión de esta fase. Merece un `/gsd:debug` propio.

30-11 cerró la acción estrella de la fase. `markPerson.js` (169 líneas) escucha el
`CustomEvent('timeline:mark-person')` que la fila ya despachaba desde 30-08 —misma
convención que el `timeline:filter-rule` de 30-10, sin que ninguno de los dos módulos
importe al otro—, abre el modal con el recorte del evento ya cargado y escribe el aviso
de alcance con el N que devuelve `GET /track-scope`: el operador ve cuántos eventos
anteriores del track van a recibir la identidad **antes** de confirmar. El enrolado sigue
siendo dos llamadas a propósito (`POST /api/enroll_face` conserva sus validaciones de
`content_type`, 10 MB y `max_length=100` con tests de regresión; `assign-person` solo
propaga un `person_id` ya enrolado). Al confirmar, `applyPersonAssignment()` en
`timeline.js` sincroniza el modelo en memoria, baja a `info` la severidad de los
`UNKNOWN_PERSON` —mismo criterio que el `UPDATE` del backend— y repinta guardando y
restaurando `scrollTop`: cero red, cero páginas perdidas. Suite completa en verde
(603 passed, 2 skipped). Pendiente de comprobación manual, que firma 30-12: modal con el
recorte real, N razonable en el aviso (si saliera en decenas o cientos sería el Pitfall 3
asomando) y filas del track cambiando en sitio al confirmar. Ver `30-11-SUMMARY.md`.

30-10 encendió la fase: hasta este plan, la línea temporal y el centro de alertas eran
código que nadie llamaba. `websocket.js` despacha ahora `type:"event"` a `onLiveEvent()`
con un `else if` más en el `onmessage` —mismo molde que el `'tracks'` de la Fase 29, ni una
segunda conexión— y `app.js` llama a `initTimeline()` **antes** de `connectWS()`, para que
el `IntersectionObserver` y los controles existan cuando llegue el primer mensaje. El
riesgo real era el doble pintado del `LINE_CROSSED`, que el backend emite por
`type:"detection"` y por `type:"event"`: queda cortado por dos sitios independientes —el
`case 'detection'` ya no pinta filas desde 30-07 y `onLiveEvent()` descarta ids repetidos—
y solo conserva contador, gráfica horaria y toast. El aviso de "sin tiempo real" se cuelga
del `onopen`/`onclose` que ya existían, sin tocar el backoff de 1 s→30 s. `LOCKED_JS` pasa
a vigilar los cinco módulos de la fase.

**El hueco de 30-09 queda cerrado**: `timeline.js` escucha `timeline:filter-rule` y
`setFocusFilter()` (en `timeline-filters.js`, con el resto del estado de filtros) traduce
el nombre de regla al parámetro `rule` del servidor —que lo resuelve con
`json_each(payload,'$.rules')`— o enciende el chip del tipo cuando el grupo no tiene regla.
De paso salió un bug: `_matchesActiveFilters()` no comprobaba `rule`, así que con el filtro
puesto un evento en vivo de otra regla se colaba en la lista. Suite completa en verde
(603 passed, 2 skipped). Pendiente de comprobación manual, que firma 30-12: evento real en
<1 s sin recargar, cruce de línea una sola vez, barra ámbar al caer el socket y filtro
aplicado al pulsar "Ver en la línea temporal". Ver `30-10-SUMMARY.md`.

30-09 cerró el centro de alertas del navegador. `alertCenter.js` (272 líneas) pide
`GET /api/v2/alerts?hours=24` y con esa única respuesta repinta tres sitios: el badge
de la campana (oculto con 0, "9+" desde 10, rojo si hay crítica y ámbar si solo hay
avisos), el cajón lateral con un grupo por regla, y el top-3 "Alertas activas" de la
Fase 29. No hay ni un `.filter()` ni un `.sort()` sobre los datos — el orden por
severidad, la agrupación y el silenciado los decide el servidor (30-06), que era el
motivo de construir ese endpoint. Silenciar usa un popover cuya duración **es** la
confirmación (15 min / 1 h / 8 h desde `dataset.duration`, cero `confirm()` nuevos,
D-07), y tras silenciar o reactivar —con éxito o con error— siempre se relee el estado
del servidor. Los grupos silenciados siguen visibles, atenuados y con "Reactivar regla".
El cajón es `role="dialog"` con foco atrapado y `Escape` que cierra primero el popover.
`loadActiveAlerts()`/`SEVERITY_RANK` salieron de `dashboard.js` (290 → 244 líneas,
recuperando margen sobre `TEST_line_limit`). Dos desviaciones: el cableado de `app.js`
que el plan dejaba para 30-10 hubo que adelantarlo (retirar el símbolo de `dashboard.js`
dejaba un import roto que habría dejado el dashboard en blanco), y una regla CSS para
que `.hidden` de Tailwind gane al selector de id del badge.

~~Hueco abierto para 30-10~~ **cerrado en 30-10**: `gotoTimeline()` despachaba
`timeline:filter-rule` sin que nadie lo escuchara; el oyente ya está en `timeline.js`.
Ver `30-09-SUMMARY.md`.

30-08 dio comportamiento a ese andamiaje: la línea temporal ya pide páginas de 50
a `/api/v2/events` con cursor, filtra **en servidor** (tipo multi-valor, severidad
excluyente, zona, persona resuelta contra el `Map` de `/persons`, y rango de
fechas), pagina con `IntersectionObserver` (`rootMargin: 200px`, sin un solo
listener de `scroll`) y mantiene el DOM en 400 filas compensando `scrollTop` al
recortar. El array completo vive en memoria y el DOM es solo una ventana sobre él,
así que volver a subir se repinta desde memoria y **no hace falta el cursor
inverso** que planteaba el UI-SPEC. Un evento en vivo entra arriba con `slide-in`
si la lista está al principio, y si el operador ha bajado se acumula en la píldora
"{N} eventos nuevos" sin tocarle el scroll. La fila monta los siete elementos del
UI-SPEC con el patrón anti-XSS del repo (plantilla vacía + `textContent`), el
descarte vive en `localStorage` y "Marcar como persona" solo despacha
`timeline:mark-person` — 30-11 es quien escucha. Cuatro módulos en vez de los dos
previstos (`timeline.js` 283, `timeline-row.js` 204, `timeline-filters.js` 133,
`timeline-virtualize.js` 67) porque el tope de 300 líneas no daba para menos.
Se cargan desde 30-10. Ver `30-08-SUMMARY.md`.

30-07 puso el andamiaje del frontend de la fase. El card "Eventos recientes" de la
columna derecha es ahora "Línea temporal" en el mismo sitio (sin vista nueva ni
router) con los ids que 30-08, 30-09 y 30-11 consumen como contrato:
`#timeline-list` y sus cuatro estados (vacío, vacío por filtros, error, cargando),
centinela de 1px para el `IntersectionObserver`, pill de eventos nuevos y barra de
"sin tiempo real"; barra de filtros `tl-*` (tipo, severidad, zona, persona con
`datalist`, dos fechas) y `#tl-active-filters`. En la cabecera, campana de 44×44
con `#alert-badge`, y "Ver todas" en el panel "Alertas activas" de la Fase 29;
ambos abrirán `#alert-drawer` (cajón de 380px con contador héroe, grupos, pie y
popover de silenciado con las tres duraciones). Modal propio `#mark-person-modal`
en vez de reutilizar `#enroll-modal` — su `submit` ya está enlazado por
`personGallery.js` con otra semántica. `components.css` pasa de 81 a 158 líneas con
las medidas exactas del UI-SPEC (fila de 52px, acciones 32×32, miniatura 64×36,
chips de 20px, 4 tamaños de fuente). En el mismo plan se retiró el JS que apuntaba
al marcado borrado —`addEvent`, `applyFilters`, `bindEventFilters`, el bloque de
`#events-list` de `loadInitialData()` y la escritura en `#events-badge`—, que era
justo lo que habría reventado el arranque de `app.js`; el export CSV sobrevive en
`bindEventExport()` y el borrado por rango no se tocó. Sin comportamiento todavía:
la lista se llena en 30-08. Ver `30-07-SUMMARY.md`.

30-06 cerró el backend del centro de alertas. `GET /api/v2/alerts` devuelve las
alertas de la ventana **ya agrupadas por la regla que las disparó**
(`key: "rule:<name>"`) o, si ninguna regla intervino, por tipo de evento
(`key: "type:<TYPE>"`, con `mutable: false` — se silencia por `Rule.name`, D-16).
Cada grupo trae `count`, `severity` (la más alta), `last_ts`, `last_event_id`,
`zone_id` y `muted_until`, y la respuesta añade `active_count` / `critical_count`
/ `muted_count`, que son exactamente los números del badge de la campana: el
navegador ya no filtra ni ordena nada. Los eventos `info` entran solo si
dispararon una regla. El conjunto está acotado a 200 eventos por severidad con
`truncated` en la respuesta, y `hours` a `1..168` (T-30-24). El silenciado
(`POST /mute` / `/unmute`) persiste en `app_config`, clave `alerts.muted_rules`,
con duración en lista blanca 15 min / 1 h / 8 h — no existe "para siempre"
(T-30-21) —, read-modify-write serializado por un `asyncio.Lock` de módulo
(T-30-23) y expiración perezosa sin tarea de fondo. Es **solo de presentación**
(D-16/D-17): el módulo no toca `RuleEngine` ni `run_actions`, así que la regla se
sigue evaluando y sus acciones siguen grabando y avisando; silenciar no hace
perder pruebas (T-30-22). Cada silenciado/reactivación emite `CONFIG_CHANGED` con
la regla y la duración (T-30-20). 16 tests nuevos en `tests/test_alerts.py`,
suite **603/603** (+2 skips). OPS-11 queda cubierto por el lado del servidor; el
cajón y la campana llegan en 30-07 y 30-09. Ver `30-06-SUMMARY.md`.

30-05 cerró la superficie HTTP de la fase: `GET /api/v2/events` deja de ser un
endpoint suelto en `main.py` (Fase 19) y pasa a `backend/api/v2/events.py` con
cuatro rutas. La lista mantiene el envelope `{events, cursor}` que
`dashboard.js:274` ya consume y solo **añade** dos claves: `total` (solo en la
primera página y solo con filtros activos — el `COUNT(*)` de 21 ms @100k no se
paga en cada scroll) y `media`, un mapa hermano `event_id -> {recording_id,
clip_url, thumbnail_url, snapshot_url}` resuelto con **una** consulta por página
vía `by_trigger_event_ids()`. `media` va fuera del objeto evento a propósito: el
DTO es el contrato persistido y también viaja por el WS. Se añaden el tipo
repetido (`?type=A&type=B`) y el filtro por regla que 30-02 dejó listos en el
repositorio, más el detalle `GET /{id}`, la previsualización
`GET /{id}/track-scope` (no escribe nada) y `POST /{id}/assign-person`
(`person_id >= 1`, el enrolado sigue en `/api/enroll_face`, aquí no se duplica su
validación). El endpoint viejo se borró en el **mismo** commit que registra el
router, así que nunca convivieron dos rutas iguales. Los cuatro endpoints llevan
`@limiter.limit(V2_RATE_LIMIT)` y el de lista `pagination_limit()`. 17 tests
nuevos en `tests/test_events_api.py`, suite 587/587 (+2 skips). Una desviación
menor: `pagination_limit` quedó sin uso en `main.py` y se retiró del import.
OPS-09 queda cubierto por el lado del servidor; OPS-07/08 esperan al frontend
(30-08 y 30-11). Ver `30-05-SUMMARY.md`.

30-04 puso en marcha el snapshot de evento: `Event.snapshot_path` existía en el
contrato desde la Fase 19 y **nadie lo escribía**, así que la miniatura de la
línea temporal habría caído siempre al marcador. Ahora cada evento con `bbox`
deja un recorte JPEG en `data/snapshots/{YYYYMMDD}/{event_id}.jpg` mediante
`_capture_event_snapshot()`, enganchada al pipeline de 30-01 como
`snapshot_hook` **antes** del `INSERT` (la ruta entra en la fila con la primera
escritura, sin segundo `UPDATE`) y con su propio `try/except` para que un disco
lleno no impida persistir el evento. `cv2.imwrite` y el `shutil.rmtree` de la
purga van siempre en `asyncio.to_thread` (T-30-14, verificado por identidad de
función en test, no por grep). Tres cotas sobre el disco: throttle de 5 s por
`(camera_id, track_id)` con el diccionario acotado a 256 entradas, reescalado a
320 px y `_purge_old_snapshots()` por directorio de día dentro del `_purge_loop`
diario. `validate_snapshot_dir` exige contención en `_PROJECT_ROOT` porque el
directorio se sirve por `StaticFiles` bajo `/snapshots` con la misma auth global
que `/gallery` y `/clips` (T-30-12). `snapshot_url()` vive en
`backend/api/v2/deps.py` para que main.py y el router de 30-05 la compartan sin
ciclo de imports, y `media.snapshot_url` ya sale resuelta en el mensaje WS.
15 tests nuevos (11 en `tests/test_snapshots.py`, 4 en `tests/test_config.py`),
suite 570/570 (+2 skips). Dos desviaciones menores documentadas: los tests usan
un stub de `Settings` porque el validador nuevo rechaza el `tmp_path` de pytest
por diseño, y se añadió `data/snapshots/` a `.gitignore`. OPS-07 avanza pero no
se cierra: la superficie HTTP llega en 30-05 y la marca 30-12.
Ver `30-04-SUMMARY.md`.

30-03 añadió al repositorio las tres operaciones de "Marcar como persona":
`EventRepo.track_scope()` (previsualiza el alcance retroactivo sin escribir),
`EventRepo.assign_person()` (propaga la identidad y baja a `info` la severidad
de los `UNKNOWN_PERSON`, con `UPDATE ... WHERE id IN (lista explícita)`, nunca
por `track_id`) y `RecordingRepo.by_trigger_event_ids()` (mapa evento → clip de
una página en una sola consulta, sobre `recordings.trigger_event_id`, que es el
vínculo real: `events.recording_id` nunca se escribe). La clave son las dos
constantes de módulo `TRACK_GAP_SECS=60.0` y `TRACK_WINDOW_HOURS=6`: los
`tracker_id` de ByteTrack se reinician al recrear el tracker
(`backend/tracker.py:181`), así que el alcance se acota por `camera_id` +
ventana de ±6 h + corte en el primer hueco > 60 s. Dos tests de regresión
(track homónimo separado 48 h) cierran el Pitfall 3 / T-30-08. 12 tests nuevos,
suite 555/555 (+2 skips). Sin desviaciones de comportamiento. OPS-08 avanza
pero no se cierra: la superficie HTTP llega en 30-05 y la marca 30-12.
Ver `30-03-SUMMARY.md`.

30-02 preparó el almacenamiento para la línea temporal: índice compuesto
`idx_events_ts_id (ts DESC, id DESC)` en `Event.__table_args__` con su
migración `_migrate_v2_to_v3` (`SCHEMA_VERSION=3`, `CREATE INDEX IF NOT
EXISTS`, no destructiva, cubierta por el `_backup_db()` que ya existía), y
`EventRepo` extendido: `_filter_conditions()` compartido, `query()` acepta
`type` como enum suelto o lista (con el `+` unario del `IN` multi-valor que
evita el `TEMP B-TREE FOR ORDER BY` — 54 ms → 0,52 ms @100k) y filtra por
nombre de regla vía `json_each(payload,'$.rules')` con `bindparam`, más un
`count()` nuevo para el contador "{N} de {total}". Ningún llamador de
`query()` necesitó tocarse. Dos correcciones sobre el plan: `_record_version()`
(el paso v1→v2 sellaba `SCHEMA_VERSION`, que al subir a 3 habría marcado v3
antes de tiempo) y `type_=String` en el bindparam expandido (sin él la
consulta no compila con `literal_binds` y el test de `EXPLAIN QUERY PLAN` no
podía inspeccionar el SQL real). 9 tests nuevos, suite 543/543 (+2 skips).
OPS-09 avanza pero no se cierra: la superficie HTTP llega en 30-05 y la
marca 30-12. Ver `30-02-SUMMARY.md`.

30-01 cerró la condición de carrera D-14: los cuatro suscriptores
concurrentes del `EventBus` colapsan en `make_event_pipeline()` (un solo
`subscribe("event_pipeline", ...)`), que evalúa las reglas con el nuevo
`RuleEngine.match()` (puro y síncrono), escribe `payload["rules"]` en el
evento ANTES del `INSERT`, emite `{"type": "event", "event": {...},
"media": {...}}` por el `/ws` legacy después del `INSERT`, y difiere en
fire-and-forget tanto `run_actions()` (Telegram/webhook/grabación) como
`_broadcast_v1_compat`. `evaluate()` queda como wrapper compatible y los
14 tests de `tests/test_rule_engine.py` pasan sin tocarse. 4 tests nuevos
en `tests/test_event_bus.py` fijan el orden con un `EventRepo` real.
Suite 534/534 (+2 skips). OPS-10/OPS-11 avanzados, no cerrados: los marca
30-12 con evidencia. Ver `30-01-SUMMARY.md`.
  ArcFace) completa encima (326/326). La puerta bloqueante de la Fase 23
  se superó con evidencia real: `insightface`+`onnxruntime` instalan sin
  compilar en Windows, `buffalo_s` descarga y ejecuta una inferencia
  real (5 submodelos ONNX, embedding 512D confirmado). `FaceEngine`,
  `FaceQualityAssessor` e `IdentityIndex` construidos y verificados
  (23-01); `backend/recognizer.py` reducido a orquestación sobre ellos,
  `scripts/reenroll.py` para re-enrolamiento real, `dlib`/
  `face-recognition` fuera de requirements.txt (23-02); y **Fase 24
  (Identidad temporal — votación y máquina de estados) completa
  encima (377/377)**: `TemporalVoter`+`IdentityStateMachine` (4 estados,
  6 transiciones), `RecognitionWorker` cableado a la FSM sustituyendo
  el gate ciego de la Fase 23, `EventEngine.emit_identity` (3 eventos
  de identidad), y los 6 criterios de éxito del ROADMAP verificados
  uno a uno con comando `pytest -k` en `24-06-SUMMARY.md` (criterio 6:
  87.5% de reducción de inferencias faciales sobre un track no
  confirmado, umbral exigido ≥70%). FACE-07..FACE-11 cerrados.
  Quedan **12 checkpoints con cámara real** sin ejecutar, ninguno
  bloqueante para seguir programando: 19-01 Task 5 (migrar BD real),
  19-02 Task 5 (validación de reglas en vivo), 20-02 Task 4 (validación
  visual del pre-buffer), 21-01 Task 5 (coste de instrumentación y
  línea base de 30 min), 22-01 Task 4 (resistencia de 8 h),
  23-02 Task 4 (tasa de aciertos ArcFace vs dlib con datos reales),
  25-06 Task 2 (tasa de falsos positivos de ReID con dos personas
  reales — la parte determinista ya está verde, `reid_inherit_identity`
  sigue en `False`), 26-05 Task 3 (calibración de
  `run_speed_px_s`/`loiter_radius_px`/`immobile_radius_px` contra
  cámara real — los defaults de SPEC_v2.md §5.7 ya están cubiertos por
  tests deterministas con trayectorias sintéticas), y 27-11 Task 2
  (calibración de `object_person_radius_px` y tasa de falsos positivos
  de `OBJECT_LEFT` — 150 px ya cubierto por tests deterministas con
  trayectorias sintéticas, `OBJECT_LEFT` sigue en `Severity.WARNING`),
  29-03 Task 3 (checkpoint visual de la vista de operaciones: criterios
  de éxito 1, 4, 5 y 6 del ROADMAP), y 30-12 Task 2 (los cuatro puntos
  del checkpoint visual de la línea temporal que exigen señal de cámara:
  fluidez percibida del scroll con miles de filas, evento nuevo en <1 s
  desde una detección real, "Marcar como persona" sobre un
  `UNKNOWN_PERSON` reciente con recorte y `track_id`, y el ciclo
  silenciar → atenuar → reactivar sobre un grupo con regla activa — el
  resto del checkpoint sí se verificó con navegador y servidor reales,
  ver `30-12-SUMMARY.md`), y 31-11 Task 3 (lo que exige actividad de
  cámara real en la vista de analítica: heatmap con datos genuinos,
  ranking con personas reconocidas de verdad — el resto del checkpoint sí
  se verificó con navegador y servidor reales, incluida una regresión
  real de Chart.js encontrada y corregida en el propio checkpoint, ver
  `31-11-SUMMARY.md`).
  **Fase 28 (Refactor del frontend a módulos ES) planificada** encima:
  9 planes en 5 waves, plan-checker verde — ver `## Siguiente paso` para
  el detalle. Ningún cambio de código todavía, solo planificación.
Last activity: 2026-08-23

Progress v2.0: [███████░░░] ~68% (15/22 fases completas)
Progress v1.2: [██████████] 100% (16/16 fases) — completado 2026-05-01

## Mediciones acumuladas del bloque A y Fase 23

| Medición | Resultado | Fuente |
|----------|-----------|--------|
| CPU antes/después de desacoplar el pipeline (Fase 18) | 587.3% → 568.8% (normalizado, 8 cores) — mejora leve, sin regresión de RAM; YOLO sigue siendo el coste dominante | `18-02-CHECKPOINT.md` |
| Soak de 30 min, cámara real (Fase 17) | FPS estable ~15, 0 reconnects, sin crecimiento de latencia | `17-02-SUMMARY.md` |
| Línea base operativa de métricas (Fase 21, 30 min) | **Pendiente** — mecánica de `/api/v2/metrics` y `/metrics` verificada end-to-end (eventos reales incrementan `events_total`, `e2e_latency_seconds` registra observaciones reales), pero sin cámara real no hay FPS/latencia de producción que promediar | `21-01-SUMMARY.md`, checkpoint 21-01 Task 5 |
| Coste de instrumentación (<2% CPU objetivo) | **Pendiente** — requiere comparar `metrics_enabled=true/false` con carga real | checkpoint 21-01 Task 5 |
| Resistencia de 8 h (RSS, colas, `active_tracks`) | **Pendiente** — `scripts/soak_test.py` escrito y verificado con servidor real (6 s, 3 muestras), ejecución completa de 8 h aún no realizada | `22-01-SUMMARY.md`, checkpoint 22-01 Task 4 |
| Latencia FaceEngine (detect+embed) tras optimizar `allowed_modules` | ~15-40ms/llamada (antes ~250-370ms con los 5 submodelos por defecto de buffalo_s) — medido con imagen real, 10-20x de mejora | `23-01-SUMMARY.md` |
| Tasa de aciertos ArcFace vs dlib (≥50 recortes reales) | **Pendiente** — requiere `data/gallery/` poblada con capturas reales | `23-02-SUMMARY.md`, checkpoint 23-02 Task 4 |

## Siguiente paso

```
/gsd:plan-phase 32
```

La **Fase 31 (Vista de analítica) está completa**: 11/11 planes (`31-01`..`31-11`),
OPS-12..OPS-15 cerrados, suite **675 passed, 2 skipped**. La vista de analítica añade
un segundo tab junto a Operaciones: personas por hora/día con superposición del
periodo anterior, ocupación por zona, heatmap acumulado con leyenda relativa, ranking
de personas con tendencia y export CSV/JSON del rango visible, con las cuatro
peticiones de cada tanda en paralelo (D-08/D-09) y las agregaciones siempre resueltas
en SQL —`TEST_analytics_no_client_aggregation` lo fija como test permanente, no como
promesa del plan (D-07)—. El checkpoint visual de `31-11` Task 3 encontró y corrigió
una regresión real: abrir `#analitica` directamente en la URL dejaba las gráficas
ancladas al tamaño de reserva de Chart.js (300×150) porque `createCharts()` se
ejecutaba en el mismo tick síncrono que revelar el contenedor, antes de que el
navegador confirmara el layout; corregido diferiendo esa primera llamada con
`requestAnimationFrame` en `nav.js`. Lo que exige actividad de cámara real (heatmap
con datos genuinos, ranking con personas reconocidas) queda diferido como **12º
checkpoint manual**, no bloqueante.

La Fase 32 (Vista de cámara y configuración visual, OPS-16..OPS-20 y SET-01..SET-04:
operar y configurar el sistema sin tocar `.env`) es la siguiente y **no está
planificada todavía** — ya cuenta con un borrador de `32-UI-SPEC.md` preparado en
paralelo en la rama `feature/fase-31-32-design`, pendiente de planificación formal.

Las Fases 28 (Refactor del frontend a módulos ES), 29 (Vista de operaciones) y 30
(Event Timeline y centro de alertas) están **completas en código** y aportan cada una
un checkpoint manual pendiente —paridad funcional y carga en LAN la 28, verificación
visual de los criterios 1/4/5/6 la 29, y los cuatro puntos que exigen cámara real de
30-12 Task 2 la 30—, ninguno bloqueante.

La Fase 27 (Multi-clase y contexto de escena) está **completa**: 11/11
planes (`27-01`..`27-11`), BEH-06..BEH-09 cerrados, suite 519/519.
`ObjectAnalyzer` (dominio puro), `ObjectTracker` con partición por clase
antes de `sv.ByteTrack` (class-agnostic — cierra el riesgo de que un
`tracker_id` migre entre persona y objeto), `DetectionStatRepo.hourly_baseline()`
(media móvil por franja horaria), `EventEngine.emit_object()`/`config_changed()`,
cableado completo en `DetectionWorker`/`manager.py` (construcción fuera de la
factoría, cuarto precedente tras FSM/ReID/BehaviorAnalyzer), router
`GET/PUT /api/v2/detection/classes` con persistencia en `app_config` (gana
sobre `YOLO_CLASSES`), overlay de objetos en magenta en el feed MJPEG,
`GET /api/v2/analytics/context` (hora, zona, personas totales/conocidas/
desconocidas, nivel de actividad contra la media móvil de 7 días) y el
panel "Clases detectadas" en el dashboard. `27-11` (puerta de fase) trazó
los 6 criterios del ROADMAP a comandos `pytest -k` que pasan sin tocar
código (ver `27-11-SUMMARY.md`); el checkpoint de calibración de
`object_person_radius_px` y de la tasa de falsos positivos de `OBJECT_LEFT`
con cámara real se **difiere** explícitamente (9º checkpoint manual, mismo
patrón que los 8 anteriores) — no bloquea el avance a la Fase 28.

La Fase 24 (Identidad temporal — votación y máquina de estados) está
**completa**: 6/6 planes (`24-01`..`24-06`), FACE-07..FACE-11 cerrados,
suite 377/377. `IdentityStateMachine`/`TemporalVoter` (4 estados: UNKNOWN →
CANDIDATE → CONFIRMED → TEMPORARILY_LOST) cableados de extremo a extremo
en `RecognitionWorker`, con los 6 criterios de éxito del ROADMAP
verificados uno a uno (`24-06-SUMMARY.md`). El research corrigió
la lista de ficheros de `SPEC_v2.md` §9 (el fichero real no es
`perception/face/engine.py` sino `pipeline/recognition.py` +
`pipeline/manager.py`), y el plan-checker encontró y se corrigió un bug
real: `_sync_identity` dependía del TTL de 30 s de `TrackRegistry.active_ids()`
para detectar tracks perdidos, lo que habría producido un segundo
`PERSON_RECOGNIZED` al recuperar una identidad con un `track_id` nuevo
dentro de ese TTL — corregido con `TrackRegistry.frame_ids()`, publicado
por `DetectionWorker` en cada frame.

La Fase 25 (Re-identificación de personas, ReID) — depende de la Fase 24
(ya completa) — está **completa** (6/6 planes, 25-01..25-06):
`.planning/phases/25-re-identificaci-n-de-personas-reid/` tiene CONTEXT,
RESEARCH, PATTERNS, VALIDATION y 6 PLAN.md (5 waves), verificados por
`gsd-plan-checker` sin blockers. `25-01` ya
está completo: `scripts/fetch_models.py` descargó el ONNX de OSNet
(`kornia/osnet`, sha256 `e78604f4...` verificado) y reescribió el eje de
batch fijo (16) a dinámico (grafo bit-idéntico, idempotente), y
`ReIDEngine` produce embeddings 512D L2-normalizados en ~5-12 ms p50 en
CPU (criterio 1 del ROADMAP cumplido), degradando con `available=False`
sin modelo o con batch fijo != 1. REID-01 cerrado — ver `25-01-SUMMARY.md`.
`25-02` también está completo: `IdentityStateMachine.on_reid_result()`
(método aditivo, justo después de `on_face_result`) reutiliza
`_claim_lost()` para heredar una identidad `TEMPORARILY_LOST` por
apariencia, sin votar en `TemporalVoter` y con `emits=False` (misma
visita, sin segundo `PERSON_RECOGNIZED`); fija `last_face_at = now` al
heredar para que el barrido de rancios de `on_tick` no purgue el estado
recién heredado (Pitfall 5) y evita el `IDENTITY_LOST` espurio que
producía resolver la herencia fuera de la FSM (Pitfall 4). 7 tests
`TEST_reid*` verdes, suite completa 388/388. REID-02 y REID-03 cerrados
— ver `25-02-SUMMARY.md`. `25-03` también está completo: `TrackGallery`
(`backend/perception/reid/gallery.py`) implementa las 4 reglas de
`resolve()` (candidatos con identidad de otro track, frescura dentro de
la ventana de 15 s, similitud máxima por coseno directo, umbral
estricto + comprobación de conflicto contra `active_identities`),
devolviendo siempre `(candidato, similitud)` reales — la política de si
aplicar la herencia queda para `25-04`. `needs_embedding()` implementa
el gate del criterio 5 y `prune()`/`_enforce_cap()` replican la doble
guarda TTL + cota dura de `IdentityStateMachine`. 12 tests con vectores
512D de coseno exacto construidos a mano (nunca `np.random`: el research
midió coseno 0,991 entre dos ruidos independientes con OSNet real) más
2 tests de cota de memoria (con y sin `prune()`). Suite completa
402/402. REID-04 cerrado (REID-02 ya cerrado en 25-02) — ver
`25-03-SUMMARY.md`. `25-04` también está completo: la vía ReID queda
cableada dentro de `RecognitionWorker` — `_loop` extrae `_face_pass`/
`_reid_pass`, ambas corren cada tick sin bloquearse mutuamente (persona
de espaldas: `needs_recognition()` dice que no, `_next_reid_candidate`
dice que sí); `_next_reid_candidate` gatea sobre
`TrackGallery.needs_embedding()` (criterio 5), nunca sobre
`needs_recognition()`; el flag `reid_inherit` vive en el worker, no en
`TrackGallery` (`resolve()` siempre calcula el candidato real, el flag
decide si se aplica vía `on_reid_result()` o solo se audita — criterio
4); 4 contadores `reid_*` en `stats`, canal de auditoría sin endpoints
nuevos; `self._rate.observe()` nunca se llama desde la vía ReID
(instrumentación separada con `stage="reid"`). Durante el test
end-to-end del criterio 3 se encontró y corrigió un bug real:
`_next_reid_candidate` re-seleccionaba tracks fuera de `frame_ids()`
(`TEMPORARILY_LOST` aún no podados por `DetectionWorker`), y
`gallery.update()` les escribía `identity_of()==None`, borrando en la
galería la identidad que ReID necesita conservar para que otro track la
reclame después — corregido con un filtro `track_id in frame_ids()`.
Suite completa 407/407 (402 previos + 5 nuevos, incluido el end-to-end
del criterio 3 verificado 3/3 sin flaky). REID-01..REID-04 ya estaban
cerrados por los planes previos; `25-04` los cablea de extremo a
extremo — ver `25-04-SUMMARY.md`. `25-05` también está completo: 7
parámetros `reid_*` en `backend/config.py` (defaults locked de
SPEC_v2.md §5.6, `reid_inherit_identity=False` como fail-safe) con
`validate_reid_model_path` (extensión + contención en `_PROJECT_ROOT`,
SEC-16) y `validate_reid_params` (rangos, T-25-18); `CameraPipeline`
construye `ReIDEngine`/`TrackGallery` FUERA de `_make_recognition`,
junto a la FSM, para que un reinicio del worker no vacíe la galería ni
recargue el ONNX; `backend/main.py` propaga los 7 settings con mapeo
explícito (`reid_inherit_window <- reid_inherit_window_secs`,
`reid_inherit <- reid_inherit_identity`, etc.), verificado que la app
importa igual con y sin el modelo ONNX presente (degradación graciosa,
T-25-19). 6 tests nuevos (4 en `test_config.py`, 2 en
`test_recognition_worker.py`). Suite completa 413/413 — ver
`25-05-SUMMARY.md`. `25-06` (puerta de fase) también está completo: la
suite completa se reejecutó verde (413/413, sin skips en
`test_reid_engine.py`, sin cambios de código) y los 5 criterios de éxito
del ROADMAP quedaron trazados a comandos `pytest -k` que pasan
(`25-06-SUMMARY.md`), con la latencia p50 de `embed()` remedida en esta
máquina (~11,9 ms, criterio 1). REID-01..REID-04 ya estaban cerrados
desde `25-01`/`25-02`/`25-03`. El checkpoint manual del criterio 4 (tasa
de falsos positivos con dos personas reales) se **difiere**: sin acceso
a cámara en esta sesión, la parte determinista ya está verde y
`reid_inherit_identity=False` sigue siendo el default seguro — no
bloquea avanzar a la Fase 26. **Fase 25 completa: 6/6 planes.**

La Fase 26 (Análisis de comportamiento) — depende de la Fase 25 (ya
completa) — está **completa** (5/5 planes, 26-01..26-05):
`BehaviorAnalyzer` (dominio puro, `26-01`) emite `BehaviorFinding` para
LOITERING, RUNNING, IMMOBILE y CROWD_DETECTED con agregados O(1) y
latch por episodio en los cuatro comportamientos; 10 umbrales
configurables en `config.py` (`26-02`); `EventEngine.emit_behavior()` +
`duration_s` en `ZONE_EXITED` (`26-03`); cableado completo en
`DetectionWorker`/`manager.py`/`main.py` (`26-04`). `26-05` (puerta de
fase) cerró el criterio 5: 3 tests nuevos en `tests/test_rule_engine.py`
prueban el camino real (YAML en `tmp_path` + `load_rules` + `evaluate`)
para los cuatro eventos de comportamiento como `when.event`, incluida
la prueba de regresión explícita del pitfall de naming (`duration`
en vez de `duration_s` no dispara la regla) — sin tocar
`backend/events/rules.py` ni `config/rules.yaml`. Suite completa
454/454. Los 5 criterios de éxito del ROADMAP quedaron trazados a
comandos `pytest -k` que pasan (`26-05-SUMMARY.md`); el criterio 2 (seis
trayectorias) se reparte entre los 4 tests de comportamiento de `26-01`
y los tests ya existentes de `EventEngine.process_zone` (2 trayectorias
de zona, propiedad de la Fase 19) — no es un hueco. BEH-01..BEH-05 ya
estaban `[x]` desde planes anteriores, confirmado. El checkpoint de
calibración de umbrales con cámara real (`run_speed_px_s`,
`loiter_radius_px`, `immobile_radius_px`) se **difiere** explícitamente
(8º checkpoint manual, sin cámara en esta sesión) — no bloquea avanzar
a la Fase 27 porque los defaults de SPEC_v2.md §5.7 ya están cubiertos
por tests deterministas con trayectorias sintéticas. **Fase 26 completa:
5/5 planes.**

La Fase 27 (Multi-clase y contexto de escena) — depende de la Fase 26
(ya completa) — está **completa** (11/11 planes, 27-01..27-11): ver el
detalle completo de cada plan en "Siguiente paso" arriba y en
`27-11-SUMMARY.md`. `27-11` (puerta de fase) reejecutó la suite completa
verde (519/519, sin cambios de código) y trazó los 6 criterios de éxito
del ROADMAP a comandos `pytest -k` que pasan, más la regresión ByteTrack
(`TEST_object_class_does_not_reach_line_zone`, `TEST_objects_not_in_registry`,
`TEST_bytetrack_ids_do_not_migrate_between_classes`). BEH-06, BEH-08 y
BEH-09 se marcan `[x]` en `REQUIREMENTS.md` (BEH-07 ya lo estaba desde
`27-01`). El checkpoint de calibración de `object_person_radius_px` y de
la tasa de falsos positivos de `OBJECT_LEFT` con cámara real se **difiere**
explícitamente (9º checkpoint manual, sin cámara en esta sesión) — no
bloquea avanzar a la Fase 28 porque los criterios deterministas ya están
verdes con trayectorias sintéticas y `objects_enabled=False`/
`UPLOAD_MIN_SEVERITY=critical` quedan como válvulas de escape sin tocar
código. **Fase 27 completa: 11/11 planes.**

Nota histórica — la Fase 23 (ya cerrada) abrió con una **puerta
bloqueante** (verificar que `insightface` + `onnxruntime` instalan y
ejecutan una inferencia real en Windows, con plan B en `SPEC_v2.md`
ADR-02 si no instalaban) que se resolvió con evidencia real antes de
planificar el resto de la fase — ver `23-CONTEXT.md`.

Los 9 checkpoints pendientes (bloque A + Fase 23 + Fase 25 + Fase 26 +
Fase 27) pueden ejecutarse en cualquier momento que haya acceso a la
cámara real; ninguno bloquea el avance a la Fase 28, pero sí deberían
cerrarse antes de dar el bloque A, la Fase 23, la Fase 25, la Fase 26 y
la Fase 27 por completamente validados en producción.

## Pendiente sin relacion con v2.0

- Token OAuth de Google Drive caducado (`data/token.json`, `invalid_grant`).
  Requiere rehacer el flujo de autorizacion manualmente.

## Documentos del milestone v2.0

| Documento | Contenido |
|-----------|-----------|
| `propuesta_mejora/SPEC_v2.md` | Referencia técnica: arquitectura objetivo, 10 ADRs, contratos de módulo, modelo de datos, catálogo de eventos, ficheros/riesgo por fase, trazabilidad de los 25 puntos, riesgos y criterios de aceptación del milestone |
| `.planning/ROADMAP.md` § v2.0 | Fases 17-38 con goal, dependencias, requisitos y criterios de éxito |
| `.planning/STATE.md` (este) | Estado real de las 22 fases — qué está completo, qué falta y por qué |
| `.planning/REQUIREMENTS.md` § v2 | 107 requisitos (PIPE, DET, EVT, RULE, DB, CLIP, OBS, SEC, FACE, REID, BEH, OPS, SET, TEST, SCALE) |
| `propuesta_mejora/mejoras_inmediatas.md` | Propuesta original (25 puntos) |
| `propuesta_mejora/vulnerabilidades.md` | Análisis de seguridad (12/14 ya corregidas en v1.2) |

## Estado de las 22 fases de v2.0

Fuente única de verdad sobre qué queda por hacer — sustituye a la extinta
tabla "Progress Tracking v2.0" de `ROADMAP.md` (quedaba desactualizada por
duplicación). Para el detalle de cada fase (goal, dependencias, requisitos,
criterios de éxito) ver `ROADMAP.md` § Phase Details v2.0; para ficheros y
riesgos de las fases aún no planificadas, `SPEC_v2.md` §9.

| Fase | Bloque | Estado | Cerrada | Pendiente |
|------|--------|--------|---------|-----------|
| 17 — Frame Broker y Capture Worker | A | ✓ Completa | 2026-08-07 | — (checkpoint superado) |
| 18 — Workers desacoplados | A | ✓ Completa | 2026-08-08 | — (checkpoint superado) |
| 19 — Event Engine y esquema v2 | A | ✓ Completa (código) | 2026-08-09 | ⧗ Migración BD real + validación de reglas en vivo |
| 20 — Pre/post-buffer | A | ✓ Completa (código) | 2026-08-09 | ⧗ Verificación visual del pre-buffer + prueba sin red |
| 21 — Observabilidad | A | ✓ Completa (código) | 2026-08-09 | ⧗ Coste de instrumentación + línea base de 30 min |
| 22 — Seguridad y memoria | A | ✓ Completa (código) | 2026-08-09 | ⧗ Prueba de resistencia de 8 h |
| 23 — InsightFace/ArcFace | B | ✓ Completa (código) | 2026-08-10 | ⧗ Tasa de aciertos ArcFace vs dlib con datos reales |
| 24 — Identidad temporal | B | ✓ Completa | 2026-08-13 | — (sin checkpoints manuales; 6 checkpoints de cámara real de fases anteriores siguen abiertos, sin relación con esta fase) |
| 25 — Re-identificación (ReID) | B | ✓ Completa (código) | 2026-08-15 | ⧗ Tasa de falsos positivos con dos personas reales (checkpoint 25-06 Task 2) |
| 26 — Análisis de comportamiento | B | ✓ Completa (código) | 2026-08-16 | ⧗ Calibración de umbrales con cámara real (checkpoint 26-05 Task 3) |
| 27 — Multi-clase y contexto de escena | B | ✓ Completa (código) | 2026-08-17 | ⧗ Calibración de `object_person_radius_px` y tasa de falsos positivos (checkpoint 27-11 Task 2) |
| 28 — Frontend a módulos ES | C | ✓ Completa (código) | 2026-08-20 | ⧗ Checklist de paridad funcional + medición de carga en LAN (28-09) |
| 29 — Vista de operaciones | C | ✓ Completa (código) | 2026-08-20 | ⧗ Checkpoint visual Task 3 de 29-03 (criterios éxito 1/4/5/6 del ROADMAP) |
| 30 — Event Timeline y alertas | C | ✓ Completa (código) | 2026-08-21 | ⧗ Cuatro puntos del checkpoint visual 30-12 Task 2 que exigen cámara real (criterios 3, 4 y 5 del ROADMAP y el ciclo completo de silenciado) |
| 31 — Vista de analítica | C | ✓ Completa | 2026-08-23 | ⧗ Lo que exige actividad de cámara real (heatmap con datos genuinos, ranking con personas reconocidas) — 12º checkpoint manual |
| 32 — Vista de cámara y config visual | C | — Sin planificar | — | Depende de 31 |
| 33 — Editores visuales | C | — Sin planificar | — | Depende de 32 |
| 34 — Tests E2E | C | — Sin planificar | — | Depende de 33 |
| 35 — CameraManager | D | — Sin planificar | — | Depende de 34 |
| 36 — Multi-cámara en runtime | D | — Sin planificar | — | Depende de 35 |
| 37 — PostgreSQL y Redis | D | — Sin planificar | — | Depende de 36 |
| 38 — Worker GPU (opcional) | D | — Sin planificar | — | Depende de 37 |

Las fases sin planificar (24-38) no tienen PLAN todavía. Generarlos con
`/gsd:plan-phase <N>` cuando llegue el momento, o pedirlos en Cowork como
se hizo con el bloque A y la Fase 23.

## Notas de ejecución

- **Puerta bloqueante en la Fase 23:** verificar que `insightface` + `onnxruntime` instalan en el entorno Windows del proyecto antes de comprometer el bloque B. Plan B documentado en `SPEC_v2.md` ADR-02.
- **Migración de embeddings:** ArcFace 512D no es compatible con dlib 128D. La Fase 23 exige re-enrolamiento desde `data/gallery/`.
- **Fase 28 (frontend) solo depende de la 21**, así que el bloque C puede solaparse con el B si interesa.

## Phases Summary

| Phase | Descripción | Estado | Fecha |
|-------|-------------|--------|-------|
| 1 | Scaffolding y entorno | ✓ Complete | 2026-04-16 |
| 2 | Captura RTSP y stream MJPEG | ✓ Complete | 2026-04-17 |
| 3 | Detección de personas YOLO26n | ✓ Complete | 2026-04-17 |
| 4 | Tracking y conteo por línea virtual | ✓ Complete | 2026-04-17 |
| 5 | Persistencia en SQLite | ✓ Complete | 2026-04-18 |
| 6 | API REST y WebSocket | ✓ Complete | 2026-04-18 |
| 7 | Dashboard web | ✓ Complete | 2026-04-18 |
| 8 | Configuración centralizada | ✓ Complete | 2026-04-16 |
| 9 | Reconocimiento facial y enrolamiento | ✓ Complete | 2026-04-19 |
| 10 | Grabación de video y upload Google Drive | ✓ Complete | 2026-04-19 |
| 11 | Rendimiento y estabilidad | ✓ Complete | 2026-04-23 |
| 12 | Alertas y notificaciones | ✓ Complete | 2026-04-26 |
| 13 | Detección avanzada e historial | ✓ Complete | 2026-04-25 |
| 14 | Seguridad | ✓ Complete | 2026-04-23 |
| 15 | UI y exportación | ✓ Complete | 2026-04-26 |
| 16 | Operaciones | ✓ Complete | 2026-05-01 |

## Test Coverage

Suite completa: **675 passed, 2 skipped** (última ejecución 2026-08-23 tras `31-11`,
puerta de la Fase 31: +68 sobre la Fase 30, entre ellos `TEST_analytics_no_client_aggregation`
—barrido literal de `.reduce(`/`.sort(`/`.filter(`/`Math.max(`/`Math.min(` sobre los seis
módulos de la vista de analítica, OPS-14/D-07— y `LOCKED_JS` ampliado con esos mismos seis
módulos. `tests/test_frontend_modules.py` verificado de nuevo tras el fix de `nav.js` del
checkpoint de Task 3 (9 passed, sin regresión). Cifra anterior **607 passed, 2 skipped**
(tras `30-12`, puerta de la Fase 30: +4 tests de rendimiento en `tests/test_repositories.py`
que miden el criterio 3 con 10.000 eventos sembrados por `scripts/seed_events.py` — primera
página, página 100 por cursor, filtro multi-tipo y existencia de `idx_events_ts_id` —, todos
por debajo del presupuesto de 100 ms; `test_architecture.py`, `test_security_regression.py` y
`test_rule_engine.py` verdes, este último sin un solo commit en toda la fase. Cifra
anterior **570/570** (tras `30-04`:
+15 tests — 11 en `tests/test_snapshots.py` (recorte real en disco, `bbox=None`, deshabilitado,
throttle por track, `to_thread`, clamp de coordenadas desbordadas, purga por directorio de día,
traducción de URL, hook antes del `INSERT` sobre `EventRepo` real, supervivencia al fallo del
hook y presencia del mount) y 4 en `tests/test_config.py` (defaults, ruta fuera del proyecto,
traversal y rangos numéricos) — ver `30-04-SUMMARY.md`. Cifra anterior
**555/555** (tras `30-03`:
+12 tests en `tests/test_repositories.py` — 5 de `track_scope` (bloque contiguo, corte por
hueco, track homónimo a 48 h, cota por `camera_id`, `None` sin `track_id`), 4 de
`assign_person` (solo el bloque contiguo, downgrade de `UNKNOWN_PERSON`, `updated=0` sin
track, homónimo intacto) y 3 de `by_trigger_event_ids` (mapeo, lista vacía sin consulta,
gana el clip más reciente) — ver `30-03-SUMMARY.md`. Cifra anterior
**543/543** (tras `30-02`:
+9 tests — 3 en `tests/test_migrations.py` (índice de la línea temporal creado por la
migración v2→v3, idempotencia y presencia en una base nueva) y 6 en
`tests/test_repositories.py` (multi-tipo, enum suelto compatible, filtro por regla,
no interpolación del filtro con carga `' OR 1=1 --`, `count()` con los mismos filtros y
plan de consulta sin `TEMP B-TREE FOR ORDER BY`) — ver `30-02-SUMMARY.md`. Cifra anterior
534/534 tras `30-01`. Histórico previo: **519/519 passing** (última ejecución 2026-08-17, tras `27-09`: +7 tests
`TEST_*` en `tests/test_scene_context.py` — 5 sobre `_person_counts`/`_classify_activity`
puras (`TEST_known_requires_confirmed`, `TEST_person_counts_uses_frame_ids_not_active_ids`,
`TEST_insufficient_history`, `TEST_partial_hour_normalised`, `TEST_activity_ratio_thresholds`)
y 2 de integracion ASGI (`TEST_context_shape`, `TEST_context_never_leaks_person_identity`) —
ver `27-09-SUMMARY.md`). Cifra anterior 512/512 (tras `27-08`: +4 tests
`TEST_*` — 3 en `tests/test_streaming_worker.py` (`TEST_object_overlay_drawn_when_boxes_present`,
`TEST_no_object_overlay_when_provider_returns_empty`, `TEST_streaming_worker_without_object_boxes_provider`,
todos sobre `_annotate` en aislamiento, sin hilo ni broker) y 1 en `tests/test_detection_worker.py`
(`TEST_streaming_factory_wires_object_boxes_provider`, identidad de referencia del `Callable`
cableado por `_make_streaming`) — ver `27-08-SUMMARY.md`). Cifra anterior 508/508 (tras `27-07`: +8 tests
`TEST_*` en `tests/test_detection_config_api.py` — `TEST_get_classes_returns_active_and_catalog`,
los 4 rechazos `TEST_rejects_*` con aserciones sobre `detail` (no solo el codigo 400),
`TEST_put_persists_propagates_and_emits`, `TEST_put_persists_before_propagating` (orden via
`MagicMock.attach_mock`) y `TEST_empty_persisted_row_is_treated_as_absent` (prueba directa de
`main._resolve_active_classes`) — ver `27-07-SUMMARY.md`). Cifra anterior 500/500 (tras `27-06`: +8 tests
`TEST_*` en `tests/test_detection_worker.py` — `TEST_object_left_emitted_from_worker`
(emision real de `OBJECT_LEFT` con reloj inyectado), `TEST_object_analysis_failure_does_not_kill_thread`,
`TEST_object_prune_findings_are_emitted` (protege el retorno de `prune()`),
`TEST_excluded_zone_suppresses_object_candidate`, `TEST_object_analyzer_survives_worker_restart`,
`TEST_object_tracker_survives_worker_restart`, `TEST_objects_disabled_leaves_pipeline_without_analyzer`
y `TEST_set_object_detection_classes_does_not_restart_worker` — ver `27-06-SUMMARY.md`). Cifra anterior
492/492 (última ejecución 2026-08-17, tras `27-05`: +5 tests
`TEST_*` en `tests/test_event_engine.py` — `TEST_emit_object_translates_both_kinds`,
`TEST_emit_object_payload_carries_magnitudes` (`duration_s`/`class_name` presentes,
`person_distance_px` ausente al ser `None`), `TEST_emit_object_severity_comes_from_catalog`
(`OBJECT_LEFT` en `Severity.WARNING`, `OBJECT_REMOVED` en `Severity.INFO`, sin que
`emit_object` pase `severity=`), `TEST_emit_object_carries_bbox_as_first_class_field` y
`TEST_config_changed_is_emitted_with_detail` — ver `27-05-SUMMARY.md`). Cifra anterior
487/487 (última ejecución 2026-08-17, tras `27-04`: +7 tests
`TEST_*` en `tests/test_repositories.py`/`tests/test_database.py` — 5 de
`DetectionStatRepo.hourly_baseline()` (orden de agregacion con datos repartidos en varios
minutos, `sample_days` con un solo dia, `until` excluyendo la hora en curso, aislamiento por
`camera_id`, ventana vacia sin excepcion), `TEST_config_repo_roundtrip_list` (roundtrip de
`list[int]` en la columna JSON de `app_config`, overwrite y default) y
`TEST_get_zones_returns_kind` (zona con `kind="exclude_objects"` y zona con `kind=None`,
ambas expuestas por `get_zones()` del ORM legacy) — ver `27-04-SUMMARY.md`. Cifra anterior
480/480 (última ejecución 2026-08-17, tras `27-03`: +7 tests
`TEST_*` en `tests/test_detection_worker.py` — regresion del riesgo ByteTrack
class-agnostic: `TEST_bytetrack_ids_do_not_migrate_between_classes` reproduce
literalmente el hallazgo del research con un `sv.ByteTrack` compartido y demuestra
que con la particion por clase (`ObjectTracker` + `PersonTracker` separados) no
ocurre; mas `TEST_object_class_does_not_reach_line_zone` (igualdad de `get_counts()`
con/sin coche), `TEST_objects_not_in_registry`, `TEST_split_by_class_preserves_class_name`,
`TEST_sync_frame_rate_reaches_both_trackers`, `TEST_no_object_classes_behaves_like_today`
y `TEST_object_boxes_snapshot_is_a_copy` — ver `27-03-SUMMARY.md`). Cifra anterior
473/473 (última ejecución 2026-08-17, tras `27-02`: +5 tests
`TEST_*` — 3 en `tests/test_config.py` (`TEST_yolo_model_default_is_yolo26n`,
`TEST_object_defaults_match_research` con un assert por cada uno de los 10 `object_*` y
4 `context_*`, `TEST_object_params_reject_impossible_values` con caso propio para
`object_class_ids=[0, 24]`) + 2 en `tests/test_detector.py`
(`TEST_set_classes_changes_next_inference`, y `TEST_multiclass_latency_under_15_percent`
que mide con pesos reales de `yolo26n.pt` sobre `bus.jpg` a 1280x720: p50 con 1 clase vs
6 clases, criterio 6 del ROADMAP con margen — sin skip, `bus.jpg` presente en
`ultralytics/assets`). Cifra anterior 468/468 (tras `27-01`: +11 tests
`TEST_*` en `tests/test_object_analyzer.py` (nuevo fichero: los 9 comportamientos de BEH-07
— `OBJECT_LEFT` tras umbral, latch por episodio, igualdad de conjunto, supresion por
persona cercana, guardas de warmup y zona de exclusion, `OBJECT_REMOVED` con/sin persona,
gracia de oclusion, payload sin `None`) + 3 tests `TEST_object_analyzer_*` en
`tests/test_memory_bounds.py` (doble guarda TTL+LRU con y sin `prune()`, incluida `_ignored`)
— ver `27-01-SUMMARY.md`). Cifra anterior 454/454 (última ejecución 2026-08-16, tras `26-05`: +3 tests `TEST_behavior_*` en `tests/test_rule_engine.py` — carga de las 4 reglas de comportamiento desde YAML real vía `load_rules`, `duration_gte` leyendo `duration_s` con prueba negativa explícita del nombre equivocado, y filtro `zone` sobre `zone_id` de primer nivel — sin cambios en `backend/events/rules.py` ni `config/rules.yaml`, ver `26-05-SUMMARY.md`). Cifra anterior 451/451 (tras `26-04`: +11 tests `TEST_behavior_*` en `tests/test_detection_worker.py` — 4 de cableado de `_analyze_behavior`/`_zone_membership_snapshot` (CROWD_DETECTED real, ausencia de `behavior`, fallo aislado, reutilización de `st["inside"]`) + 3 de supervivencia/desactivación/umbrales vía `CameraPipeline` (mismo molde que `TEST_fsm_survives_worker_restart` de la Fase 24) — sin cambios en `backend/perception/behavior.py` ni `backend/events/engine.py`, ver `26-04-SUMMARY.md`). Cifra anterior 444/444 (tras `26-03`: +7 tests — 3 `TEST_emit_behavior_*` y 3 `TEST_zone_dwell_*` en `tests/test_event_engine.py` (traducción de los 4 `BehaviorKind`, magnitudes en payload, severidad INFO por defecto, `duration_s` en `ZONE_EXITED` con/sin reloj monotónico) + 1 `TEST_zone_entry_at_bounded` en `tests/test_memory_bounds.py` (10.000 entradas/salidas efímeras en dos zonas, ambos dicts quedan vacíos)). Cifra anterior 437/437 (tras `26-02`: +3 tests `TEST_behavior_*` en `tests/test_config.py` — defaults de los 10 parámetros `behavior_*`, positividad de umbrales, y cota de `run_window_secs <= 12.0`). Cifra anterior 434/434 (tras `26-01`: +21 tests — 19 `TEST_*` nuevos en `tests/test_behavior_analyzer.py` (las 4 reglas de `BehaviorAnalyzer`, sus latches, el payload de magnitudes y 4 tests de trayectoria con igualdad de conjunto para el criterio 2 del ROADMAP) + 2 tests de cota en `tests/test_memory_bounds.py` (`TEST_behavior_state_bounded`/`..._without_prune`)). Cifra anterior 413/413 (última ejecución 2026-08-15, tras `25-06`: sin cambios de código, puerta de fase pura — misma cifra que tras `25-05`: +6 tests — 4 `TEST_reid_*` en `tests/test_config.py` (defaults, umbral fuera de rango, parámetros temporales/cota, extensión+traversal del modelo) y 2 en `tests/test_recognition_worker.py` (supervivencia de motor/galería a reinicio de worker, `reid_enabled=False`)). Cifra anterior 407/407 tras `25-04` (+5 tests `TEST_*` en `tests/test_recognition_worker.py` — presupuesto de inferencias criterio 5, modo solo-observación criterio 4, contadores en `stats`, compatibilidad sin ReID, y el end-to-end del criterio 3). Cifra anterior 402/402 tras `25-03` (+12 tests `TEST_*` en `tests/test_track_gallery.py` (nuevo fichero, `TrackGallery` con vectores 512D de coseno exacto) + 2 tests de cota en `tests/test_memory_bounds.py`. Cifra anterior 388/388 tras `25-02` (+7 tests `TEST_reid*` en `tests/test_identity_state_machine.py` — herencia, no-voto, no-secuestro, no-interferencia, ausencia de identidad perdida, `IDENTITY_LOST` espurio y barrido de rancios). 381/381 tras `25-01` (+4 tests en `tests/test_reid_engine.py`); 377/377 verificada en `24-06`).
La tabla por módulo de v1.2 (38 tests) quedó obsoleta al crecer la suite en v2.0 —
ver `pytest tests/ -v` para el desglose actual por fichero.

## Accumulated Context

### Decisions

- YOLO26n en lugar de YOLOv8n (31% más rápido en CPU, misma API)
- supervision (ByteTrack + LineZone) para tracking y conteo
- aiosqlite + SQLAlchemy 2.0 async para persistencia
- pydantic-settings para configuración centralizada
- face-recognition/dlib HOG para reconocimiento facial (sin GPU)
- mp4v fourcc para VideoWriter en Windows (más fiable que H.264)
- asyncio.run_coroutine_threadsafe para bridge thread→async en recorder/uploader
- Degradación elegante sin credentials.json (Drive upload deshabilitado, resto funciona)
- psutil para métricas de salud (CPU/RAM) sin dependencias extra
- Rotación diaria con tarea async (`_purge_loop`) usando `asyncio.sleep(24*3600)`
- Docker Compose con volúmenes para `data/`, `certs/` y `.env`
- TemporalVoter (Fase 24): confianza agregada = media de scores del ganador (no el máximo) y el ratio de veredicto se calcula sobre el total de votos de la ventana (incluidos los `None`), para que identidades alternadas no confirmen ninguna
- IdentityStateMachine (Fase 24, 24-02): `_claim_lost` (herencia de identidad por `person_id`) se consulta también desde la rama UNKNOWN, no solo CANDIDATE — un track nuevo con un primer match ya intenta heredar una identidad `TEMPORARILY_LOST` antes de pasar por votación completa (Pitfall 3 del RESEARCH, FACE-09/FACE-10)
- IdentityStateMachine (Fase 24, 24-02): el reset del contador de fallos de revalidación exige coincidencia del frame actual (`person_id == st.person_id`), no el veredicto agregado del voter — necesario porque `needs_recognition()` espacia las inferencias ~120 s y el voter retiene votos históricos varios ciclos
- PersonRecognizer (Fase 24, 24-03): retirada por completo la votación interna por mayoría (`_votes`/`VOTE_WINDOW=5`) — mantenerla habría encadenado dos votaciones delante de `TemporalVoter`, invalidando sus parámetros configurados; el match ahora es por frame y `process_crop_scored()` expone el score real para que la agregación temporal viva solo en `TemporalVoter`/`IdentityStateMachine`
- EventEngine.emit_identity (Fase 24, 24-04): nunca pasa `severity=` explícita, para que `UNKNOWN_PERSON` conserve el `WARNING` por defecto del catálogo (`_apply_default_severity` solo actúa si `severity` no está en `model_fields_set`); las transiciones intermedias (destino `CANDIDATE`/`TEMPORARILY_LOST`) no generan evento — la UI las lee directamente del `TrackRegistry`
- RecognitionWorker/TrackRegistry (Fase 24, 24-05, D-05 bloqueante): `_sync_identity` detecta tracks perdidos con `TrackRegistry.frame_ids()` (el set exacto de tracks del frame actual, escrito por `DetectionWorker`), nunca con `active_ids()` (TTL de 30s de `prune()`) — con `active_ids()`, un track recuperado con un `track_id` nuevo dentro del TTL habría confirmado como visita nueva en vez de heredar la identidad (segundo `PERSON_RECOGNIZED`, rompe FACE-10). `set_frame_ids()` se publica ANTES de la guarda `if event_engine is None` en `_emit_track_lifecycle`, porque la construcción por defecto de `DetectionWorker` no lleva `event_engine`
- IdentityStateMachine en manager.py (Fase 24, 24-05): se construye FUERA de la factoría `_make_recognition` que registra el `WorkerSupervisor`, para que un reinicio del worker no pierda la identidad ya confirmada — mismo motivo por el que `_make_streaming` rescata `clients`
- Criterio 6 (Fase 24, 24-05, D-01): medido sobre un track NO confirmado (persona estática cuyo reconocimiento nunca tiene éxito), no sobre uno ya identificado — con baseline real medido en la misma ejecución del test (16 inferencias/s sin FSM → 2 con FSM, 87.5% de reducción, umbral exigido ≥70%)
- Puerta de fase (Fase 24, 24-06): la suite ya estaba verde (377/377) y FACE-07..FACE-11 ya marcados desde 24-01/24-02 al cierre de `24-05` — `24-06` no requirió ningún fix de código, solo trazabilidad criterio→comando→test en `24-06-SUMMARY.md`
- ReIDEngine (Fase 25, 25-01): la salida cruda del modelo OSNet NO está L2-normalizada (norma ~52,4 medida) — `embed()` normaliza explícitamente antes de devolver, porque SPEC_v2.md §5.6 y el futuro coseno de `TrackGallery` dan por hecho un vector unitario
- scripts/fetch_models.py (Fase 25, 25-01): el export público de OSNet trae el eje de batch fijo a 16 (una inferencia suelta costaría 84,5 ms en vez de 4,97 ms, criterio 1 fallado por 4x) — el script reescribe ese eje a simbólico antes de guardar el fichero en `models/` (gitignored), verificando sha256 y tamaño exacto antes de escribir; `ReIDEngine` además se autodeshabilita si detecta batch fijo != 1, por si el script no se ejecutó
- IdentityStateMachine.on_reid_result (Fase 25, 25-02): la herencia de identidad por apariencia entra por la FSM, nunca por el worker — resolver la herencia fuera de la FSM deja huérfana la entrada `TEMPORARILY_LOST` en `_states`, y 30 s después `on_tick()` emitiría un `IDENTITY_LOST` espurio de una persona ya reetiquetada delante de la cámara (Pitfall 4); el método fija `last_face_at = now` al heredar porque sin eso el barrido de rancios de `on_tick` (`stale_ttl = lost_ttl + revalidate_after * MAX_FAILED_REVALIDATIONS`) purgaría el estado recién heredado (Pitfall 5); nunca vota en `TemporalVoter` para no contaminar los parámetros medidos de FACE-07
- TrackGallery.resolve (Fase 25, 25-03): calcula SIEMPRE el candidato real `(person_id, similitud)`, incluso cuando no se hereda por umbral no superado o conflicto — la política de si aplicar la herencia (modo solo-observación vs aplicar) vive en el flag del worker, cableado en `25-04`; el umbral es estricto (`sim > 0.7`, no `>=`), coherente con la redacción del criterio 2 del ROADMAP
- TrackGallery._enforce_cap (Fase 25, 25-03): la cota dura de 256 entradas se invoca tanto desde `update()` como desde `prune()` — mismo patrón "seguro de vida" de la Fase 22, verificado con un test que nunca llama a `prune()`
- tests/test_track_gallery.py (Fase 25, 25-03): vectores 512D construidos a mano con coseno exacto (`cos*e_base + sqrt(1-cos^2)*e_other`), nunca ruido aleatorio — el research midió coseno 0,991 entre dos embeddings de OSNet alimentados con ruido independiente (colapso fuera de distribución) que invalidaría cualquier test de umbral
- RecognitionWorker._reid_pass (Fase 25, 25-04): `reid_inherit` es un flag del worker, no de `TrackGallery` — `resolve()` siempre calcula el candidato real y el worker decide si lo aplica (`on_reid_result()`) o solo lo audita (contadores + log INFO, modo solo-observación del criterio 4); `self._rate.observe()` nunca se llama desde la vía ReID para no contaminar `avg_latency` de `/api/v2/cameras/{id}/health` (instrumentación propia con `stage="reid"`)
- RecognitionWorker._next_reid_candidate (Fase 25, 25-04, bug encontrado en el test del criterio 3): exige `track_id in registry.frame_ids()`, no solo `TrackGallery.needs_embedding()` — sin este filtro, un track `TEMPORARILY_LOST` que aún no ha sido podado por `DetectionWorker` (TTL 30 s por defecto) se re-embebía con `identity_of()==None` (identity.py solo devuelve `person_id` si el track está `CONFIRMED`), borrando en la galería la identidad que ReID necesita conservar para que otro track la reclame después — justo lo contrario del criterio 3
- backend/config.py (Fase 25, 25-05): `reid_inherit_window_secs` (15 s) es deliberadamente MÁS CORTA que `identity_lost_ttl_secs` (30 s, Fase 24) — la apariencia es menos fiable que la votación facial y debe caducar antes; `reid_inherit_identity=False` por defecto (fail-safe, T-25-17): ReID calcula y registra la herencia sin aplicarla hasta que el operador la active explícitamente
- CameraPipeline (Fase 25, 25-05): `self.reid_engine`/`self.reid_gallery` se construyen junto a `self.identity_fsm`, FUERA de `_make_recognition` — mismo motivo que la FSM de la Fase 24: el `WorkerSupervisor` re-ejecuta la factoría en cada reinicio del worker, y construirlos dentro vaciaría la galería de apariencia y recargaría el ONNX en cada reinicio
- Puerta de fase (Fase 25, 25-06): no hizo falta ningún fix de código — la suite ya estaba verde (413/413) y REID-01..REID-04 ya estaban marcados `[x]` desde 25-01/25-02/25-03; el checkpoint del criterio 4 (tasa de falsos positivos con personas reales) se difiere explícitamente por falta de acceso a cámara en la sesión, sin bloquear el avance a la Fase 26 porque `reid_inherit_identity=False` sigue siendo el default y la mitad determinista del criterio ya está probada
- BehaviorAnalyzer (Fase 26, 26-01): `BehaviorFinding` es dominio puro (no `Event`), mismo patrón que `IdentityTransition` — corrige la firma `analyze(...) -> list[Event]` de SPEC_v2.md §5.7 (26-RESEARCH.md D-3); IMMOBILE usa la caja envolvente (`span`) del recorrido y no la distancia al ancla, porque la distancia permitiría un diámetro real de 2R; LOITERING usa una ancla independiente por `(track, zona)` — sin zonas configuradas cae a `zone_id=None` (escena implícita, D-02) salvo `loiter_require_zone=True`, y con zonas solapadas emite un finding por zona (D-04); los 4 comportamientos (no solo CROWD) llevan latch por episodio con re-armado por histéresis (`REARM_RATIO=0.8` en RUNNING/CROWD) — sin latch, una persona parada 10 min generaría miles de eventos IMMOBILE; `_enforce_cap()` se invoca también desde `analyze()` además de `prune()`, mismo "seguro de vida" de la Fase 22/25
- EventEngine.emit_behavior (Fase 26, 26-03): nunca pasa `severity=` explícita, para que `@model_validator` de `Event` aplique el default `INFO` del catálogo (D-01) y los comportamientos no crucen `upload_min_severity="warning"`; `process_zone()` añade `now_monotonic` AL FINAL de la firma (aditivo, compatible con el único llamador posicional) porque `captured_at`/`processed_at` son conceptos privados de latencia OBS-03, no un reloj semántico — restar dos `datetime.datetime.now()` sería sensible a saltos de reloj por NTP; `duration_s` es la clave literal del payload porque `rules.py:88-91` la lee tal cual para `duration_gte`; `_zone_entry_at` se acota con `pop()` en el mismo bucle que emite `ZONE_EXITED` (mismo "seguro de vida" que `TrackGallery`/`BehaviorAnalyzer` de las Fases 25/26)
- DetectionWorker/manager.py (Fase 26, 26-04): `_analyze_behavior` toma los ids del frame de `tracked.tracker_id` directamente, nunca de `self._registry.frame_ids()` — `set_frame_ids()` se llama dentro de `_emit_track_lifecycle`, que corre DESPUÉS en `_loop`, así que leer `frame_ids()` en `_analyze_behavior` vería el frame anterior; `self.behavior` se construye en `CameraPipeline.__init__` ANTES del bloque `if detector is not None and tracker is not None`, gateado solo por `behavior_enabled`, y se pasa como último kwarg dentro de `_make_detection` — mismo motivo que `identity_fsm`/`reid_gallery`: el `WorkerSupervisor` re-ejecuta la factoría en cada reinicio y construir el analizador dentro borraría las anclas y latches, produciendo una ráfaga de eventos duplicados
- backend/config.py (Fase 26, 26-02): `validate_behavior_params` acota `run_window_secs <= 12.0` — es la misma clase de guarda que `validate_identity_params` (impide una configuración que nunca podría cumplirse), aquí contra el límite real de `centroid_history` (`tracking.py:47`, `deque(maxlen=150)`) al peor caso de FPS (`rate.py:26`, `AdaptiveRate.STEPS[0]=12.0`) — sin esta cota, un operador podría configurar una ventana de RUNNING que jamás se calcularía; `loiter_require_zone=False` por defecto (fallback D-02) para que una instalación limpia sin zonas configuradas siga pudiendo emitir LOITERING
- backend/config.py (Fase 27, 27-02, D-03): `yolo_model_path` por defecto pasa de `yolov8n.pt` a `yolo26n.pt` — corrige la deriva respecto a CLAUDE.md; se aplica en este plan y no antes porque el criterio 6 (latencia con 6 clases) se mide despues, sobre la ruta de post-proceso NMS-free de `yolo26n.pt`. `validate_object_params` sigue el molde de `validate_behavior_params` y rechaza explicitamente la clase 0 (person) en `object_class_ids` — desviarla ahi perderia el `LineZone`/identidad/comportamiento del `PersonTracker`
- PersonDetector.set_classes (Fase 27, 27-02): mutacion en caliente de `self._classes` (rebind atomico, sin lock) en vez de reconstruir el detector — mismo motivo que `PersonTracker.set_frame_rate`, pero con coste mayor si se reconstruyera: `WorkerSupervisor._check()` cuenta cualquier parada del worker como caida y tres reinicios en 60 s lo dejarian en `FAILED` permanente
- ObjectAnalyzer (Fase 27, 27-01): `ObjectObservation`/`PersonObservation` (dataclasses con 6 atributos) en vez de los `dict[int, tuple]` de `BehaviorAnalyzer` — varios dicts paralelos por objeto serían un criadero de bugs de desincronización; `prune()` devuelve `list[ObjectFinding]` (a diferencia de `BehaviorAnalyzer.prune` que devuelve `None`) porque `OBJECT_REMOVED` se decide ahí, no en `analyze()`, para exigir `gone_secs` de gracia contra oclusiones de un frame; `stable` se deriva de `object_gone_secs` sin parámetro nuevo (mínimo tiempo quieto para considerarse "establecido" = la misma ventana de gracia con la que se declara la desaparición); asimetría deliberada entre el radio de persona en `OBJECT_LEFT` (negativo: pasarse de grande suprime eventos, lado seguro) y en `OBJECT_REMOVED` (positivo: pasarse de grande es peligroso)
- ObjectTracker (Fase 27, 27-03): análogo por sustracción de `PersonTracker` — mismo `sv.ByteTrack`+`LOST_TRACK_BUFFER`+`set_frame_rate`, SIN `DetectionsSmoother` (congelaría `class_id` hasta 5 frames) y SIN `LineZone` (el conteo de la Fase 4, en producción, es solo de personas); `PersonTracker` queda intacto, verificado por `git diff` sin líneas `-`
- EventEngine.emit_object (Fase 27, 27-05): nunca pasa `severity=` explicita — a diferencia de los 4 comportamientos de la Fase 26 (que se quedaron en INFO a proposito), aqui `OBJECT_LEFT` hereda `WARNING` del catalogo y por tanto SUBE EL CLIP A GOOGLE DRIVE al cruzar `upload_min_severity`; decision cerrada con el usuario (T-27-19). `bbox` viaja como campo de primer nivel del `Event` (los eventos de objeto llevan caja, los de comportamiento no). `config_changed()` es el primer emisor de `CONFIG_CHANGED` desde que existe en el catalogo (Fase 19) — unica mitigacion de repudio disponible sin roles en el sistema (ASVS V4, T-27-20)
- DetectionWorker._split_by_class (Fase 27, 27-03): la partición por `class_id` (`np.isin` contra `PERSON_CLASS_IDS=(0,)`) ocurre DENTRO del `try` de inferencia ya existente, para que un `sv_dets` malformado siga cayendo en el mismo `except`; `PersonTracker.update` recibe siempre `person_dets`, nunca `sv_dets` completo — sin esto, un objeto (coche, mochila) sumaría al conteo de línea de la Fase 4 o entraría en `TrackRegistry`/reconocimiento facial. Los objetos NUNCA entran en `TrackRegistry`: su estado vive en `self._object_boxes` bajo `self._lock` (mismo patrón que `_zone_states`), con escritor único (hilo de detección) y lectores desde fuera (`get_object_boxes`/`get_object_stats`, copias defensivas). `self._rate.observe()` sigue midiendo solo la vía de personas — la vía de objetos nunca la llama, mismo patrón que ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26)
- Riesgo de primer orden verificado con test de reproducción (Fase 27, 27-03): `sv.ByteTrack` es class-agnostic (el tensor del matcher usa solo `xyxy`+`confidence`, `supervision/tracker/byte_tracker/core.py:104-110`) — `TEST_bytetrack_ids_do_not_migrate_between_classes` reproduce literalmente que un `sv.ByteTrack` COMPARTIDO transfiere el id de una mochila "perdida" a una persona casi en la misma caja, y demuestra que con `ObjectTracker`+`PersonTracker` separados no ocurre
- DetectionWorker._analyze_objects / CameraPipeline (Fase 27, 27-06): `findings += self._objects.prune(...)` se recoge explícitamente — a diferencia de `BehaviorAnalyzer.prune` (devuelve `None`), el `prune()` de `ObjectAnalyzer` decide `OBJECT_REMOVED` y su retorno no se puede ignorar sin perder la mitad del requisito BEH-07; `_excluded_object_ids`/`_object_zone_ids` reutilizan `sv.PolygonZone.trigger()` sobre los mismos `_zone_states` (con `kind` ya propagado desde `27-04`) en vez de escribir geometría punto-en-polígono propia. `self.objects`/`self.object_tracker` se construyen en `CameraPipeline.__init__` ANTES de `_make_detection` — cuarto precedente del mismo patrón que la FSM (Fase 24), la galería ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26): reconstruirlos en cada reinicio del `DetectionWorker` reabriría la ventana de warmup y reiniciaría los `track_id` de objeto, emitiendo una ráfaga de `OBJECT_LEFT` (`WARNING`) que subiría un clip a Google Drive por cada mueble fijo de la escena
- backend/api/v2/detection.py (Fase 27, 27-07): el PUT persiste en `app_config` (`ConfigRepo.set`) ANTES de propagar al pipeline y emitir `CONFIG_CHANGED` — si el proceso muriera entre ambos pasos, el arranque siguiente (precedencia BD > env var) aplicaria lo que el operador pidio en vez de perderlo; `LOCKED_CLASS_IDS={0}` rechaza con 400 cualquier PUT que no incluya "person" (decision cerrada con el usuario, el frontend de `27-10` ademas la muestra marcada y deshabilitada)
- backend/main.py `_resolve_active_classes` (Fase 27, 27-07): logica de precedencia extraida a funcion modulo-privada para poder testearla sin arrancar el lifespan completo — mejora prevista explicitamente por el plan; `if persisted` (no `is not None`) trata una fila `[]` guardada por error como ausente, nunca como "no detectes nada"
- StreamingWorker/manager.py (Fase 27, 27-08): `object_boxes` es un `Callable[[], list[dict]] | None` inyectado en el constructor (via pull), nunca un setter tipo `set_zone_overlay` (patron muerto, sin llamadores, 27-PATTERNS.md § No Analog Found); `manager.py` pasa `self.get_object_boxes` (metodo bound de `CameraPipeline`) directamente, sin envolverlo en una lambda — un metodo bound resuelve `self.detection` en cada llamada, asi que sobrevive a un reinicio del `DetectionWorker` sin volver a pasar la referencia. Color magenta `(255, 0, 255)` BGR, deliberadamente distinto del naranja de zonas `(0, 200, 255)` — decision cerrada con el usuario en 27-RESEARCH.md Open Question #1
- Puerta de fase (Fase 27, 27-11): no hizo falta ningún fix de código — la suite ya estaba verde (519/519) y BEH-07 ya estaba `[x]` desde `27-01`; `27-11` marca BEH-06/BEH-08/BEH-09 y traza los 6 criterios del ROADMAP a comandos `pytest -k`. Las decisiones clave de la fase quedan resumidas aquí: (1) `sv.ByteTrack` es class-agnostic (reproducido en `27-RESEARCH.md` Q4 y en `TEST_bytetrack_ids_do_not_migrate_between_classes`) — la partición por clase ANTES del tracker y un `ObjectTracker` dedicado son obligatorios, no una optimización, o un track de objeto puede transferir su id a una persona solapada y contaminar el `LineZone` de la Fase 4; (2) los objetos nunca entran en `TrackRegistry` — su estado vive en `self._object_boxes` bajo `self._lock`, mismo patrón que `_zone_states`; (3) `self.objects`/`self.object_tracker` (y el resto de estado de la fase) se construyen en `CameraPipeline.__init__` ANTES de `_make_detection`/`_make_recognition`, fuera de la factoría del `WorkerSupervisor` — cuarto precedente tras FSM (Fase 24), galería ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26); (4) la BD (`app_config`) gana sobre `YOLO_CLASSES` al arrancar, y una fila `[]` persistida se trata como ausente para no dejar el sistema ciego en silencio; (5) `person` (clase 0) siempre viaja forzada/activa y bloqueada en el catálogo — ningún PUT puede desactivarla; (6) `OBJECT_LEFT` se mantiene en `Severity.WARNING` (decisión del usuario) y por tanto cruza `upload_min_severity="warning"` y sube clips a Drive desde el primer evento — exige calibrar `object_person_radius_px` con cámara real antes de operar desatendido (checkpoint diferido de este plan); (7) el nivel de actividad de BEH-09 se normaliza a tasa por minuto en baseline y "ahora" para no sesgar `"low"` al principio de cada hora, y cae a `"unknown"` con menos de `context_min_sample_days` de historial; (8) `yolo_model_path` por defecto corregido a `yolo26n.pt` (D-03), alineado con CLAUDE.md. El checkpoint de calibración de `object_person_radius_px` (150 px, 1,9× `loiter_radius_px`) y de la tasa de falsos positivos de `OBJECT_LEFT` se difiere explícitamente — 9º checkpoint manual pendiente, no bloquea avanzar a la Fase 28
- Puerta de fase (Fase 26, 26-05): no hizo falta ningún fix de código — `tests/test_rule_engine.py` ganó 3 tests que recorren el camino real (YAML en `tmp_path` + `load_rules` + `evaluate`) para demostrar el criterio 5 sin tocar `backend/events/rules.py` ni `config/rules.yaml`, y BEH-01..BEH-05 ya estaban `[x]` desde planes anteriores. Las seis decisiones clave de la fase quedan resumidas aquí: (1) el historial de 120 s se disuelve con agregados incrementales O(1) en vez de ampliar `history_len` (584 B/track medidos frente a 141,8 KB si se hubiera ampliado a 1000, `tracking.py` intacto); (2) los CUATRO comportamientos llevan latch por episodio, no solo CROWD — sin él, una persona parada 10 min generaría miles de eventos IMMOBILE, y `debounce_secs` de `rules.yaml` no sustituye al latch porque actúa después de persistir y difundir; (3) `analyze()` devuelve `list[BehaviorFinding]`, no `list[Event]` (D-3, corrige SPEC §5.7) — `perception/` no conoce `camera_id` ni el reloj de pared; (4) semántica de zonas: LOITERING cae a escena implícita (`zone_id=None`) sin zonas configuradas salvo `loiter_require_zone=True` (D-02), LOITERING e IMMOBILE coexisten (D-03), y con zonas solapadas se emite un finding por zona (D-04); (5) la clave del payload es `duration_s` literal porque `rules.py:88-91` la lee así para `duration_gte` — cualquier otro nombre rompe el criterio 5 en silencio; (6) los 4 comportamientos se quedan en `Severity.INFO` por defecto (D-01, cambio cero) — subirlos a WARNING habría activado la subida automática de clips a Google Drive. El checkpoint de calibración de umbrales con cámara real (Task 3) se difiere explícitamente — 8º checkpoint manual pendiente, no bloquea avanzar a la Fase 27
- [Phase 31]: seed_events(): orden de rng preservado byte a byte (type/severity antes que track_id/confidence) al anadir persons/zones — el borrador del plan invertia el orden y habria roto el determinismo de los tests de la Fase 30
- [Phase 31]: Regla global [hidden] { display: none !important; } en base.css para restaurar la precedencia de hidden frente a las utilidades de display de Tailwind CDN — El checkpoint de 31-03 detecto con navegador real que Tailwind (cargado via CDN, origen autor) vence siempre al [hidden] del User-Agent; !important en base.css es el fix estandar y queda como base para cualquier futuro uso de hidden en el proyecto
- [Phase 31]: El endpoint v1 /api/heatmap y backend/main.py no se tocan en 31-06: sigue sin cambios y hereda INFERNO por compartir compose_heatmap con el v2
- [Phase 31]: unit va en el JSON de /heatmap/scale, no como constante fija del cliente: quien lea la respuesta cruda ve la unidad (frames de deteccion con presencia) junto al numero

### Pendiente manual (no es código)

- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app)
  y colocarlo en la raíz del proyecto para habilitar upload a Google Drive

- Carpeta Drive destino: «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`)

### Blockers/Concerns

Ninguno bloqueante para el desarrollo de v2.0. Ver "Pendiente sin relacion
con v2.0" arriba (token OAuth de Google Drive caducado) y los 9 checkpoints
manuales con cámara real listados en la tabla de fases — ninguno bloquea
avanzar a la Fase 28, pero deben cerrarse antes de dar el bloque A, la
Fase 23, la Fase 25, la Fase 26 y la Fase 27 por completamente validados
en producción.

## Session Continuity

Last session: 2026-08-23T14:44:53.246Z
Stopped at: Completada 31-06-PLAN.md
  "Marcar como persona" está completo: `markPerson.js` precarga el recorte del evento,
  muestra el aviso de alcance retroactivo con el N del servidor antes de confirmar,
  enrola contra `/api/enroll_face` (sin duplicar sus validaciones), aplica la identidad
  al bloque del track en una sola llamada y `applyPersonAssignment()` repinta las filas
  en sitio conservando el `scrollTop`. `components/markPerson.js` añadido a `LOCKED_JS`.
  Suite completa en verde (603 passed, 2 skipped). Pendiente de comprobación manual,
  que firma 30-12: recorte real en el modal, N razonable en el aviso y filas del track
  cambiando en sitio. Siguiente: 30-12 (puerta de fase)
Resume file: None

---

Last session: 2026-08-21
Stopped at: Ejecutado 30-10-PLAN.md (wave 8, depende de 30-08 y 30-09). La línea
  temporal y el centro de alertas ya arrancan con el dashboard: `case 'event'` en
  `websocket.js` hacia `onLiveEvent()`, `initTimeline()` antes de `connectWS()`,
  aviso de "sin tiempo real" colgado del `onopen`/`onclose` existente y `LOCKED_JS`
  con los cinco módulos de la fase. Cerrado el hueco que dejó 30-09: `timeline.js`
  escucha `timeline:filter-rule` y aplica el filtro de regla en servidor. Suite
  completa en verde (603 passed, 2 skipped). Pendiente de comprobación manual, que
  firma 30-12: evento real en <1 s sin recargar y cruce de línea una sola vez.
  Siguiente: 30-11 (marcar como persona)
Resume file: ninguno — continuar con `.planning/phases/30-event-timeline-y-centro-de-alertas/30-11-PLAN.md`

---

Last session: 2026-08-21
Stopped at: Ejecutado 30-08-PLAN.md (wave 6, depende de 30-05 y 30-07). Cuatro
  módulos ES nuevos con la línea temporal completa: fila sin XSS con las cuatro
  acciones y descarte en `localStorage`, filtros en servidor con cursor y páginas
  de 50, doble centinela de `IntersectionObserver` (abajo pide página, arriba
  desliza la ventana), DOM acotado a 400 filas con compensación de `scrollTop`, y
  evento en vivo arriba o en píldora según la posición del scroll. Pendiente de
  comprobación manual (no hay runner JS): que el recorte a 400 filas no dé un salto
  perceptible — plan B ya documentado en el módulo (subir a 1000 y no recortar).
  Nadie llama todavía a `initTimeline()`: eso es 30-10. Siguiente: 30-09
  (`alertCenter.js`). Ver `30-08-SUMMARY.md`.

Sesión anterior (2026-08-21, misma jornada)
Stopped at: Ejecutado 30-07-PLAN.md (wave 5, depende de 30-05 y 30-06). Marcado y
  estilos de la línea temporal, campana con badge, cajón de alertas y modal de
  marcar como persona, con los 35 ids del contrato que consumen 30-08/30-09/30-11;
  y retirada en el mismo plan de `addEvent`/`applyFilters`/`bindEventFilters` y del
  bloque de `#events-list`, que habrían dejado el arranque de `app.js` roto.
  Pendiente de comprobación manual: abrir `/` y confirmar consola limpia (el card
  aparecerá vacío hasta 30-08, es lo esperado). Siguiente: 30-08 (`timeline.js`).
  Ver `30-07-SUMMARY.md`.

Sesión anterior (2026-08-21, misma jornada)
Stopped at: Ejecutado 30-06-PLAN.md (wave 4, depende de 30-05). Router
  `backend/api/v2/alerts.py` con `GET /api/v2/alerts` (agrupación por regla o por
  tipo, contadores del badge, ventana 1..168 h) y `POST /mute` / `/unmute`
  (persistencia en `app_config`, duración en lista blanca, expiración perezosa,
  `CONFIG_CHANGED` por cada cambio). Silenciar es solo de presentación: no toca
  `RuleEngine` ni `run_actions`. 16 tests nuevos, suite 603/603 (+2 skips).
  Siguiente: 30-07 (marcado y estilos de la línea temporal y el cajón). Ver
  `30-06-SUMMARY.md`.

Sesión anterior (2026-08-21, misma jornada)
Stopped at: Ejecutado 30-05-PLAN.md (wave 3, depende de 30-01..30-04).
  Router `backend/api/v2/events.py` con lista paginada (`total` condicional +
  mapa `media`), detalle, `track-scope` y `assign-person`; endpoint suelto de
  `main.py` borrado en el mismo commit. 17 tests nuevos, suite 587/587 (+2
  skips). Siguiente: 30-06 (centro de alertas backend). Ver `30-05-SUMMARY.md`.

Sesión anterior (2026-08-17)
Stopped at: Ejecutado 27-11-PLAN.md (puerta de fase, wave 6, depende de
  27-08+27-09+27-10). Suite completa reejecutada verde: `pytest tests/ -q`
  → 519/519, sin cambios de código. Trazabilidad de los 6 criterios de
  éxito del ROADMAP a comandos `pytest -k` que pasan, más la regresión
  ByteTrack (`TEST_object_class_does_not_reach_line_zone`,
  `TEST_objects_not_in_registry`, `TEST_bytetrack_ids_do_not_migrate_between_classes`)
  — ver la tabla completa en `27-11-SUMMARY.md`. `REQUIREMENTS.md`:
  BEH-06/BEH-08/BEH-09 marcados `[x]` (BEH-07 ya lo estaba desde `27-01`).
  `ROADMAP.md`: Fase 27 marcada `[x]` en el bloque B y "11/11 plans
  complete (6 waves)" en el detalle. El checkpoint de calibración de
  `object_person_radius_px` y de la tasa de falsos positivos de
  `OBJECT_LEFT` con cámara real se **difiere** explícitamente (9º
  checkpoint manual, sin cámara en esta sesión, mismo patrón que los 8
  anteriores) — no bloquea el cierre de la Fase 27 en código/tests ni el
  avance a la Fase 28. Sin desviaciones de código. **Fase 27 completa:
  11/11 planes.** Siguiente: `/gsd:plan-phase 28`.
Resume file: ninguno — Fase 27 completa. Siguiente paso: planificar la
  Fase 28 con `/gsd:plan-phase 28`.

Sesión anterior (2026-08-17): Ejecutado 27-08-PLAN.md (wave 4, depende de 27-03+27-06). `StreamingWorker`
  (`backend/pipeline/streaming.py`) acepta `object_boxes: Callable[[], list[dict]] | None = None`
  en el constructor (via pull, mismo patron que `registry`/`tracker` — `set_zone_overlay` se
  descarto por no tener llamadores) y `_annotate` dibuja cada caja de objeto en magenta
  `(255, 0, 255)` con etiqueta `class_name #track_id`, tras el bloque de zonas. `manager.py`:
  `_make_streaming` pasa `object_boxes=self.get_object_boxes` (metodo bound de `CameraPipeline`,
  27-06) sin logica nueva. 4 tests nuevos `TEST_*` (3 en `test_streaming_worker.py` sobre
  `_annotate` en aislamiento, 1 en `test_detection_worker.py` de identidad de referencia del
  Callable cableado por la factoria del supervisor) — ver `27-08-SUMMARY.md`. Suite completa
  512/512 (508 previos + 4). Sin desviaciones de codigo (una nota sobre un detalle menor del
  propio criterio de aceptacion del plan, documentada en `27-08-SUMMARY.md` § Deviations).
  BEH-06 contribuido pero NO marcado en REQUIREMENTS.md (mismo criterio que 27-06/27-07: el
  ROADMAP cierra BEH-06/07 en la puerta de fase 27-11). Fase 27: 8/11 planes. Siguiente:
  `/gsd:execute-phase 27` para continuar con `27-09` (endpoint de contexto de escena).
Resume file: ninguno registrado todavía para `27-09` — generar/ejecutar con
  `/gsd:execute-phase 27`.

Sesión anterior (2026-08-17): Ejecutado 27-07-PLAN.md (wave 4, depende de 27-02+27-04+27-06). Router
  `GET/PUT /api/v2/detection/classes` en `backend/api/v2/detection.py` con persistencia en
  `app_config` (precedencia sobre `YOLO_CLASSES`), las 4 validaciones con 400 y `detail` en
  lenguaje llano, y `CONFIG_CHANGED` como rastro — ver detalle en `27-07-SUMMARY.md`. Suite
  completa 508/508. Fase 27: 7/11 planes. Siguiente: `/gsd:execute-phase 27` para continuar
  con `27-08` (overlay MJPEG).

Sesión anterior (2026-08-17): Ejecutado 27-06-PLAN.md (wave 3, depende de 27-01+27-03+27-04+27-05).
  `_analyze_objects` cableado en `DetectionWorker._loop` justo despues de `_analyze_behavior`:
  construye `ObjectObservation`/`PersonObservation` con anclas `BOTTOM_CENTER`, recoge
  `findings += self._objects.prune(...)` explicitamente (el retorno NO se ignora, a
  diferencia de `BehaviorAnalyzer.prune`), y emite via `EventEngine.emit_object` fuera del
  `try` de aislamiento de fallos. `_excluded_object_ids`/`_object_zone_ids` reutilizan
  `sv.PolygonZone.trigger()` sobre los mismos `_zone_states` (nueva clave `kind` propagada en
  `_rebuild_zone_states`), sin geometria propia. `CameraPipeline.__init__`: `self.objects`/
  `self.object_tracker` construidos ANTES de `_make_detection`, gateados por
  `objects_enabled` — cuarto precedente de estado que sobrevive a un reinicio del
  `DetectionWorker` (FSM Fase 24, ReID Fase 25, `BehaviorAnalyzer` Fase 26). Fachada
  `set_detection_classes`/`get_object_stats`/`get_object_boxes`; `set_detection_classes` muta
  detector+reparto sin reiniciar ningun worker (test explicito `stop.assert_not_called()`).
  `backend/main.py` propaga los 10 parametros `object_*`/`objects_enabled`. 8 tests nuevos
  `TEST_*` en `tests/test_detection_worker.py`. Suite completa 500/500 (492 previos + 8). Dos
  discrepancias de conteo en los `<verify>` automatizados del propio plan, documentadas y sin
  impacto funcional (ver `27-06-SUMMARY.md` § Deviations): `grep -c "object_" backend/main.py`
  da 9 no >=10 (`objects_enabled` no matchea por la "s" de plural; nombre fijado por el
  contrato LOCKED) y `pytest -k object` recoge 12 no >=13 (3 de los 7 tests de `27-03` no
  contienen la palabra "object" en su nombre). BEH-06/07 NO se marcan `[x]`: el ROADMAP
  asigna esa puerta a `27-11`. Quedan `27-07`..`27-11` (router de clases activas, overlay
  MJPEG, endpoint de contexto, control de clases en el dashboard y puerta de fase). Siguiente:
  `/gsd:execute-phase 27` para continuar con `27-07`.
Resume file: ninguno registrado todavía para `27-07` — generar/ejecutar con
  `/gsd:execute-phase 27`.

Sesión anterior (2026-08-17): Ejecutado 27-04-PLAN.md (media movil horaria + kind de zona,
  wave 1, sin dependencias de codigo). backend/storage/repositories.py:
  DetectionStatRepo.hourly_baseline() con doble GROUP BY (subquery por dia+hora, luego avg
  por hora) sobre unique_tracks, parametro until para excluir la hora en curso, todo
  parametros ligados. backend/database.py: kind en el Zone legacy (copiado caracter a
  caracter de storage/models.py) y en get_zones(), que main.py:468 usa para alimentar al
  DetectionWorker. Sin indice nuevo ni migracion (confirmado con git diff --stat vacio en
  models.py/migrations.py). tests: +7 tests TEST_* (5 de hourly_baseline: orden de
  agregacion, sample_days, until, filtro por camara, ventana vacia; 1 de ConfigRepo roundtrip
  de list[int]; 1 de get_zones_returns_kind). Suite completa 487/487. Sin desviaciones.

Sesión anterior (2026-08-17): Ejecutado 27-02-PLAN.md (wave 1, sin dependencias reales de
  código). D-03: `yolo_model_path` por defecto pasa de `yolov8n.pt` a `yolo26n.pt`
  (end2end=True, NMS-free). 10 parámetros `object_*` y 4 `context_*` en `backend/config.py`
  con los defaults del research, más `validate_object_params` (rechaza clase 0/person en
  `object_class_ids`, ratios fuera de rango, ids COCO inválidos,
  `context_low_ratio >= context_high_ratio`). `PersonDetector.set_classes()`
  (`backend/detector.py`): mutación en caliente de `self._classes` con rebind atómico (sin
  lock, mismo patrón que `PersonTracker.set_frame_rate`), verificado que no recarga el
  modelo (`id(self._model)` no cambia). 5 tests nuevos: 3 en `tests/test_config.py`
  (default `yolo26n.pt`, defaults de los 14 parámetros, rechazo de las 6 configuraciones
  imposibles) + 2 en `tests/test_detector.py` (`TEST_set_classes_changes_next_inference` y
  `TEST_multiclass_latency_under_15_percent`, el benchmark del criterio 6 del ROADMAP con
  pesos reales de `yolo26n.pt` sobre `bus.jpg`, sin skip). Suite completa 473/473 (468
  previos + 5). Sin desviaciones de código — ver `27-02-SUMMARY.md`.

Sesión anterior (2026-08-16): Ejecutado 26-05-PLAN.md (criterio 5 `when.event` desde YAML
  real + puerta de fase, wave 4, depende de `26-01`..`26-04`). Los 3
  tasks: (1) `tests/test_rule_engine.py` gana `BEHAVIOR_RULES_YAML`
  (4 reglas, una por evento de comportamiento) y 3 tests que recorren
  el camino real (`tmp_path` + `load_rules` + `evaluate`) —
  `TEST_behavior_events_usable_as_when_event` (`errors == []`, 4
  reglas), `TEST_behavior_duration_gte_reads_duration_s` (dispara con
  `duration_s=130.0`, no dispara con `90.0` ni con la clave equivocada
  `duration=130.0` — regresión explícita del pitfall de naming),
  `TEST_behavior_zone_filter_uses_first_class_zone_id` (`zone: "z1"`
  filtra sobre `zone_id` de primer nivel del `Event`) — sin tocar
  `backend/events/rules.py` ni `config/rules.yaml` (criterio 5 es cero
  código); (2) puerta de fase: suite completa **454/454** (451 previos

  + 3), los 5 criterios del ROADMAP trazados a comandos `pytest -k` que
  pasan (ver tabla en `26-05-SUMMARY.md`), con el criterio 2 repartido
  explícitamente entre los 4 tests de trayectoria de `26-01`
  (comportamiento) y los tests ya existentes de
  `EventEngine.process_zone` (2 trayectorias de zona, propiedad de la
  Fase 19); BEH-01..BEH-05 confirmados `[x]` en `REQUIREMENTS.md`
  (ya lo estaban desde planes anteriores); `ROADMAP.md`/`STATE.md`
  actualizados (Fase 26 completa, 5/5 planes); (3) checkpoint de
  calibración de umbrales con cámara real (`run_speed_px_s`,
  `loiter_radius_px`, `immobile_radius_px`) **diferido** explícitamente
  — sin acceso a cámara en esta sesión, mismo patrón que los 7
  checkpoints anteriores (25-06 Task 2 fue el último); los defaults de
  SPEC_v2.md §5.7 (350 px/s, 80 px, 20 px) ya están cubiertos por tests
  deterministas con trayectorias sintéticas y no bloquea avanzar a la
  Fase 27. Sin desviaciones de código, ver `26-05-SUMMARY.md`.
  **Fase 26 completa: 5/5 planes.** Siguiente: `/gsd:plan-phase 27`.
Resume file: ninguno — Fase 26 completa. Siguiente paso: planificar la
  Fase 27 con `/gsd:plan-phase 27`.
