# Phase 33: Editores visuales de zonas, líneas y reglas - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning
**Source:** Discusión directa con el usuario (3 preguntas de alcance tras 33-RESEARCH.md)

<domain>
## Phase Boundary

Dibujar zonas, líneas de conteo y componer reglas desde la interfaz, sin editar YAML ni
fracciones de coordenadas a mano (OPS-21..OPS-24, RULE-05). Tres piezas:

1. **Editor de zonas**: dibujar/mover/editar vértices/borrar polígonos sobre el frame de
   vídeo, con tipo (counting/restricted/exclusion) y horario propio.
2. **Editor de líneas de conteo**: múltiples líneas por cámara (ver D-01), con indicador
   visual de dirección.
3. **Editor de reglas**: composición completa por formularios, validación en servidor, y
   `POST /api/v2/rules/{id}/test` contra los últimos 500 eventos.

</domain>

<decisions>
## Implementation Decisions

Estas tres decisiones cierran los puntos de alcance que `33-RESEARCH.md` dejó abiertos
explícitamente (zonas duplicadas en BD, líneas única-vs-N, ubicación en la navegación).
El resto de detalles de implementación queda a discreción del investigador/planificador.

### Líneas de conteo
- **D-01:** Esta fase soporta **N líneas de conteo por cámara**, no solo mejora la línea
  única actual. Implica refactorizar `PersonTracker` (hoy una única `sv.LineZone`
  configurada por `.env` con `applies="restart_camera"`) para usar la tabla `lines` del
  esquema v2 (ya modelada, sin uso real hoy) como fuente real, con el mismo patrón de
  hot-reload thread-safe que ya usan las zonas (`CameraPipeline.set_zones()` /
  `backend/pipeline/detection.py:135-139`). Cambiar líneas debe recargar el pipeline en
  <1s sin reiniciar (criterio 6 de ROADMAP.md), igual que las zonas.

### Modelo de datos de zonas
- **D-02:** Unificar en el modelo v2. El editor visual escribe y lee únicamente contra
  `storage/models.py:Zone` + `ZoneRepo` (esquema v2). El modelo legacy de `database.py`
  (que mapea la misma tabla física `zones` con columnas distintas — `polygon_json` vs
  `polygon`) queda fuera de esta fase: el investigador/planificador debe primero
  verificar qué código real (endpoints v1, si los hay) sigue usando el modelo legacy
  antes de tocarlo, para no romper nada que dependa de él. Si algo v1 lo usa activamente,
  documentarlo como riesgo conocido en el plan en vez de migrarlo a ciegas dentro de esta
  fase — la unificación es del *editor nuevo*, no necesariamente una migración de datos
  retroactiva de todo el sistema.

### Ubicación en la navegación
- **D-03:** El editor vive dentro de la vista **Cámara** (no en Ajustes ni en una
  pestaña nueva), como panel/sub-vista que reutiliza el frame de vídeo en vivo que esa
  vista ya monta desde la Fase 32. Coherente con `frontend/js/components/videoCanvas.js`
  (patrón de canvas sobre `<img>` MJPEG con corrección `object-fit: cover`, ya usado para
  overlays de detección) — el editor de zonas/líneas es una extensión de ese mismo
  patrón, no un componente de dibujo nuevo desde cero. Las subsecciones de solo lectura
  "zonas_definidas"/"reglas_cargadas" que ya existen en el árbol de Ajustes (Fase 32)
  pueden seguir sirviendo como listado/resumen, con enlace al editor real en Cámara — no
  se duplican como formularios completos en Ajustes.

### Claude's Discretion
- Si esta fase unifica `/api/zones` (v1) y `/api/v2/zones` (`ZoneRepo`) o los deja
  coexistir: decisión técnica de integración, no de producto — el investigador/
  planificador decide según lo que encuentre usando el modelo legacy (ver D-02).
- Diseño exacto del editor de reglas por formularios (qué widgets por tipo de condición,
  cómo se componen AND/OR si el esquema los soporta): sin UI-SPEC previo para esta fase,
  el planificador puede apoyarse en los patrones ya establecidos de `settings-field.js`
  (Fase 32) para tipos de campo, y debe documentar cualquier decisión visual nueva.
- Origen de datos para verificar `POST /rules/{id}/test`: si el volumen de eventos reales
  no basta para una prueba significativa, usar `scripts/seed_events.py` (ya existe,
  usado en la Fase 30 para medir presupuestos de consulta) en vez de inventar un
  generador ad hoc.
- Orden de los planes/waves: lo decide el planificador según dependencias reales (p. ej.
  unificación del modelo Zone y refactor de líneas probablemente antes que el frontend
  de dibujo).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Investigación técnica (fuente primaria de esta fase)
- `.planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-RESEARCH.md` —
  investigación completa del estado real del código: hot-reload de zonas ya funcional,
  duplicidad de modelos `Zone`, línea única vs tabla `lines` sin usar, `RuleEngine`
  reutilizable, patrón de canvas en `videoCanvas.js`.

### Spec de producto
- `propuesta_mejora/SPEC_v2.md` §6.4 — spec funcional referenciada por `ROADMAP.md` para
  esta fase.

### Patrones de frontend a reutilizar (Fase 32, recién cerrada)
- `frontend/js/components/videoCanvas.js` — canvas sobre `<img>` MJPEG,
  `normalizedBoxToCanvasRect()`, base para el editor de clics.
- `frontend/js/views/settings-field.js` — renderers por tipo de campo (bool/int/float/
  str/enum/time/list_int/list_str/secret/readonly), reutilizables para el formulario de
  reglas.
- `frontend/js/views/camera.js` — patrón de vista Cámara donde debe montarse el editor
  (D-03).

</canonical_refs>

<specifics>
## Specific Ideas

Ninguna referencia visual o de ejemplo adicional aportada por el usuario — las tres
decisiones de alcance (D-01, D-02, D-03) son la totalidad del input recogido en esta
sesión.

</specifics>

<deferred>
## Deferred Ideas

None — el alcance de la fase queda tal como lo fija ROADMAP.md, con las tres decisiones
de arriba resolviendo las ambigüedades que 33-RESEARCH.md había dejado abiertas.

</deferred>

---

*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Context gathered: 2026-08-24 vía discusión directa (sin /gsd-discuss-phase interactivo)*
