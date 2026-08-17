# Contexto — Fase 27: Multi-clase y contexto de escena

Generado directamente a partir de ROADMAP.md, REQUIREMENTS.md, SPEC_v2.md y
verificación de código real (agente Explore), sin pasar por `discuss-phase`
interactivo — el alcance ya estaba suficientemente definido salvo por 3
decisiones de arquitectura, resueltas abajo con `AskUserQuestion`.

## Requisitos

- **BEH-06**: clases detectadas configurables más allá de "persona"
  (bicicleta, coche, moto, mochila, maleta)
- **BEH-07**: detección de objetos abandonados (`OBJECT_LEFT`) y retirados
  (`OBJECT_REMOVED`)
- **BEH-08**: endpoint de contexto de escena agregado (hora, zona, personas
  totales/conocidas/desconocidas, nivel de actividad)
- **BEH-09**: nivel de actividad calculado contra la media móvil histórica
  de esa franja horaria

## Criterios de éxito (ROADMAP)

1. Las clases detectadas son configurables desde la UI
2. `OBJECT_LEFT` se emite tras 60s de objeto inmóvil sin persona asociada cerca
3. `OBJECT_REMOVED` se emite cuando un objeto estable desaparece con una
   persona cerca
4. `/api/v2/analytics/context` devuelve el estado agregado con nivel de
   actividad calculado contra la media móvil de 7 días
5. Escena con mochila abandonada emite un único `OBJECT_LEFT`; con la
   persona presente no lo emite
6. Activar 6 clases no incrementa la latencia de inferencia más de un 15%
   (medido contra `yolo26n.pt`, ver D-03)

## Hallazgos verificados en código (no fiarse de SPEC_v2.md §Phase 27)

- **H-1 — mecanismo de clases ya existe**: `PersonDetector` (`backend/detector.py:20-49`)
  ya acepta `classes=` en el constructor y lo pasa a cada inferencia
  (`detector.py:40,54`). `backend/config.py:54` ya tiene
  `yolo_classes: list[int] = [0]` parametrizable vía `YOLO_CLASSES`.
  `detect_sv()` (`detector.py:51-57`) ya devuelve `sv.Detections` con
  `class_id` de serie — el dato existe, nadie lo lee aguas abajo. BEH-06 es
  sobre todo mapeo nombre↔ID + propagación al registry + UI, no tocar el
  detector.
- **H-2 — tracking es mono-clase hoy**: `TrackState` (`backend/pipeline/tracking.py:18-34`)
  no tiene `class_id`/`class_name`. `TrackRegistry.update_from_detections`
  (`tracking.py:55-85`) solo lee `xyxy`/`confidence` de `sv.Detections`,
  ignora `class_id` aunque ya viaja en el objeto. `PersonTracker`
  (`backend/tracker.py:11-153`, OJO: no está en `pipeline/tracking.py`)
  inicializa `sv.ByteTrack` sin ningún parámetro de clase
  (`tracker.py:30-32`); el `LineZone` cuenta cruces de cualquier track sin
  distinguir clase.
- **H-3 — `OBJECT_LEFT`/`OBJECT_REMOVED` ya catalogados**: `backend/events/types.py:36-38`
  ya los define, añadidos junto a los 6 de Fase 26 "para estabilidad del
  contrato" (comentario explícito en el código). `OBJECT_LEFT` tiene
  severidad `WARNING` por defecto (`types.py:55`); `OBJECT_REMOVED` cae al
  fallback `INFO`. Ninguno se emite todavía desde ningún sitio — sin
  `emit_object_*` en `EventEngine`, sin lógica en `DetectionWorker`.
- **H-4 — patrón `backend/api/v2/` ya en migración parcial**: existen 2
  módulos reales con `APIRouter` + `include_router` (`backend/api/v2/recordings.py`,
  `backend/api/v2/metrics.py`, ambos registrados en `main.py:557-561`), más
  `backend/api/v2/deps.py` para rate-limit/paginación compartidos. Conviven
  con rutas `/api/v2/*` que siguen en `main.py` directamente (events, rules,
  cameras). Crear `backend/api/v2/context.py` como módulo separado es
  coherente con el patrón ya establecido — seguir el ejemplo de
  `recordings.py`/`metrics.py`.
- **H-5 — no existe infraestructura de media móvil**: `EventRepo.hourly_counts()`
  (`backend/storage/repositories.py:153-169`) agrupa por hora con
  `strftime("%H", ts)`, solo del día actual. `DetectionStat`
  (`backend/storage/models.py:112-128`) es minuto a minuto, con
  `upsert_minute`/`recent()` (`repositories.py:198-259`). Ninguna tabla ni
  query calcula media móvil/baseline histórico por franja horaria — BEH-09
  parte de cero en este punto (resuelto por D-02: query sobre datos
  existentes, sin tabla nueva).
- **H-6 — patrón de dominio puro de referencia**: `backend/perception/behavior.py`
  (Fase 26) es la referencia correcta — top-level bajo `perception/`, sin
  imports de `time`/`backend.events`, reloj inyectado, devuelve un
  `dataclass` propio (`BehaviorFinding`, no `Event`), consumido por
  `DetectionWorker._analyze_behavior()` con aislamiento de excepciones
  (`pipeline/detection.py:191-227`). OJO: `perception/identity.py` y
  `perception/gallery.py` **no existen** como ficheros planos — están en
  `perception/face/identity.py` y `perception/reid/gallery.py`
  (subpaquetes). El nuevo `objects.py` para BEH-06/07 va top-level junto a
  `behavior.py`, replicando exactamente su patrón (clase `ObjectAnalyzer`,
  reloj inyectado, `ObjectFinding` propio).
- **H-7 — sin UI de configuración de detección**: `frontend/app.js` es un
  stub vacío; toda la lógica vive inline en `frontend/index.html` (1954
  líneas). Cero controles de clases/filtros hoy — toda la config de
  detección es solo env var + reinicio. Confirma que BEH-06 (resuelto por
  D-01: endpoint + UI en vivo) es trabajo nuevo de punta a punta.
- **H-8 — deriva de modelo default**: `yolo26n.pt` ya está descargado en el
  repo pero `backend/config.py:37` sigue en `yolo_model_path: str = "yolov8n.pt"`,
  contradiciendo la decisión de stack fijada en `CLAUDE.md`. Resuelto por
  D-03: se corrige en esta fase.

## Decisiones (resueltas con `AskUserQuestion`, opción recomendada aceptada en las 3)

- **D-01 (BEH-06, alcance de configurabilidad)**: endpoint + control UI en
  vivo. Nuevo endpoint (GET/PUT, probablemente en un módulo nuevo o en
  `context.py`/uno dedicado) para leer y cambiar las clases activas en
  caliente, con persistencia en `AppConfig` y un control simple en el
  dashboard (checkboxes). El `DetectionWorker` debe recoger el cambio sin
  caída del pipeline — investigar en research el mecanismo más limpio dado
  que `BehaviorAnalyzer`/etc. se construyen fuera de la factoría del
  supervisor (mismo problema de "cómo actualizar parámetros en caliente sin
  perder estado" que ya se resolvió para otras fases, pero aquí el cambio
  es sobre `classes=` del propio detector YOLO, no sobre un analizador de
  dominio).
- **D-02 (BEH-08/09, cálculo de media móvil)**: query sobre datos
  existentes, sin tabla nueva. Al pedir `/api/v2/analytics/context`, la
  media de la franja horaria se calcula sobre los últimos N días (7, según
  criterio 4) de `DetectionStat`/`Event` ya persistidos. Sin migración,
  coste de query aceptable a esta escala (una cámara, tráfico de consulta
  bajo). El research debe determinar la query SQL concreta (probablemente
  sobre `DetectionStat.detections` agrupado por hora del día, filtrado a
  los últimos 7 días) y si necesita un índice nuevo.
- **D-03 (modelo default)**: corregir `backend/config.py:37` a
  `yolo_model_path: str = "yolo26n.pt"` como parte de esta fase, alineado
  con `CLAUDE.md`. El criterio 6 (latencia +15% máx con 6 clases) se mide
  contra `yolo26n.pt`, el modelo realmente decidido para el proyecto.

## Puntos abiertos para el research (no bloquean CONTEXT, pero condicionan el plan)

- **Distancia "persona cerca"** para BEH-07 (ni ROADMAP ni SPEC dan un
  valor numérico, a diferencia de la Fase 26 que traía la tabla de
  umbrales de §5.7). El ROADMAP sí fija el tiempo (60s inmóvil). El
  research debe proponer un valor coherente con los radios ya usados en
  `behavior.py` (p.ej. `immobile_radius_px=20`, `loiter_radius_px=80`) en
  vez de inventar una magnitud nueva sin relación.
- **"Objeto que ha aparecido"** (SPEC, riesgo Fase 27): exclusión de
  mobiliario fijo requiere (a) que el objeto haya hecho una transición
  ausente→presente después del arranque del pipeline (no estaba desde el
  primer frame) Y (b) una lista de exclusión por zona. El research debe
  confirmar si esto se puede resolver sin nuevo estado persistente (flag en
  memoria por track, análogo al análisis de comportamiento) o si necesita
  algo más.
- **Actualización en caliente de `classes=`** del detector (D-01): cómo
  propagar un cambio de configuración al `DetectionWorker`/`PersonDetector`
  ya en marcha sin reiniciar el proceso ni perder el estado de tracking
  acumulado.
- **Multi-clase en `TrackRegistry`/`ByteTrack`**: confirmar si ByteTrack
  necesita tracking separado por clase (para que un track de "persona" y
  uno de "mochila" solapados en posición no se confundan) o si el `class_id`
  ya presente en `sv.Detections` es suficiente como metadato adicional sin
  tocar la lógica interna de asociación de ByteTrack.
