# Phase 32: Vista de cámara y configuración visual - Context

**Gathered:** 2026-08-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Operar y configurar el sistema sin tocar `.env`. Dos piezas:

1. **Vista Cámara** (OPS-16, OPS-17): live view + salud en tiempo real (FPS, latencia
   e2e, CPU, RAM, FPS de detector, estado RTSP) reunidos junto al vídeo, más una barra
   de ajustes rápidos de detección/grabación.
2. **Vista Ajustes** (OPS-18..20, SET-01..04): árbol completo de configuración (Cámara,
   Detección, Tracking, Reconocimiento, Zonas, Reglas, Alertas, Almacenamiento) con
   persistencia en `app_config`, aplicación en caliente donde ya existe la ruta técnica,
   validación en servidor con 422 legible, restaurar por defecto por sección y auditoría
   `CONFIG_CHANGED` con diff.

</domain>

<decisions>
## Implementation Decisions

Esta fase no tuvo discusión interactiva: el `32-UI-SPEC.md` (aprobado por el checker,
6/6 PASS) ya fija explícitamente casi todas las decisiones de visión y de contrato de
interacción, con hallazgos medidos contra el código actual, no supuestos. Lo que sigue
resume esas decisiones ya cerradas para que el investigador y el planificador no las
reabran.

### Estructura y navegación
- **D-01:** Dos pestañas nuevas, "Cámara" y "Ajustes", en el mismo `role="tablist"` que
  construyó la Fase 31 — mismo hash-routing (`#camara`, `#ajustes/{sección}`), sin
  segundo mecanismo de navegación.
- **D-02:** La vista Cámara reutiliza el `<img id="video-feed">` / `/video_feed` que ya
  pinta Operaciones — no se duplica el stream MJPEG, se mueve la referencia visual.
  Operaciones no se toca: ningún panel se mueve, ningún id se borra.
- **D-03:** El árbol de secciones de Ajustes es un `role="tablist"` vertical anidado, no
  un componente nuevo. Dos niveles reales: 8 secciones × subsecciones como `<fieldset>`
  dentro de un único panel por sección — un solo diff, un solo guardado, un solo
  `CONFIG_CHANGED` por sección, no un panel por subsección.

### Esquema y datos
- **D-04:** `GET/PUT /api/v2/config` no existe hoy y hay que crearlo. El esquema
  completo (`label`, `hint`, `min`/`max`/`default`, `origin`, `applies`, `secret`,
  `readonly`) lo decide y sirve el servidor; el cliente no mantiene copia de rangos ni
  traducciones de nombres de campo — así SET-02 y SET-03 no pueden desincronizarse.
- **D-05:** Reutilizar `ConfigRepo` (`backend/storage/repositories.py:795`,
  `get`/`set`/`get_all` sobre `app_config`) como almacén de overrides — ya en
  producción. No crear un segundo almacén.
- **D-06:** Precedencia `runtime (app_config) > .env > default del código`, siguiendo el
  patrón ya implementado dos veces: `PUT /api/v2/detection/classes` (Fase 27) y el
  silenciado de alertas (Fase 30, clave `alerts.muted_rules`).

### Aplicación en caliente vs reinicio
- **D-07:** Solo existen hoy tres rutas de aplicación en caliente:
  `CameraPipeline.set_zones()`, `set_detection_classes()` y `set_process_size()`
  (`backend/pipeline/manager.py:322/329/386`). El resto de los ~88 campos requiere
  reinicio. Esta fase **no amplía** esas rutas ni añade un botón de "Reiniciar el
  pipeline/servidor" — OPS-19 pide *señalizar* (`applies: hot|restart_camera|
  restart_server`, badge siempre visible), no *ejecutar*. Ampliar el hot-apply es
  trabajo de una fase futura, no de esta.
- **D-08:** Guardar siempre persiste, aunque el cambio requiera reinicio. Nunca se
  bloquea un cambio por no poder aplicarse en caliente de inmediato.

### Guardado, validación y auditoría
- **D-09:** Guardado explícito por sección (no autoguardado por campo); un
  `CONFIG_CHANGED` por sección guardada con el diff completo de esa sección, vía
  `EventEngine.config_changed()` (`backend/events/engine.py:315`, ya existe desde la
  Fase 27 — solo hay que pasarle el diff, no construir nada nuevo).
- **D-10:** El servidor valida el lote completo del PUT y devuelve todos los errores 422
  a la vez, no el primero. En error, el diff pendiente no se descarta: solo se marcan
  las filas inválidas: las válidas siguen modificadas y pendientes de guardar.
- **D-11:** "Restaurar valores por defecto" borra las filas de `app_config` de esa
  sección — no escribe los defaults del código encima — así un valor que venía de
  `.env` vuelve a `.env` en vez de congelarse. Confirmación por popover (patrón D-07 de
  la Fase 30), no `confirm()` nativo, con el recuento en el botón destructivo.

### Secretos
- **D-12:** Ningún campo `secret` (credenciales RTSP, Tapo, dashboard, token de
  Telegram, webhook, credenciales de Google Drive, rutas de certificado SSL) sale del
  servidor, ni siquiera enmascarado — el esquema manda `configured: true|false` y nada
  más. Ninguno es editable desde esta interfaz; se editan en `.env`. El `CONFIG_CHANGED`
  de auditoría nunca lleva valores `secret`, ni en el lado "antes" del diff.

### Barra de ajustes rápidos (vista Cámara, OPS-17)
- **D-13:** Los 4 controles rápidos (clases detectadas, resolución de proceso,
  confianza de detección, umbral de severidad para subir a Drive) escriben por el mismo
  `PUT /api/v2/config` que el árbol — no hay endpoint ni almacén paralelo, ni un
  segundo `CONFIG_CHANGED` con otra forma. Guardan al cambiar (sin botón de guardado),
  con `debounce` de 600 ms en el deslizador de confianza.

### Claude's Discretion
- El endpoint `GET /api/alerts/config` (`backend/main.py:1197`) existe hoy pero está
  huérfano — ningún fichero de `frontend/` lo consume. Queda a discreción del
  investigador/planificador decidir si la nueva sección "Alertas → Canales" del árbol lo
  reutiliza como fuente de `telegram_configured`, lo sustituye, o lo deja intacto sin
  relación. No es una decisión de visión del usuario — es un detalle de integración
  técnica sin impacto de producto.
- Rangos/validación exactos para los campos donde `backend/config.py` no declare
  min/max explícitos hoy: derivarlos de los valores y comentarios ya existentes en el
  código, sin inventar límites arbitrarios ni pedir al usuario que los defina campo a
  campo.
- Orden de los planes/waves para cubrir las 8 secciones dentro de esta única fase: lo
  decide el planificador según dependencias reales (p. ej. `GET/PUT /api/v2/config` y el
  armazón del árbol antes que ninguna sección concreta).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato visual y de interacción (fuente primaria)
- `.planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-UI-SPEC.md` — contrato
  de diseño completo, verificado por `gsd-ui-checker` (6/6 PASS, `status: approved`).
  Fija estructura, copywriting, badges, accesibilidad y los contratos de guardado/diff/
  restaurar/secretos resumidos en `<decisions>`.

### Especificación y requisitos
- `propuesta_mejora/SPEC_v2.md` §"Phase 32 — Vista de cámara y configuración visual" —
  ficheros esperados (`frontend/js/views/{camera,settings}.js`,
  `backend/api/v2/config.py`, `backend/storage/repositories.py`) y riesgo declarado
  (config runtime y `.env` divergentes → precedencia única + origen visible por campo).
- `.planning/REQUIREMENTS.md` — OPS-16..OPS-20, SET-01..SET-04 (líneas 258-262, 270-273).
- `.planning/ROADMAP.md` §"Phase 32" (línea 612) — 7 criterios de éxito.

### Código a reutilizar (medido, no supuesto)
- `backend/storage/repositories.py:795` — `ConfigRepo` (`get`/`set`/`get_all` sobre
  `app_config`), ya en producción.
- `backend/events/engine.py:315` — `EventEngine.config_changed()`, ya emite
  `CONFIG_CHANGED`.
- `backend/pipeline/manager.py:322,329,386` — `CameraPipeline.set_zones()` /
  `set_detection_classes()` / `set_process_size()`, únicas tres rutas de aplicación en
  caliente existentes hoy.
- `backend/pipeline/capture.py:26` — `CaptureHealth` (`connected`, `reconnects`,
  `last_frame_age_s`, `native_resolution`, `frames_captured`), ya lo devuelve
  `/api/v2/cameras/{id}/health` pero nadie lo pinta.
- `backend/main.py:1197` — `GET /api/alerts/config` (`telegram_configured: bool`),
  precedente de enmascarado de secretos; hoy huérfano en el frontend.
- `backend/config.py` — `Settings` (`pydantic-settings`), fuente de los ~88 campos, sus
  valores por defecto y (donde existan) sus rangos.

### Precedentes de patrones reutilizados
- `.planning/phases/27-multi-clase-y-contexto-de-escena/27-CONTEXT.md` — primer
  precedente de precedencia `app_config` > `.env` (clases YOLO).
- `.planning/phases/30-event-timeline-y-centro-de-alertas/30-CONTEXT.md` — segundo
  precedente de precedencia (`alerts.muted_rules`) y patrón de confirmación por popover
  (D-07 de esa fase, reutilizado aquí para "Restaurar valores por defecto").

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ConfigRepo` — almacén clave/valor sobre `app_config`, ya soporta lo que SET-01 pide.
- `EventEngine.config_changed()` — solo falta pasarle el diff por sección.
- CSS ya aprobado y reutilizable tal cual: `.cam-toggle` (interruptor con
  `role="switch"`), `.filter-input`, `.filter-select`, `.filter-chip`, `.card`,
  `.ptz-btn` (para el patrón `.busy` del botón de guardado).
- `<img id="video-feed">` / `/video_feed` — se referencia, no se duplica.

### Established Patterns
- Precedencia `app_config` > `.env` > default: dos precedentes reales (Fase 27, Fase 30)
  a seguir exactamente, no reinventar un tercer mecanismo.
- Confirmación destructiva por popover con recuento en el botón (D-07, Fase 30) — mismo
  patrón para "Restaurar valores por defecto".
- Validación 422 con mensaje legible junto al campo — mismo criterio que ya usa el PUT
  de clases de la Fase 27.

### Integration Points
- Nuevo router `backend/api/v2/config.py` (no existe) — se suma a
  `alerts, context, deps, detection, events, metrics, recordings` ya presentes en
  `backend/api/v2/`.
- Nuevas pestañas "Cámara" y "Ajustes" en el `tablist` de vista existente — no se toca
  el contenido de "Operaciones" ni "Analítica".

</code_context>

<specifics>
## Specific Ideas

No hay ideas específicas adicionales fuera de lo ya capturado en `32-UI-SPEC.md` y en
`<decisions>` — el usuario confirmó generar este contexto directamente a partir de
ROADMAP + REQUIREMENTS + UI-SPEC, sin discusión interactiva adicional, dado que el
UI-SPEC ya deja las decisiones de producto cerradas.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Context gathered: 2026-08-22*
