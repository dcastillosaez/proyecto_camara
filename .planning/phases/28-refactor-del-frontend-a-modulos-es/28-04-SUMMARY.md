---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 04
subsystem: frontend
tags: [refactor, es-modules, video-canvas, zone-editor]
dependency-graph:
  requires: [28-01, 28-02]
  provides: [videoCanvas.js, zoneEditor.js]
  affects: [28-05, 28-07, 28-08]
tech-stack:
  added: []
  patterns: ["extraccion 1:1 desde index.html a modulos ES", "dueño unico de badge DOM (#rec-badge/#res-badge)"]
key-files:
  created:
    - frontend/js/components/videoCanvas.js
    - frontend/js/components/zoneEditor.js
  modified: []
decisions:
  - "z.name se interpola directo en innerHTML en loadZones() — patron preexistente, no endurecido en esta fase (T-28-07, disposition accept)"
metrics:
  duration: "~15 min"
  completed: 2026-08-18
---

# Phase 28 Plan 04: videoCanvas.js + zoneEditor.js Summary

Extraccion 1:1 del selector de resolucion y el CRUD de zonas desde `frontend/index.html` a
dos modulos ES nuevos bajo `frontend/js/components/`, sin cambio de comportamiento observable.

## What Was Built

- **`frontend/js/components/videoCanvas.js`** (65 lineas) — selector de resolucion
  (`loadResolutions`, listener `change` de `#resolution-select`) + 2 funciones nuevas
  `setRecBadge(visible, count)`/`setResolutionBadge(text)` que centralizan el acceso a
  `#rec-badge`/`#res-badge` (antes tocados desde 3 sitios distintos del script monolitico).
  Ambas usan `textContent`, nunca `innerHTML` (mitigacion T-28-08).
- **`frontend/js/components/zoneEditor.js`** (103 lineas) — CRUD completo de zonas de interes:
  `bindZoneForm()` (listeners de `btn-add-zone`/`zone-cancel-btn`/`zone-save-btn`, valida JSON de
  poligono con minimo 3 puntos antes de `POST /api/zones`) y `loadZones()` (`GET /api/zones`,
  render de filas con boton de borrado `DELETE /api/zones/{id}`).

Ambos modulos importan `showToast` desde `../views/dashboard.js` (ya existente desde 28-02) y no
ejecutan `fetch`/`loadX()` como efecto lateral de import — solo `app.js` (28-08) decidira cuando
se invocan `loadResolutions()`/`loadZones()`; el unico listener a nivel de modulo es el `change`
de `#resolution-select` (no depende de orden con otros modulos).

## Deviations from Plan

None — plan ejecutado exactamente como estaba escrito. El codigo de ambos ficheros es copia
literal del bloque `<action>` del plan, verificado linea a linea contra `frontend/index.html:1303-1361`
y `1690-1789` antes de escribir (ver 28-PATTERNS.md, "Match Quality: exact").

**Discrepancia no bloqueante en el comando `<verify>` de la Tarea 2:** el criterio de aceptacion
pide `grep -c "fetch('/api/zones" zoneEditor.js >= 3`, pero el resultado real es `2`. Causa: el
DELETE usa template literal con backtick (`` fetch(`/api/zones/${encodeURIComponent(z.id)}`) ``),
no la comilla simple que busca el patron `fetch('/api/zones`. Verificado con `grep -n "fetch("`
que las 3 llamadas (POST, GET, DELETE) estan presentes y son identicas al original — es un
desajuste del propio patron de grep del plan, no un defecto de codigo (mismo tipo de discrepancia
documentado como precedente en `27-06-SUMMARY.md`).

## Self-Check: PASSED

```
FOUND: frontend/js/components/videoCanvas.js
FOUND: frontend/js/components/zoneEditor.js
```

- `frontend/js/components/videoCanvas.js` — 65 lineas, 3 exports (`setRecBadge`,
  `setResolutionBadge`, `loadResolutions`), ambas por debajo de 300 lineas.
- `frontend/js/components/zoneEditor.js` — 103 lineas, 2 exports (`bindZoneForm`, `loadZones`).
- Commits verificados en `git log --oneline`:
  - `cb2e388` feat(28-04): extraer selector de resolucion a videoCanvas.js
  - `1003383` feat(28-04): extraer CRUD de zonas a zoneEditor.js
